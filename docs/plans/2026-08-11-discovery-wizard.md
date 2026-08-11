# Discovery Update Implementation Plan — locations, roles, registry, wizard

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users search by location (country / US state, with alias intelligence), by role type (named presets), and across a large curated registry of big *and* small companies — through an interactive first-run wizard, while cron/scripted use stays byte-for-byte compatible.

**Architecture:** Three new pure-data/pure-function modules (`locations.py`, `roles.py`, `registry.py`) feed a thin "effective config" layer in `cli.py` that expands aliases and role presets into the existing whole-word filter machinery and unions registry tiers into the company list. A `wizard.py` with an injectable input function drives the interactive flow (no-config TTY runs and `scan --interactive`); it produces the same effective options and can persist them as a generated `interninbox.toml`. Nothing about fetching, filtering internals, output, or state changes.

**Approved design decisions (user-confirmed):**
- Wizard triggers ONLY when (a) `scan` runs with no config file on a real terminal, or (b) `--interactive` is passed. Existing configs and non-TTY (cron/pipes) behave exactly as today.
- Registry choices are presented as options with rough scan-time estimates (politeness makes big sweeps take minutes; say so up front).
- Registry target ~120 verified companies (mix of `large`/`startup`, industry tags, ~50-company `top` tier). **Every shipped slug must be live-verified; unverified candidates are dropped.**
- No new list syntax: `companies` in a config is the user's list; multiple lists = multiple config files (per-config state already exists).
- Out of scope: slug crawling/discovery, fuzzy geocoding, USAJOBS prompts in the wizard.

**Tech Stack:** Python ≥3.11, httpx (only runtime dep — do not add more), pytest + httpx.MockTransport (offline), ruff, uv, hatchling.

## Global Constraints

