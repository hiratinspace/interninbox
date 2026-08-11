# Known issues

An honest, living list of `interninbox`'s current limitations and rough edges,
from an adversarial review of the codebase (2026-08-11, against v0.1.0). Nothing
here is a secret; it is all discoverable from the source. It is written down so
users can set expectations, contributors can find good first issues, and nobody
is surprised.

> **Status 2026-08-11:** the issues below marked *Fixed* were resolved on the
> known-issues-remediation branch; unmarked issues remain open.

Severity key:

- **High**: a normal user hits it and loses trust, or it is a real security/trust gap.
- **Medium**: a real defect, but situational.
- **Low**: polish, maintenance, or an edge case.

Each entry notes where it lives in the code. "Verified" means it was reproduced
against the code or a live API during review, not just reasoned about.

---

## High

### H1: Terminal escape sequences from job boards reach your terminal unsanitized — Fixed
`src/interninbox/output.py` (table and markdown paths)

**Fix:** table and markdown output now strip `Cc`/`Cf` control characters
(ANSI/OSC, C1, bidi, zero-width) and escape markdown brackets, pipes, and URL
parens, so untrusted board text can no longer reach the terminal or forge a
link (Task 1).

Job titles, locations, company names, and URLs come straight from third-party
board JSON and are printed without sanitization. A title containing ANSI/OSC
control sequences passes through byte-for-byte (verified). A malicious or
compromised board tenant; remember slugs are arbitrary ATS tenants, not a
vetted allowlist; could retitle your terminal window, recolor or overwrite
output, or on some terminal emulators abuse OSC sequences (hyperlink spoofing,
clipboard writes). JSON output happens to be safe because `json.dumps` defaults
to `ensure_ascii=True` (escapes ESC); markdown output is **not** safe (raw ESC,
plus unescaped `[x](y)` in titles and unescaped `)` in URLs can forge links in
a pasted table). This is the one place untrusted remote data crosses into your
terminal, and it undercuts the project's "safe by design" pitch.

**Workaround:** prefer `--json` for untrusted or unfamiliar boards; treat
`--markdown` output as untrusted before pasting it anywhere.

### H2: `include_keywords` broadens results and matches loosely; there is no way to narrow — Fixed
`src/interninbox/filters.py:56-60`

**Fix:** a new `match_keywords` filter narrows to "internship AND keyword"
(whole-word, case-insensitive, OR within the list, AND-ed with the signal),
alongside the still-broadening `include_keywords` (Task 2).

`include_keywords` is OR-ed with the built-in internship signal and matched as a
bare case-insensitive substring (no word boundaries, unlike the built-ins).
Consequences, both verified:

- Adding `["software"]` prints **every** "Software Engineer" title, intern or
  not; the tool stops being an internship finder.
- `["ai"]` matches "Ch**ai**r of Maintenance"; `["security"]` matches every
  security role.

