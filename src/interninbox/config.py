"""Load and validate `interninbox.toml`.

Every validation failure raises `ConfigError` with a message a person can
act on; the CLI prints it and exits non-zero, never a traceback.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

KNOWN_ATS = ("greenhouse", "lever", "ashby")

DEFAULT_CONFIG_NAME = "interninbox.toml"


class ConfigError(Exception):
    """A problem in the user's config file, with a friendly message."""


@dataclass(frozen=True)
class Company:
    ats: str  # one of KNOWN_ATS
    slug: str  # the company's board slug on that ATS

    @property
    def label(self) -> str:
        return f"{self.ats}:{self.slug}"


@dataclass(frozen=True)
class Filters:
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    match_keywords: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    remote_ok: bool = True
    # Eligibility (see eligibility.py). Unknown values never drop a listing.
    require_sponsorship: bool = False
    terms: tuple[str, ...] = ()
    degrees: tuple[str, ...] = ()


@dataclass(frozen=True)
class UsaJobsConfig:
    enabled: bool = False
    keywords: tuple[str, ...] = ()
    api_key_env: str = "USAJOBS_API_KEY"
    email: str = ""


@dataclass(frozen=True)
class Config:
    companies: tuple[Company, ...]
    filters: Filters = field(default_factory=Filters)
    registry: str = "none"
    sources: tuple[str, ...] = ()
    usajobs: UsaJobsConfig = field(default_factory=UsaJobsConfig)
    path: Path | None = None


def parse_company(entry: object) -> Company:
    """Parse one `"ats:slug"` shorthand entry."""
    if not isinstance(entry, str):
        raise ConfigError(
            f"companies entries must be strings like \"greenhouse:stripe\", got {entry!r}"
        )
    ats, sep, slug = entry.partition(":")
    if not sep or not slug.strip() or not ats.strip():
        raise ConfigError(
            f"company entry {entry!r} is not in \"ats:slug\" form "
            "(example: \"greenhouse:stripe\")"
        )
    ats = ats.strip().lower()
    slug = slug.strip()
    if ats not in KNOWN_ATS:
        known = ", ".join(KNOWN_ATS)
        raise ConfigError(
            f"unknown ATS {ats!r} in company entry {entry!r}; supported: {known}"
        )
    return Company(ats=ats, slug=slug)


