"""End-to-end CLI tests through main() with an injected MockTransport."""

import json
from pathlib import Path

import httpx
import pytest
from conftest import json_response, load_fixture, make_transport

from interninbox.cli import main

NO_SLEEP = {"sleep": lambda _: None, "env": {}}


def route(request: httpx.Request) -> httpx.Response:
    """Serve the synthetic fixture boards on the real API hosts."""
    host = request.url.host
    if host == "boards-api.greenhouse.io":
        return json_response(load_fixture("greenhouse/aurora_widgets.json"))
    if host == "api.lever.co":
        return json_response(load_fixture("lever/cobalt_cartography.json"))
    if host == "api.ashbyhq.com":
        return json_response(load_fixture("ashby/harborline.json"))
    if host == "data.usajobs.gov":
        page = request.url.params.get("Page")
        return json_response(load_fixture(f"usajobs/page{page}.json"))
    return httpx.Response(404)


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "interninbox.toml"
    path.write_text(body, encoding="utf-8")
    return path


THREE_BOARDS = """
companies = ["greenhouse:aurora-widgets", "lever:cobalt-cartography", "ashby:harborline"]
"""


def test_scan_end_to_end_table(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config(tmp_path, THREE_BOARDS)
    code = main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP)
    out = capsys.readouterr().out
    assert code == 0
    # Interns from all three boards; staff/senior/international roles are out.
    assert "Software Engineering Intern (Summer 2027)" in out
    assert "Cartography Engineering Intern" in out
    assert "Platform Engineering Intern (Fall)" in out
    assert "Internship Program Manager" not in out
    assert "International Sales Associate" not in out
    assert "Senior Backend Engineer" not in out
    assert "6 internships across 3 companies" in out


def test_scan_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config(tmp_path, THREE_BOARDS)
    code = main(
        ["scan", "--config", str(config), "--json"], transport=make_transport(route), **NO_SLEEP
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["companies_scanned"] == 3
    assert payload["summary"]["internships"] == len(payload["listings"]) == 6
    # Newest-first where dates exist.
    dated = [item["posted_at"] for item in payload["listings"] if item["posted_at"]]
    assert dated == sorted(dated, reverse=True)


def test_scan_markdown_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config(tmp_path, 'companies = ["ashby:harborline"]')
    code = main(
        ["scan", "--config", str(config), "--markdown"],
        transport=make_transport(route),
        **NO_SLEEP,
    )
    assert code == 0
    assert capsys.readouterr().out.startswith("| Company | Title |")


def test_failing_company_warns_but_scan_continues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.lever.co":
            return httpx.Response(404)
        return route(request)

    config = write_config(tmp_path, THREE_BOARDS)
    code = main(["scan", "--config", str(config)], transport=make_transport(flaky), **NO_SLEEP)
    captured = capsys.readouterr()
    assert code == 0
    assert "warning: lever:cobalt-cartography" in captured.err
    assert "(1 company failed)" in captured.out


def test_all_companies_failing_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic outage", request=request)

    config = write_config(tmp_path, THREE_BOARDS)
    code = main(["scan", "--config", str(config)], transport=make_transport(down), **NO_SLEEP)
    captured = capsys.readouterr()
    assert code == 1
    assert "every configured company failed" in captured.err


def test_config_error_is_friendly_and_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(tmp_path, 'companies = ["taleo:megacorp"]')
    code = main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP)
    captured = capsys.readouterr()
    assert code == 1
    assert "error: unknown ATS 'taleo'" in captured.err


def test_missing_config_suggests_init(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["scan", "--config", str(tmp_path / "none.toml")],
        transport=make_transport(route),
        **NO_SLEEP,
    )
    assert code == 1
    assert "interninbox init" in capsys.readouterr().err


def test_new_only_first_run_shows_all_then_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(tmp_path, 'companies = ["ashby:harborline"]')
    args = ["scan", "--config", str(config), "--new-only"]

    assert main(args, transport=make_transport(route), **NO_SLEEP) == 0
    first_out = capsys.readouterr().out
    assert "Platform Engineering Intern (Fall)" in first_out
    assert (tmp_path / ".interninbox-state.json").is_file()

    assert main(args, transport=make_transport(route), **NO_SLEEP) == 0
    second_out = capsys.readouterr().out
    assert "Platform Engineering Intern (Fall)" not in second_out
    assert "0 internships" in second_out


