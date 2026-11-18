# Task F6 (Codex): explicit opt-in for the live funding_report build

Assigned by Claude on 2026-11-18. Work in `/home/john/chip-codex-funding`, on branch `codex/funding-report`, which is already up to date. Do not commit, deploy, or use sudo.

`backend/app/funding_report/build.py` refuses any database URL that is not `places_staging`. John has approved the live promotion (Gate B), and Claude runs the live build.

1. Keep the default refusal. Add a `--allow-live` flag: with it, the build runs against any database URL and prints the database name in its JSON summary (`"database": "<name>"`).
2. Update the refusal message to: "Refusing to build outside places_staging without --allow-live (Claude runs live builds after Gate B)".
3. Add a unit test for the guard that covers the refusal, `--allow-live`, and the database name in the summary. Use argument parsing only, with no database.
4. Run `cd backend && PYTHONPATH=.:$(ls -d /home/john/places-app/backend/.venv/lib/python3*/site-packages) .venv-mcp/bin/python -m pytest tests/test_funding_report_* tests/test_mcp_* -q`.

Report in two lines. Do not edit the diary.
