# interninbox-cli

A zero-API-key, locally-run internship finder: list your target companies in a
config file, run one command, and get matching internships in your terminal.
It reads the documented public job-board APIs of Greenhouse, Lever, and Ashby
(plus, optionally, the official USAJOBS API) — no scraping, no accounts, no
LLMs, nothing leaves your machine.

## Quickstart

```sh
# with pipx
pipx install interninbox-cli

# or with uv, straight from a checkout
uv sync
uv run interninbox init
```

```sh
interninbox init        # writes a starter interninbox.toml
interninbox companies   # prints a starter list of well-known companies
interninbox scan        # scans every configured company
```

## Configuration (`interninbox.toml`)

```toml
companies = [
    "greenhouse:stripe",   # job-boards.greenhouse.io/<slug>
    "lever:plaid",         # jobs.lever.co/<slug>
    "ashby:linear",        # jobs.ashbyhq.com/<slug>
]

[filters]
# Extra title keywords that count as an internship signal, in addition to the
# built-in one (intern, internship, co-op, summer analyst, apprentice, ...).
include_keywords = []
# Drop listings whose title contains any of these (case-insensitive).
exclude_keywords = ["mechanical"]
# Keep only listings whose location contains one of these substrings.
# Empty = keep every location.
locations = ["New York", "Remote"]
# When true (default), remote listings always pass the locations filter.
# When false, remote-only listings are dropped.
remote_ok = true

# Optional: federal internships (Pathways program) from the official USAJOBS API.
[usajobs]
enabled = true
email = "you@example.com"        # the email your API key is registered under
keywords = ["software"]
api_key_env = "USAJOBS_API_KEY"  # environment variable holding your key
```

A copy of this example ships as [`interninbox.example.toml`](interninbox.example.toml).

## Commands

| Command | What it does |
| --- | --- |
| `interninbox init` | Write a starter `interninbox.toml` into the current directory |
| `interninbox scan` | Scan every configured company and print matching internships |
| `interninbox scan --json` / `--markdown` | Machine-readable / Markdown output |
| `interninbox scan --new-only` | Show only listings not seen by a previous scan |
| `interninbox companies` | Print a starter list of well-known companies |

### Example output

```
COMPANY  TITLE                                  LOCATIONS      POSTED      URL
stripe   Software Engineering Intern (Summer)   New York, NY   2026-08-01  https://stripe.com/jobs/...
linear   Product Engineering Intern             Remote         2026-07-28  https://jobs.ashbyhq.com/linear/...
plaid    Data Science Intern                    San Francisco  -           https://jobs.lever.co/plaid/...

3 internships across 3 companies
```

`--new-only` keeps a small state file (`.interninbox-state.json`, next to your
config; override with `--state PATH`) recording which listings you have already
seen. Every scan updates it, so "new" always means "since my last scan". If the
file is missing or corrupt, everything counts as new — you get one warning, not
a crash.

## How it matches

All matching is local, deterministic heuristics — no LLM:

- **Internship signal**: word-boundary regexes on the title (`intern`,
  `internship`, `co-op`, `summer analyst`, `apprentice`, `student trainee`, ...)
  OR any of your `include_keywords`. Word boundaries mean "International
  Program Manager" and "Internal Tools Engineer" do *not* match.
- **Staff-role exclusion**: roles *about* interns (recruiter, program manager,
  university relations) and clear seniority markers (Senior, Staff, II/III) are
  dropped.
- Then your `exclude_keywords` and `locations` filters apply.

## Politeness (built in, not optional)

- Requests run sequentially with at least 500 ms between requests to the same
  host, a 15 s timeout, and at most one retry.
- Every request carries an honest User-Agent:
  `interninbox-cli/<version> (+https://github.com/hiratinspace/interninbox-cli)`.
- Only documented public APIs are used — the same endpoints the companies'
  own careers pages call.
- A failing company prints a one-line warning; it never aborts your scan.

## USAJOBS (optional)

Federal Pathways internships come from the official USAJOBS Search API, which
requires a free API key:

1. Request a key at <https://developer.usajobs.gov/apirequest/>.
2. Export it: `export USAJOBS_API_KEY=...` (or set `api_key_env` to your
   preferred variable name).
3. Set `[usajobs] enabled = true` and `email = "..."` — per USAJOBS's
   documented contract, the User-Agent for its API must be the email address
   the key is registered under, so this tool sends exactly that (only there).

If `[usajobs]` is enabled but the key variable is unset, the scan skips it with
an info line and carries on.

## Scope, honestly

This does one-shot local scans. It doesn't verify listings are still live,
dedupe reposts, or alert you — that's what the hosted Interninbox product
(coming soon) does.

## Support

Best-effort community support via GitHub issues. See
[CONTRIBUTING.md](CONTRIBUTING.md) if you'd like to help.

## License

[MIT](LICENSE)