def test_state_updates_even_without_new_only_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(tmp_path, 'companies = ["ashby:harborline"]')
    # Plain scan first (no flag) — it must still record what was seen.
    assert main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP) == 0
    capsys.readouterr()
    # A --new-only scan right after shows nothing new.
    code = main(
        ["scan", "--config", str(config), "--new-only"],
        transport=make_transport(route),
        **NO_SLEEP,
    )
    assert code == 0
    assert "0 internships" in capsys.readouterr().out


def test_corrupt_state_warns_and_scan_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(tmp_path, 'companies = ["ashby:harborline"]')
    (tmp_path / ".interninbox-state.json").write_text("{ nope", encoding="utf-8")
    code = main(
        ["scan", "--config", str(config), "--new-only"],
        transport=make_transport(route),
        **NO_SLEEP,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "treating every listing as new" in captured.err
    assert "Platform Engineering Intern (Fall)" in captured.out


def test_two_configs_in_one_dir_have_separate_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Non-default config names get their own state file, so --new-only under
    # one config does not suppress listings first seen under the other.
    cfg_a = tmp_path / "work.toml"
    cfg_a.write_text('companies = ["ashby:harborline"]', encoding="utf-8")
    cfg_b = tmp_path / "personal.toml"
    cfg_b.write_text('companies = ["ashby:harborline"]', encoding="utf-8")

    assert main(["scan", "--config", str(cfg_a)], transport=make_transport(route), **NO_SLEEP) == 0
    capsys.readouterr()
    # First --new-only scan of the *other* config must still see the listings.
    code = main(
        ["scan", "--config", str(cfg_b), "--new-only"],
        transport=make_transport(route),
        **NO_SLEEP,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Platform Engineering Intern (Fall)" in out  # not suppressed by cfg_a's state
    assert (tmp_path / ".interninbox-state.work.json").is_file()
    assert (tmp_path / ".interninbox-state.personal.json").is_file()
    assert not (tmp_path / ".interninbox-state.json").exists()


def test_default_config_keeps_plain_state_filename(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The default config name must keep the historical .interninbox-state.json
    # (no silent break for existing users).
    config = write_config(tmp_path, 'companies = ["ashby:harborline"]')
    assert main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP) == 0
    capsys.readouterr()
    assert (tmp_path / ".interninbox-state.json").is_file()


def test_state_path_override(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config(tmp_path, 'companies = ["ashby:harborline"]')
    state_path = tmp_path / "custom" / "state.json"
    state_path.parent.mkdir()
    code = main(
        ["scan", "--config", str(config), "--state", str(state_path)],
        transport=make_transport(route),
        **NO_SLEEP,
    )
    assert code == 0
    assert state_path.is_file()
    assert not (tmp_path / ".interninbox-state.json").exists()
    capsys.readouterr()


def test_usajobs_enabled_without_key_skips_with_info_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(
        tmp_path,
        'companies = ["ashby:harborline"]\n'
        '[usajobs]\nenabled = true\nemail = "fixture@example.test"',
    )
    code = main(
        ["scan", "--config", str(config)],
        transport=make_transport(route),
        sleep=lambda _: None,
        env={},  # USAJOBS_API_KEY unset
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "USAJOBS_API_KEY is not set" in captured.err
    assert "2 internships across 1 companies" in captured.out  # ashby still scanned


def test_usajobs_enabled_with_key_is_scanned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(
        tmp_path,
        'companies = ["ashby:harborline"]\n'
        '[usajobs]\nenabled = true\nemail = "fixture@example.test"',
    )
    code = main(
        ["scan", "--config", str(config)],
        transport=make_transport(route),
        sleep=lambda _: None,
        env={"USAJOBS_API_KEY": "fixture-key"},
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "Student Trainee (Information Technology)" in captured.out
    assert "Pathways Intern - Data Analysis" in captured.out
    assert "across 2 companies" in captured.out


def test_usajobs_disabled_never_touches_the_host(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hosts: list[str] = []

    def tracking(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return route(request)

    config = write_config(tmp_path, 'companies = ["ashby:harborline"]')
    assert (
        main(["scan", "--config", str(config)], transport=make_transport(tracking), **NO_SLEEP)
        == 0
    )
    capsys.readouterr()
    assert "data.usajobs.gov" not in hosts


def test_init_writes_config_and_next_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init"], **NO_SLEEP) == 0
    out = capsys.readouterr().out
    assert (tmp_path / "interninbox.toml").is_file()
    assert "interninbox scan" in out
    # Re-running must not clobber the user's edits.
    assert main(["init"], **NO_SLEEP) == 1
    assert "not overwriting" in capsys.readouterr().err


def test_init_config_is_loadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from interninbox.config import load_config

    monkeypatch.chdir(tmp_path)
    assert main(["init"], **NO_SLEEP) == 0
    config = load_config(tmp_path / "interninbox.toml")
    assert len(config.companies) == 3


def test_companies_lists_starter_entries(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["companies"], **NO_SLEEP) == 0
    out = capsys.readouterr().out
    assert '"greenhouse:stripe"' in out
    assert '"lever:plaid"' in out
    assert '"ashby:linear"' in out
    assert "verify" in out.lower()


def test_progress_lines_written_when_tty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from interninbox.cli import _scan_boards
    from interninbox.config import load_config
    from interninbox.fetch import Fetcher
    from interninbox.models import ScanResult

    config = load_config(write_config(tmp_path, THREE_BOARDS))
    result = ScanResult()
    with Fetcher(transport=make_transport(route), sleep=lambda _: None) as fetcher:
        _scan_boards(config, fetcher, result, progress=True)
    err = capsys.readouterr().err
    assert "[1/3] greenhouse:aurora-widgets ..." in err
    assert "[3/3] ashby:harborline ..." in err


def test_no_progress_lines_when_not_a_tty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(tmp_path, THREE_BOARDS)
    assert main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP) == 0
    assert "[1/3]" not in capsys.readouterr().err  # capsys stderr is not a tty


def test_keyboard_interrupt_is_clean_and_130(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupt(request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt

    config = write_config(tmp_path, THREE_BOARDS)
    code = main(["scan", "--config", str(config)], transport=make_transport(interrupt), **NO_SLEEP)
    captured = capsys.readouterr()
    assert code == 130
    assert "interrupted" in captured.err


def test_unreadable_config_is_friendly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path, THREE_BOARDS)
    real_open = Path.open

    def deny(self: Path, *args: object, **kwargs: object):
        if self == config:
            raise PermissionError(13, "Permission denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny)
    code = main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP)
    captured = capsys.readouterr()
    assert code == 1
    assert "could not read" in captured.err


def test_init_unwritable_directory_is_friendly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    def deny(self: Path, *args: object, **kwargs: object) -> int:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "write_text", deny)
    assert main(["init"], **NO_SLEEP) == 1
    assert "could not write" in capsys.readouterr().err


def test_filter_loosening_does_not_flood_new_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scan once with a filter that hides the Design Intern.
    write_config(
        tmp_path,
        'companies = ["ashby:harborline"]\n[filters]\nexclude_keywords = ["design"]\n',
    )
    config = tmp_path / "interninbox.toml"
    assert main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP) == 0
    capsys.readouterr()
    # Loosen the filter: the Design Intern was FETCHED before, so it is not "new".
    write_config(tmp_path, 'companies = ["ashby:harborline"]')
    code = main(
        ["scan", "--config", str(config), "--new-only"],
        transport=make_transport(route),
        **NO_SLEEP,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Design Intern" not in out


def test_usajobs_only_scan_works_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(
        tmp_path, '[usajobs]\nenabled = true\nemail = "fixture@example.test"\n'
    )
    code = main(
        ["scan", "--config", str(config)],
        transport=make_transport(route),
        sleep=lambda _: None,
        env={"USAJOBS_API_KEY": "fixture-key"},
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "Student Trainee (Information Technology)" in captured.out


def test_location_alias_full_state_name_matches_abbreviation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(
        tmp_path,
        'companies = ["ashby:harborline"]\n[filters]\nlocations = ["Washington"]\n',
    )
    assert main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP) == 0
    out = capsys.readouterr().out
    # "Washington" expands to "WA", matching the board's "Seattle, WA".
    assert "Platform Engineering Intern (Fall)" in out
