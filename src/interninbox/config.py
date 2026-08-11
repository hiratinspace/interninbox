"""Load and validate `interninbox.toml`.

Every validation failure raises `ConfigError` with a message a person can
act on — the CLI prints it and exits non-zero, never a traceback.
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
    locations: tuple[str, ...] = ()
    remote_ok: bool = True


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
            f"unknown ATS {ats!r} in company entry {entry!r} — supported: {known}"
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
    return Filters(
        include_keywords=include,
        exclude_keywords=exclude,
        locations=_string_list(raw.get("locations"), where="filters.locations"),
        remote_ok=_boolean(raw.get("remote_ok"), where="filters.remote_ok", default=True),
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
            "usajobs.enabled is true but usajobs.email is not set — USAJOBS requires "
            "the email address your API key is registered under (it becomes the "
            "User-Agent header, per their documented contract)"
        )
    return UsaJobsConfig(
        enabled=enabled,
        keywords=_string_list(raw.get("keywords"), where="usajobs.keywords"),
        api_key_env=api_key_env.strip(),
        email=email.strip(),
    )


def load_config(path: Path) -> Config:
    """Read and validate the config file at `path`."""
    if not path.is_file():
        raise ConfigError(
            f"no config file at {path} — run `interninbox init` to create a starter "
            f"{DEFAULT_CONFIG_NAME}, or pass --config PATH"
        )
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    raw_companies = data.get("companies")
    if raw_companies is None:
        raise ConfigError(
            f"{path} has no `companies` list — add e.g. companies = [\"greenhouse:stripe\"]"
        )
    if not isinstance(raw_companies, list) or not raw_companies:
        raise ConfigError("`companies` must be a non-empty list of \"ats:slug\" strings")

    companies = tuple(parse_company(entry) for entry in raw_companies)
    seen: set[str] = set()
    for company in companies:
        if company.label in seen:
            raise ConfigError(f"duplicate company entry {company.label!r}")
        seen.add(company.label)

    return Config(
        companies=companies,
        filters=_parse_filters(data.get("filters")),
        usajobs=_parse_usajobs(data.get("usajobs")),
        path=path,
    )


STARTER_CONFIG = """\
# interninbox configuration — edit this, then run `interninbox scan`.

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

[filters]
# Extra title keywords to treat as an internship signal, in addition to the
# built-in one (intern, internship, co-op, summer analyst, ...).
include_keywords = []
# Drop any listing whose title contains one of these (case-insensitive).
exclude_keywords = []
# Keep only listings whose location contains one of these substrings
# (case-insensitive). Empty = keep every location. A listing that lists no
# location at all passes only when this is empty.
locations = []
# When true (the default), remote listings pass the locations filter too.
# When false, remote-only listings are dropped.
remote_ok = true

# Optional: federal internships from USAJOBS (Pathways program).
# Requires a free API key from https://developer.usajobs.gov/apirequest/ —
# the email below MUST be the one the key is registered under.
# [usajobs]
# enabled = true
# email = "you@example.com"
# keywords = ["software"]
# api_key_env = "USAJOBS_API_KEY"
"""
