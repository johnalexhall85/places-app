# Task M2 (Codex): build the CHIP MCP server

Assigned by Claude Code (project manager), 2026-11-17. Branch `codex/mcp-m2` in `/home/john/chip-codex` (already checked out).

## Read first

1. `AGENTS.md`, especially "MCP server: three-agent ownership".
2. `docs/mcp/TOOL_CONTRACT.md`. **This is the specification; build exactly to it.**
3. `docs/mcp/PLAN.md` (background, including the "Amendments from M0" section).
4. `backend/app/area_pilot/lookup.py` (read only; Claude owns it). Note `measure_values_within`, `area_values`, `catalog`, `area_info`, `area_facilities`, `district_counties`, `county_districts`, `state_counties`, `state_districts`, `states`, `STATUS_TEXT`, `LookupError_`.
5. `backend/app/routers/search.py` (`search_counties`) and `backend/app/community/topics.json` (read only).

## Build

Only in these paths: `backend/app/mcp_server/**` and `backend/tests/test_mcp_*.py`. Nothing else. If you think another file must change, write that in your status file instead of changing it.

- `backend/app/mcp_server/requirements.txt`: pinned versions for the separate venv. The venv `backend/.venv-mcp` already exists with `mcp==2.3.0`, `fastapi==0.163.1`, `starlette==1.10.0`, `uvicorn==0.54.0`, `SQLAlchemy==2.0.34`, `psycopg[binary]==3.2.3`, `python-dotenv==1.0.1`, `requests`, `openpyxl`, `pypdf`, and `pytest`. Pin what is installed (`backend/.venv-mcp/bin/pip freeze`), keeping only the direct dependencies listed here.
- `__init__.py`, `config.py` (allowlist, limits, rule strings, allowed hosts from the environment), `envelope.py` (value-row builder, citation, sources, rules, size limit), `places.py` (find_places matching), `measures.py` (search and details over catalog and topics), `tools.py` (the seven tools), `cache.py`, `app.py` (the `MCPServer`, the instructions text, the `/healthz` route, and the `app` ASGI object). Split differently if you prefer, but keep it small and readable.
- Typed return models (Pydantic) so clients receive `structured_content`.
- Tests `backend/tests/test_mcp_*.py`, runnable with `cd backend && PYTHONPATH=. .venv-mcp/bin/python -m pytest -q tests/test_mcp_*.py`:
  - **Unit tests with a stubbed db or lookup** for: the envelope, citations, AHRF exclusion everywhere (search, details, values, catalog, topics), sort and position numbering with ties, `without_value` never truncated, row and size limits, error text, and the district-name parser.
  - **Integration tests against `places_staging`** (the `DATABASE_URL` in `backend/.env`). Mark them so they skip cleanly when the database is unreachable. Call the tools in-process, and also once through the real HTTP app with `mcp.Client` against a uvicorn server started on a free loopback port inside the test.
  - **Assert the real staging values** in the contract's "Real examples" table.

## Rules

- Read data only through `lookup`, `search_counties`, and `topics.json`. No SQL in `mcp_server`, and no writes of any kind.
- Never expose `ahrf`. Never compute values across areas, composite scores, or ranks beyond the single-measure `position` defined in the contract. Never use the words best, worst, or score.
- Tool descriptions are written for an LLM reader: when to use the tool, what to call first, and what statuses mean. Keep each one under about 600 characters.
- **Do not commit, push, merge, deploy, run sudo, start services, or edit files outside your paths.** Claude reviews and commits. The AGENTS.md diary rule is replaced here: put diary-worthy facts in your status file instead.
- Do not modify `backend/.env`, `backend/.venv`, or `backend/requirements.txt`.

## Done when

1. `PYTHONPATH=. .venv-mcp/bin/python -m pytest -q tests/test_mcp_*.py` passes, with the integration tests run (not skipped) against `places_staging`.
2. `PYTHONPATH=. .venv-mcp/bin/uvicorn app.mcp_server.app:app --port 8013` starts. A `mcp.Client` call to `get_measure_across_areas(measure_key="places:diabetes_crudeprev", level="county", within="AL", sort="value_desc", limit=5)` returns 5 `with_value` rows plus the ordering warning. Stop the server afterwards.
3. The website venv still passes `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_area_lookup.py tests/test_community_api.py`. You changed nothing it uses, so this confirms you didn't.
4. `docs/mcp/status/codex.md` has an M2 row with the state, test counts, any contract questions, and anything Claude must do (for example, a contract change you need).

Finish with a short report: files created, test results (counts), deviations from the contract and why, and open questions.
