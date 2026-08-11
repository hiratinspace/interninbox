# Known-Issues Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every fixable defect in `docs/KNOWN-ISSUES.md` (v0.1.0 adversarial review), highest severity first, without breaking the project's politeness/no-telemetry/friendly-errors guarantees.

**Architecture:** interninbox is a small offline-testable pipeline: `cli.py` orchestrates → `fetch.py` (one polite HTTP client) → `adapters/*` (per-ATS JSON → `Listing`) → `filters.py` (title heuristics) → `output.py` (table/JSON/markdown) with `state.py` (`--new-only` seen-file). Each ticket touches one layer and lands as one commit. Tickets are ordered by user impact and dependency (config keys before the filters that read them; fetch changes before adapters that use new parameters).

**Tech Stack:** Python ≥3.11, httpx (only runtime dependency — do not add more), pytest + httpx.MockTransport (all tests offline), ruff, uv, hatchling.

## Global Constraints

- No new runtime dependencies. `dependencies = ["httpx>=0.27"]` stays as-is.
- All tests are offline: `httpx.MockTransport` and synthetic fixtures only. Never hit a real network in tests.
- Anticipated failures never print a traceback: `ConfigError`/`AdapterError` + stderr message + exit code.
- Politeness invariants must not regress: sequential requests, ≥500 ms per host, 15 s connect/read timeout, exactly one retry on transient failure, honest User-Agent.
- Line length 100; lint gate is `uv run ruff check .` (rules E, F, W, I, UP, B).
- Test gate is `uv run pytest -q`. Run BOTH gates before every commit.
- Commit style (match `git log`): `fix:`, `feat:`, `docs:`, `ci:`, `chore:` with a `Fixes KNOWN-ISSUES <ID>`-style body line, ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Do the work on a branch: `git checkout -b known-issues-remediation` before Task 1 (skip if it already exists).
- Full suite currently passes with 102 tests. If a task changes an existing test's expectation, the task says so explicitly; any OTHER unexpected failure means stop and re-read the task.

**Issue coverage map** (KNOWN-ISSUES ID → task): H1→1, H2→2, H3→8 (plus 7), H4→7, M1→10, M2→13, M3→4, M4→13 (docs only), M5→3+13, M6→3, M7→11, M8→9, M9→9, M10→7+12, M11→5, M12→12, M13→12, L1→13, L2→7, L3→1 (control chars; wide-char alignment deliberately deferred), L4→3, L5→13 (docs only), L6→13 (docs only; pruning deferred), L7→13 (docs only), L8→6, L9→1 (markdown) + 10 (bool date), L10→12.

**Deliberately deferred (documented in Task 13, not coded):** M4 alias/word-boundary location matching (heuristic risk beyond this pass), M8 cross-process file locking, L3 East-Asian display-width alignment, L6 state pruning + USAJOBS identity, L7 per-config state paths (breaking default).

---

### Task 1: Output sanitization — control characters and markdown injection (H1, L3-part, L9-part)

**Files:**
- Modify: `src/interninbox/output.py`
- Test: `tests/test_output.py`

**Interfaces:**
- Consumes: `Listing`, `ScanResult` from `interninbox.models` (unchanged).
- Produces: `format_table`/`format_markdown` signatures unchanged; internal helpers `_clean(text: str) -> str`, `_md_escape(text: str) -> str`, `_md_url(url: str) -> str`. Later tasks don't call these, but Task 8 edits `format_table`'s empty branch — keep the function shape.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_output.py`:

```python
def test_table_strips_ansi_and_control_chars() -> None:
    result = ScanResult(
        listings=[
            make_listing(
                title="Intern\x1b]0;pwned\x07 \x1b[31mRed\x1b[0m",
                company="acme\x9bevil",
                locations=("New\nYork", "SF\rBay"),
            )
        ],
        companies_scanned=1,
    )
    text = format_table(result)
    assert "\x1b" not in text
    assert "\x07" not in text
    assert "\x9b" not in text
    assert "\r" not in text
    # A newline smuggled inside a location must not create an extra row.
    assert len(text.splitlines()) == 4  # header, one row, blank, summary


def test_markdown_strips_ansi_and_escapes_link_syntax() -> None:
    result = ScanResult(
        listings=[
            make_listing(
                title="\x1b[31m[click me](https://evil.test)",
                company="ac|me",
                url="https://boards.example.test/jobs/1)?tracking=(x",
            )
        ],
        companies_scanned=1,
    )
    text = format_markdown(result)
    assert "\x1b" not in text
    # Title cannot forge a markdown link.
    assert "[click me](https://evil.test)" not in text
    # Company pipes are escaped like title pipes already are.
    assert "ac\\|me" in text
    # A ')' in the URL cannot terminate the [apply](...) link early.
    row = text.splitlines()[2]
    assert "[apply](https://boards.example.test/jobs/1%29?tracking=%28x)" in row
```

- [ ] **Step 2: Verify they fail** — `uv run pytest tests/test_output.py -q` → exactly these 2 fail (raw `\x1b` present; unescaped link).

- [ ] **Step 3: Implement** in `src/interninbox/output.py`:

Add `import unicodedata` to the imports, then above `_truncate`:

```python
def _clean(text: str) -> str:
    """Drop control/format characters from untrusted board text.

    Board JSON is arbitrary third-party data; ANSI/OSC escapes, C0/C1
    controls, bidi overrides, and zero-width characters (categories Cc/Cf)
    must never reach the terminal or a pasted markdown table.
    """
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("Cc", "Cf"))
```

Replace `_row` so every untrusted field passes through `_clean`:

```python
def _row(listing: Listing) -> tuple[str, str, str, str, str]:
    locations = ", ".join(_clean(entry) for entry in listing.locations) or "-"
    posted = listing.posted_at.date().isoformat() if listing.posted_at else "-"
    return (
        _clean(listing.company),
        _truncate(_clean(listing.title), _MAX_TITLE_WIDTH),
        _truncate(locations, _MAX_LOCATIONS_WIDTH),
        posted,
        _clean(listing.url),
    )
```

Add the two markdown helpers above `format_markdown`:

```python
def _md_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _md_url(url: str) -> str:
    return url.replace("(", "%28").replace(")", "%29")
```

Replace the loop body inside `format_markdown` (the current `title = title.replace(...)` lines go away):

```python
    for listing in listings:
        company, title, locations, posted, url = _row(listing)
        lines.append(
            f"| {_md_escape(company)} | {_md_escape(title)} | {_md_escape(locations)} "
            f"| {posted} | [apply]({_md_url(url)}) |"
        )
```

`format_json` stays untouched — `json.dumps` with default `ensure_ascii=True` already escapes ESC.

- [ ] **Step 4: Verify** — `uv run pytest -q && uv run ruff check .` → all pass (104 tests).

- [ ] **Step 5: Commit**

```bash
git add src/interninbox/output.py tests/test_output.py
git commit -m "fix: sanitize untrusted board text in table and markdown output

Strips Cc/Cf characters (ANSI/OSC escapes, C1, bidi/zero-width) from
company/title/locations/url, and hardens markdown against link forging
(escaped brackets/pipes, percent-encoded parens in URLs).

Fixes KNOWN-ISSUES H1, the control-character half of L3, and the
markdown half of L9.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `match_keywords` — a narrowing filter (H2)

