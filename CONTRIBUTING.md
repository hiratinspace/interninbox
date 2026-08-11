# Contributing

Thanks for your interest! This project aims to stay small and dependency-light
(httpx is the only runtime dependency), so please open an issue to discuss
larger changes before writing them.

## Setup

```sh
uv sync
uv run pytest
uv run ruff check .
```

## Ground rules

- Tests are offline-only: use `httpx.MockTransport` and the authored synthetic
  fixtures in `tests/fixtures/` (fictional companies, never recorded real data).
- New job sources must use a documented public API and keep the built-in
  politeness (per-host delay, honest User-Agent, single retry).
- Keep ruff clean (`line-length = 100`) and type hints on public functions.
- Every user-facing failure needs a clear message and a non-zero exit — no
  tracebacks for anticipated errors.

Support is best-effort by community volunteers — please be patient with reviews.
