"""run_scan called directly: the scan core the CLI (and later MCP, watch) share."""

from pathlib import Path

import httpx
from conftest import json_response, load_fixture, make_transport

from interninbox.config import Company, Config
from interninbox.scan import run_scan


def route(request: httpx.Request) -> httpx.Response:
    if request.url.host == "api.ashbyhq.com":
        return json_response(load_fixture("ashby/harborline.json"))
    return httpx.Response(404)


def test_run_scan_direct_with_progress_state_and_new_only(tmp_path: Path) -> None:
    config = Config(companies=(Company(ats="ashby", slug="harborline"),))
    state_path = tmp_path / "state.json"
    lines: list[tuple[str, bool]] = []

    def progress(line: str, *, essential: bool = False) -> None:
        lines.append((line, essential))

    result = run_scan(
        config,
        transport=make_transport(route),
        sleep=lambda _: None,
        env={},
        progress=progress,
        state_path=state_path,
    )
    assert result.companies_scanned == 1
    titles = [listing.title for listing in result.listings]
    assert "Platform Engineering Intern (Fall)" in titles
    assert "Principal Infrastructure Engineer" not in titles  # staff filter applied
    assert result.listings_matched == len(result.listings) == 2
    # Per-company progress flows through the injected callable, not stderr.
    assert ("[1/1] ashby:harborline ...", False) in lines
    assert state_path.is_file()  # the scan recorded everything it fetched

    # A second run with new_only shows nothing: the first run saw it all.
    again = run_scan(
        config,
        new_only=True,
        transport=make_transport(route),
        sleep=lambda _: None,
        env={},
        state_path=state_path,
    )
    assert again.listings == []
    assert again.listings_matched == 2  # still matched, just not new
