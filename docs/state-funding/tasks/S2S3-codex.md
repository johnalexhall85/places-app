# Task S2+S3 (Codex): state funding read model, API, and the new state funding page

Assigned by Claude on 2026-11-19. Work in `/home/john/chip-codex-state` on branch `codex/state-funding`. `backend/.env` there points at `places_staging`. Run Python with `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest ...` (that venv has every backend dependency). Frontend: `cd frontend && npm test` and `npm run build` (node_modules is installed).

**You own:**
- `backend/app/state_funding/**` (new)
- `backend/tests/test_state_funding_*`, except `test_state_funding_audit.py`, which is Antigravity's
- `frontend/**`
- `docs/state-funding/status/codex.md`
- One line in `backend/app/main.py` to register the router. This is the only edit allowed outside your paths.

Do not commit, push, merge, deploy, or use sudo. Do not edit migrations: the schema already exists on staging (migration `e4b8c2f6a9d1`). Do not change `backend/app/community/**` or `docs/beta/contract-examples`. You may run the builder against `places_staging` as often as you need. Write to no other schema, and never point anything at the live `places` database.

## Read first

1. [PLAN.md](../PLAN.md): the decisions with John and the facts checked on staging.
2. The whole of [CONTRACT.md](../CONTRACT.md). This is the specification: §1 the build, §2 lookup, §3 HTTP, §4 page.
3. `backend/alembic/versions/e4b8c2f6a9d1_add_state_funding.py`: the tables you fill.
4. `backend/app/funding_report/build.py` and `keys.py`: the pattern to follow for build_run/active_build, the `--allow-live` guard, keeping two builds, the TAGGS title selection, and the prime-transaction sources for FON and business types. Reuse `keys.nofo_key`; do not copy it.
5. Brand: `docs/beta/EXECUTION_PLAN.md` lines 94–114, `frontend/src/community/tokens.css`, `frontend/src/components/SiteHeader.jsx`, and `frontend/src/community/community.css`. The community pages are the reference for what "on brand" looks like.
6. The `/cdc-funding` Filters panel and diverging bars to reuse in spirit: `frontend/src/pages/CdcFundingOverviewRedesign.jsx`, around lines 401–480 (diverging bars), 942 (filter chips), and 1870–2000 (Filters panel).

## Part A: backend (S2)

1. `app/state_funding/build.py`: `python -m app.state_funding.build [--allow-live]`, exactly per contract §1. Do the heavy lifting in set-based SQL, with temp tables as in `funding_report`. Log the timings. Fill `build_run.sources` and `build_run.counts` as listed. `nofo_title` may be empty when you start (Claude is loading it in parallel), so the build must work either way.
2. `app/state_funding/lookup.py`: contract §2.
3. `app/state_funding/router.py`: prefix `/state-funding/v1`, contract §3. Register it in `app/main.py`. Run blocking database work the way the existing routers do. State names come from an existing CHIP helper if one exists (search before writing a new table).
4. Tests, `tests/test_state_funding_build.py` and `test_state_funding_api.py`:
   - unit tests for the `grant_name` rule order;
   - the `is_state_government` tri-state;
   - the `'__'` handling;
   - filter validation (422);
   - an unknown state (404);
   - CSV shape;
   - `q` matching every term;
   - plus a test against `places_staging` that skips when the database is unreachable, checking invariant §5.1 for one fiscal year and §5.3 for one state.
5. Run the build on `places_staging`. Record in your status file:
   - the build id;
   - the time it took;
   - the row counts;
   - the `name_source` counts;
   - the Unattributed dollars per fiscal year;
   - which contracts column you used for state government.

**Checkpoint:** stop and record your status if the §5.1 reconciliation does not hold to the cent. Do not adjust numbers to make it pass.

## Part B: page (S3)

1. `frontend/src/api/stateFunding.js` for the four endpoints, using the same base URL handling as the other API modules.
2. Replace `frontend/src/pages/CdcStateFundingProfile.jsx`, `.css`, and `.test.jsx` with the new page. Keep the file name so the route wiring in `main.jsx` and `utils/routeResolver.js` stays put. Make `/taggs/funding-profile?state=XX` redirect to `/cdc-funding/state/XX`. Delete helpers that only the old page used (for example `utils/cdcFundingProfileTarget.*` if nothing else imports it); check with grep, not by assumption.
3. Sections, top to bottom (contract §4):
   1. Title "CDC funding to recipients in {State}" (Roboto Slab), with the fiscal-year selector and the period label ("FY2026 P12").
   2. KPI tiles: Total obligations, Regular, Supplemental/emergency, Grants, Recipients.
   3. A Filters panel with chips: Funding type, Award type, Federal account (from `accounts_available`), Recipient type. Include a "Clear filters" button.
   4. "Funding by federal account": ranked horizontal bars, with regular and supplemental as separate bars around a zero line, a "Show as table" toggle, and the citation line below.
   5. "Grants": a search box (debounced), a sortable table, and expandable rows.
      - Columns: Grant (name, plus the name-source label, with the project title beneath it when it differs), Recipient (marked "State government" when true), NOFO number, Federal account(s), Regular, Supplemental, Total.
      - An expanded row shows the full description, the assistance listing, the award ID, and a "View on USAspending" link.
      - Include paging (25/50/100), "Download CSV", and the citation line.
   6. "About these numbers": the method notes from the contract, in plain sentences of 55–80 characters per line.
4. Empty state, loading state, and an error state with a retry. The layout must work at 375 px width with no horizontal page scroll; the table may scroll inside its own container. Every amount shows its sign. Do not convey meaning by colour alone.
5. Vitest tests:
   - rendering with mocked API data;
   - filters updating the query string and refetching;
   - search;
   - sort;
   - expanding a row;
   - a negative supplemental value rendered with its sign;
   - the redirect.
   Fix any other tests that referenced the old page. `npm test` and `npm run build` must pass.
6. If `frontend/scripts/beta-walkthrough.mjs` visits the state funding page, update its checks.

## Done when

- Backend and frontend tests pass, and the staging build exists and reconciles.
- `docs/state-funding/status/codex.md` has a row for this task and a section `## S2+S3 diary facts — <ISO timestamp with timezone>`. That section lists:
  - files changed;
  - commands run and their results;
  - the build id and the counts;
  - anything you could not do;
  - any contract ambiguity you resolved, and how.
- `git status` shows changes only in your owned paths (plus the one `main.py` line).

Finish with a report of 10 lines or fewer.