Users naturally expect an "include" list to *narrow* ("only security
internships"); it does the opposite. There is currently **no** narrowing
mechanism; "internship AND security" is inexpressible. `exclude_keywords` is
the only subtractive control.

**Direction:** a separate `match_keywords` (word-boundary, AND-ed with the
internship signal) would give the narrowing users expect while keeping today's
broadening behavior available.

### H3: First-run experience is structurally likely to disappoint — Fixed (partial)
`src/interninbox/config.py` (starter config), `src/interninbox/companies.py`,
`src/interninbox/cli.py` (scan output timing)

**Fix (partial):** scans now show per-company progress and an empty result
explains *why* nothing matched (filtered out, already seen, or empty boards)
(Tasks 7, 8). Starter-list rot and off-season empties from the bundled
companies remain open.

Three things compound on a new user's first run:

- **Off-season zero results.** `init` ships three companies (Stripe, Plaid,
  Linear). Outside intern-recruiting season these boards often have zero
  matching titles, so the most likely day-one output is
  `No matching internships found.`; directly under a README example showing
  three hits. No hint whether the tool worked, the filter missed, or the
  companies simply have no interns right now.
- **Silent scans (see H4).** Nothing prints until the whole scan finishes.
- **Starter-list rot blames the user.** The 34 bundled slugs are correct as of
  authoring with no mechanism to detect ATS migrations. A migrated company later
  yields `HTTP … check the slug exists` (see M3), which reads as "you typed the
  slug wrong." Verified today: the shipped starter entry `lever:plaid` returns a
  valid **empty** board; a silent zero from an example company on day one.

### H4: A scan prints nothing until it finishes, so a slow scan looks hung — Fixed
`src/interninbox/cli.py` (results emitted only at the end),
`src/interninbox/fetch.py:23` (500 ms per-host floor, 15 s timeout, one retry)

**Fix:** `scan` prints a per-company `[n/total] label ...` progress line to
stderr when stderr is a tty (Task 7).

There is no progress indicator, spinner, or per-company line. On a healthy
network, 50 Greenhouse companies share one host and serialize at the 500 ms
floor → 25 s+ of silence before any output. On a bad network (captive portal,
slow DNS), each company can cost up to 2×15 s; the 34-company starter list is
~17 minutes of silence before an error. The natural user reaction is Ctrl-C , 
which currently dumps a raw `KeyboardInterrupt` traceback (see L2).

---

## Medium

### M1: Multi-location postings are truncated — Fixed
`src/interninbox/adapters/ashby.py` (reads only `location`),
`src/interninbox/adapters/lever.py` (reads only `categories.location`)

**Fix:** Ashby `secondaryLocations` and Lever `categories.allLocations` are now
read (and deduped) so multi-office postings keep all their locations (Task 10).

Ashby exposes `secondaryLocations` and Lever exposes `categories.allLocations`,
both ignored. Verified against the live Ashby API: 3 of 31 Linear jobs carry a
secondary location (e.g. primary "North America", secondary "Europe"). Effects:
the LOCATIONS column understates where a job is offered, and a `locations`
filter for the secondary city wrongly drops the job.

### M2: The README contradicts the code on no-location listings — Fixed
`src/interninbox/filters.py:80-82`, `tests/test_filters.py:86-88`, README
"How matching works"

**Fix:** the README now matches the code — a no-location listing is dropped when
`locations` is set; leave `locations = []` to keep such listings (Task 13).

The README says a listing with no stated location passes the locations filter.
The code does the opposite: when `filters.locations` is set and a listing has no
location, it is dropped (and a test locks that in). A user who sets
`locations = ["New York"]` silently loses every listing whose board omitted
location metadata, contrary to the README's promise. (The starter config's
inline comment documents the real behavior; the README is the one that is wrong.)

### M3: Every 4xx is reported as "check the slug exists" — Fixed
`src/interninbox/fetch.py:91-94`

**Fix:** 401/403 now say the request was refused (key/WAF), 429 says rate
limited and gets one retry honoring `Retry-After` (capped at 10 s); only 404/410
suggest checking the slug (Task 4).

All 4xx responses map to one message about the slug. So a USAJOBS bad key (401)
or exceeded quota (429) says `HTTP 401 from data.usajobs.gov: check the slug
exists`; there is no slug for USAJOBS. A rate-limited or WAF-blocked board (403
/ 429), plausible when scanning many companies, tells the user their (correct)
slug is wrong. There is also no `Retry-After` handling on 429.

### M4: Location filtering is naive substring matching
`src/interninbox/filters.py:83-84`

Bare `in` on lowercased strings. Verified: `locations = ["NY"]` matches
"Su**nny**vale, CA". Conversely "New York" will not match a board that writes
"NYC", and vice versa. Location strings are per-ATS free text, so both false
positives and false negatives are easy to hit.

### M5: Missed internships the title heuristic cannot see (and the README does not disclose)
`src/interninbox/filters.py:20-38` (signal), `:44-51` (staff/level exclusion)

Title-only matching misses whole classes, verified:

- Program titles without intern-words: "Software Engineer - Summer 2027"
  (only `summer analyst`/`summer associate` are patterns, not bare "Summer YYYY").
- Fellowship / placement / trainee programs: "Engineering Fellowship",
  "Industrial Placement" (standard UK term), bare "Trainee".
