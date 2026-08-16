"""The MCP server core, driven in-process over injected line IO.

`serve` speaks newline-delimited JSON-RPC 2.0; every test feeds it a list
of input lines and collects the responses it writes, with MockTransport
behind any tool call that fetches.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from conftest import json_response, load_fixture, make_transport

from interninbox import __version__
from interninbox.mcp import serve


def run_server(
    lines: list[object],
    *,
    transport: httpx.BaseTransport | None = None,
    env: dict[str, str] | None = None,
) -> list[dict]:
    """Drive serve over `lines` (dicts are JSON-encoded) and parse its output."""
    encoded = [line if isinstance(line, str) else json.dumps(line) for line in lines]
    inputs = iter(encoded)

    def read_line() -> str:
        try:
            return next(inputs) + "\n"
        except StopIteration:
            return ""

    outputs: list[str] = []
    serve(
        read_line,
        outputs.append,
        transport=transport,
        sleep=lambda _: None,
        env=env if env is not None else {},
    )
    return [json.loads(text) for text in outputs]


def request(request_id: object, method: str, params: dict | None = None) -> dict:
    message: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def tool_call(request_id: object, name: str, arguments: dict) -> dict:
    return request(request_id, "tools/call", {"name": name, "arguments": arguments})


def tool_payload(response: dict) -> dict:
    """Decode the JSON text block a successful tools/call result carries."""
    result = response["result"]
    assert result.get("isError") is False
    block = result["content"][0]
    assert block["type"] == "text"
    return json.loads(block["text"])


def ashby_route(request: httpx.Request) -> httpx.Response:
    if request.url.host == "api.ashbyhq.com":
        return json_response(load_fixture("ashby/harborline.json"))
    return httpx.Response(404)


# --- handshake ---------------------------------------------------------------


def test_initialize_handshake() -> None:
    responses = run_server([
        request(0, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.0.1"},
        }),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ])
    assert len(responses) == 1  # the notification gets no reply
    reply = responses[0]
    assert reply["jsonrpc"] == "2.0"
    assert reply["id"] == 0
    result = reply["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"] == {"name": "interninbox", "version": __version__}
    assert "tools" in result["capabilities"]


# --- tools/list --------------------------------------------------------------


def test_tools_list_names_and_schemas() -> None:
    responses = run_server([request(1, "tools/list")])
    tools = {tool["name"]: tool for tool in responses[0]["result"]["tools"]}
    assert set(tools) == {"scan_internships", "list_role_presets", "find_board"}
    for tool in tools.values():
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"

    scan_schema = tools["scan_internships"]["inputSchema"]
    assert set(scan_schema["properties"]) == {
        "roles", "locations", "terms", "require_sponsorship", "registry",
        "sources", "companies", "since", "limit",
    }
    assert scan_schema["properties"]["registry"]["enum"] == [
        "none", "top", "all", "large", "startups",
    ]
    assert scan_schema["properties"]["limit"]["type"] == "integer"
    assert scan_schema["properties"]["roles"]["items"]["type"] == "string"

    find_schema = tools["find_board"]["inputSchema"]
    assert find_schema["required"] == ["name"]
    assert find_schema["properties"]["name"]["type"] == "string"


# --- tools/call: list_role_presets and find_board ----------------------------


def test_list_role_presets_tool() -> None:
    responses = run_server([tool_call(2, "list_role_presets", {})])
    payload = tool_payload(responses[0])
    assert "swe" in payload["roles"]["software"]
    assert "cybersecurity" in payload["roles"]


def test_find_board_tool() -> None:
    def probe_route(request: httpx.Request) -> httpx.Response:
        if (
            request.url.host == "boards-api.greenhouse.io"
            and request.url.path == "/v1/boards/harborline/jobs"
        ):
            return json_response({"jobs": []})
        return httpx.Response(404)

    responses = run_server(
        [tool_call(3, "find_board", {"name": "Harborline"})],
        transport=make_transport(probe_route),
    )
    payload = tool_payload(responses[0])
    assert payload["boards"] == ["greenhouse:harborline"]


def test_find_board_requires_a_name() -> None:
    responses = run_server([tool_call(4, "find_board", {})])
    error = responses[0]["error"]
    assert error["code"] == -32602
    assert "name" in error["message"]


# --- tools/call: scan_internships --------------------------------------------


def test_scan_tool_returns_listings_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # prove the scan leaves no state behind
    responses = run_server(
        [tool_call(5, "scan_internships", {
            "companies": ["ashby:harborline"], "registry": "none", "sources": [],
        })],
        transport=make_transport(ashby_route),
    )
    payload = tool_payload(responses[0])
    titles = [listing["title"] for listing in payload["listings"]]
    assert "Platform Engineering Intern (Fall)" in titles
    assert "Design Intern" in titles
    assert "Principal Infrastructure Engineer" not in titles  # staff filter applies
    listing = payload["listings"][0]
    # The listing shape matches `interninbox scan --json`.
    assert set(listing) == {
        "company", "source", "id", "title", "locations", "posted_at", "url",
        "sponsorship", "sponsorship_evidence", "terms",
    }
    summary = payload["summary"]
    assert summary["internships"] == 2
    assert summary["shown"] == 2
    assert summary["companies_scanned"] == 1
    assert summary["companies_failed"] == 0
    # MCP calls never touch user state: nothing was written to the cwd.
    assert list(tmp_path.iterdir()) == []


def test_scan_tool_caps_listings_at_limit() -> None:
    responses = run_server(
        [tool_call(6, "scan_internships", {
            "companies": ["ashby:harborline"], "registry": "none", "sources": [],
            "limit": 1,
        })],
        transport=make_transport(ashby_route),
    )
    payload = tool_payload(responses[0])
    assert len(payload["listings"]) == 1
    assert payload["summary"]["internships"] == 2  # the cap is honest
    assert payload["summary"]["shown"] == 1


def test_scan_tool_defaults_to_top_registry_and_simplify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))  # isolate the list cache
    hosts: list[str] = []

    def route(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(404)

    responses = run_server(
        [tool_call(7, "scan_internships", {})], transport=make_transport(route)
    )
    payload = tool_payload(responses[0])
    assert payload["listings"] == []
    # registry defaulted to "top": the whole tier was attempted.
    assert payload["summary"]["companies_failed"] >= 50
    # sources defaulted to ["simplify"]: the community list was attempted too.
    assert "raw.githubusercontent.com" in hosts
    assert payload["summary"]["warnings"]


def test_scan_tool_does_not_repeat_seen_state_between_calls() -> None:
    # Two identical scans in one session both return the listings: MCP scans
    # are stateless (new_only is always False, state goes to a temp path).
    responses = run_server(
        [
            tool_call(8, "scan_internships", {
                "companies": ["ashby:harborline"], "registry": "none", "sources": [],
            }),
            tool_call(9, "scan_internships", {
                "companies": ["ashby:harborline"], "registry": "none", "sources": [],
            }),
        ],
        transport=make_transport(ashby_route),
    )
    assert len(responses) == 2
    for response in responses:
        assert len(tool_payload(response)["listings"]) == 2


# --- errors ------------------------------------------------------------------


def test_unknown_method_error() -> None:
    responses = run_server([request(10, "resources/list")])
    reply = responses[0]
    assert reply["id"] == 10
    assert reply["error"]["code"] == -32601
    assert "resources/list" in reply["error"]["message"]


def test_unknown_notification_gets_no_reply() -> None:
    responses = run_server([{"jsonrpc": "2.0", "method": "notifications/cancelled"}])
    assert responses == []


def test_malformed_json_line_then_recovery() -> None:
    responses = run_server([
        '{"jsonrpc": "2.0", "id": 11,',  # truncated JSON
        request(12, "tools/list"),
    ])
    assert len(responses) == 2
    parse_error = responses[0]
    assert parse_error["id"] is None
    assert parse_error["error"]["code"] == -32700
    assert responses[1]["id"] == 12  # the server kept serving
    assert "tools" in responses[1]["result"]


def test_non_object_request_is_invalid() -> None:
    responses = run_server(["42"])
    error = responses[0]["error"]
    assert error["code"] == -32600
    assert responses[0]["id"] is None


def test_request_without_method_is_invalid() -> None:
    responses = run_server([{"jsonrpc": "2.0", "id": 13}])
    assert responses[0]["id"] == 13
    assert responses[0]["error"]["code"] == -32600


def test_unknown_tool_error() -> None:
    responses = run_server([tool_call(14, "make_coffee", {})])
    error = responses[0]["error"]
    assert error["code"] == -32602
    assert "make_coffee" in error["message"]


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        ({"roles": ["underwater"]}, "unknown role"),
        ({"roles": "software"}, "roles must be an array"),
        ({"registry": "bogus"}, "registry must be one of"),
        ({"sources": ["linkedin"]}, "unknown source"),
        ({"companies": ["notanats:acme"]}, "unknown ATS"),
        ({"companies": ["acme"]}, "ats:slug"),
        ({"companies": ["ashby:x", "ashby:x"]}, "duplicate company"),
        ({"since": "next week"}, "7d"),
        ({"limit": 0}, "limit"),
        ({"limit": "ten"}, "limit"),
        ({"require_sponsorship": "yes"}, "require_sponsorship"),
        ({"frobnicate": True}, "frobnicate"),
    ],
)
def test_scan_tool_invalid_params(arguments: dict, fragment: str) -> None:
    # No transport: validation must fail before any fetch is attempted.
    responses = run_server([tool_call(15, "scan_internships", arguments)])
    error = responses[0]["error"]
    assert error["code"] == -32602
    assert fragment in error["message"]


def test_blank_lines_are_skipped() -> None:
    responses = run_server(["", "   ", request(16, "tools/list")])
    assert len(responses) == 1
    assert responses[0]["id"] == 16
