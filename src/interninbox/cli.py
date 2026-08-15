"""The `interninbox` command: init / scan / companies."""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from interninbox import __version__, banner, wizard
from interninbox import companies as companies_mod
from interninbox.config import (
    DEFAULT_CONFIG_NAME,
    Company,
    Config,
    ConfigError,
    load_config,
)
from interninbox.fetch import Fetcher
from interninbox.freshness import parse_since
from interninbox.models import ScanResult
from interninbox.output import format_json, format_markdown, format_table
from interninbox.scan import (
    dedupe_listings,
    effective_filters,
    run_scan,
    scan_boards,
)
from interninbox.state import STATE_FILE_NAME, default_state_path


def entrypoint() -> None:  # pragma: no cover - thin wrapper for the console script
    # Legacy Windows consoles need virtual-terminal mode switched on before
    # ANSI (banner colors, OSC 8 links) renders instead of printing escapes.
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            for handle_id in (-11, -12):  # stdout, stderr
                handle = kernel32.GetStdHandle(handle_id)
                mode = ctypes.c_uint32()
                if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass  # cosmetic only; never block the scan
    # A console that cannot encode a title (Windows legacy codepages under
    # redirection) degrades characters instead of crashing the whole scan.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        code = main()
    except BrokenPipeError:
        # `interninbox scan | head`: stdout is gone. Point fd 1 at devnull so
        # interpreter shutdown doesn't print an ignored-exception warning.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        code = 0
    sys.exit(code)


def _since_arg(text: str) -> object:
    """argparse adapter: surface parse_since's friendly message on bad input."""
    try:
        return parse_since(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="interninbox",
        description="Zero-API-key internship finder: scan your target companies' "
        "public job boards for internships, locally.",
    )
    parser.add_argument("--version", action="version", version=f"interninbox {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help=f"write a starter {DEFAULT_CONFIG_NAME} into the current directory"
    )
    init_parser.set_defaults(func=_cmd_init)

    scan_parser = subparsers.add_parser("scan", help="scan every configured company")
    scan_parser.add_argument(
        "--config",
        type=Path,
        default=Path(DEFAULT_CONFIG_NAME),
        help=f"path to the config file (default: ./{DEFAULT_CONFIG_NAME})",
    )
    output_group = scan_parser.add_mutually_exclusive_group()
    output_group.add_argument("--json", action="store_true", help="output JSON")
    output_group.add_argument("--markdown", action="store_true", help="output a Markdown table")
    scan_parser.add_argument(
        "--new-only",
        action="store_true",
        help="show only listings not seen by a previous scan",
    )
    scan_parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help=f"path to the seen-listings state file (default: {STATE_FILE_NAME} next to "
        "the config, or a name derived from a non-default config filename)",
    )
    scan_parser.add_argument(
        "--interactive",
        action="store_true",
        help="ask location/role/companies questions before scanning "
        "(automatic on a terminal when no config exists)",
    )
    scan_parser.add_argument(
        "--since",
        type=_since_arg,
        default=None,
        metavar="WINDOW",
        help="show only listings posted within this window (7d, 36h, 2w); "
        "undated listings are kept",
    )
    scan_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="suppress the banner and per-company progress lines",
    )
    scan_parser.set_defaults(func=_cmd_scan)

    companies_parser = subparsers.add_parser(
        "companies", help="print a starter list of well-known companies"
    )
    companies_parser.set_defaults(func=_cmd_companies)

    roles_parser = subparsers.add_parser("roles", help="print the role presets")
    roles_parser.set_defaults(func=_cmd_roles)

    find_parser = subparsers.add_parser(
        "find-board", help="probe the supported ATSes for a company's board slug"
    )
    find_parser.add_argument("name", help='company name, e.g. "Acme Corp"')
    find_parser.set_defaults(func=_cmd_find_board)

    mcp_parser = subparsers.add_parser(
        "mcp",
        help="serve the scanner to AI agents over MCP (JSON-RPC on stdin/stdout)",
    )
    mcp_parser.set_defaults(func=_cmd_mcp)

    return parser