- Non-English titles: "Praktikant", "Werkstudent", "Stagiaire" (only the English
  "working student" is a pattern), despite these ATSes hosting EU boards.
- Real internships dropped by the seniority filter: "Software Engineer (Intern)
  II" is signal-positive, then dropped by the roman-numeral `II` marker.

The README's "Scope, honestly" section lists non-goals but never states that
titles without intern-words are missed. `include_keywords` can recover some of
these but see H2 for what using it costs.

**Narrowed (still open):** new signal patterns now catch "Summer 20XX",
industrial placements, fellowships, and German/French student-role words, and
the README's "Scope, honestly" section discloses the remaining misses (Tasks 3,
13). Title-only matching still misses bare "Trainee" and level-suffixed
internships — open.

### M6: `pathways` is treated as an internship signal, which over-includes federal Recent-Graduate roles — Fixed
`src/interninbox/filters.py:37`

**Fix:** the signal now requires `pathways intern(ship)`, so full-time "Pathways
Recent Graduates" roles no longer surface as internships (Task 3).

`\bpathways\b` is in the match signal to catch USAJOBS Pathways Internships. But
"Pathways Recent Graduates" is a post-degree, full-time federal program, so
bare-"Pathways" titles surface as internships. (The hosted product deliberately
keeps this token out of its publish bar for exactly this reason.)

### M7: USAJOBS: results truncated at 2,500, keyword list AND-ed, USAJOBS-only config impossible — Fixed
`src/interninbox/adapters/usajobs.py:36-37,58-59,64-80`,
`src/interninbox/config.py:148-154`

**Fix:** keyword lists are now OR-ed (one deduped query per keyword), hitting
the page cap emits a truncation warning, and a config with only `[usajobs]`
enabled no longer needs a dummy company (Task 11).

- The page loop stops after 5×500 = 2,500 results with no warning; a broad
  `HiringPath=student` nationwide query can exceed that and silently truncate.
- `keywords` is joined into one space-separated `Keyword` query, which USAJOBS
  matches as AND. A user writing `keywords = ["software", "data"]` likely means
  OR and gets fewer results than intended.
- `companies` is required and non-empty, so a user who wants only federal
  Pathways listings must invent a dummy ATS entry.

### M8: `--new-only` cries wolf after a flaky scan or a filter change — Fixed (partial)
`src/interninbox/cli.py:137-146`, `src/interninbox/state.py:29-31`

**Fix (partial):** `--new-only` now records everything *fetched* (not just
matches), so a flaky run or a loosened filter no longer floods it with old
posts (Task 9). Cross-process file locking for overlapping cron runs is still
open.

Only *matched* listings are recorded in the state file. So:

- A company that times out or 404s one run contributes nothing to state; the
  next healthy `--new-only` run floods in all its month-old listings as "new".
- Loosen `locations` or `exclude_keywords` and every previously-filtered old
  listing arrives as "new".

Both are the exact false-positive behavior `--new-only` exists to prevent.

### M9: State file writes are not atomic and are not locked — Fixed
`src/interninbox/state.py:33-35`

**Fix:** state is written to a `.tmp` file and then `os.replace`d, so a crash,
Ctrl-C, or full disk mid-write can no longer leave a corrupt file (Task 9).
Cross-process locking remains open (see M8).

`write_text` truncates then writes in place. A crash, Ctrl-C, or full disk
mid-write leaves corrupt JSON; the next `--new-only` run then treats everything
as new (graceful warning, but the seen/new contract is lost). Two overlapping
cron invocations also race; load → record → save loses one process's updates.

### M10: Windows: redirected/piped output can crash on non-ASCII, and CI never tests it — Fixed
`src/interninbox/output.py:31` (uses "…"), `src/interninbox/cli.py` (`print`),
`.github/workflows/ci.yml:13` (ubuntu-only, 3.11/3.12 only)

**Fix:** `entrypoint` reconfigures stdout/stderr with `errors="replace"` so a
console that cannot encode a character degrades instead of crashing, and CI now
runs ubuntu + windows across Python 3.11-3.13 (Tasks 7, 12).

