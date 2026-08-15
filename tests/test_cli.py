"""End-to-end CLI tests through main() with an injected MockTransport."""

import json
import sys
from pathlib import Path

import httpx
import pytest
from conftest import json_response, load_fixture, make_transport

from interninbox.cli import main

NO_SLEEP = {"sleep": lambda _: None, "env": {}}

_BANNER_TAGLINE = "find internships. in the terminal."


def _force_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend stderr is an interactive terminal for banner/progress tests."""
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)


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
    if host == "raw.githubusercontent.com":
        return json_response(load_fixture("sources/simplify.json"))
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
    # Plain scan first (no flag), it must still record what was seen.
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


def test_banner_shown_on_interactive_scan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_tty(monkeypatch)
    config = write_config(tmp_path, THREE_BOARDS)
    code = main(
        ["scan", "--config", str(config)],
        transport=make_transport(route),
        sleep=lambda _: None,
        env={},  # no NO_COLOR
    )
    err = capsys.readouterr().err
    assert code == 0
    assert _BANNER_TAGLINE in err
    assert "\x1b[" in err  # colored on a tty without NO_COLOR


def test_banner_respects_no_color(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_tty(monkeypatch)
    config = write_config(tmp_path, THREE_BOARDS)
    main(
        ["scan", "--config", str(config)],
        transport=make_transport(route),
        sleep=lambda _: None,
        env={"NO_COLOR": "1"},
    )
    err = capsys.readouterr().err
    banner_line = next(line for line in err.splitlines() if _BANNER_TAGLINE in line)
    assert "\x1b" not in banner_line  # plain when NO_COLOR is set


def test_no_banner_when_not_a_tty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # capsys stderr is not a tty, so a piped/redirected run stays clean.
    config = write_config(tmp_path, THREE_BOARDS)
    main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP)
    assert _BANNER_TAGLINE not in capsys.readouterr().err


def test_quiet_suppresses_banner_and_progress(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_tty(monkeypatch)
    config = write_config(tmp_path, THREE_BOARDS)
    main(
        ["scan", "--config", str(config), "--quiet"],
        transport=make_transport(route),
        sleep=lambda _: None,
        env={},
    )
    err = capsys.readouterr().err
    assert _BANNER_TAGLINE not in err
    assert "[1/3]" not in err  # --quiet also silences the progress lines


def test_json_scan_has_no_banner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_tty(monkeypatch)
    config = write_config(tmp_path, THREE_BOARDS)
    main(
        ["scan", "--config", str(config), "--json"],
        transport=make_transport(route),
        sleep=lambda _: None,
        env={},
    )
    captured = capsys.readouterr()
    assert _BANNER_TAGLINE not in captured.err  # machine output stays clean
    json.loads(captured.out)  # stdout is still valid JSON


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
        _scan_boards(config.companies, fetcher, result, progress=True)
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


def test_roles_narrow_scan_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config(tmp_path, THREE_BOARDS + '[filters]\nroles = ["software"]\n')
    assert main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP) == 0
    out = capsys.readouterr().out
    assert "Software Engineering Intern (Summer 2027)" in out
    assert "Platform Engineering Intern (Fall)" in out  # "platform" is a software keyword
    assert "Cartography Engineering Intern" not in out  # no software keyword in title


def test_roles_command_lists_presets(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["roles"], **NO_SLEEP) == 0
    out = capsys.readouterr().out
    assert "cybersecurity" in out and "finance" in out
    assert "security" in out  # keywords are shown, not just names


def test_registry_tier_unions_with_config_companies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from interninbox.registry import RegistryCompany

    # Shrink the registry to fixture-backed boards; one duplicates the config.
    monkeypatch.setattr(
        "interninbox.registry.REGISTRY",
        (
            RegistryCompany("ashby", "harborline", "Harborline", "startup", ()),
            RegistryCompany("lever", "cobalt-cartography", "Cobalt", "startup", ()),
        ),
    )
    config = write_config(tmp_path, 'companies = ["ashby:harborline"]\nregistry = "all"\n')
    assert main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP) == 0
    out = capsys.readouterr().out
    # harborline deduped (config first), cobalt added from the registry.
    assert "across 2 companies" in out
    assert "Cartography Engineering Intern" in out


def test_large_scan_prints_scale_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from interninbox.registry import RegistryCompany

    entries = tuple(
        RegistryCompany("ashby", f"board-{i}", f"Board {i}", "startup", ()) for i in range(25)
    )
    monkeypatch.setattr("interninbox.registry.REGISTRY", entries)

    def all_empty(request: httpx.Request) -> httpx.Response:
        return json_response({"jobs": []})

    config = write_config(tmp_path, 'registry = "all"\n')
    assert main(["scan", "--config", str(config)], transport=make_transport(all_empty),
                **NO_SLEEP) == 0
    err = capsys.readouterr().err
    assert "25 boards" in err and "~" in err  # scale + rough estimate disclosed


def test_interactive_scan_without_config_runs_and_offers_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from interninbox.registry import RegistryCompany

    monkeypatch.setattr(
        "interninbox.registry.REGISTRY",
        (RegistryCompany("ashby", "harborline", "Harborline", "startup", (), top=True),),
    )
    monkeypatch.chdir(tmp_path)
    # location blank, roles blank, companies -> [1] all, save? -> y
    scripted = iter(["", "", "1", "y"])
    code = main(
        ["scan", "--interactive"],
        transport=make_transport(route),
        sleep=lambda _: None,
        env={},
        input_fn=lambda prompt: next(scripted),
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "Platform Engineering Intern (Fall)" in captured.out
    assert (tmp_path / "interninbox.toml").is_file()  # saved on request


def test_interactive_save_declined_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from interninbox.registry import RegistryCompany

    monkeypatch.setattr(
        "interninbox.registry.REGISTRY",
        (RegistryCompany("ashby", "harborline", "Harborline", "startup", (), top=True),),
    )
    monkeypatch.chdir(tmp_path)
    scripted = iter(["", "", "1", "n"])
    code = main(
        ["scan", "--interactive"],
        transport=make_transport(route),
        sleep=lambda _: None,
        env={},
        input_fn=lambda prompt: next(scripted),
    )
    capsys.readouterr()
    assert code == 0
    assert not (tmp_path / "interninbox.toml").exists()


def test_missing_config_without_tty_still_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Non-interactive (cron/pipes): behavior is unchanged from today.
    code = main(
        ["scan", "--config", str(tmp_path / "none.toml")],
        transport=make_transport(route),
        **NO_SLEEP,
    )
    assert code == 1
    assert "interninbox init" in capsys.readouterr().err


def test_sources_scan_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config(tmp_path, 'sources = ["simplify"]\n')
    code = main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP)
    out = capsys.readouterr().out
    assert code == 0
    assert "Quantum Software Intern" in out
    # Curated bypass end to end: no intern-word in this title, still shown.
    assert "2027 Mapping Analyst Program" in out
    assert "Closed Intern" not in out  # inactive rows never surface
    assert "and 1 list" in out  # summary counts the source separately


def test_require_sponsorship_hides_known_bad_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(
        tmp_path, 'sources = ["simplify"]\n[filters]\nrequire_sponsorship = true\n'
    )
    assert main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP) == 0
    out = capsys.readouterr().out
    assert "Quantum Software Intern" in out  # offers sponsorship
    assert "2027 Mapping Analyst Program" not in out  # does not sponsor
    assert "Systems Intern (Clearance)" not in out  # citizenship required


def test_require_sponsorship_requests_greenhouse_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    urls: list[str] = []

    def tracking(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return route(request)

    config = write_config(
        tmp_path,
        'companies = ["greenhouse:aurora-widgets"]\n[filters]\nrequire_sponsorship = true\n',
    )
    code = main(["scan", "--config", str(config)], transport=make_transport(tracking), **NO_SLEEP)
    assert code == 0
    capsys.readouterr()
    assert any("content=true" in url for url in urls)
    # The SWE intern's description says "unable to sponsor": hidden.
    # (behavior covered above; here we care that the param was sent)

    urls.clear()
    config2 = write_config(tmp_path, 'companies = ["greenhouse:aurora-widgets"]\n')
    code = main(["scan", "--config", str(config2)], transport=make_transport(tracking), **NO_SLEEP)
    assert code == 0
    capsys.readouterr()
    assert not any("content=true" in url for url in urls)  # don't pay for unused filters


def test_source_failure_warns_and_boards_continue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.host == "raw.githubusercontent.com":
            return httpx.Response(500)
        return route(request)

    config = write_config(tmp_path, 'companies = ["ashby:harborline"]\nsources = ["simplify"]\n')
    code = main(["scan", "--config", str(config)], transport=make_transport(flaky), **NO_SLEEP)
    captured = capsys.readouterr()
    assert code == 0
    assert "source simplify" in captured.err  # one warning line
    assert "Platform Engineering Intern (Fall)" in captured.out  # boards unaffected


def test_successful_source_prevents_all_failed_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def boards_down(request: httpx.Request) -> httpx.Response:
        if request.url.host == "raw.githubusercontent.com":
            return json_response(load_fixture("sources/simplify.json"))
        return httpx.Response(500)

    config = write_config(tmp_path, 'companies = ["ashby:harborline"]\nsources = ["simplify"]\n')
    code = main(
        ["scan", "--config", str(config)], transport=make_transport(boards_down), **NO_SLEEP
    )
    captured = capsys.readouterr()
    assert code == 0  # the list delivered results; not a total failure
    assert "Quantum Software Intern" in captured.out


def test_smartrecruiters_scan_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def sr_route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.smartrecruiters.com":
            return json_response(load_fixture("smartrecruiters/meridian.json"))
        return route(request)

    config = write_config(tmp_path, 'companies = ["smartrecruiters:MeridianPay"]\n')
    code = main(["scan", "--config", str(config)], transport=make_transport(sr_route), **NO_SLEEP)
    out = capsys.readouterr().out
    assert code == 0
    assert "Payments Software Intern (Summer 2027)" in out
    assert "Risk Analytics Intern" in out
    assert "Senior Treasury Manager" not in out  # staff filter still applies
    assert "jobs.smartrecruiters.com/MeridianPay/744000900000001" in out


def test_find_board_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "boards-api.greenhouse.io" and "/acme/" in request.url.path:
            return json_response({"jobs": []})
        if request.url.host == "api.smartrecruiters.com":
            return json_response({"totalFound": 0, "content": []})
        return httpx.Response(404)

    code = main(["find-board", "Acme"], transport=make_transport(handler), **NO_SLEEP)
    out = capsys.readouterr().out
    assert code == 0
    assert '"greenhouse:acme"' in out  # ready to paste into the config


def test_find_board_none_found_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def nothing(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.smartrecruiters.com":
            return json_response({"totalFound": 0, "content": []})
        return httpx.Response(404)

    code = main(["find-board", "Ghost"], transport=make_transport(nothing), **NO_SLEEP)
    captured = capsys.readouterr()
    assert code == 1
    assert "careers page" in captured.err  # points at the manual method
