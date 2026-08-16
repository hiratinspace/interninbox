"""MCP server core: the scanner exposed to AI agents over JSON-RPC.

`serve(read_line, write_line)` speaks the Model Context Protocol
(version 2024-11-05) as newline-delimited JSON-RPC 2.0, far enough for
tool use: initialize, notifications/initialized, tools/list, tools/call,
and graceful errors for everything else. IO arrives as injected callables
(`read_line` behaves like `sys.stdin.readline`, returning "" at EOF;
`write_line` receives one serialized response per request), so tests and
the CLI stdio loop drive the same code.

Three tools: scan_internships (the same scan core as the CLI, built from
an in-memory Config), list_role_presets, and find_board. Scans always run
with new_only False against a temporary state path, so an AI agent's
calls can never consume or pollute the user's own `scan --new-only`
state. Politeness is unchanged: every fetch goes through the shared
Fetcher.
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from interninbox import __version__
from interninbox.config import Config, ConfigError, Filters, parse_company
from interninbox.discover import find_boards
from interninbox.fetch import Fetcher
from interninbox.freshness import parse_since
from interninbox.models import Listing, ScanResult
from interninbox.output import sort_listings
from interninbox.registry import TIERS
from interninbox.roles import ROLE_PRESETS, expand_roles
from interninbox.scan import run_scan
from interninbox.sources import is_known_source, known_source_names

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_LIMIT = 50

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


class ToolError(Exception):
    """Invalid tool arguments; reported as a JSON-RPC invalid-params error."""


def _string_array_schema(description: str) -> dict[str, object]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def _scan_tool_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "roles": _string_array_schema(
                "Role preset names narrowing results to a field, e.g. [\"software\"]. "
                "list_role_presets shows every preset and its keywords."
            ),
            "locations": _string_array_schema(
                "Keep only listings whose location contains one of these as a whole "
                "word (case-insensitive), e.g. [\"NY\", \"Remote\"]. Empty keeps all."
            ),
            "terms": _string_array_schema(
                "Keep only listings for these seasons, e.g. [\"Summer 2027\"]. "
                "Listings whose season is unknown are kept."
            ),
            "require_sponsorship": {
                "type": "boolean",
                "description": "Hide listings KNOWN to not sponsor visas or to require "
                "US citizenship. Listings that say nothing are always kept.",
            },
            "registry": {
                "type": "string",
                "enum": ["none", *TIERS],
                "description": "Curated registry tier of company boards to sweep "
                "(default \"top\", roughly 50 well-known boards).",
            },
            "sources": _string_array_schema(
                "Community internship lists to include (default [\"simplify\"], the "
                "SimplifyJobs seasonal list). Pass [] to scan boards only."
            ),
            "companies": _string_array_schema(
                "Extra company boards as \"ats:slug\" entries, e.g. "
                "[\"greenhouse:stripe\"]. find_board can discover a company's slug."
            ),
            "since": {
                "type": "string",
                "description": "Only listings posted within this window: a number and "
                "unit like \"7d\", \"36h\", \"2w\". Undated listings are kept.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": f"Maximum listings returned (default {DEFAULT_LIMIT}). "
                "The summary always reports the full match count.",
            },
        },
        "additionalProperties": False,
    }


def _tool_definitions() -> list[dict[str, object]]:
    return [
        {
            "name": "scan_internships",
            "description": "Scan public company job boards and community internship "
            "lists for open internships, locally and politely (rate-limited, no API "
            "keys), and return matching listings with location, posting date, and "
            "visa-sponsorship evidence as JSON.",
            "inputSchema": _scan_tool_schema(),
        },
        {
            "name": "list_role_presets",
            "description": "List the named role presets (curated keyword sets) that "
            "scan_internships accepts in its roles parameter.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "find_board",
            "description": "Probe the supported ATS endpoints for a company's job "
            "board and return \"ats:slug\" labels ready for scan_internships' "
            "companies parameter.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Company name, e.g. \"Acme Corp\".",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    ]


def _string_list(arguments: Mapping[str, object], key: str) -> tuple[str, ...] | None:
    """The named array-of-strings argument, or None when absent (defaults apply)."""
    raw = arguments.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ToolError(f"{key} must be an array of strings")
    return tuple(item.strip() for item in raw if item.strip())


def _build_scan_config(
    arguments: Mapping[str, object],
) -> tuple[Config, dt.timedelta | None, int]:
    """Validate scan_internships arguments into (Config, since window, limit).

    Reuses the same validators the config file goes through, so an AI agent
    gets exactly the CLI's rules with a friendly message on any violation.
    """
    allowed = {
        "roles", "locations", "terms", "require_sponsorship", "registry",
        "sources", "companies", "since", "limit",
    }
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ToolError(f"unexpected parameter(s): {', '.join(unknown)}")

    roles = _string_list(arguments, "roles") or ()
    if roles:
        try:
            expand_roles(roles)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    require_sponsorship = arguments.get("require_sponsorship", False)
    if not isinstance(require_sponsorship, bool):
        raise ToolError("require_sponsorship must be a boolean")

    registry = arguments.get("registry", "top")
    if not isinstance(registry, str) or registry not in ("none", *TIERS):
        choices = ", ".join(f'"{choice}"' for choice in ("none", *TIERS))
        raise ToolError(f"registry must be one of {choices}")

    sources = _string_list(arguments, "sources")
    if sources is None:
        sources = ("simplify",)
    for source in sources:
        if not is_known_source(source):
            valid = ", ".join(known_source_names())
            raise ToolError(f"unknown source {source!r}; valid sources: {valid}")

    try:
        companies = tuple(
            parse_company(entry) for entry in _string_list(arguments, "companies") or ()
        )
    except ConfigError as exc:
        raise ToolError(str(exc)) from exc
    seen: set[str] = set()
    for company in companies:
        if company.label in seen:
            raise ToolError(f"duplicate company entry {company.label!r}")
        seen.add(company.label)

    since_raw = arguments.get("since")
    since: dt.timedelta | None = None
    if since_raw is not None:
        if not isinstance(since_raw, str):
            raise ToolError("since must be a string like 7d, 36h, 2w")
        try:
            since = parse_since(since_raw)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    limit = arguments.get("limit", DEFAULT_LIMIT)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ToolError("limit must be an integer of at least 1")

    config = Config(
        companies=companies,
        filters=Filters(
            roles=roles,
            locations=_string_list(arguments, "locations") or (),
            terms=_string_list(arguments, "terms") or (),
            require_sponsorship=require_sponsorship,
        ),
        registry=registry,
        sources=tuple(sources),
    )
    return config, since, limit


def _listing_dict(listing: Listing) -> dict[str, object]:
    """One listing in the same JSON shape as `interninbox scan --json`."""
    return {
        "company": listing.company,
        "source": listing.source,
        "id": listing.listing_id,
        "title": listing.title,
        "locations": list(listing.locations),
        "posted_at": listing.posted_at.isoformat() if listing.posted_at else None,
        "url": listing.url,
        "sponsorship": listing.sponsorship,
        "sponsorship_evidence": listing.sponsorship_evidence,
        "terms": list(listing.terms),
    }


def _scan_payload(result: ScanResult, limit: int) -> dict[str, object]:
    listings = sort_listings(result.listings)
    shown = listings[:limit]
    return {
        "listings": [_listing_dict(listing) for listing in shown],
        "summary": {
            "internships": len(listings),
            "shown": len(shown),
            "companies_scanned": result.companies_scanned,
            "companies_failed": result.companies_failed,
            "listings_checked": result.listings_checked,
            "sources_scanned": result.sources_scanned,
            "warnings": list(result.warnings),
        },
    }


def _run_scan_tool(
    arguments: Mapping[str, object],
    *,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
    env: Mapping[str, str] | None,
) -> dict[str, object]:
    config, since, limit = _build_scan_config(arguments)
    # A throwaway state path: recorded seen-listings vanish with the tempdir,
    # so MCP scans never read or write the user's own state file.
    with tempfile.TemporaryDirectory(prefix="interninbox-mcp-") as tmp:
        result = run_scan(
            config,
            new_only=False,
            since=since,
            transport=transport,
            sleep=sleep,
            env=env,
            progress=None,
            state_path=Path(tmp) / "state.json",
        )
    return _scan_payload(result, limit)


def _role_presets_tool(arguments: Mapping[str, object]) -> dict[str, object]:
    if arguments:
        raise ToolError("list_role_presets takes no parameters")
    return {"roles": {name: list(ROLE_PRESETS[name]) for name in sorted(ROLE_PRESETS)}}


def _find_board_tool(
    arguments: Mapping[str, object],
    *,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
) -> dict[str, object]:
    unknown = sorted(set(arguments) - {"name"})
    if unknown:
        raise ToolError(f"unexpected parameter(s): {', '.join(unknown)}")
    name = arguments.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ToolError("name must be a non-empty string, e.g. \"Acme Corp\"")
    with Fetcher(transport=transport, sleep=sleep) as fetcher:
        found = find_boards(fetcher, name)
    return {"boards": found}


def _result_response(request_id: object, result: dict[str, object]) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _handle_tool_call(
    request_id: object,
    params: Mapping[str, object],
    *,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
    env: Mapping[str, str] | None,
) -> dict[str, object]:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return _error_response(request_id, INVALID_PARAMS, "tools/call needs a tool name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _error_response(request_id, INVALID_PARAMS, "arguments must be an object")
    try:
        if name == "scan_internships":
            payload = _run_scan_tool(arguments, transport=transport, sleep=sleep, env=env)
        elif name == "list_role_presets":
            payload = _role_presets_tool(arguments)
        elif name == "find_board":
            payload = _find_board_tool(arguments, transport=transport, sleep=sleep)
        else:
            known = ", ".join(str(tool["name"]) for tool in _tool_definitions())
            return _error_response(
                request_id, INVALID_PARAMS, f"unknown tool {name!r}; available tools: {known}"
            )
    except ToolError as exc:
        return _error_response(request_id, INVALID_PARAMS, str(exc))
    text = json.dumps(payload, indent=2)
    return _result_response(
        request_id, {"content": [{"type": "text", "text": text}], "isError": False}
    )


def _handle_line(
    line: str,
    *,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
    env: Mapping[str, str] | None,
) -> dict[str, object] | None:
    """One JSON-RPC message in, one response dict out (None for notifications)."""
    try:
        message = json.loads(line)
    except ValueError as exc:
        return _error_response(None, PARSE_ERROR, f"parse error: {exc}")
    if not isinstance(message, dict):
        return _error_response(None, INVALID_REQUEST, "request must be a JSON object")

    raw_id = message.get("id")
    request_id = raw_id if isinstance(raw_id, str | int | float) else None
    if isinstance(raw_id, bool):
        request_id = None
    is_notification = "id" not in message

    method = message.get("method")
    if not isinstance(method, str) or not method:
        if is_notification:
            return None  # not addressable and not answerable
        return _error_response(request_id, INVALID_REQUEST, "request has no method")

    params_raw = message.get("params")
    params: Mapping[str, object] = params_raw if isinstance(params_raw, dict) else {}
    if params_raw is not None and not isinstance(params_raw, dict):
        if is_notification:
            return None
        return _error_response(request_id, INVALID_REQUEST, "params must be an object")

    if method == "notifications/initialized":
        return None  # acknowledged silently, per the protocol
    if is_notification:
        return None  # JSON-RPC notifications never get replies, known or not
    if method == "initialize":
        return _result_response(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "interninbox", "version": __version__},
        })
    if method == "tools/list":
        return _result_response(request_id, {"tools": _tool_definitions()})
    if method == "tools/call":
        return _handle_tool_call(request_id, params, transport=transport, sleep=sleep, env=env)
    return _error_response(request_id, METHOD_NOT_FOUND, f"unknown method {method!r}")


def serve(
    read_line: Callable[[], str],
    write_line: Callable[[str], None],
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    env: Mapping[str, str] | None = None,
) -> None:
    """Serve MCP over newline-delimited JSON-RPC until `read_line` hits EOF.

    Blank lines are skipped; a malformed line answers with a parse error and
    the loop keeps serving. `transport`, `sleep`, and `env` flow into every
    tool call so tests run fully offline and instant.
    """
    while True:
        line = read_line()
        if line == "" or line is None:
            break
        stripped = line.strip()
        if not stripped:
            continue
        response = _handle_line(stripped, transport=transport, sleep=sleep, env=env)
        if response is not None:
            write_line(json.dumps(response))