On Windows, `interninbox scan > jobs.txt` or a Task Scheduler capture uses the
legacy ANSI codepage; a CJK duty station (USAJOBS lists overseas locations), a
curly quote in a title, or a cp437 console (no "…") raises `UnicodeEncodeError`
and kills the run after all the network work. File I/O correctly pins UTF-8;
only stdout is exposed. CI is ubuntu-only and stops at 3.12, while fresh PyPI
installs in late 2026 default to 3.13+; the gap is untested exactly where
users are.

### M11: Timeout resets per chunk; response size is unbounded; deep JSON escapes the error wrapper — Fixed
`src/interninbox/fetch.py:38-39,95-98`

**Fix:** responses are streamed under a 10 MB size cap and a 60 s read deadline,
and a `RecursionError` from deeply-nested JSON is now caught and reported as an
`AdapterError` instead of a traceback (Task 5).

`httpx.Client(timeout=15.0)` sets the read timeout per socket read, so a server
dripping one byte every 14 s holds a request (and the whole sequential scan)
open indefinitely. Nothing caps response body size. A deeply-nested JSON body
raises `RecursionError`, which is not a `ValueError`, so it escapes the
`AdapterError` wrapper and crashes the scan with a traceback.

### M12: Release/version has two sources of truth and no guardrail — Fixed
`pyproject.toml:3`, `src/interninbox/__init__.py:3`, `.github/workflows/release.yml`

**Fix:** hatch reads the version from `__init__.py` (single source via
`dynamic = ["version"]`) and the release job refuses a tag that does not match
`__version__` (Task 12).

The version is hardcoded in two files, bumped by hand, with nothing checking
that they agree or that a release tag matches them. A release that updates only
one ships a wheel whose `--version` and User-Agent lie; and PyPI will not let
you re-upload the corrected file under the same version.

### M13: Release workflow pins actions by tag, not commit SHA — Fixed
`.github/workflows/release.yml:15-16,20`

**Fix:** every action in both workflows is now pinned by commit SHA, and both
carry a top-level `permissions: contents: read` block (Task 12).

`actions/checkout@v4` and `astral-sh/setup-uv@v5` are tag-pinned, and the build
job's artifact is published verbatim under Trusted Publishing. A compromised
action tag could tamper with the built wheel while provenance still looks clean.
There is also no top-level `permissions:` block, so the build job runs at the
default token scope. (For balance: OIDC Trusted Publishing, `id-token: write`
scoped to the publish job, no repository secrets, and no `pull_request_target`
make the overall posture safe; fork PRs run with a read-only token.)

---

## Low

### L1: README overstates `init`'s gitignore behavior — Fixed
README "state file" section, `src/interninbox/cli.py` (`init`)

**Fix:** the README no longer claims `init` gitignores the state file; it tells
you to add `.interninbox-state.json` to your `.gitignore` yourself (Task 13).

The README implies `init` gitignores the state file "by convention"; `init` only
writes the TOML. A user running `init` inside a git repo may commit
`.interninbox-state.json`.

### L2: "Never a traceback" is not airtight — Fixed
`src/interninbox/config.py:142-146`, `src/interninbox/cli.py` (`init`, main loop)

**Fix:** friendly messages and exit codes now cover a permission-denied config,
an unwritable `init` target, Ctrl-C (exit 130), a broken pipe (quiet exit), and
the `RecursionError` from M11 (Tasks 5, 7).

Anticipated failures still traceback: a permission-denied config file
(`PermissionError`), `init` in an unwritable directory, Ctrl-C
(`KeyboardInterrupt`), `interninbox scan | head` (`BrokenPipeError`), and the
`RecursionError` from M11.

### L3: Table/markdown alignment breaks on wide characters and embedded control chars — Fixed (partial)
`src/interninbox/output.py:30-31`

**Fix (partial):** control characters (including embedded newlines) are now
stripped from every field, so they can no longer break a table or markdown row
(Task 1). East-Asian wide-character column alignment is deliberately deferred
and still open.

Truncation counts codepoints, so CJK titles misalign columns; a title containing
a newline (nothing strips control characters; see H1) destroys both the table
and the markdown row.

