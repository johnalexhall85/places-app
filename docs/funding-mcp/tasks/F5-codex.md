# Task F5 (Codex): update the staging test for full-year FY2026 award data

Assigned by Claude on 2026-11-18. Work in `/home/john/chip-codex-funding`, on branch `codex/funding-report`. First run `git merge --ff-only claude/funding-report`; it is checked out locally. Same owned paths as before. Do not commit, deploy, or use sudo.

`places_staging` now holds FY2026 award-level prime transactions through 2026-09-30. They come from the USAspending Award Data Archive, with the funding opportunity numbers restored. See "FY2026 full-year award data" in `docs/funding-mcp/PLAN.md`. The active build is 7.

1. In `backend/tests/test_funding_report_staging.py`, replace the assertion that requires the "awards first made after that date" caveat with these three:
   - `sources[usaspending_award].data_through == '2026-09-30'`;
   - that caveat is absent;
   - the PS21-2102 FY2026 `award_obligation` is within $2 of 10,166,689.
2. Make the caveat logic test in `test_funding_report_unit.py` cover both cases: present when award data ends before the account fiscal year ends, and absent when it covers the whole year. Keep the existing tests passing.
3. Run `cd backend && PYTHONPATH=.:$(ls -d /home/john/places-app/backend/.venv/lib/python3*/site-packages) .venv-mcp/bin/python -m pytest tests/test_mcp_* tests/test_funding_report_* -q` and report the result in three lines or fewer. Add a short entry to `docs/funding-mcp/status/codex.md`.