def _string_list(raw: object, *, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ConfigError(f"{where} must be a list of strings")
    return tuple(item.strip() for item in raw if item.strip())


def _boolean(raw: object, *, where: str, default: bool) -> bool:
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise ConfigError(f"{where} must be true or false")
    return raw


def _parse_filters(raw: object) -> Filters:
    if raw is None:
        return Filters()
    if not isinstance(raw, dict):
        raise ConfigError("[filters] must be a table")
    include = _string_list(raw.get("include_keywords"), where="filters.include_keywords")
    exclude = _string_list(raw.get("exclude_keywords"), where="filters.exclude_keywords")
    roles = _string_list(raw.get("roles"), where="filters.roles")
    if roles:
        from interninbox.roles import expand_roles

        try:
            expand_roles(roles)  # validate names now, fail with a friendly message
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
    return Filters(
        include_keywords=include,
        exclude_keywords=exclude,
        match_keywords=_string_list(raw.get("match_keywords"), where="filters.match_keywords"),
        roles=roles,
        locations=_string_list(raw.get("locations"), where="filters.locations"),
        remote_ok=_boolean(raw.get("remote_ok"), where="filters.remote_ok", default=True),
        require_sponsorship=_boolean(
            raw.get("require_sponsorship"), where="filters.require_sponsorship", default=False
        ),
        terms=_string_list(raw.get("terms"), where="filters.terms"),
        degrees=_string_list(raw.get("degrees"), where="filters.degrees"),
    )


def _parse_usajobs(raw: object) -> UsaJobsConfig:
    if raw is None:
        return UsaJobsConfig()
    if not isinstance(raw, dict):
        raise ConfigError("[usajobs] must be a table")
    enabled = _boolean(raw.get("enabled"), where="usajobs.enabled", default=False)
    email = raw.get("email", "")
    if not isinstance(email, str):
        raise ConfigError("usajobs.email must be a string")
    api_key_env = raw.get("api_key_env", "USAJOBS_API_KEY")
    if not isinstance(api_key_env, str) or not api_key_env.strip():
        raise ConfigError("usajobs.api_key_env must be a non-empty string")
    if enabled and not email.strip():
        raise ConfigError(
            "usajobs.enabled is true but usajobs.email is not set. USAJOBS requires "
            "the email address your API key is registered under (it becomes the "
            "User-Agent header, per their documented contract)"
        )
    return UsaJobsConfig(
        enabled=enabled,
        keywords=_string_list(raw.get("keywords"), where="usajobs.keywords"),
        api_key_env=api_key_env.strip(),
        email=email.strip(),
    )


def _registry_tiers() -> tuple[str, ...]:
    from interninbox.registry import TIERS

    return TIERS


def load_config(path: Path) -> Config:
    """Read and validate the config file at `path`."""
    if not path.is_file():
        raise ConfigError(
            f"no config file at {path}; run `interninbox init` to create a starter "
            f"{DEFAULT_CONFIG_NAME}, or pass --config PATH"
        )
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    raw_companies = data.get("companies")
    if raw_companies is None:
        raw_companies = []
    if not isinstance(raw_companies, list):
        raise ConfigError("`companies` must be a list of \"ats:slug\" strings")

    companies = tuple(parse_company(entry) for entry in raw_companies)
    seen: set[str] = set()
    for company in companies:
        if company.label in seen:
            raise ConfigError(f"duplicate company entry {company.label!r}")
        seen.add(company.label)

    usajobs_cfg = _parse_usajobs(data.get("usajobs"))

    registry = data.get("registry", "none")
    if not isinstance(registry, str) or registry not in ("none", *_registry_tiers()):
        raise ConfigError(
            'registry must be one of "none", "top", "all", "large", "startups"'
        )

    sources = _string_list(data.get("sources"), where="sources")
    from interninbox.sources import KNOWN_SOURCES

    for source in sources:
        if source not in KNOWN_SOURCES:
            valid = ", ".join(sorted(KNOWN_SOURCES))
            raise ConfigError(f"unknown source {source!r}; valid sources: {valid}")

    if not companies and not usajobs_cfg.enabled and registry == "none" and not sources:
        raise ConfigError(
            f"{path} configures nothing to scan; add a `companies` list "
            "(e.g. companies = [\"greenhouse:stripe\"]), set registry = \"top\", "
            "add sources = [\"simplify\"], or enable [usajobs]"
        )

    return Config(
        companies=companies,
        filters=_parse_filters(data.get("filters")),
        registry=registry,
        sources=sources,
        usajobs=usajobs_cfg,
        path=path,
    )


STARTER_CONFIG = """\
# interninbox configuration. Edit this, then run `interninbox scan`.

# Target companies as "ats:slug". Find a company's ATS and slug from its
# careers page URL:
#   job-boards.greenhouse.io/<slug>  ->  "greenhouse:<slug>"
#   jobs.lever.co/<slug>             ->  "lever:<slug>"
#   jobs.ashbyhq.com/<slug>          ->  "ashby:<slug>"
# `interninbox companies` prints a starter list of well-known companies.
companies = [
    "greenhouse:stripe",
    "lever:plaid",
    "ashby:linear",
]

# Also sweep the bundled curated registry: "none" (default), "top" (~50
# well-known boards), "all", "large", or "startups". `interninbox companies`
# lists what's in it. Big sweeps take a couple of minutes, by polite design.
# registry = "none"

# Community internship lists to scan too. "simplify" is the SimplifyJobs
# seasonal list (thousands of curated internships across every employer,
# with sponsorship/term/degree metadata) fetched as one polite request.
# sources = ["simplify"]

[filters]
# Extra title keywords to treat as an internship signal, in addition to the
# built-in one (intern, internship, co-op, summer analyst, ...).
include_keywords = []
# Drop any listing whose title contains one of these (case-insensitive).
exclude_keywords = []
# Require at least one of these words in the title, on top of the internship
# signal, i.e. "internship AND security". Whole-word, case-insensitive. This
# NARROWS results; include_keywords above BROADENS them.
match_keywords = []
# Named role presets that narrow to a field. `interninbox roles` lists them.
# Example: roles = ["cybersecurity"]  keeps only security internships.
roles = []
# Keep only listings whose location contains one of these as a whole word
# (case-insensitive): "NY" matches "Albany, NY" but not "Sunnyvale". Empty =
# keep every location. A listing that lists no location at all passes only
# when this is empty.
locations = []
# When true (the default), remote listings pass the locations filter too.
# When false, remote-only listings are dropped.
remote_ok = true
# Hide listings KNOWN to not sponsor visas or to require US citizenship
# (from list metadata and job descriptions). Listings that say nothing are
# always kept; a posting is only hidden on a known disqualifier.
require_sponsorship = false
# Keep only listings for these seasons (e.g. ["Summer 2027"]). Listings
# whose season is unknown are kept.
terms = []
# Keep only listings open to these degrees (e.g. ["Bachelor's"]). Only
# community-list entries carry degree data; unknown is kept.
degrees = []

# Optional: federal internships from USAJOBS (Pathways program).
# Requires a free API key from https://developer.usajobs.gov/apirequest/.
# The email below MUST be the one the key is registered under.
# [usajobs]
# enabled = true
# email = "you@example.com"
# keywords = ["software"]   # each keyword is searched separately (OR)
# api_key_env = "USAJOBS_API_KEY"
"""
