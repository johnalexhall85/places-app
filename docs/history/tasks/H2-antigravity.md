# Task H2 (Antigravity): history parsers, general rules

Assigned by Claude (project manager). Every H2x task names one product and refers to this file. Work in `/home/john/chip-agy` on the branch Claude has checked out for you.

You write pure parsers that turn source files CHIP has already archived into normalized history rows. Claude runs the real downloads, the database staging, the review, and publication.

## Read first

1. [docs/history/PLAN.md](../PLAN.md) and [docs/history/SOURCES.md](../SOURCES.md).
2. The parser contract in `backend/app/area_pilot/history/parsers/__init__.py`.
3. `backend/app/area_pilot/history/rows.py`: `make_row`, `to_decimal`, `row_problems`.
4. The product's history registry, `backend/app/area_pilot/registry/history/<product>.json`. It is read-only for you; if it is wrong or incomplete, say so in your status file.
5. The product's current adapter in `backend/app/area_pilot/<product>.py`. Reuse its pure helpers (value parsing, status rules, sentinel handling) by importing them. Do not copy them.

## Build

Only in these paths: `backend/app/area_pilot/history/parsers/<product>.py`, `backend/tests/test_history_parsers_<product>.py`, and `docs/history/status/antigravity.md`.

1. `SCHEMA_VERSION = '1'` and `parse(config, files, evidence)` exactly as the contract says.
2. Check the source header or schema against the registry before reading values. On any difference, raise `ValueError` with a plain message.
3. Emit every area the source publishes for each declared (measure, period) and level, including suppressed or missing cells with their own status. Drop only rows that a registry exclusion rule names, and count those drops in `evidence` by period and reason. Any other unexpected code raises `ValueError`.
4. Statuses must come from the registry's `statuses`. The value is `None` exactly for `null_statuses`.
5. Tests use the fixture Claude provides in `backend/tests/fixtures/history/<product>/` and pass `files={role: Path}` directly. At minimum, cover:
   - the exact row count per (measure, period, level) in the fixture
   - three hand-checked values copied from the fixture file, one of them a suppressed or missing cell
   - every exclusion reason
   - a changed header, which raises
   - an age-stratified or otherwise non-selected row, which is ignored
   - every row passes `row_problems`
   - parts are unique and stable across two runs

## Environment

- No network. Do not try to work around this.
- Run tests with `cd backend && PYTHONPATH=. .venv-mcp/bin/python -m pytest -q tests/test_history_parsers_<product>.py` (the venv in your worktree; it has everything the parsers need).
- Do not run the store, the CLI, or anything that needs a database.

## Rules

- Do not commit, push, merge, deploy, or use sudo. Leave changes uncommitted.
- Do not edit files outside your paths, including registries, `rows.py`, and the store.
- Never invent, derive, aggregate, round, or fill values. Keep the source text in `source_value`.

## Done when

1. The tests pass, and `python -m py_compile` passes on the parser.
2. `docs/history/status/antigravity.md` has a row for the package: what the parser reads and drops, the counts from the fixture, any registry problems found, and "Diary facts" (files changed, commands run, results).

Finish with a report of five lines or fewer.
