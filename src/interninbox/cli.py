"""The `interninbox` command: init / scan / companies."""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import time
import urllib.parse
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from interninbox import __version__, banner, wizard
from interninbox import companies as companies_mod
from interninbox import registry as registry_mod
from interninbox import sources as sources_mod
from interninbox.adapters import ADAPTERS, usajobs
from interninbox.config import (
    DEFAULT_CONFIG_NAME,
    Company,
    Config,
    ConfigError,
    Filters,
    load_config,
)
from interninbox.fetch import Fetcher
from interninbox.filters import matches
from interninbox.freshness import apply_since, parse_since
from interninbox.locations import expand_location_terms
from interninbox.models import AdapterError, Listing, ScanResult
from interninbox.output import format_json, format_markdown, format_table
from interninbox.roles import expand_roles
from interninbox.state import STATE_FILE_NAME, default_state_path, load_state


def entrypoint() -> None:  # pragma: no cover - thin wrapper for the console script
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


def _effective_filters(config: Config) -> Filters:
    """Scan-time filter view: aliases expanded, role presets merged in."""
    role_keywords = expand_roles(config.filters.roles)
    merged = config.filters.match_keywords + tuple(
        keyword for keyword in role_keywords
        if keyword not in config.filters.match_keywords
    )
    return dataclasses.replace(
        config.filters,
        match_keywords=merged,
        locations=expand_location_terms(config.filters.locations),
    )


def _effective_companies(config: Config) -> tuple[Company, ...]:
    """Config companies first, then the chosen registry tier (deduped)."""
    companies = list(config.companies)
    if config.registry != "none":
        listed = {company.label for company in companies}
        for entry in registry_mod.select(config.registry):
            company = Company(ats=entry.ats, slug=entry.slug)
            if company.label not in listed:
                listed.add(company.label)
                companies.append(company)
    return tuple(companies)


def _normalize_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"


def _dedupe_listings(listings: list[Listing]) -> list[Listing]:
    """Collapse the same posting seen via a board AND a community list.

    The direct board version wins (fresher title and locations), but inherits
    any eligibility metadata only the list knew (sponsorship, terms, degrees).
    Order-preserving; first occurrence keeps its position.
    """
    by_url: dict[str, int] = {}
    kept: list[Listing] = []
    for listing in listings:
        key = _normalize_url(listing.url)
        index = by_url.get(key)
        if index is None:
            by_url[key] = len(kept)
            kept.append(listing)
            continue
        existing = kept[index]
        base, extra = (
            (existing, listing) if listing.curated or not existing.curated
            else (listing, existing)
        )
        kept[index] = dataclasses.replace(
            base,
            sponsorship=base.sponsorship or extra.sponsorship,
            terms=base.terms or extra.terms,
            degrees=base.degrees or extra.degrees,
        )
    return kept


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
    state = load_state(state_path)
    if state.warning:
        print(f"warning: {state.warning}", file=sys.stderr)

    companies = _effective_companies(config)
    filters = _effective_filters(config)
    if len(companies) >= 20:
        note = (
            f"scanning {len(companies)} boards, roughly "
            f"{registry_mod.estimate_label_for(companies)} at polite pacing"
        )
        if filters.require_sponsorship:
            note += " (downloading descriptions for the sponsorship filter)"
        print(note, file=sys.stderr)

    progress = sys.stderr.isatty() and not args.quiet
    result = ScanResult()
    with Fetcher(transport=transport, sleep=sleep) as fetcher:
        # Descriptions are only worth fetching when a filter reads them.
        _scan_boards(
            companies, fetcher, result, progress=progress, content=filters.require_sponsorship
        )
        _scan_usajobs(config, fetcher, env, result, progress=progress)
        _scan_sources(config, fetcher, result, progress=progress)

    result.listings = _dedupe_listings(result.listings)
    result.listings_checked = len(result.listings)
    matched = [listing for listing in result.listings if matches(listing, filters)]
    if args.since is not None:
        matched = apply_since(matched, args.since)
    result.listings_matched = len(matched)
    shown = [listing for listing in matched if state.is_new(listing)] if args.new_only else matched
    # Record EVERYTHING fetched, flag or not, so "new" means "never fetched
    # before": loosening a filter later cannot flood --new-only with old posts.
    state.record(result.listings)
    result.listings = shown
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


def _scan_boards(
    companies: tuple[Company, ...],
    fetcher: Fetcher,
    result: ScanResult,
    *,
    progress: bool = False,
    content: bool = False,
) -> None:
    total = len(companies)
    for index, company in enumerate(companies, start=1):
        if progress:
            print(f"[{index}/{total}] {company.label} ...", file=sys.stderr, flush=True)
        adapter_fetch = ADAPTERS[company.ats]
        try:
            listings = adapter_fetch(
                fetcher, company.slug, content=content, warn=result.warnings.append
            )
        except AdapterError as exc:
            result.companies_failed += 1
            result.warnings.append(f"{company.label}: {exc}")
            continue
        result.companies_scanned += 1
        result.listings.extend(listings)


def _scan_sources(
    config: Config, fetcher: Fetcher, result: ScanResult, *, progress: bool = False
) -> None:
    for name in config.sources:
        if progress:
            print(f"[source] {name} ...", file=sys.stderr, flush=True)
        try:
            listings = sources_mod.fetch_source(fetcher, name, warn=result.warnings.append)
        except AdapterError as exc:
            result.companies_failed += 1
            result.warnings.append(f"source {name}: {exc}")
            continue
        result.sources_scanned += 1
        result.listings.extend(listings)


def _scan_usajobs(
    config: Config,
    fetcher: Fetcher,
    env: Mapping[str, str],
    result: ScanResult,
    *,
    progress: bool = False,
) -> None:
    cfg = config.usajobs
    if not cfg.enabled:
        return
    api_key = env.get(cfg.api_key_env, "").strip()
    if not api_key:
        result.notes.append(
            f"usajobs: enabled but {cfg.api_key_env} is not set, skipping "
            "(get a free key at https://developer.usajobs.gov/apirequest/)"
        )
        return
    if progress:
        print("[usajobs] data.usajobs.gov ...", file=sys.stderr, flush=True)
    try:
        listings = usajobs.fetch(fetcher, cfg, api_key, warn=result.warnings.append)
    except AdapterError as exc:
        result.companies_failed += 1
        result.warnings.append(f"usajobs: {exc}")
        return
    result.companies_scanned += 1
    result.listings.extend(listings)