### L4: `sr\.` staff-role pattern is effectively dead — Fixed
`src/interninbox/filters.py:44-48`

**Fix:** the pattern is now `\bsr\b`, which matches "Sr. Engineer" and "Sr
Engineer" but not "SRE" (Task 3).

Verified: `is_staff_role("Sr. Engineer")` is `False`; the trailing `\b` after
`sr\.` requires a word character immediately after the period, which "Sr. X"
never provides. Impact is small (the title must also carry an intern signal, and
`senior|manager|…` catch most cases), but the pattern does not do what it says.

### L5: POSTED column mixes meanings across ATSes
`src/interninbox/adapters/*` (date fields), `src/interninbox/output.py` (sort)

Greenhouse `first_published` and Lever `createdAt` are stable, but Ashby
`publishedAt` updates on unpublish/republish (a repost sorts to the top looking
new, while its stable UUID keeps `--new-only` from flagging it), and USAJOBS
`PublicationStartDate` is the announcement open date. One column header, several
meanings.

### L6: State grows forever; USAJOBS identity is fragile; stored `url` is unused
`src/interninbox/state.py:29-31`, `src/interninbox/models.py:22-24`

State keys are never pruned. The key is `source:company:listing_id`; for USAJOBS
`company` is the free-text organization name, so an agency rename resurfaces
every existing listing as "new". The stored `url` value is never read back.

### L7: Shared state path across configs in one directory
`src/interninbox/cli.py` (default state path derives from the config directory)

Two different config files in the same directory silently share
`.interninbox-state.json`, so `--new-only` under one config suppresses listings
first seen under the other.

### L8: `follow_redirects=True` forwards custom headers and skips the politeness delay — Fixed
`src/interninbox/fetch.py:42`, `src/interninbox/adapters/usajobs.py:45-49`

**Fix:** USAJOBS drops the hardcoded `Host` header (httpx derives it from the
URL) and requests it with `follow_redirects=False`, so a cross-origin redirect
can no longer carry its auth headers elsewhere (Task 6).

On a cross-origin redirect, httpx forwards custom headers (the USAJOBS
`Authorization-Key`, the email `User-Agent`, and a hardcoded `Host` header),
redirect hops bypass the per-host delay, and the hardcoded `Host:
data.usajobs.gov` would be sent to any redirect target. Unlikely with these
HTTPS vendors, but real if one ever redirects.

### L9: Lever date accepts `bool`; markdown escaping is incomplete — Fixed
`src/interninbox/adapters/lever.py:55`, `src/interninbox/output.py:103`

**Fix:** Lever now rejects a boolean `createdAt` (no 1970 date), and markdown
escapes company and URL fields and percent-encodes parens in the apply URL
(Tasks 1, 10).

`isinstance(created_at, int | float)` accepts `True`/`False` (a 1970 date).
Markdown output escapes pipes in title/locations but not in company or URL, and
a URL containing `)` breaks the `[apply](url)` link.

### L10: CI matrix and lockfile posture — Fixed
`.github/workflows/ci.yml:13`, `.gitignore` (ignores `uv.lock`)

**Fix:** CI now covers Python 3.11-3.13 on ubuntu + windows, and `uv.lock` is
committed so CI and contributors resolve dependencies identically (Task 12).

CI stops at Python 3.12 (see M10). `uv.lock` is gitignored while the docs tell
contributors to `uv sync`, so CI and every contributor resolve dependencies
freshly and unpinned (`httpx>=0.27`, no cap); a bad httpx release can break CI
and dev with no committed known-good resolution.

---

## Verified working (for balance)

These were checked during review and hold up: the politeness guarantees
(sequential requests, ≥500 ms per host, 15 s timeout, one retry, honest
User-Agent); the no-telemetry claim (the only writes are your config and state
file); the exit-code table in the README; the USAJOBS "User-Agent is the
registered email" contract, correctly scoped to that host; the Greenhouse
boards API being genuinely unpaginated (562 live Stripe jobs in one response);
and the 102-test offline suite. Fork pull requests run CI with a read-only token
and no access to secrets.

---

*Found something not listed here? Please open an issue.*
