"""The `interninbox` command: init / scan / companies."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from interninbox import __version__
from interninbox import companies as companies_mod
from interninbox.adapters import ADAPTERS, usajobs
from interninbox.config import (
    DEFAULT_CONFIG_NAME,
    Config,
    ConfigError,
    load_config,
)
from interninbox.fetch import Fetcher
from interninbox.filters import matches
from interninbox.models import AdapterError, ScanResult
from interninbox.output import format_json, format_markdown, format_table
from interninbox.state import STATE_FILE_NAME, load_state


def entrypoint() -> None:  # pragma: no cover - thin wrapper for the console script
    sys.exit(main())


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
        help=f"path to the seen-listings state file (default: {STATE_FILE_NAME} "
        "next to the config)",
    )
    scan_parser.set_defaults(func=_cmd_scan)

    companies_parser = subparsers.add_parser(
        "companies", help="print a starter list of well-known companies"
    )
    companies_parser.set_defaults(func=_cmd_companies)

    return parser


def main(
    argv: list[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    env: Mapping[str, str] | None = None,
) -> int:
    """CLI entry. `transport`, `sleep`, and `env` are injectable for tests."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        resolved_env = env if env is not None else os.environ
        return args.func(args, transport=transport, sleep=sleep, env=resolved_env)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _cmd_init(args: argparse.Namespace, **_: object) -> int:
    from interninbox.config import STARTER_CONFIG

    target = Path.cwd() / DEFAULT_CONFIG_NAME
    if target.exists():
        print(f"error: {target} already exists — not overwriting it", file=sys.stderr)
        return 1
    target.write_text(STARTER_CONFIG, encoding="utf-8")
    print(f"Wrote {target}")
    print("Next steps:")
    print(f"  1. Edit {DEFAULT_CONFIG_NAME} — add your target companies")
    print("     (`interninbox companies` prints a starter list)")
    print("  2. Run `interninbox scan`")
    return 0


def _cmd_companies(args: argparse.Namespace, **_: object) -> int:
    print(companies_mod.render())
    return 0


def _cmd_scan(
    args: argparse.Namespace,
    *,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
    env: Mapping[str, str],
) -> int:
    config = load_config(args.config)
    state_path = args.state if args.state else args.config.resolve().parent / STATE_FILE_NAME
    state = load_state(state_path)
    if state.warning:
        print(f"warning: {state.warning}", file=sys.stderr)

    result = ScanResult()
    with Fetcher(transport=transport, sleep=sleep) as fetcher:
        _scan_boards(config, fetcher, result)
        _scan_usajobs(config, fetcher, env, result)

    matched = [listing for listing in result.listings if matches(listing, config.filters)]
    shown = [listing for listing in matched if state.is_new(listing)] if args.new_only else matched
    result.listings = shown

    # Always update state — flag or not — so "new" means "since last scan".
    state.record(matched)
    try:
        state.save(state_path)
    except OSError as exc:
        result.warnings.append(f"could not write state file {state_path}: {exc}")

    for note in result.notes:
        print(note, file=sys.stderr)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if args.json:
        print(format_json(result))
    elif args.markdown:
        print(format_markdown(result))
    else:
        print(format_table(result))

    attempted = result.companies_scanned + result.companies_failed
    if attempted and result.companies_scanned == 0:
        print("error: every configured company failed — is the network down?", file=sys.stderr)
        return 1
    return 0


def _scan_boards(config: Config, fetcher: Fetcher, result: ScanResult) -> None:
    for company in config.companies:
        adapter_fetch = ADAPTERS[company.ats]
        try:
            listings = adapter_fetch(fetcher, company.slug)
        except AdapterError as exc:
            result.companies_failed += 1
            result.warnings.append(f"{company.label}: {exc}")
            continue
        result.companies_scanned += 1
        result.listings.extend(listings)


def _scan_usajobs(
    config: Config, fetcher: Fetcher, env: Mapping[str, str], result: ScanResult
) -> None:
    cfg = config.usajobs
    if not cfg.enabled:
        return
    api_key = env.get(cfg.api_key_env, "").strip()
    if not api_key:
        result.notes.append(
            f"usajobs: enabled but {cfg.api_key_env} is not set — skipping "
            "(get a free key at https://developer.usajobs.gov/apirequest/)"
        )
        return
    try:
        listings = usajobs.fetch(fetcher, cfg, api_key)
    except AdapterError as exc:
        result.companies_failed += 1
        result.warnings.append(f"usajobs: {exc}")
        return
    result.companies_scanned += 1
    result.listings.extend(listings)