def main(
    argv: list[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    env: Mapping[str, str] | None = None,
    input_fn: Callable[[str], str] | None = None,
) -> int:
    """CLI entry. `transport`, `sleep`, `env`, `input_fn` are injectable for tests."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        resolved_env = env if env is not None else os.environ
        return args.func(
            args, transport=transport, sleep=sleep, env=resolved_env, input_fn=input_fn
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


def _cmd_init(args: argparse.Namespace, **_: object) -> int:
    from interninbox.config import STARTER_CONFIG

    target = Path.cwd() / DEFAULT_CONFIG_NAME
    if target.exists():
        print(f"error: {target} already exists, not overwriting it", file=sys.stderr)
        return 1
    try:
        target.write_text(STARTER_CONFIG, encoding="utf-8")
    except OSError as exc:
        print(f"error: could not write {target}: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {target}")
    print("Next steps:")
    print(f"  1. Edit {DEFAULT_CONFIG_NAME} to add your target companies")
    print("     (`interninbox companies` prints a starter list)")
    print("  2. Run `interninbox scan`")
    return 0


def _cmd_companies(args: argparse.Namespace, **_: object) -> int:
    print(companies_mod.render())
    return 0


def _cmd_roles(args: argparse.Namespace, **_: object) -> int:
    from interninbox import roles as roles_mod

    print(roles_mod.render())
    return 0


def _cmd_find_board(
    args: argparse.Namespace,
    *,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
    **_: object,
) -> int:
    from interninbox.discover import find_boards

    with Fetcher(transport=transport, sleep=sleep) as fetcher:
        found = find_boards(fetcher, args.name)
    if not found:
        print(
            f"no board found for {args.name!r} on the supported ATSes. The slug may "
            "be unusual: open the company's careers page and read the URL "
            "(job-boards.greenhouse.io/<slug>, jobs.lever.co/<slug>, "
            "jobs.ashbyhq.com/<slug>, jobs.smartrecruiters.com/<slug>).",
            file=sys.stderr,
        )
        return 1
    print("# add to interninbox.toml under companies = [...]")
    for label in found:
        print(f'"{label}",')
    return 0


def _cmd_mcp(
    args: argparse.Namespace,
    *,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
    env: Mapping[str, str],
    **_: object,
) -> int:
    """Speak MCP over stdio: stdin lines in, JSON-RPC lines out, nothing else.

    stdout carries only protocol lines (no banner, flushed per line so the
    client never waits on a buffer) and stderr stays silent. EOF ends the
    loop with 0; Ctrl-C exits quietly with 130, without the "interrupted"
    note an interactive scan prints (an MCP client owns this process, and
    noise on shutdown would only alarm it).
    """
    from interninbox import mcp

    def write_line(text: str) -> None:
        print(text, flush=True)

    try:
        mcp.serve(sys.stdin.readline, write_line, transport=transport, sleep=sleep, env=env)
    except KeyboardInterrupt:
        return 130
    return 0


# The scan machinery lives in interninbox.scan now; these names stay on the
# cli module (they are its historical surface, and tests import them here).
_effective_filters = effective_filters
_dedupe_listings = dedupe_listings


def _scan_boards(
    companies: tuple[Company, ...],
    fetcher: Fetcher,
    result: ScanResult,
    *,
    progress: bool = False,
    content: bool = False,
) -> None:
    """Compatibility wrapper over scan.scan_boards with the old bool progress."""
    scan_boards(
        companies,
        fetcher,
        result,
        progress=_stderr_line if progress else None,
        content=content,
    )


def _stderr_line(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _cmd_scan(
    args: argparse.Namespace,
    *,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
    env: Mapping[str, str],
    input_fn: Callable[[str], str] | None,
) -> int:
    # Brand banner: interactive terminals only, never on machine output, and
    # only to stderr so it can never corrupt piped --json / --markdown.
    if sys.stderr.isatty() and not (args.quiet or args.json or args.markdown):
        print(banner.render_banner(color=not env.get("NO_COLOR")), file=sys.stderr)

    wizard_wants = args.interactive or (
        not args.config.is_file() and sys.stdin.isatty() and sys.stderr.isatty()
    )
    answers = None
    if wizard_wants:
        ask = input_fn if input_fn is not None else input
        existing = load_config(args.config) if args.config.is_file() else None
        answers = wizard.run(
            input_fn=ask,
            print_fn=lambda line: print(line, file=sys.stderr),
            config_companies=len(existing.companies) if existing else 0,
        )
        # Rebase on the existing config (or an empty one) so an --interactive
        # run only overrides what the wizard actually asked about: locations,
        # roles, and the registry tier. Everything else the user configured
        # (exclude_keywords, match_keywords, remote_ok, [usajobs]) survives.
        base = existing if existing is not None else Config(companies=())
        config = dataclasses.replace(
            base,
            filters=dataclasses.replace(
                base.filters,
                locations=answers.locations,
                roles=answers.roles,
                require_sponsorship=answers.require_sponsorship,
            ),
            registry=base.registry if answers.tier == "config" else answers.tier,
            sources=("simplify",) if answers.include_list else base.sources,
        )
    else:
        config = load_config(args.config)
    state_path = args.state if args.state else default_state_path(args.config)

    show_progress = sys.stderr.isatty() and not args.quiet

    def progress(line: str, *, essential: bool = False) -> None:
        # Essential lines (the state warning, the scale note) always print;
        # per-company progress only on an interactive, non-quiet terminal.
        if essential or show_progress:
            _stderr_line(line)

    result = run_scan(
        config,
        new_only=args.new_only,
        since=args.since,
        transport=transport,
        sleep=sleep,
        env=env,
        progress=progress,
        state_path=state_path,
    )

    for note in result.notes:
        print(note, file=sys.stderr)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if args.json:
        print(format_json(result))
    elif args.markdown:
        print(format_markdown(result))
    else:
        hyperlinks = sys.stdout.isatty() and not env.get("NO_COLOR")
        print(format_table(result, hyperlinks=hyperlinks))

    if answers is not None and not args.config.is_file() and answers.tier != "config":
        ask = input_fn if input_fn is not None else input
        reply = ask(f"Save these choices to {args.config}? [y/N] ").strip().lower()
        if reply in ("y", "yes"):
            args.config.write_text(wizard.render_config(answers), encoding="utf-8")
            print(f"Wrote {args.config}. Next time, plain `interninbox scan` "
                  "uses it.", file=sys.stderr)

    attempted = result.companies_scanned + result.companies_failed
    if attempted and result.companies_scanned == 0 and result.sources_scanned == 0:
        print("error: every configured company failed; is the network down?", file=sys.stderr)
        return 1
    return 0