**Files:**
- Modify: `src/interninbox/config.py` (Filters dataclass, `_parse_filters`, `STARTER_CONFIG`)
- Modify: `src/interninbox/filters.py`
- Test: `tests/test_filters.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `Filters.match_keywords: tuple[str, ...] = ()` (new frozen-dataclass field); `filters.matches_required_keywords(title: str, keywords: tuple[str, ...]) -> bool`. Task 13 documents the semantics: whole-word, case-insensitive, OR within the list, AND-ed with the internship signal — it narrows, unlike `include_keywords` which broadens.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_filters.py`:

```python
def test_match_keywords_narrow_within_internships() -> None:
    filters = Filters(match_keywords=("security",))
    assert matches(make_listing(title="Security Engineering Intern"), filters)
    assert not matches(make_listing(title="Software Engineering Intern"), filters)
    # match_keywords never widens: a non-internship stays out.
    assert not matches(make_listing(title="Security Engineer"), filters)


def test_match_keywords_are_whole_word() -> None:
    filters = Filters(match_keywords=("ai",))
    assert not matches(make_listing(title="Chair of Maintenance Intern"), filters)
    assert matches(make_listing(title="AI Research Intern"), filters)


def test_match_keywords_list_is_any_of() -> None:
    filters = Filters(match_keywords=("security", "data"))
    assert matches(make_listing(title="Data Platform Intern"), filters)
```