- Work on branch `discovery-wizard` (created from up-to-date `main`; PR #7 is already merged).
- No new runtime dependencies. All tests offline (`httpx.MockTransport`, synthetic fixtures). The ONLY network step in this plan is the maintainer registry-verification script in Task 3, run manually during authoring — never from tests.
- Anticipated failures never traceback (`ConfigError` + stderr + exit code).
- Politeness invariants unchanged (sequential, ≥500 ms/host, 15 s timeout, one retry, honest UA).
- Gates before every commit: `.venv/bin/python -m pytest -q` AND `.venv/bin/ruff check .` (line length 100; rules E,F,W,I,UP,B).
- Commit style as in `git log` (`feat:`/`fix:`/`docs:` + body), ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Suite currently at 157 passing. Tasks state explicitly when an existing test's expectation changes; any other failure means your implementation is wrong — fix it, never weaken a test.
- Wizard/registry code must never run in tests via real TTY detection — tests always go through `--interactive` or injected `input_fn`.

---

### Task 1: Location alias expansion (`locations.py`)

**Files:**
- Create: `src/interninbox/locations.py`
- Modify: `src/interninbox/cli.py` (effective-filters layer)
- Test: `tests/test_locations.py` (new), `tests/test_cli.py`

**Interfaces:**
- Produces: `locations.expand_location_terms(terms: tuple[str, ...]) -> tuple[str, ...]` — returns the input terms plus every known alias, order-preserving, case-insensitively deduped. `cli._effective_filters(config: Config) -> Filters` — the single place scan-time expansion happens (Task 2 extends it with roles; Task 5 reuses it).

- [ ] **Step 1: Write the failing tests.** Create `tests/test_locations.py`:

```python
"""US-state / country alias expansion for location filters."""

from interninbox.locations import expand_location_terms


def test_state_abbreviation_gains_full_name() -> None:
    assert "California" in expand_location_terms(("CA",))
    assert "CA" in expand_location_terms(("CA",))  # original term kept, first


def test_full_name_gains_abbreviation() -> None:
    assert "CA" in expand_location_terms(("California",))
    assert "WA" in expand_location_terms(("washington",))  # case-insensitive lookup


def test_common_aliases() -> None:
    assert "New York" in expand_location_terms(("NYC",))
    assert "United Kingdom" in expand_location_terms(("UK",))
    assert "United States" in expand_location_terms(("USA",))


def test_unknown_terms_pass_through_unchanged() -> None:
    assert expand_location_terms(("Germany",)) == ("Germany",)


def test_no_duplicates_and_order_preserved() -> None:
    expanded = expand_location_terms(("CA", "California", "Berlin"))
    assert expanded[0] == "CA"
    assert len([t for t in expanded if t.lower() == "california"]) == 1
    assert expanded[-1] == "Berlin"


def test_empty_input_is_empty() -> None:
    assert expand_location_terms(()) == ()
```

And append to `tests/test_cli.py` (uses the ashby fixture's "Seattle, WA" jobs):

```python
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
```

- [ ] **Step 2: Verify RED** — `.venv/bin/python -m pytest tests/test_locations.py tests/test_cli.py -q` → `test_locations.py` fails with `ModuleNotFoundError: interninbox.locations`; the CLI test fails (no expansion, "Washington" ≠ "WA").

- [ ] **Step 3: Implement.** Create `src/interninbox/locations.py`:

```python
"""Location alias intelligence: US states/DC and common country/city forms.

Board location strings are free text; whole-word matching (filters.py) fixed
substring false-positives, but "CA" vs "California" remained the user's
problem. Expanding each filter term to its known aliases closes the common
cases; genuinely unknown terms pass through unchanged.
"""

from __future__ import annotations

# Full name -> USPS abbreviation, all 50 states + DC.
US_STATES: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
}

# Groups of equivalent spellings beyond the states table. Each group expands
# to all of its members whenever any member is used as a filter term.
_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("New York", "NYC", "NY"),
    ("United States", "USA", "US"),
    ("United Kingdom", "UK", "Great Britain"),
    ("Washington, D.C.", "Washington DC", "D.C.", "DC"),
    ("San Francisco", "SF"),
    ("Los Angeles", "LA"),
)


def _alias_map() -> dict[str, tuple[str, ...]]:
    """lowercased term -> every equivalent spelling (including itself)."""
    groups: dict[str, set[str]] = {}
    for name, abbr in US_STATES.items():
        for term in (name, abbr):
            groups.setdefault(term.lower(), set()).update((name, abbr))
    for group in _ALIAS_GROUPS:
        for term in group:
            groups.setdefault(term.lower(), set()).update(group)
    return {key: tuple(sorted(values)) for key, values in groups.items()}


_ALIASES = _alias_map()


def expand_location_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    """Each term, followed by its known aliases; deduped case-insensitively."""
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        for candidate in (term, *_ALIASES.get(term.strip().lower(), ())):
            if candidate.lower() not in seen:
                seen.add(candidate.lower())
                out.append(candidate)
    return tuple(out)
```

In `src/interninbox/cli.py`: add imports `import dataclasses` (stdlib group) and `from interninbox.locations import expand_location_terms`. Add above `_cmd_scan`:

```python
def _effective_filters(config: Config) -> Filters:
    """Scan-time filter view: config values with aliases expanded."""
    return dataclasses.replace(
        config.filters,
        locations=expand_location_terms(config.filters.locations),
    )
```

`Filters` must be imported in cli (extend the existing `from interninbox.config import (...)` block with `Filters`). In `_cmd_scan`, replace the matching line:

```python
    matched = [listing for listing in result.listings if matches(listing, config.filters)]
```

with:

```python
    filters = _effective_filters(config)
    matched = [listing for listing in result.listings if matches(listing, filters)]
```

- [ ] **Step 4: Verify GREEN** — full `pytest -q` (163 expected) + `ruff check .`.

- [ ] **Step 5: Commit** — `git add src/interninbox/locations.py src/interninbox/cli.py tests/test_locations.py tests/test_cli.py`; message:

```
feat: location aliases — US states, DC, and common forms

"California" now also matches boards that write "CA" (and vice versa),
NYC<->New York, UK<->United Kingdom, US/USA<->United States. Expansion
happens at scan time in a new _effective_filters layer; config values
stay raw and unknown terms pass through unchanged.

Closes most of KNOWN-ISSUES M4's remaining alias half.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

---

### Task 2: Role presets (`roles.py`, `[filters] roles`, `interninbox roles`)

**Files:**
- Create: `src/interninbox/roles.py`
- Modify: `src/interninbox/config.py` (Filters.roles, parsing, starter config), `src/interninbox/cli.py` (`roles` subcommand, effective-filters merge)
- Test: `tests/test_roles.py` (new), `tests/test_config.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `roles.ROLE_PRESETS: dict[str, tuple[str, ...]]`; `roles.expand_roles(names: tuple[str, ...]) -> tuple[str, ...]` (union of keyword lists, deduped, order-preserving; raises `ValueError` naming the unknown role and listing valid ones — config wraps it into `ConfigError`); `Filters.roles: tuple[str, ...] = ()`. Task 5's wizard consumes `ROLE_PRESETS` for its menu.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_roles.py`:

```python
"""Role presets expand to whole-word keyword sets."""

import pytest

from interninbox.roles import ROLE_PRESETS, expand_roles


def test_every_preset_is_nonempty_lowercase() -> None:
    assert ROLE_PRESETS  # ships with presets
    for name, keywords in ROLE_PRESETS.items():
        assert name == name.lower() and keywords
        assert all(kw == kw.lower() for kw in keywords)


def test_expand_unions_and_dedupes() -> None:
    both = expand_roles(("software", "data"))
    assert set(ROLE_PRESETS["software"]).issubset(both)
    assert set(ROLE_PRESETS["data"]).issubset(both)
    assert len(both) == len(set(both))


def test_unknown_role_names_valid_ones() -> None:
    with pytest.raises(ValueError, match="cybersecurity"):
        expand_roles(("underwater-basketweaving",))


def test_no_overbroad_engineer_keyword() -> None:
    # Bare "engineer" would match every engineering discipline.
    for keywords in ROLE_PRESETS.values():
        assert "engineer" not in keywords and "engineering" not in keywords
```

Append to `tests/test_config.py`:

```python
def test_filters_roles_parsed_and_validated(tmp_path: Path) -> None:
    path = tmp_path / "interninbox.toml"
    path.write_text(
        'companies = ["greenhouse:stripe"]\n[filters]\nroles = ["cybersecurity"]\n',
        encoding="utf-8",
    )
    assert load_config(path).filters.roles == ("cybersecurity",)

    path.write_text(
        'companies = ["greenhouse:stripe"]\n[filters]\nroles = ["wizardry"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="wizardry"):
        load_config(path)
```

Append to `tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Verify RED** — targeted run: `ModuleNotFoundError: interninbox.roles`; config test `TypeError`/no-error; CLI `roles` exits 2 (unknown command).

- [ ] **Step 3: Implement.** Create `src/interninbox/roles.py`:

```python
"""Named role presets — curated whole-word keyword sets for match_keywords.

Each preset narrows results to "internship AND (any of these words)" via the
existing match_keywords machinery. Keywords are whole-word matched, so they
must be specific: bare "engineer" would match every engineering discipline
and is deliberately absent. `interninbox roles` prints this table so nothing
is magic.
"""

from __future__ import annotations

ROLE_PRESETS: dict[str, tuple[str, ...]] = {
    "software": (
        "software", "swe", "developer", "backend", "back end", "frontend",
        "front end", "full stack", "fullstack", "platform", "mobile", "ios",
        "android", "devops", "sre", "site reliability", "computer science",
        "programming", "web",
    ),
    "data": (
        "data", "machine learning", "ml", "ai", "analytics", "data science",
        "business intelligence", "statistics", "quantitative", "quant",
    ),
    "cybersecurity": (
        "security", "cybersecurity", "cyber", "infosec", "information security",
        "threat", "soc", "appsec", "application security", "penetration",
        "pentest", "vulnerability", "grc", "incident response",
    ),
    "finance": (
        "finance", "financial", "accounting", "audit", "tax", "treasury",
        "investment", "banking", "equity research", "fp&a", "underwriting",
        "actuarial",
    ),
    "business": (
        "business", "management", "operations", "consulting", "strategy",
        "supply chain", "logistics", "procurement", "project management",
        "program management", "sales", "partnerships",
    ),
    "marketing": (
        "marketing", "growth", "brand", "communications", "social media",
        "content", "seo", "public relations",
    ),
    "design": (
        "design", "ux", "ui", "user experience", "product design",
        "graphic", "visual", "industrial design",
    ),
    "product": (
        "product", "product management", "apm", "technical program",
    ),
    "hardware": (
        "hardware", "electrical", "mechanical", "embedded", "firmware",
        "robotics", "manufacturing", "aerospace", "semiconductor", "asic",
        "fpga",
    ),
}


def expand_roles(names: tuple[str, ...]) -> tuple[str, ...]:
    """Union of the named presets' keywords, deduped, order-preserving.

    Raises ValueError naming the unknown role and the valid choices.
    """
    keywords: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = name.strip().lower()
        if key not in ROLE_PRESETS:
            valid = ", ".join(sorted(ROLE_PRESETS))
            raise ValueError(f"unknown role {name!r} — valid roles: {valid}")
        for keyword in ROLE_PRESETS[key]:
            if keyword not in seen:
                seen.add(keyword)
                keywords.append(keyword)
    return tuple(keywords)


def render() -> str:
    lines = ["Role presets (use in [filters] roles = [...] or pick in the wizard):", ""]
    for name in sorted(ROLE_PRESETS):
        lines.append(f"  {name}")
        lines.append(f"      {', '.join(ROLE_PRESETS[name])}")
    lines.append("")
    lines.append("A role keeps only internships whose title contains one of its words "
                 "(whole-word).")
    return "\n".join(lines)
```

`src/interninbox/config.py` — `Filters` gains `roles: tuple[str, ...] = ()` (place after `match_keywords`). In `_parse_filters`, add before the `return`:

```python
    roles = _string_list(raw.get("roles"), where="filters.roles")
    if roles:
        from interninbox.roles import expand_roles

        try:
            expand_roles(roles)  # validate names now, fail with a friendly message
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
```

and pass `roles=roles` in the `Filters(...)` construction. (Import inside the function avoids a module cycle: roles.py imports nothing from config.) In `STARTER_CONFIG`, after the `match_keywords = []` lines add:

```toml
# Named role presets that narrow to a field — `interninbox roles` lists them.
# Example: roles = ["cybersecurity"]  keeps only security internships.
roles = []
```

`src/interninbox/cli.py` — extend `_effective_filters` to merge role keywords into match_keywords:

```python
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
```

with `from interninbox.roles import expand_roles` added to imports, plus the subcommand in `build_parser` (after the companies parser):

```python
    roles_parser = subparsers.add_parser("roles", help="print the role presets")
    roles_parser.set_defaults(func=_cmd_roles)
```

and next to `_cmd_companies`:

```python
def _cmd_roles(args: argparse.Namespace, **_: object) -> int:
    from interninbox import roles as roles_mod

    print(roles_mod.render())
    return 0
```

- [ ] **Step 4: Verify GREEN** — full suite + ruff. Semantics check the tests already lock in: `roles` AND user `match_keywords` merge as one OR-list (both express "what I want to see").

- [ ] **Step 5: Commit** — `feat: role presets — scan by field with 'roles = [\"cybersecurity\"]'` (body: presets expand into match_keywords; `interninbox roles` prints the exact keywords; unknown roles fail with the valid list; trailer as always).

---

### Task 3: The curated registry (`registry.py`) + `interninbox companies` rewrite

**Files:**
- Create: `src/interninbox/registry.py`, `scripts/verify_registry.py`
- Modify: `src/interninbox/companies.py`
- Test: `tests/test_registry.py` (new)

**Interfaces:**
- Produces: `RegistryCompany` (frozen dataclass: `ats: str`, `slug: str`, `name: str`, `size: str` — `"large"|"startup"`, `tags: tuple[str, ...]`, `top: bool`); `REGISTRY: tuple[RegistryCompany, ...]`; `TIERS = ("top", "all", "large", "startups")`; `select(tier: str) -> tuple[RegistryCompany, ...]`; `estimate_label(count: int) -> str` (e.g. `"~40 s"`, `"~2 min"`). Task 4 wires `select` into scan; Task 5's wizard uses `select` + `estimate_label`.
- `companies.py` keeps its public `render()` (cli untouched) but renders from the registry. **Existing-test note:** `tests/test_cli.py::test_companies_lists_starter_entries` asserts `"greenhouse:stripe"`, `"lever:plaid"`, `"ashby:linear"` (quoted form) and the word "verify" — the new renderer and registry must keep all four true.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_registry.py`:

```python
"""Registry shape, tiers, and estimates — data-integrity tests, all offline."""

import pytest

from interninbox.config import KNOWN_ATS
from interninbox.registry import REGISTRY, TIERS, estimate_label, select


def test_registry_is_reasonably_large_and_mixed() -> None:
    assert len(REGISTRY) >= 100
    sizes = {entry.size for entry in REGISTRY}
    assert sizes == {"large", "startup"}  # update 4: big AND small every run


def test_entries_are_wellformed_and_unique() -> None:
    seen: set[str] = set()
    for entry in REGISTRY:
        assert entry.ats in KNOWN_ATS
        assert entry.slug and entry.slug == entry.slug.strip()
        assert entry.size in ("large", "startup")
        label = f"{entry.ats}:{entry.slug}"
        assert label not in seen, f"duplicate registry entry {label}"
        seen.add(label)


def test_top_tier_is_a_subset_of_about_fifty() -> None:
    top = select("top")
    assert 40 <= len(top) <= 60
    assert set(top) <= set(select("all"))


def test_size_tiers_partition_all() -> None:
    assert len(select("large")) + len(select("startups")) == len(select("all"))


def test_unknown_tier_raises() -> None:
    with pytest.raises(ValueError, match="top"):
        select("everything")
    assert "top" in TIERS and "all" in TIERS


def test_estimate_label_scales() -> None:
    assert estimate_label(4).endswith("s")
    assert "min" in estimate_label(150)
```

- [ ] **Step 2: Verify RED** — `ModuleNotFoundError: interninbox.registry`.

- [ ] **Step 3: Implement `src/interninbox/registry.py`.** Module docstring + dataclass + helpers:

```python
"""The curated company registry behind `--all` / the wizard's company menu.

Every entry was verified against its live public board API when authored
(scripts/verify_registry.py) — slugs rot as companies migrate ATSes, so
re-verify when touching this file. A dead slug degrades gracefully at scan
time (one warning line), but shipping known-dead entries is not acceptable.
"""

from __future__ import annotations

from dataclasses import dataclass

TIERS: tuple[str, ...] = ("top", "all", "large", "startups")

# Very rough sequential-scan pacing: politeness floors same-host requests at
# 0.5 s and responses take a few hundred ms, so ~0.75 s per board.
_SECONDS_PER_BOARD = 0.75


@dataclass(frozen=True)
class RegistryCompany:
    ats: str
    slug: str
    name: str
    size: str  # "large" | "startup"
    tags: tuple[str, ...] = ()
    top: bool = False


def select(tier: str) -> tuple[RegistryCompany, ...]:
    if tier == "all":
        return REGISTRY
    if tier == "top":
        return tuple(entry for entry in REGISTRY if entry.top)
    if tier == "large":
        return tuple(entry for entry in REGISTRY if entry.size == "large")
    if tier == "startups":
        return tuple(entry for entry in REGISTRY if entry.size == "startup")
    valid = ", ".join(TIERS)
    raise ValueError(f"unknown registry tier {tier!r} — valid tiers: {valid}")


def estimate_label(count: int) -> str:
    """Human 'how long will this take' hint. Rough on purpose; network varies."""
    seconds = max(5, round(count * _SECONDS_PER_BOARD))
    if seconds < 90:
        return f"~{seconds} s"
    return f"~{max(2, round(seconds / 60))} min"
```

Then the data. **Authoring procedure (mandatory, in this order):**

1. Write `scripts/verify_registry.py`:

```python
"""Maintainer tool: live-verify every registry slug against its public API.

Run manually when authoring or updating the registry (never from tests):
    .venv/bin/python scripts/verify_registry.py
Sequential, ~0.6 s between requests, honest User-Agent — the same manners the
tool itself has. Prints PASS/FAIL per entry and exits non-zero on any FAIL.
"""

from __future__ import annotations

import sys
import time

import httpx

from interninbox import USER_AGENT
from interninbox.registry import REGISTRY

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


def main() -> int:
    failures = 0
    with httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT},
                      follow_redirects=True) as client:
        for entry in REGISTRY:
            url = ENDPOINTS[entry.ats].format(slug=entry.slug)
            try:
                response = client.get(url)
                ok = response.status_code == 200
            except httpx.HTTPError:
                ok = False
            status = "PASS" if ok else "FAIL"
            if not ok:
                failures += 1
            print(f"{status}  {entry.ats}:{entry.slug}  ({entry.name})")
            time.sleep(0.6)
    print(f"\n{len(REGISTRY) - failures}/{len(REGISTRY)} verified")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
```

2. Add the candidate `REGISTRY` below (~140 entries). These are **candidates**: slugs believed correct, to be pruned by verification.
3. Run the verifier. **Delete every FAIL entry** (or fix an obviously wrong slug by checking the company's careers page URL, then re-verify). Iterate until the script exits 0.
4. If fewer than 100 entries survive, add more candidates (find real slugs from careers-page URLs of well-known startups on jobs.ashbyhq.com / jobs.lever.co / job-boards.greenhouse.io) and re-verify until `len(REGISTRY) >= 100` with a `large`/`startup` mix and 40–60 `top` entries. Adjust `top` flags if pruning unbalanced the tier.

Candidate data (tags are 1–2 short lowercase words; `top=True` marks the most-recognized ~50):

```python
_G, _L, _A = "greenhouse", "lever", "ashby"

REGISTRY: tuple[RegistryCompany, ...] = (
    # ---- greenhouse, large ----
    RegistryCompany(_G, "stripe", "Stripe", "large", ("fintech",), top=True),
    RegistryCompany(_G, "airbnb", "Airbnb", "large", ("consumer",), top=True),
    RegistryCompany(_G, "coinbase", "Coinbase", "large", ("crypto",), top=True),
    RegistryCompany(_G, "databricks", "Databricks", "large", ("data",), top=True),
    RegistryCompany(_G, "datadog", "Datadog", "large", ("infra",), top=True),
    RegistryCompany(_G, "dropbox", "Dropbox", "large", ("productivity",), top=True),
    RegistryCompany(_G, "duolingo", "Duolingo", "large", ("consumer", "edtech"), top=True),
    RegistryCompany(_G, "figma", "Figma", "large", ("design",), top=True),
    RegistryCompany(_G, "gitlab", "GitLab", "large", ("devtools",), top=True),
    RegistryCompany(_G, "lyft", "Lyft", "large", ("consumer",), top=True),
    RegistryCompany(_G, "mongodb", "MongoDB", "large", ("data",), top=True),
    RegistryCompany(_G, "pinterest", "Pinterest", "large", ("consumer",), top=True),
    RegistryCompany(_G, "reddit", "Reddit", "large", ("consumer",), top=True),
    RegistryCompany(_G, "robinhood", "Robinhood", "large", ("fintech",), top=True),
    RegistryCompany(_G, "roblox", "Roblox", "large", ("gaming",), top=True),
    RegistryCompany(_G, "twilio", "Twilio", "large", ("infra",), top=True),
    RegistryCompany(_G, "cloudflare", "Cloudflare", "large", ("infra", "security"), top=True),
    RegistryCompany(_G, "anthropic", "Anthropic", "large", ("ai",), top=True),
    RegistryCompany(_G, "asana", "Asana", "large", ("productivity",)),
    RegistryCompany(_G, "discord", "Discord", "large", ("consumer", "gaming"), top=True),
    RegistryCompany(_G, "instacart", "Instacart", "large", ("consumer",), top=True),
    RegistryCompany(_G, "affirm", "Affirm", "large", ("fintech",)),
    RegistryCompany(_G, "gusto", "Gusto", "large", ("fintech", "hr")),
    RegistryCompany(_G, "samsara", "Samsara", "large", ("iot",)),
    RegistryCompany(_G, "scaleai", "Scale AI", "large", ("ai",), top=True),
    RegistryCompany(_G, "epicgames", "Epic Games", "large", ("gaming",), top=True),
    RegistryCompany(_G, "spacex", "SpaceX", "large", ("aerospace",), top=True),
    RegistryCompany(_G, "elastic", "Elastic", "large", ("infra",)),
    RegistryCompany(_G, "hashicorp", "HashiCorp", "large", ("infra",)),
    RegistryCompany(_G, "okta", "Okta", "large", ("security",)),
    RegistryCompany(_G, "pagerduty", "PagerDuty", "large", ("infra",)),
    RegistryCompany(_G, "squarespace", "Squarespace", "large", ("consumer",)),
    RegistryCompany(_G, "chime", "Chime", "large", ("fintech",)),
    RegistryCompany(_G, "doordashusa", "DoorDash", "large", ("consumer",), top=True),
    RegistryCompany(_G, "wise", "Wise", "large", ("fintech",)),
    RegistryCompany(_G, "monzo", "Monzo", "large", ("fintech",)),
    RegistryCompany(_G, "klaviyo", "Klaviyo", "large", ("marketing",)),
    RegistryCompany(_G, "sofi", "SoFi", "large", ("fintech",)),
    RegistryCompany(_G, "nianticlabs", "Niantic", "large", ("gaming",)),
    RegistryCompany(_G, "carta", "Carta", "large", ("fintech",)),
    # ---- greenhouse, startup ----
    RegistryCompany(_G, "vercel", "Vercel", "startup", ("devtools",), top=True),
    RegistryCompany(_G, "brex", "Brex", "startup", ("fintech",), top=True),
    RegistryCompany(_G, "flexport", "Flexport", "startup", ("logistics",)),
    RegistryCompany(_G, "benchling", "Benchling", "startup", ("biotech",)),
    RegistryCompany(_G, "airtable", "Airtable", "startup", ("productivity",)),
    RegistryCompany(_G, "checkr", "Checkr", "startup", ("hr",)),
    RegistryCompany(_G, "sentry", "Sentry", "startup", ("devtools",)),
    RegistryCompany(_G, "amplitude", "Amplitude", "startup", ("data",)),
    RegistryCompany(_G, "launchdarkly", "LaunchDarkly", "startup", ("devtools",)),
    RegistryCompany(_G, "webflow", "Webflow", "startup", ("design",)),
    RegistryCompany(_G, "calendly", "Calendly", "startup", ("productivity",)),
    RegistryCompany(_G, "snyk", "Snyk", "startup", ("security",)),
    RegistryCompany(_G, "grammarly", "Grammarly", "startup", ("ai", "productivity")),
    RegistryCompany(_G, "huggingface", "Hugging Face", "startup", ("ai",), top=True),
    RegistryCompany(_G, "ironcladhq", "Ironclad", "startup", ("legal",)),
    RegistryCompany(_G, "lattice", "Lattice", "startup", ("hr",)),
    RegistryCompany(_G, "gongio", "Gong", "startup", ("sales",)),
    RegistryCompany(_G, "postman", "Postman", "startup", ("devtools",)),
    RegistryCompany(_G, "circleci", "CircleCI", "startup", ("devtools",)),
    RegistryCompany(_G, "coursera", "Coursera", "large", ("edtech",)),
    # ---- lever ----
    RegistryCompany(_L, "plaid", "Plaid", "large", ("fintech",), top=True),
    RegistryCompany(_L, "palantir", "Palantir", "large", ("data",), top=True),
    RegistryCompany(_L, "kraken", "Kraken", "large", ("crypto",)),
    RegistryCompany(_L, "wealthfront", "Wealthfront", "startup", ("fintech",)),
    RegistryCompany(_L, "attentive", "Attentive", "startup", ("marketing",)),
    RegistryCompany(_L, "voleon", "The Voleon Group", "startup", ("quant",)),
    RegistryCompany(_L, "zoox", "Zoox", "large", ("automotive",)),
    RegistryCompany(_L, "quora", "Quora", "startup", ("consumer",)),
    RegistryCompany(_L, "whoop", "WHOOP", "startup", ("health",)),
    RegistryCompany(_L, "mistral", "Mistral AI", "startup", ("ai",), top=True),
    RegistryCompany(_L, "octopusenergy", "Octopus Energy", "large", ("energy",)),
    RegistryCompany(_L, "welocalize", "Welocalize", "large", ("services",)),
    # ---- ashby, top startups & scale-ups ----
    RegistryCompany(_A, "openai", "OpenAI", "large", ("ai",), top=True),
    RegistryCompany(_A, "linear", "Linear", "startup", ("devtools",), top=True),
    RegistryCompany(_A, "notion", "Notion", "large", ("productivity",), top=True),
    RegistryCompany(_A, "ramp", "Ramp", "large", ("fintech",), top=True),
    RegistryCompany(_A, "replit", "Replit", "startup", ("devtools",), top=True),
    RegistryCompany(_A, "cursor", "Cursor", "startup", ("ai", "devtools"), top=True),
    RegistryCompany(_A, "deel", "Deel", "large", ("hr",), top=True),
    RegistryCompany(_A, "posthog", "PostHog", "startup", ("data",)),
    RegistryCompany(_A, "zapier", "Zapier", "startup", ("productivity",)),
    RegistryCompany(_A, "vanta", "Vanta", "startup", ("security",), top=True),
    RegistryCompany(_A, "mercury", "Mercury", "startup", ("fintech",), top=True),
    RegistryCompany(_A, "retool", "Retool", "startup", ("devtools",)),
    RegistryCompany(_A, "supabase", "Supabase", "startup", ("devtools",), top=True),
    RegistryCompany(_A, "elevenlabs", "ElevenLabs", "startup", ("ai",), top=True),
    RegistryCompany(_A, "perplexity-ai", "Perplexity", "startup", ("ai",), top=True),
    RegistryCompany(_A, "sierra", "Sierra", "startup", ("ai",)),
    RegistryCompany(_A, "harvey", "Harvey", "startup", ("ai", "legal")),
    RegistryCompany(_A, "modal", "Modal", "startup", ("infra",)),
    RegistryCompany(_A, "cohere", "Cohere", "startup", ("ai",)),
    RegistryCompany(_A, "docker", "Docker", "large", ("devtools",)),
    RegistryCompany(_A, "1password", "1Password", "large", ("security",)),
    RegistryCompany(_A, "wander", "Wander", "startup", ("travel",)),
    RegistryCompany(_A, "clever", "Clever", "startup", ("edtech",)),
    RegistryCompany(_A, "lambda", "Lambda", "startup", ("ai", "infra")),
    RegistryCompany(_A, "eightsleep", "Eight Sleep", "startup", ("health",)),
    RegistryCompany(_A, "warp", "Warp", "startup", ("devtools",)),
    RegistryCompany(_A, "browserbase", "Browserbase", "startup", ("ai", "devtools")),
    RegistryCompany(_A, "clay", "Clay", "startup", ("sales",)),
    RegistryCompany(_A, "wispr", "Wispr", "startup", ("ai",)),
    RegistryCompany(_A, "kikoff", "Kikoff", "startup", ("fintech",)),
)
```

*(The executor extends this list with further verified candidates during step 4 of the authoring procedure until the ≥100 / balanced-tier data tests pass. Do NOT pad with invented slugs — every added entry must PASS the verifier first.)*

5. Rewrite `src/interninbox/companies.py` to render from the registry (public `render()` unchanged for the CLI):

```python
"""`interninbox companies` — the curated registry, human-readable."""

from __future__ import annotations

from interninbox.registry import REGISTRY


def render() -> str:
    lines = [
        "Curated companies (copy the ats:slug entries you want into interninbox.toml,",
        'or scan them all with `registry = "all"` / the wizard):',
        "",
    ]
    width = max(len(f'"{entry.ats}:{entry.slug}"') for entry in REGISTRY)
    for entry in sorted(REGISTRY, key=lambda e: (e.ats, e.slug)):
        label = f'"{entry.ats}:{entry.slug}"'.ljust(width)
        tags = ", ".join(entry.tags)
        lines.append(f"  {label}  # {entry.name}  [{entry.size}]  {tags}")
    lines.append("")
    lines.append(
        f"{len(REGISTRY)} companies, verified when authored — companies migrate ATSes, "
        "so verify a slug with a scan; a wrong one just prints a warning."
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Verify GREEN** — full suite + ruff, **and** a final `scripts/verify_registry.py` run that exits 0 (record the `N/N verified` line in the commit body). `test_companies_lists_starter_entries` must still pass unmodified.

- [ ] **Step 5: Commit** — `feat: curated company registry — ~120 live-verified boards with size and tags` (body: registry module + tiers + estimates; companies command now renders it; verification script + the verified count; trailer).

---

### Task 4: `registry` config key + scan wiring + scale note

**Files:**
- Modify: `src/interninbox/config.py` (Config.registry, parsing, starter config, nothing-to-scan check), `src/interninbox/cli.py` (`_effective_companies`, scale note)
- Test: `tests/test_config.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `Config.registry: str = "none"`; `cli._effective_companies(config: Config) -> tuple[Company, ...]` (config companies first, then registry-tier entries not already listed). Task 5's wizard builds an in-memory `Config` and flows through the same two functions.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_config.py`:

```python
def test_registry_key_parsed_and_validated(tmp_path: Path) -> None:
    path = tmp_path / "interninbox.toml"
    path.write_text('companies = ["greenhouse:stripe"]\nregistry = "top"\n', encoding="utf-8")
    assert load_config(path).registry == "top"

    path.write_text('companies = ["greenhouse:stripe"]\nregistry = "everything"\n',
                    encoding="utf-8")
    with pytest.raises(ConfigError, match="registry"):
        load_config(path)


def test_registry_alone_is_something_to_scan(tmp_path: Path) -> None:
    path = tmp_path / "interninbox.toml"
    path.write_text('registry = "top"\n', encoding="utf-8")
    config = load_config(path)  # no companies, no usajobs — registry suffices
    assert config.companies == () and config.registry == "top"
```

Append to `tests/test_cli.py`:

```python
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
```

(`json_response` is already imported in `tests/test_cli.py` via conftest? If not: add `json_response` to the existing `from conftest import ...` line.)

- [ ] **Step 2: Verify RED** — registry key unknown to config (`ConfigError`/attribute errors); union test scans 1 company; no scale note.

- [ ] **Step 3: Implement.**

`src/interninbox/config.py` — `Config` gains `registry: str = "none"` (after `filters`). In `load_config`, after `usajobs_cfg = ...`:

```python
    registry = data.get("registry", "none")
    if not isinstance(registry, str) or registry not in ("none", *_REGISTRY_TIERS()):
        raise ConfigError(
            'registry must be one of "none", "top", "all", "large", "startups"'
        )
```

with the helper (module level, lazy import to keep config free of a hard registry dependency at import time):

```python
def _REGISTRY_TIERS() -> tuple[str, ...]:
    from interninbox.registry import TIERS

    return TIERS
```

Replace the nothing-to-scan check:

```python
    if not companies and not usajobs_cfg.enabled and registry == "none":
        raise ConfigError(
            f"{path} configures nothing to scan — add a `companies` list "
            "(e.g. companies = [\"greenhouse:stripe\"]), set registry = \"top\", "
            "or enable [usajobs]"
        )
```

and pass `registry=registry` into `Config(...)`. In `STARTER_CONFIG`, after the companies list add:

```toml
# Also sweep the bundled curated registry: "none" (default), "top" (~50
# well-known boards), "all", "large", or "startups". `interninbox companies`
# lists what's in it. Big sweeps take a couple of minutes — politeness.
# registry = "none"
```

`src/interninbox/cli.py` — add `from interninbox import registry as registry_mod` and:

```python
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
```

(`Company` joins the config import block.) In `_cmd_scan`, after loading state and before the Fetcher block:

```python
    companies = _effective_companies(config)
    if len(companies) >= 20:
        print(
            f"scanning {len(companies)} boards — roughly "
            f"{registry_mod.estimate_label(len(companies))} at polite pacing",
            file=sys.stderr,
        )
```

and change `_scan_boards` to take the effective tuple: give `_scan_boards` a new signature `(companies: tuple[Company, ...], fetcher, result, *, progress=False)` — inside, `total = len(companies)` and iterate `companies`; the call site becomes `_scan_boards(companies, fetcher, result, progress=progress)`. (Keep `_scan_usajobs` untouched.)

- [ ] **Step 4: Verify GREEN** — full suite + ruff. (The `test_progress_lines_written_when_tty` test calls `_scan_boards(config, ...)` today — update its call to `_scan_boards(config.companies, ...)`; this is the ONLY existing-test change in this task.)

- [ ] **Step 5: Commit** — `feat: scan the curated registry — registry = "top"|"all"|"large"|"startups"` (body: union + dedupe with config companies, scale note with honest estimate for ≥20 boards; trailer).

---

### Task 5: The interactive wizard (`wizard.py`, `--interactive`, save-to-config)

**Files:**
- Create: `src/interninbox/wizard.py`
- Modify: `src/interninbox/cli.py` (flag, trigger, injectable input), `src/interninbox/config.py` (nothing — wizard builds an in-memory `Config`)
- Test: `tests/test_wizard.py` (new), `tests/test_cli.py`

**Interfaces:**
- Produces: `wizard.WizardAnswers` (frozen dataclass: `locations: tuple[str, ...]`, `roles: tuple[str, ...]`, `tier: str` — a registry tier or `"config"`); `wizard.run(*, input_fn, print_fn, config_companies: int) -> WizardAnswers`; `wizard.render_config(answers: WizardAnswers) -> str` (valid TOML the wizard offers to save); `cli.main(..., input_fn: Callable[[str], str] | None = None)`.
- Trigger rule (approved design): wizard runs when `args.interactive` is true, or when the config file is missing AND `sys.stdin.isatty()` AND `sys.stderr.isatty()`. Tests always use `--interactive` (never fake TTYs); one test locks in that missing-config + non-TTY still errors like today.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_wizard.py`:

```python
"""Wizard flow with scripted answers — no TTY, no network."""

from interninbox import wizard
from interninbox.config import Filters
from interninbox.roles import ROLE_PRESETS


def _scripted(answers: list[str]):
    answers = list(answers)

    def input_fn(prompt: str) -> str:
        return answers.pop(0)

    return input_fn


def test_wizard_collects_location_roles_and_tier() -> None:
    lines: list[str] = []
    # location -> "California"; roles -> pick 1 and 3; companies -> option 2 (top)
    answers = wizard.run(
        input_fn=_scripted(["California", "1 3", "2"]),
        print_fn=lines.append,
        config_companies=0,
    )
    role_names = sorted(ROLE_PRESETS)
    assert answers.locations == ("California",)
    assert answers.roles == (role_names[0], role_names[2])
    assert answers.tier == "top"
    joined = "\n".join(lines)
    assert "~" in joined  # menu shows time estimates


def test_wizard_blank_answers_mean_everything() -> None:
    answers = wizard.run(
        input_fn=_scripted(["", "", "1"]),
        print_fn=lambda _: None,
        config_companies=0,
    )
    assert answers.locations == () and answers.roles == () and answers.tier == "all"


def test_wizard_offers_my_config_option_when_config_exists() -> None:
    lines: list[str] = []
    answers = wizard.run(
        input_fn=_scripted(["", "", "0"]),
        print_fn=lines.append,
        config_companies=3,
    )
    assert answers.tier == "config"
    assert any("my config" in line for line in lines)


def test_wizard_reprompts_on_bad_menu_choice() -> None:
    answers = wizard.run(
        input_fn=_scripted(["", "", "99", "2"]),  # invalid, then valid
        print_fn=lambda _: None,
        config_companies=0,
    )
    assert answers.tier == "top"


def test_render_config_is_loadable(tmp_path) -> None:
    from interninbox.config import load_config

    answers = wizard.WizardAnswers(
        locations=("California",), roles=("cybersecurity",), tier="top"
    )
    path = tmp_path / "interninbox.toml"
    path.write_text(wizard.render_config(answers), encoding="utf-8")
    config = load_config(path)
    assert config.registry == "top"
    assert config.filters.locations == ("California",)
    assert config.filters.roles == ("cybersecurity",)


def test_wizard_filters_flow_through_expansion() -> None:
    # The answers become a Filters the normal effective-filters layer expands.
    answers = wizard.WizardAnswers(locations=("CA",), roles=("software",), tier="top")
    filters = Filters(locations=answers.locations, roles=answers.roles)
    assert filters.locations == ("CA",)
```

Append to `tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Verify RED** — `ModuleNotFoundError: interninbox.wizard`; `--interactive` unknown flag (argparse exit 2); `input_fn` unexpected kwarg on `main`.

- [ ] **Step 3: Implement.** Create `src/interninbox/wizard.py`:

```python
"""The first-run interactive wizard: location -> roles -> companies -> scan.

Pure question/answer logic with injectable input/print so tests script it.
It never touches the network or the filesystem itself — `cli.py` turns the
answers into an in-memory Config (same expansion path as a file config) and
handles the optional save.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from interninbox.registry import TIERS, estimate_label, select
from interninbox.roles import ROLE_PRESETS


@dataclass(frozen=True)
class WizardAnswers:
    locations: tuple[str, ...]
    roles: tuple[str, ...]
    tier: str  # a registry tier, or "config" for the user's own list


def run(
    *,
    input_fn: Callable[[str], str],
    print_fn: Callable[[str], None],
    config_companies: int,
) -> WizardAnswers:
    print_fn("interninbox — a few questions, then the scan. Blank = no preference.")

    raw = input_fn("Location (country, US state, or city — blank = anywhere): ").strip()
    locations = (raw,) if raw else ()

    names = sorted(ROLE_PRESETS)
    print_fn("Role types (numbers separated by spaces, blank = all):")
    for index, name in enumerate(names, start=1):
        print_fn(f"  [{index}] {name}")
    roles = _pick_many(input_fn("Roles: "), names)

    options: list[tuple[str, str]] = []  # (tier, menu line)
    if config_companies:
        options.append(("config", f"my config ({config_companies} boards)"))
    for tier in ("all", "top", "large", "startups"):
        count = len(select(tier))
        options.append((tier, f"{tier:<8} — {count} boards, {estimate_label(count)}"))
    print_fn("Companies:")
    start = 0 if config_companies else 1
    for index, (_, line) in enumerate(options, start=start):
        print_fn(f"  [{index}] {line}")
    tier = _pick_one(input_fn, print_fn, options, start=start)

    return WizardAnswers(locations=locations, roles=tuple(roles), tier=tier)


def _pick_many(raw: str, names: list[str]) -> list[str]:
    picked: list[str] = []
    for token in raw.split():
        if token.isdigit() and 1 <= int(token) <= len(names):
            name = names[int(token) - 1]
            if name not in picked:
                picked.append(name)
    return picked


def _pick_one(
    input_fn: Callable[[str], str],
    print_fn: Callable[[str], None],
    options: list[tuple[str, str]],
    *,
    start: int,
) -> str:
    while True:
        raw = input_fn("Companies: ").strip()
        if raw.isdigit() and start <= int(raw) < start + len(options):
            return options[int(raw) - start][0]
        print_fn(f"Pick a number between {start} and {start + len(options) - 1}.")


def render_config(answers: WizardAnswers) -> str:
    """A loadable interninbox.toml capturing the wizard's answers."""
    def toml_list(items: tuple[str, ...]) -> str:
        return "[" + ", ".join(f'"{item}"' for item in items) + "]"

    tier = answers.tier if answers.tier in TIERS else "none"
    return (
        "# Written by the interninbox wizard — edit freely; `interninbox scan`\n"
        "# uses it from now on (rerun the wizard any time with --interactive).\n"
        "companies = []\n"
        f'registry = "{tier}"\n'
        "\n"
        "[filters]\n"
        f"roles = {toml_list(answers.roles)}\n"
        f"locations = {toml_list(answers.locations)}\n"
    )
```

Wait — `render_config` with `tier="none"` and no companies would fail `load_config`'s nothing-to-scan check. Guard: when `answers.tier == "config"` the save step is skipped entirely (the user already has a config — see the cli wiring below), so `render_config` is only called with real tiers; keep the `TIERS` guard anyway as belt-and-braces.

`src/interninbox/cli.py` wiring:

1. `build_parser`: add to the scan parser:

```python
    scan_parser.add_argument(
        "--interactive",
        action="store_true",
        help="ask location/role/companies questions before scanning "
        "(automatic on a terminal when no config exists)",
    )
```

2. `main` signature gains `input_fn: Callable[[str], str] | None = None`; pass it through: `return args.func(args, transport=transport, sleep=sleep, env=resolved_env, input_fn=input_fn)`. Give `_cmd_init`/`_cmd_companies`/`_cmd_roles` a `**_: object` catch-all (already present) and `_cmd_scan` the explicit parameter `input_fn: Callable[[str], str] | None`.

3. In `_cmd_scan`, replace `config = load_config(args.config)` with:

```python
    wizard_wants = getattr(args, "interactive", False) or (
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
        if answers.tier == "config" and existing is not None:
            config = dataclasses.replace(
                existing,
                filters=dataclasses.replace(
                    existing.filters, locations=answers.locations, roles=answers.roles
                ),
            )
        else:
            config = Config(
                companies=existing.companies if existing else (),
                filters=Filters(locations=answers.locations, roles=answers.roles),
                registry=answers.tier if answers.tier != "config" else "none",
            )
    else:
        config = load_config(args.config)
```

with `from interninbox import wizard` and `Config` in the config import block. After the scan output (just before the `attempted` check), add the save offer:

```python
    if answers is not None and not args.config.is_file() and answers.tier != "config":
        ask = input_fn if input_fn is not None else input
        reply = ask(f"Save these choices to {args.config}? [y/N] ").strip().lower()
        if reply in ("y", "yes"):
            args.config.write_text(wizard.render_config(answers), encoding="utf-8")
            print(f"Wrote {args.config} — next time, plain `interninbox scan` "
                  "uses it.", file=sys.stderr)
```

Note the state-path consequence: the wizard run uses `default_state_path(args.config)` exactly as normal scans do (`interninbox.toml` stem → the plain state file), so a saved config picks up the wizard run's seen-state seamlessly.

- [ ] **Step 4: Verify GREEN** — full suite + ruff. Check the wizard prompts went to **stderr** (stdout stays clean for piping results even in interactive runs — the tests read listings from `captured.out` and menus land in `err`; `input()`'s own prompt echo is a TTY concern, invisible in tests because `input_fn` is injected).

- [ ] **Step 5: Commit** — `feat: first-run wizard — location, role, companies with time estimates` (body: trigger rule [no-config TTY or --interactive], injectable input for offline tests, optional save to interninbox.toml, cron behavior unchanged; trailer).

---

### Task 6: Documentation sweep

**Files:**
- Modify: `README.md`, `docs/KNOWN-ISSUES.md`

- [ ] **Step 1: README.** (a) Quick-start: show the wizard as the new day-one path (`pip install interninbox` → `interninbox scan` → answer three questions), with the old `init`+edit flow kept as the "scripted setup" alternative. (b) Config reference table: add `registry` and `filters.roles` rows. (c) New short sections: "Role presets" (point at `interninbox roles`; whole-word semantics; roles merge with `match_keywords`), "The company registry" (curated + live-verified, sizes/tags, honest scan-time estimates, how to contribute an entry), and extend the locations section with the alias behavior ("California" ⇄ "CA", NYC, UK — unknown terms unchanged). (d) `--interactive` in the CLI flags table.

- [ ] **Step 2: KNOWN-ISSUES.** M4: note the alias half is now largely addressed for US states/DC + common forms via the bundled alias table (arbitrary city aliases remain free-text reality). H3: note the wizard + registry close the "day-one disappointment" (no more editing TOML before first results; empty results already explain themselves). Keep both entries' history intact; adjust only the status notes.

- [ ] **Step 3: Verify** — `.venv/bin/python -m pytest -q && .venv/bin/ruff check .`; `grep -n "registry" README.md` and `grep -n "roles" README.md` show the new rows/sections.

- [ ] **Step 4: Commit** — `docs: wizard-first quick start; registry, roles, and location aliases documented` (+ trailer).

---

## Completion

1. Full gates one last time; then push branch `discovery-wizard` and open ONE PR titled `feat: discovery update — locations, role presets, curated registry, first-run wizard`, body summarizing the four user-facing updates and the verified-registry count.
2. The registry verification output (`N/N verified`) belongs in the Task 3 commit body and the PR body — it is the evidence the shipped slugs were real on authoring day.
3. Follow-ups deliberately not in this plan: role-preset tuning from real-world feedback, additional countries/aliases, richer wizard steps (USAJOBS opt-in), registry tag filters in the wizard menu.