And append to `tests/test_config.py` (mirror that file's existing helper style for writing a TOML to `tmp_path`):

```python
def test_match_keywords_parsed(tmp_path: Path) -> None:
    path = tmp_path / "interninbox.toml"
    path.write_text(
        'companies = ["greenhouse:stripe"]\n[filters]\nmatch_keywords = ["security"]\n',
        encoding="utf-8",
    )
    assert load_config(path).filters.match_keywords == ("security",)
```

- [ ] **Step 2: Verify they fail** — `uv run pytest tests/test_filters.py tests/test_config.py -q` → the three filter tests fail with `TypeError: ... unexpected keyword argument 'match_keywords'`; the config test fails on the missing attribute.

- [ ] **Step 3: Implement.**

`src/interninbox/config.py` — add the field to `Filters`:

```python
@dataclass(frozen=True)
class Filters:
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    match_keywords: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    remote_ok: bool = True
```

In `_parse_filters`, parse it alongside the others:

```python
    return Filters(
        include_keywords=include,
        exclude_keywords=exclude,
        match_keywords=_string_list(raw.get("match_keywords"), where="filters.match_keywords"),
        locations=_string_list(raw.get("locations"), where="filters.locations"),
        remote_ok=_boolean(raw.get("remote_ok"), where="filters.remote_ok", default=True),
    )
```

In `STARTER_CONFIG`, after the `exclude_keywords = []` lines insert:

```toml
# Require at least one of these words in the title, on top of the internship
# signal — "internship AND security". Whole-word, case-insensitive. This
# NARROWS results; include_keywords above BROADENS them.
match_keywords = []
```

`src/interninbox/filters.py` — add after `has_internship_signal`:

```python
def matches_required_keywords(title: str, keywords: tuple[str, ...]) -> bool:
    """True when `title` contains at least one keyword as a whole word.

    An empty list means no requirement. Unlike include_keywords (which is
    OR-ed INTO the internship signal and so broadens results), this is
    AND-ed with it and narrows.
    """
    if not keywords:
        return True
    return any(
        re.search(rf"\b{re.escape(keyword)}\b", title, re.IGNORECASE) for keyword in keywords
    )
```

In `matches()`, insert directly after the `has_internship_signal` check:

```python
    if not matches_required_keywords(listing.title, filters.match_keywords):
        return False
```

- [ ] **Step 4: Verify** — `uv run pytest -q && uv run ruff check .` → all pass.

- [ ] **Step 5: Commit**

```bash
git add src/interninbox/config.py src/interninbox/filters.py tests/test_filters.py tests/test_config.py
git commit -m "feat: match_keywords filter — narrow to 'internship AND keyword'

include_keywords broadens (it extends the internship signal); until now
nothing narrowed. match_keywords is whole-word, case-insensitive, OR
within the list, AND-ed with the signal.

Fixes KNOWN-ISSUES H2.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Title-pattern fixes — dead `sr.`, over-eager `pathways`, missing signals (L4, M6, M5)

**Files:**
- Modify: `src/interninbox/filters.py` (`_SIGNAL_PATTERNS`, `STAFF_ROLE`)
- Test: `tests/test_filters.py`

**Interfaces:** No signature changes — only the two module-level regexes.

**Fixture interaction check (do not skip):** the CLI fixtures contain no titles the new patterns newly match ("Summer 2027" titles already carry "Intern"), so `tests/test_cli.py` counts ("6 internships across 3 companies") must NOT change. If they do, a new pattern is over-matching — fix the pattern, not the test.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_filters.py`:

```python
@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer - Summer 2027",
        "Industrial Placement, Devices",
        "Placement Student - Manufacturing",
        "Engineering Fellowship",
        "Praktikant Softwareentwicklung",
        "Werkstudentin QA",
        "Stagiaire ingénieur logiciel",
    ],
)
def test_new_signal_patterns(title: str) -> None:
    assert has_internship_signal(title)


def test_pathways_recent_graduates_is_not_a_signal() -> None:
    # "Pathways Recent Graduates" is a post-degree full-time federal program.
    assert not has_internship_signal("Pathways Recent Graduates - Accounting")
    assert has_internship_signal("Pathways Internship Program - IT")


def test_sr_abbreviation_is_staff() -> None:
    assert is_staff_role("Sr. Software Engineer")
    assert is_staff_role("Sr Engineer, Platforms")


def test_sre_is_not_a_staff_marker() -> None:
    assert not is_staff_role("Site Reliability Intern (SRE)")
```

- [ ] **Step 2: Verify they fail** — `uv run pytest tests/test_filters.py -q` → the new-signal parametrized cases, the Recent-Graduates negative, and `Sr.` cases fail. (`Pathways Intern - Data Analysis` in the existing positives must KEEP passing.)

- [ ] **Step 3: Implement** in `src/interninbox/filters.py`.

In `_SIGNAL_PATTERNS`, replace the two-line pathways block at the end:

```python
    # US-federal Pathways titling: "Student Trainee (Information Technology)".
    r"\bstudent\s+trainee\b",
    r"\bpathways\b",
)
```

with:

```python
    # US-federal Pathways titling: "Student Trainee (Information Technology)".
    # Bare "Pathways" would also catch "Pathways Recent Graduates", a
    # post-degree full-time program — so require the intern word.
    r"\bstudent\s+trainee\b",
    r"\bpathways\s+intern(ship)?s?\b",
    # Program titles that don't say "intern": "... - Summer 2027",
    # UK industrial placements, fellowships, and the standard German/French
    # student-role words these ATSes host EU boards under.
    r"\bsummer\s+20\d{2}\b",
    r"\bindustrial\s+placement\b",
    r"\bplacement\s+(student|year)\b",
    r"\bfellowship\b",
    r"\bpraktikant(in)?\b",
    r"\bwerkstudent(in)?\b",
    r"\bstagiaire\b",
)
```

Replace `STAFF_ROLE` (the old `sr\.` sat before `)\b`, and `\b` after `.` requires a word character, so "Sr. X" never matched):

```python
STAFF_ROLE = re.compile(
    r"\b(manager|director|coordinator|recruiter|recruiting|head of|team lead|supervisor"
    r"|professor|instructor|senior|staff|principal)\b|\bsr\b",
    re.IGNORECASE,
)
```

(`\bsr\b` matches "Sr. Engineer" and "Sr Engineer" but not "SRE" — no word boundary inside "sre".)

- [ ] **Step 4: Verify** — `uv run pytest -q && uv run ruff check .` → ALL tests pass, including the untouched `tests/test_cli.py` counts.

- [ ] **Step 5: Commit**

```bash
git add src/interninbox/filters.py tests/test_filters.py
git commit -m "fix: title patterns — dead sr., bare pathways, missing intern signals

- 'sr\\.' never matched ('\\b' after '.' needs a word char): now '\\bsr\\b'.
- bare 'pathways' surfaced full-time Recent-Graduate federal roles: now
  requires 'pathways intern(ship)'.
- new signals: 'Summer 20XX', industrial placement / placement student,
  fellowship, Praktikant(in), Werkstudent(in), Stagiaire.

Fixes KNOWN-ISSUES L4 and M6; narrows M5.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Honest 4xx errors and a Retry-After-aware 429 retry (M3)

**Files:**
- Modify: `src/interninbox/fetch.py`
- Test: `tests/test_politeness.py`

**Interfaces:**
- Produces: module helpers `_client_error(status: int, host: str) -> str` and `_retry_after_seconds(header_value: str | None) -> float`. `get_json`'s signature is unchanged. Task 5 rewrites `get_json`'s body around these same helpers — implement them exactly as written here.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_politeness.py`:

```python
def test_401_mentions_key_or_blocking_not_slug() -> None:
    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(401)), sleep=lambda _: None
    ) as fetcher:
        with pytest.raises(AdapterError, match="request refused"):
            fetcher.get_json("https://data.usajobs.gov/api/search")


def test_429_retried_once_honoring_retry_after() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return json_response({"ok": True})

    with Fetcher(transport=make_transport(handler), sleep=sleeps.append) as fetcher:
        assert fetcher.get_json("https://api.lever.co/v0/postings/one") == {"ok": True}
    assert len(calls) == 2
    assert 3.0 in sleeps


def test_persistent_429_reports_rate_limit_not_slug() -> None:
    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(429)), sleep=lambda _: None
    ) as fetcher:
        with pytest.raises(AdapterError, match="rate limited"):
            fetcher.get_json("https://api.lever.co/v0/postings/one")
```

- [ ] **Step 2: Verify they fail** — `uv run pytest tests/test_politeness.py -q` → the three new tests fail (current message is always "check the slug exists"; 429 is not retried).

- [ ] **Step 3: Implement** in `src/interninbox/fetch.py`. Add module-level helpers below the constants:

```python
def _client_error(status: int, host: str) -> str:
    if status in (401, 403):
        return (
            f"HTTP {status} from {host}: request refused — an API-key problem, or the "
            "host is blocking automated requests (not a slug problem)"
        )
    if status == 429:
        return f"HTTP 429 from {host}: rate limited — wait a while before rescanning"
    if status in (404, 410):
        return f"HTTP {status} from {host}: board not found — check the slug exists"
    return f"HTTP {status} from {host}"


def _retry_after_seconds(header_value: str | None) -> float:
    """Seconds to wait before the single 429 retry — header value capped at 10 s."""
    try:
        seconds = float(header_value) if header_value is not None else 2.0
    except ValueError:
        seconds = 2.0  # an HTTP-date Retry-After: use the default rather than parse it
    return max(0.0, min(seconds, 10.0))
```

In `get_json`'s attempt loop, replace the `>= 400` block:

```python
            if response.status_code >= 500:
                last_error = f"server error HTTP {response.status_code}"
                continue  # transient — retry once
            if response.status_code == 429 and _attempt == 1:
                self._sleep(_retry_after_seconds(response.headers.get("Retry-After")))
                last_error = f"HTTP 429 from {host} (rate limited)"
                continue  # one polite retry, then _client_error below reports it
            if response.status_code >= 400:
                raise AdapterError(_client_error(response.status_code, host))
```

- [ ] **Step 4: Verify** — `uv run pytest -q && uv run ruff check .` → all pass. The pre-existing `test_4xx_is_not_retried_and_mentions_slug_check` (404) must still pass — 404 keeps the slug wording.

- [ ] **Step 5: Commit**

```bash
git add src/interninbox/fetch.py tests/test_politeness.py
git commit -m "fix: stop blaming the slug for every 4xx; retry 429 once per Retry-After

401/403 now say the request was refused (key/WAF), 429 says rate limited
and gets one retry honoring Retry-After (capped at 10 s); only 404/410
suggest checking the slug.

Fixes KNOWN-ISSUES M3.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Bounded responses — size cap, read deadline, RecursionError containment (M11)

**Files:**
- Modify: `src/interninbox/fetch.py`
- Test: `tests/test_politeness.py`

**Interfaces:**
- Consumes: `_client_error` / `_retry_after_seconds` from Task 4.
- Produces: `Fetcher.__init__` gains `max_response_bytes: int = MAX_RESPONSE_BYTES` (keyword-only, like its siblings); new constants `MAX_RESPONSE_BYTES = 10_000_000`, `READ_DEADLINE_SECONDS = 60.0`; `get_json` gains `follow_redirects: bool = True` keyword (consumed by Task 6). Behavior contract for callers is unchanged: JSON object out, `AdapterError` on any failure.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_politeness.py`:

```python
def test_oversized_response_is_refused() -> None:
    big = b'{"jobs": "' + b"x" * 2048 + b'"}'
    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(200, content=big)),
        sleep=lambda _: None,
        max_response_bytes=1024,
    ) as fetcher:
        with pytest.raises(AdapterError, match="larger than"):
            fetcher.get_json("https://api.lever.co/v0/postings/one")


def test_pathological_nesting_is_an_adapter_error() -> None:
    depth = 100_000
    body = b"[" * depth + b"]" * depth
    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(200, content=body)),
        sleep=lambda _: None,
    ) as fetcher:
        with pytest.raises(AdapterError, match="nested too deeply"):
            fetcher.get_json("https://api.lever.co/v0/postings/one")


def test_dripping_response_hits_read_deadline() -> None:
    clock = FakeClock()

    def drip():
        yield b'{"jobs"'
        clock.now += 61.0  # the second chunk arrives after the deadline
        yield b": []}"

    with Fetcher(
        transport=make_transport(lambda _: httpx.Response(200, content=drip())),
        sleep=lambda _: None,
        clock=clock,
    ) as fetcher:
        with pytest.raises(AdapterError, match="too slowly"):
            fetcher.get_json("https://api.lever.co/v0/postings/one")
```

- [ ] **Step 2: Verify they fail** — `uv run pytest tests/test_politeness.py -q` → `TypeError` for the unknown `max_response_bytes` kwarg; the other two get the whole body without limits (nesting raises raw `RecursionError`, escaping `AdapterError`).

- [ ] **Step 3: Implement** in `src/interninbox/fetch.py`.

Add `import json` to the imports. Add constants next to the existing ones:

```python
MAX_RESPONSE_BYTES = 10_000_000  # no board API legitimately sends 10 MB of JSON
READ_DEADLINE_SECONDS = 60.0  # total body-download budget, not per-socket-read
```

Extend `__init__` (parameter and attribute):

```python
        min_host_delay: float = MIN_HOST_DELAY,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
```

and store `self._max_response_bytes = max_response_bytes` with the other attributes.

Replace `get_json` entirely (this folds in Task 4's status handling; streaming means the body is read under our own limits — `httpx.Client(timeout=...)` only bounds each socket read, so a 1-byte-per-14 s dripper previously held a scan open forever):

```python
    def get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> object:
        """GET `url` and return the decoded JSON body.

        Raises `AdapterError` with a one-line human message on any failure
        (after one retry for transient ones).
        """
        host = urllib.parse.urlsplit(url).netloc
        last_error: str = "unknown error"
        for _attempt in (1, 2):
            self._wait_for_host(host)
            try:
                with self._client.stream(
                    "GET", url, params=params, headers=headers, follow_redirects=follow_redirects
                ) as response:
                    if response.status_code >= 500:
                        last_error = f"server error HTTP {response.status_code}"
                        continue  # transient — retry once
                    if response.status_code == 429 and _attempt == 1:
                        self._sleep(_retry_after_seconds(response.headers.get("Retry-After")))
                        last_error = f"HTTP 429 from {host} (rate limited)"
                        continue  # one polite retry, then _client_error below reports it
                    if response.status_code >= 400:
                        raise AdapterError(_client_error(response.status_code, host))
                    if response.status_code >= 300:
                        raise AdapterError(
                            f"unexpected redirect (HTTP {response.status_code}) from {host}"
                        )
                    body = self._read_limited(response, host)
            except httpx.HTTPError as exc:
                last_error = f"network error: {exc}"
                continue  # transient — retry once
            return _parse_json(body, host)
        raise AdapterError(f"{last_error} (after retry)")

    def _read_limited(self, response: httpx.Response, host: str) -> bytes:
        chunks: list[bytes] = []
        total = 0
        started = self._clock()
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self._max_response_bytes:
                raise AdapterError(
                    f"response from {host} is larger than {self._max_response_bytes} bytes "
                    "— refusing it"
                )
            if self._clock() - started > READ_DEADLINE_SECONDS:
                raise AdapterError(f"response from {host} is downloading too slowly — gave up")
            chunks.append(chunk)
        return b"".join(chunks)
```

Add the parse helper at module level (below `_retry_after_seconds`):

```python
def _parse_json(body: bytes, host: str) -> object:
    try:
        return json.loads(body)
    except RecursionError:
        raise AdapterError(f"response from {host} is nested too deeply to parse") from None
    except ValueError as exc:
        raise AdapterError(f"response from {host} is not valid JSON: {exc}") from exc
```

- [ ] **Step 4: Verify** — `uv run pytest -q && uv run ruff check .` → all pass, including the pre-existing retry/UA/politeness tests against the streamed path.

- [ ] **Step 5: Commit**

```bash
git add src/interninbox/fetch.py tests/test_politeness.py
git commit -m "fix: bound every response — 10 MB size cap, 60 s read deadline, RecursionError contained

httpx's timeout is per socket read, so a dripping server could hold a
scan open forever; responses are now streamed under our own budget, and
pathologically nested JSON becomes an AdapterError instead of a traceback.

Fixes KNOWN-ISSUES M11.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: USAJOBS request hygiene — no hardcoded Host, no redirect following (L8)

**Files:**
- Modify: `src/interninbox/adapters/usajobs.py`
- Test: `tests/test_usajobs.py`

**Interfaces:**
- Consumes: `get_json(..., follow_redirects=False)` from Task 5.
- Produces: `usajobs._headers` returns only `User-Agent` and `Authorization-Key`. Task 11 rewrites `fetch`'s loop but keeps `follow_redirects=False` — nothing else depends on this task.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_usajobs.py`:

```python
def test_no_hardcoded_host_header() -> None:
    # httpx derives Host from the URL; hardcoding it would follow a redirect
    # to a different host while still claiming to be data.usajobs.gov.
    assert "Host" not in usajobs._headers("key", "fixture@example.test")


def test_redirects_are_not_followed(instant_fetcher) -> None:
    def redirecting(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://elsewhere.test/x"})

    with instant_fetcher(make_transport(redirecting)) as fetcher:
        with pytest.raises(AdapterError, match="unexpected redirect"):
            usajobs.fetch(fetcher, CFG, "fixture-api-key")
```

- [ ] **Step 2: Verify they fail** — `uv run pytest tests/test_usajobs.py -q` → `_headers` still contains `Host`; the redirect is followed and fails differently (network error to elsewhere.test).

- [ ] **Step 3: Implement** in `src/interninbox/adapters/usajobs.py`:

Replace `_headers`:

```python
def _headers(api_key: str, email: str) -> dict[str, str]:
    # The documented auth contract: the User-Agent IS the registered email.
    # Host is NOT set by hand — httpx derives it from the URL, so a redirect
    # can never carry a stale data.usajobs.gov Host header elsewhere.
    return {
        "User-Agent": email,
        "Authorization-Key": api_key,
    }
```

In `fetch`, add `follow_redirects=False` to the `get_json` call:

```python
        payload = fetcher.get_json(
            SEARCH_URL,
            params={**params, "Page": str(page_number)},
            headers=headers,
            follow_redirects=False,
        )
```

Update the module docstring's "three headers" sentence to "two headers plus the URL-derived Host", and in `tests/test_usajobs.py` update the comment in `test_fetch_sends_documented_auth_headers` from "The three documented headers: Host, User-Agent = registered email, key." to "User-Agent = registered email, plus the key; Host comes from the URL." (its assertions already only check those). Delete the `SEARCH_HOST` constant if nothing references it after this change.

- [ ] **Step 4: Verify** — `uv run pytest -q && uv run ruff check .` → all pass.

- [ ] **Step 5: Commit**

```bash
git add src/interninbox/adapters/usajobs.py tests/test_usajobs.py
git commit -m "fix: USAJOBS — drop hardcoded Host header, refuse redirects

A cross-origin redirect could previously carry the Authorization-Key,
email User-Agent, and a stale Host header to an arbitrary target and
skipped the per-host politeness delay.

Fixes KNOWN-ISSUES L8.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Scan progress + clean Ctrl-C, broken pipes, and unreadable files (H4, L2, part of M10)

**Files:**
- Modify: `src/interninbox/cli.py`, `src/interninbox/config.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `_scan_boards(config, fetcher, result, *, progress: bool = False)` and `_scan_usajobs(config, fetcher, env, result, *, progress: bool = False)`; `main()` returns 130 on KeyboardInterrupt; `load_config` raises `ConfigError` (not `PermissionError`) on unreadable files. Task 8 edits `_cmd_scan` further — apply this task first.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_cli.py`:

```python
def test_progress_lines_written_when_tty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from interninbox.cli import _scan_boards
    from interninbox.config import load_config
    from interninbox.fetch import Fetcher
    from interninbox.models import ScanResult

    config = load_config(write_config(tmp_path, THREE_BOARDS))
    result = ScanResult()
    with Fetcher(transport=make_transport(route), sleep=lambda _: None) as fetcher:
        _scan_boards(config, fetcher, result, progress=True)
    err = capsys.readouterr().err
    assert "[1/3] greenhouse:aurora-widgets ..." in err
    assert "[3/3] ashby:harborline ..." in err


def test_no_progress_lines_when_not_a_tty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config(tmp_path, THREE_BOARDS)
    assert main(["scan", "--config", str(config)], transport=make_transport(route), **NO_SLEEP) == 0
    assert "[1/3]" not in capsys.readouterr().err  # capsys stderr is not a tty


def test_keyboard_interrupt_is_clean_and_130(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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
```

- [ ] **Step 2: Verify they fail** — `uv run pytest tests/test_cli.py -q` → progress test: `TypeError` (no `progress` kwarg); KeyboardInterrupt/PermissionError tests: raw exceptions.

- [ ] **Step 3: Implement.**

`src/interninbox/config.py` — wrap the file read (`OSError` before `TOMLDecodeError`; note `TOMLDecodeError` is not an `OSError`):

```python
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
```

`src/interninbox/cli.py`:

1. `main()` — add the KeyboardInterrupt arm after the `ConfigError` handler:

```python
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
```

2. `entrypoint()` — replace it (stays `# pragma: no cover`):

```python
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
```

3. `_cmd_init` — wrap the write:

```python
    try:
        target.write_text(STARTER_CONFIG, encoding="utf-8")
    except OSError as exc:
        print(f"error: could not write {target}: {exc}", file=sys.stderr)
        return 1
```

4. Progress plumbing. In `_cmd_scan`, replace the `with Fetcher(...)` block:

```python
    progress = sys.stderr.isatty()
    result = ScanResult()
    with Fetcher(transport=transport, sleep=sleep) as fetcher:
        _scan_boards(config, fetcher, result, progress=progress)
        _scan_usajobs(config, fetcher, env, result, progress=progress)
```

`_scan_boards` becomes:

```python
def _scan_boards(
    config: Config, fetcher: Fetcher, result: ScanResult, *, progress: bool = False
) -> None:
    total = len(config.companies)
    for index, company in enumerate(config.companies, start=1):
        if progress:
            print(f"[{index}/{total}] {company.label} ...", file=sys.stderr, flush=True)
        adapter_fetch = ADAPTERS[company.ats]
        try:
            listings = adapter_fetch(fetcher, company.slug)
        except AdapterError as exc:
            result.companies_failed += 1
            result.warnings.append(f"{company.label}: {exc}")
            continue
        result.companies_scanned += 1
        result.listings.extend(listings)
```

`_scan_usajobs` gains `*, progress: bool = False` and, directly before the `usajobs.fetch(...)` try block:

```python
    if progress:
        print("[usajobs] data.usajobs.gov ...", file=sys.stderr, flush=True)
```

- [ ] **Step 4: Verify** — `uv run pytest -q && uv run ruff check .` → all pass.

- [ ] **Step 5: Commit**

```bash
git add src/interninbox/cli.py src/interninbox/config.py tests/test_cli.py
git commit -m "feat: per-company progress on a tty; clean Ctrl-C, pipes, and unreadable files

A 34-company scan was silent until the very end (minutes on a bad
network) and Ctrl-C dumped a traceback. Now: progress lines to stderr
when it's a tty, exit 130 on interrupt, quiet exit on a closed pipe,
errors='replace' on Windows consoles, and friendly messages for an
unreadable config / unwritable init target.

Fixes KNOWN-ISSUES H4 and L2; crash half of M10.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Zero-result diagnostics — say WHY nothing matched (H3)

**Files:**
- Modify: `src/interninbox/models.py`, `src/interninbox/cli.py`, `src/interninbox/output.py`
- Test: `tests/test_output.py`, `tests/test_cli.py` (one existing test updated)

**Interfaces:**
- Consumes: Task 7's `_cmd_scan` shape.
- Produces: `ScanResult.listings_checked: int = 0` and `ScanResult.listings_matched: int = 0`; JSON summary gains `"listings_checked"`. Task 9 reorders `_cmd_scan`'s state recording around these same lines.

**Existing-test update (expected):** `tests/test_output.py::test_json_output_shape` asserts the summary dict by equality — it gains the `"listings_checked": 3` key, and `_result()` gains `listings_checked=3`. No other existing test changes.

- [ ] **Step 1: Write the failing tests.** In `tests/test_output.py`, change `_result()` to pass `listings_checked=3` and the summary assertion in `test_json_output_shape` to:

```python
    assert payload["summary"] == {
        "internships": 3,
        "companies_scanned": 2,
        "companies_failed": 1,
        "listings_checked": 3,
    }
```

Append:

```python
def test_empty_table_explains_filters_matched_none() -> None:
    result = ScanResult(companies_scanned=3, listings_checked=57)
    text = format_table(result)
    assert "57 listings checked" in text


def test_empty_table_explains_empty_boards() -> None:
    result = ScanResult(companies_scanned=3, listings_checked=0)
    text = format_table(result)
    assert "no jobs at all" in text


def test_empty_table_explains_nothing_new() -> None:
    result = ScanResult(companies_scanned=1, listings_checked=10, listings_matched=4)
    text = format_table(result)
    assert "already seen" in text
```

- [ ] **Step 2: Verify they fail** — `uv run pytest tests/test_output.py -q` → `TypeError: unexpected keyword argument 'listings_checked'`.

- [ ] **Step 3: Implement.**

`src/interninbox/models.py` — extend `ScanResult`:

```python
@dataclass
class ScanResult:
    """Everything one scan produced, for the output layer."""

    listings: list[Listing] = field(default_factory=list)
    companies_scanned: int = 0
    companies_failed: int = 0
    listings_checked: int = 0  # everything fetched, before any filtering
    listings_matched: int = 0  # after filters, before --new-only
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
```

`src/interninbox/cli.py` — in `_cmd_scan`, replace the two lines computing `matched`/`shown` with:

```python
    result.listings_checked = len(result.listings)
    matched = [listing for listing in result.listings if matches(listing, config.filters)]
    result.listings_matched = len(matched)
    shown = [listing for listing in matched if state.is_new(listing)] if args.new_only else matched
    result.listings = shown
```

`src/interninbox/output.py` — replace `format_table`'s empty branch:

```python
    if not listings:
        lines = ["No matching internships found."]
        if result.listings_matched:
            lines.append(
                f"({result.listings_matched} matched but were already seen — "
                "nothing new since the last scan)"
            )
        elif result.listings_checked:
            lines.append(
                f"({result.listings_checked} listings checked; none matched your filters "
                "— internships may be off-season, or try loosening [filters])"
            )
        elif result.companies_scanned:
            lines.append("(the boards responded but list no jobs at all right now)")
        lines.append(summary_line(result))
        return "\n".join(lines)
```

and add to `format_json`'s summary dict:

```python
            "listings_checked": result.listings_checked,
```

- [ ] **Step 4: Verify** — `uv run pytest -q && uv run ruff check .` → all pass (the `--new-only` CLI tests assert substrings, so the new explanatory line does not break them).

- [ ] **Step 5: Commit**

```bash
git add src/interninbox/models.py src/interninbox/cli.py src/interninbox/output.py tests/test_output.py
git commit -m "feat: explain empty results — filtered out, already seen, or empty boards

'No matching internships found.' on day one gave no hint whether the
tool failed, the filters missed, or the boards are off-season. The empty
result now says which, and the JSON summary carries listings_checked.

Addresses KNOWN-ISSUES H3.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: State — atomic writes, and record everything fetched (M9, M8)

**Files:**
- Modify: `src/interninbox/state.py`, `src/interninbox/cli.py`
- Test: `tests/test_state.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 8's `_cmd_scan` lines.
- Produces: `State.save` writes `<name>.tmp` then `os.replace`s it (same JSON schema, version 1 — no migration). Semantic change to document in Task 13: "new" now means "never *fetched* before", not "never matched before".

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_state.py` (add `import json` and `import pytest` to its imports):

```python
def test_save_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / ".interninbox-state.json"
    state = load_state(path)
    state.record([make_listing()])
    state.save(path)
    assert [entry.name for entry in tmp_path.iterdir()] == [path.name]


def test_failed_save_preserves_previous_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".interninbox-state.json"
    path.write_text('{"version": 1, "seen": {"old": {"url": ""}}}', encoding="utf-8")
    state = load_state(path)
    state.record([make_listing()])

    def no_space(self: Path, *args: object, **kwargs: object) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", no_space)
    with pytest.raises(OSError):
        state.save(path)
    monkeypatch.undo()
    assert "old" in json.loads(path.read_text(encoding="utf-8"))["seen"]
```

Append to `tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Verify they fail** — `uv run pytest tests/test_state.py tests/test_cli.py -q` → the failed-save test corrupts the file (in-place truncating write); the flood test shows "Design Intern" as new.

- [ ] **Step 3: Implement.**

`src/interninbox/state.py` — add `import os`, replace `save`:

```python
    def save(self, path: Path) -> None:
        payload = {"version": _VERSION, "seen": self._seen}
        text = json.dumps(payload, indent=1, sort_keys=True) + "\n"
        # Write-then-rename: a crash, Ctrl-C, or full disk mid-write can
        # never leave a half-written (corrupt) state file behind.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
```

`src/interninbox/cli.py` — in `_cmd_scan`, move recording BEFORE `result.listings = shown` and record the full fetched list (replaces the old `state.record(matched)` line below the comment):

```python
    result.listings_checked = len(result.listings)
    matched = [listing for listing in result.listings if matches(listing, config.filters)]
    result.listings_matched = len(matched)
    shown = [listing for listing in matched if state.is_new(listing)] if args.new_only else matched
    # Record EVERYTHING fetched — flag or not — so "new" means "never fetched
    # before": loosening a filter later cannot flood --new-only with old posts.
    state.record(result.listings)
    result.listings = shown
```

(The old comment "Always update state — flag or not …" is superseded by this one; delete it.)

- [ ] **Step 4: Verify** — `uv run pytest -q && uv run ruff check .` → all pass (existing `--new-only` tests still hold: recording a superset can only mark more things seen).

- [ ] **Step 5: Commit**

```bash
git add src/interninbox/state.py src/interninbox/cli.py tests/test_state.py tests/test_cli.py
git commit -m "fix: atomic state writes; --new-only records all fetched listings

write-then-os.replace means a crash mid-write can't corrupt the seen
file. Recording everything fetched (not just matches) stops --new-only
from flooding after a filter change.

Fixes KNOWN-ISSUES M9 and M8 (cross-process locking stays documented).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Adapters — secondary/all locations, and the bool-date guard (M1, L9-part)

**Files:**
- Modify: `src/interninbox/adapters/ashby.py`, `src/interninbox/adapters/lever.py`
- Modify: `tests/fixtures/ashby/harborline.json`, `tests/fixtures/lever/cobalt_cartography.json`
- Test: `tests/test_ashby.py`, `tests/test_lever.py` (two existing assertions updated)

**Interfaces:** `parse`/`fetch` signatures unchanged; only richer `Listing.locations`.

**Existing-test updates (expected):** `test_ashby.py::test_parse_remote_workplace_type_adds_remote_location` expects `("North America", "Europe", "Remote")` after the fixture change; `test_lever.py::test_parse_full_board` expects `first.locations == ("San Francisco, CA", "New York, NY")`. Nothing else — in particular `tests/test_cli.py` counts stay at 6 across 3.

- [ ] **Step 1: Extend fixtures and write the failing tests.**

In `tests/fixtures/ashby/harborline.json`, add to the SECOND job ("Design Intern", the one with `"location": "North America"`), after its `"workplaceType"` line:

```json
      "secondaryLocations": [
        { "location": "Europe" },
        { "location": "North America" }
      ],
```

In `tests/fixtures/lever/cobalt_cartography.json`, change the FIRST posting's categories to:

```json
    "categories": {
      "location": "San Francisco, CA",
      "allLocations": ["San Francisco, CA", "New York, NY"],
      "team": "Engineering"
    }
```

Append to `tests/test_ashby.py`:

```python
def test_parse_secondary_locations_included_and_deduped() -> None:
    listings = ashby.parse(load_fixture("ashby/harborline.json"), "harborline")
    # Primary "North America" + secondary "Europe"; the duplicate secondary
    # "North America" is dropped; "Remote" still appended from workplaceType.
    assert listings[1].locations == ("North America", "Europe", "Remote")
```

Append to `tests/test_lever.py`:

```python
def test_parse_all_locations_preferred_over_single() -> None:
    listings = lever.parse(load_fixture("lever/cobalt_cartography.json"), "cobalt-cartography")
    assert listings[0].locations == ("San Francisco, CA", "New York, NY")


def test_boolean_created_at_is_not_a_date() -> None:
    posting = {
        "id": "x1",
        "text": "QA Intern",
        "hostedUrl": "https://jobs.example-lever.test/x/x1",
        "createdAt": True,  # bool is an int subclass; must not become 1970-01-01
    }
    assert lever.parse([posting], "x")[0].posted_at is None
```

Update the two existing assertions named above to their new expected tuples.

- [ ] **Step 2: Verify failures** — `uv run pytest tests/test_ashby.py tests/test_lever.py -q` → new tests fail (secondary/allLocations ignored; `True` parses as epoch 0).

- [ ] **Step 3: Implement.**

`src/interninbox/adapters/ashby.py` — replace the locations block at the top of `_parse_job`:

```python
    locations: list[str] = []
    location = job.get("location")
    if location:
        locations.append(str(location))
    secondary = job.get("secondaryLocations")
    if isinstance(secondary, list):
        for entry in secondary:
            if isinstance(entry, dict) and entry.get("location"):
                name = str(entry["location"])
                if name not in locations:
                    locations.append(name)
    workplace_type = job.get("workplaceType")
    if isinstance(workplace_type, str) and workplace_type.lower() == "remote":
        if not any("remote" in entry.lower() for entry in locations):
            locations.append("Remote")
```

and pass `locations=tuple(locations)` in the `Listing(...)` call. Add to the module docstring's field notes: `` - `secondaryLocations[].location` lists additional offices. ``

`src/interninbox/adapters/lever.py` — replace the locations block in `_parse_posting`:

```python
    locations: list[str] = []
    categories = posting.get("categories")
    if isinstance(categories, dict):
        raw_all = categories.get("allLocations")
        if isinstance(raw_all, list):
            for entry in raw_all:
                if isinstance(entry, str) and entry and entry not in locations:
                    locations.append(entry)
        if not locations and categories.get("location"):
            locations.append(str(categories["location"]))
    workplace_type = posting.get("workplaceType")
    if isinstance(workplace_type, str) and workplace_type.lower() == "remote":
        if not any("remote" in location.lower() for location in locations):
            locations.append("Remote")
```

pass `locations=tuple(locations)`, and guard the date (bool is an int subclass):

```python
    created_at = posting.get("createdAt")
    if isinstance(created_at, int | float) and not isinstance(created_at, bool):
        posted_at = dt.datetime.fromtimestamp(created_at / 1000, tz=dt.UTC)
```

Add to lever's docstring field notes: `` - `categories.allLocations` (when present) supersedes the single `categories.location`. ``

- [ ] **Step 4: Verify** — `uv run pytest -q && uv run ruff check .` → all pass.

- [ ] **Step 5: Commit**

```bash
git add src/interninbox/adapters/ashby.py src/interninbox/adapters/lever.py \
        tests/fixtures/ashby/harborline.json tests/fixtures/lever/cobalt_cartography.json \
        tests/test_ashby.py tests/test_lever.py
git commit -m "fix: read Ashby secondaryLocations and Lever allLocations; bool is not a date

Multi-office postings no longer lose their extra locations (which also
made the locations filter wrongly drop them), and a boolean createdAt no
longer parses as 1970-01-01.

Fixes KNOWN-ISSUES M1 and the Lever half of L9.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: USAJOBS — OR keywords, truncation warning, USAJOBS-only configs (M7)

**Files:**
- Modify: `src/interninbox/config.py` (`load_config`, `STARTER_CONFIG`), `src/interninbox/adapters/usajobs.py`, `src/interninbox/cli.py`
- Test: `tests/test_usajobs.py`, `tests/test_config.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `follow_redirects=False` from Task 6.
- Produces: `usajobs.fetch(fetcher, cfg, api_key, warn: Callable[[str], None] = ...)`; `load_config` accepts a missing/empty `companies` list when `[usajobs].enabled = true`.

**Existing-test update (expected):** whichever test in `tests/test_config.py` asserts the missing-`companies` error message must switch to the new "configures nothing to scan" wording (find it with `grep -n "companies" tests/test_config.py`). No other existing expectations change.

- [ ] **Step 1: Write the failing tests.**

Append to `tests/test_usajobs.py`:

```python
def test_two_keywords_are_queried_separately_or_semantics(instant_fetcher) -> None:
    # USAJOBS ANDs words inside one Keyword param; a keyword LIST means OR,
    # so each keyword gets its own query (deduped on control number).
    requests_seen: list[httpx.Request] = []
    cfg = UsaJobsConfig(enabled=True, keywords=("software", "data"), email="fixture@example.test")
    with instant_fetcher(make_transport(_paginated_handler(requests_seen))) as fetcher:
        usajobs.fetch(fetcher, cfg, "fixture-api-key")
    keywords = {request.url.params["Keyword"] for request in requests_seen}
    assert keywords == {"software", "data"}


def test_truncation_at_page_cap_warns(instant_fetcher) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["Page"]
        item = {
            "MatchedObjectId": f"9000{page}",
            "MatchedObjectDescriptor": {
                "PositionTitle": "Student Trainee (Synthetic)",
                "PositionURI": f"https://example.test/ViewDetails/9000{page}",
                "OrganizationName": "Bureau of Fictional Statistics",
            },
        }
        return json_response(
            {"SearchResult": {"SearchResultCountAll": 10000, "SearchResultItems": [item]}}
        )

    warnings: list[str] = []
    with instant_fetcher(make_transport(handler)) as fetcher:
        usajobs.fetch(fetcher, CFG, "fixture-api-key", warn=warnings.append)
    assert warnings and "truncated" in warnings[0]
```

Append to `tests/test_config.py`:

```python
def test_usajobs_only_config_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "interninbox.toml"
    path.write_text(
        '[usajobs]\nenabled = true\nemail = "fixture@example.test"\n', encoding="utf-8"
    )
    config = load_config(path)
    assert config.companies == ()
    assert config.usajobs.enabled


def test_nothing_to_scan_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "interninbox.toml"
    path.write_text("companies = []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="nothing to scan"):
        load_config(path)
```

Append to `tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Verify failures** — `uv run pytest tests/test_usajobs.py tests/test_config.py tests/test_cli.py -q` → keyword test sees one joined `"software data"` query; truncation test: `TypeError` (no `warn` kwarg); config tests: "no `companies` list" error.

- [ ] **Step 3: Implement.**

`src/interninbox/config.py` — in `load_config`, replace everything from `raw_companies = data.get("companies")` to the `return Config(...)` with:

```python
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
    if not companies and not usajobs_cfg.enabled:
        raise ConfigError(
            f"{path} configures nothing to scan — add a `companies` list "
            "(e.g. companies = [\"greenhouse:stripe\"]) or enable [usajobs]"
        )

    return Config(
        companies=companies,
        filters=_parse_filters(data.get("filters")),
        usajobs=usajobs_cfg,
        path=path,
    )
```

In `STARTER_CONFIG`, change the commented `# keywords = ["software"]` line to:

```toml
# keywords = ["software"]   # each keyword is searched separately (OR)
```

`src/interninbox/adapters/usajobs.py` — add `from collections.abc import Callable` to the imports and replace `fetch`:

```python
def fetch(
    fetcher: Fetcher,
    cfg: UsaJobsConfig,
    api_key: str,
    warn: Callable[[str], None] = lambda message: None,
) -> list[Listing]:
    headers = _headers(api_key, cfg.email)
    base_params: dict[str, str] = {
        "HiringPath": "student",
        "ResultsPerPage": str(RESULTS_PER_PAGE),
    }
    # One query per keyword: USAJOBS ANDs the words inside a single Keyword
    # param, but a configured keyword list means OR. No keywords = one
    # unrestricted query. Results are deduped on the control number.
    queries: list[dict[str, str]] = (
        [{**base_params, "Keyword": keyword} for keyword in cfg.keywords]
        if cfg.keywords
        else [base_params]
    )

    listings: list[Listing] = []
    seen_ids: set[str] = set()
    for params in queries:
        fetched = 0
        count_all: int | None = None
        for page_number in range(1, MAX_PAGES + 1):
            payload = fetcher.get_json(
                SEARCH_URL,
                params={**params, "Page": str(page_number)},
                headers=headers,
                follow_redirects=False,
            )
            items, count_all = _page_items(payload)
            if not items:
                break
            for item in items:
                listing = parse_item(item)
                if listing.listing_id in seen_ids:
                    continue
                seen_ids.add(listing.listing_id)
                listings.append(listing)
            fetched += len(items)
            if count_all is not None and fetched >= count_all:
                break
        if count_all is not None and fetched < count_all:
            keyword = params.get("Keyword", "")
            scope = f" for keyword {keyword!r}" if keyword else ""
            warn(
                f"usajobs: results truncated{scope} — fetched {fetched} of {count_all}; "
                "add or narrow keywords to see everything"
            )
    return listings
```

`src/interninbox/cli.py` — in `_scan_usajobs`, pass the warning sink:

```python
        listings = usajobs.fetch(fetcher, cfg, api_key, warn=result.warnings.append)
```

- [ ] **Step 4: Verify** — `uv run pytest -q && uv run ruff check .` → all pass (single-keyword tests unchanged: one keyword still produces `Keyword=software`).

- [ ] **Step 5: Commit**

```bash
git add src/interninbox/config.py src/interninbox/adapters/usajobs.py src/interninbox/cli.py \
        tests/test_usajobs.py tests/test_config.py tests/test_cli.py
git commit -m "feat: USAJOBS — OR keyword queries, truncation warning, USAJOBS-only configs

Multiple keywords now mean OR (one query each, deduped) instead of a
silently AND-ed phrase; hitting the page cap warns instead of silently
truncating; and a config with only [usajobs] no longer needs a dummy
ATS company.

Fixes KNOWN-ISSUES M7.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 12: Release & CI hardening — one version source, SHA-pinned actions, real matrix (M12, M13, L10, CI half of M10)

**Files:**
- Modify: `pyproject.toml`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.gitignore`
- Create: `uv.lock` (committed)

No unit tests — verification is build/CI evidence. Do the steps in order.

- [ ] **Step 1: Single version source.** In `pyproject.toml` `[project]`: delete `version = "0.1.0"`, add `dynamic = ["version"]`, and add `"Programming Language :: Python :: 3.13"` to `classifiers`. Add a new table:

```toml
[tool.hatch.version]
path = "src/interninbox/__init__.py"
```

Verify: `uv build` succeeds and `ls dist/` shows `interninbox-0.1.0-py3-none-any.whl` (version read from `__init__.py`). Then `rm -rf dist/`.

- [ ] **Step 2: Tag-version guard.** In `.github/workflows/release.yml`, in the `build` job after the checkout step, insert:

```yaml
      - name: Ensure the release tag matches the package version
        run: |
          tag="${GITHUB_REF_NAME#v}"
          version="$(python3 -c 'import re, pathlib; print(re.search(r"__version__ = \"([^\"]+)\"", pathlib.Path("src/interninbox/__init__.py").read_text()).group(1))')"
          if [ "$tag" != "$version" ]; then
            echo "release tag v$tag does not match __version__ $version" >&2
            exit 1
          fi
```

- [ ] **Step 3: Least-privilege token.** Add to BOTH workflow files, top level (after `on:`):

```yaml
permissions:
  contents: read
```

(`release.yml`'s publish job keeps its existing job-level `id-token: write`.)

- [ ] **Step 4: Pin actions by commit SHA.** Resolve each SHA at execution time — do NOT copy SHAs from this plan, resolve fresh:

```bash
git ls-remote https://github.com/actions/checkout refs/tags/v4 | cut -f1
git ls-remote https://github.com/astral-sh/setup-uv refs/tags/v5 | cut -f1
git ls-remote https://github.com/actions/upload-artifact refs/tags/v4 | cut -f1
git ls-remote https://github.com/actions/download-artifact refs/tags/v4 | cut -f1
git ls-remote https://github.com/pypa/gh-action-pypi-publish refs/heads/release/v1 | cut -f1
```

Replace every `uses:` in both workflows with `uses: <owner>/<repo>@<full-sha> # <old tag>`, e.g. `uses: actions/checkout@<sha> # v4`.

- [ ] **Step 5: CI matrix + lockfile.** In `.github/workflows/ci.yml`:

```yaml
jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest]
        python-version: ["3.11", "3.12", "3.13"]
```

(keep the steps; only `runs-on` and the matrix change). In `.gitignore`, delete the `uv.lock` line. Run `uv lock` and `git add uv.lock`. If `CONTRIBUTING.md` mentions the lockfile being ignored, update that sentence to say it is committed.

- [ ] **Step 6: Verify locally** — `uv sync && uv run pytest -q && uv run ruff check .` all green; `python3 -c "import yaml"` is NOT required — instead sanity-check workflow syntax with `uvx --from yamllint yamllint .github/workflows/ || true` (advisory only).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml .github/workflows/release.yml .gitignore uv.lock CONTRIBUTING.md
git commit -m "ci: single version source, SHA-pinned actions, least-privilege token, real matrix

hatch reads the version from __init__.py and the release job refuses a
mismatched tag; actions are pinned by commit SHA; workflows get a
top-level read-only token; CI covers ubuntu+windows x 3.11-3.13; uv.lock
is committed so CI and contributors resolve identically.

Fixes KNOWN-ISSUES M12, M13, L10, and the CI half of M10.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Note: Windows CI runs for the first time on push. If a test fails only on Windows, fix it in a follow-up commit on this branch — the suite avoids chmod/tty tricks precisely so it should pass.

---

### Task 13: Documentation sweep — README truth, new features, KNOWN-ISSUES refresh (M2, M4, M5, L1, L5, L6, L7)

**Files:**
- Modify: `README.md`, `docs/KNOWN-ISSUES.md`

No unit tests — the gate is `grep` evidence plus a full-suite run.

- [ ] **Step 1: README corrections and additions.**

1. **M2 (the README is the wrong side of the contradiction — the code and starter config agree):** find the paragraph under "How matching works" that reads "A listing with no stated location passes the locations filter (boards often omit location metadata; dropping those silently would hide real internships)." and replace it with:

   > A listing with no stated location is **dropped** when `locations` is set — there is nothing to match against. Leave `locations = []` to keep such listings (boards often omit location metadata).

2. **match_keywords (Task 2):** in the config-reference table add, next to the `filters.include_keywords` row:

   `| \`filters.match_keywords\` | list of strings | \`[]\` | Whole-word title keywords required on top of the internship signal (narrows; \`include_keywords\` broadens) |`

   and in "How matching works", document the order: internship signal (built-ins OR `include_keywords`) → `match_keywords` requirement → staff-role exclusion → `exclude_keywords` → `locations`/`remote_ok`.

3. **M4 (docs-only):** under the `filters.locations` explanation add:

   > Location matching is plain substring matching: `"NY"` also matches "Su**nny**vale, CA", and "New York" will not catch a board that writes "NYC". Prefer full names and list both forms when a city has a common abbreviation: `locations = ["New York", "NYC"]`.

4. **M5 (honest scope):** in "Scope, honestly" add a bullet:

   > Title-only matching still misses some real internships: bare "Trainee", titles like "Software Engineer (Intern) II" (the seniority-level filter wins), and languages beyond the built-in German/French patterns. `include_keywords` can widen the net.

5. **L1:** in the "`--new-only` and the state file" section, replace the claim that the state file is "gitignored by `init`'s convention" with:

   > `init` writes only the TOML — if your config lives in a git repository, add `.interninbox-state.json` to your `.gitignore` yourself.

6. **L5:** same section, add:

   > The POSTED column means slightly different things per source: Greenhouse first-published, Lever created, Ashby last-published (a repost looks new), USAJOBS announcement-open date.

7. **L7:** in the `--state` flag row/section add: "Two different configs in the same directory share the default state file — pass `--state` to keep them separate."

8. **M8 semantics (Task 9):** same state section, state plainly: "A listing counts as *seen* once it has been fetched, even if your filters hid it."

- [ ] **Step 2: Refresh `docs/KNOWN-ISSUES.md`.** Add under the intro: `> **Status 2026-08-11:** the issues below marked *Fixed* were resolved on the known-issues-remediation branch; unmarked issues remain open.` Then annotate each fixed entry's heading, e.g. `### H1: … — Fixed`, with a one-line note of the fix, for: H1, H2, H3 (partially — progress + diagnostics; starter-list rot remains), H4, M1, M2, M3, M6, M7, M8 (atomicity/flood fixed; cross-process locking still open), M9, M10, M11, M12, M13, L1, L2, L4, L8, L9, L10, and the control-character half of L3. Leave M4, M5 (narrowed, not closed), L5, L6, L7, and L3's wide-character half clearly open.

- [ ] **Step 3: Verify** — `uv run pytest -q && uv run ruff check .` still green; `grep -c "Fixed" docs/KNOWN-ISSUES.md` ≥ 20; `grep -n "match_keywords" README.md` shows the table row and matching-order text.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/KNOWN-ISSUES.md
git commit -m "docs: README matches the code; KNOWN-ISSUES marked up with fixes

Fixes the no-location contradiction (M2), documents match_keywords,
location-matching honesty (M4), heuristic misses (M5), init/gitignore
wording (L1), POSTED semantics (L5), shared state paths (L7), and the
new 'seen = fetched' --new-only contract.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Completion

1. Run the full gates one last time: `uv run pytest -q && uv run ruff check .`.
2. Push the branch and open ONE pull request titled `fix: resolve the High/Medium findings from the v0.1.0 adversarial review`, whose body lists the issue-ID → task map from the header. (Repo habit is PR-per-change via `gh pr create`.)
3. Leave the version at 0.1.0 — bumping to 0.2.0 is the maintainer's release decision; with Task 12 done it is a one-line edit to `src/interninbox/__init__.py`.
4. Deferred items (M4 matching, M8 locking, L3 wide-char widths, L6 pruning, L7 state paths) stay documented in KNOWN-ISSUES as open — candidates for a follow-up plan.
