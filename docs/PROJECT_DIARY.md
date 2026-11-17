# CHIP project diary

Reverse chronological handoff record. Timestamps use ISO 8601 with an explicit timezone. Entries describe verified actions; guide-only history is labeled. Keep current state in [the handbook](PROJECT_HANDBOOK.md), not here. Preserve entries and add corrections when evidence changes.

## 2026-11-17T23:25:00+00:00 — Historical periods promoted to live (Claude, Gate B)

- **Approval:** John said "Push it live" for `beta` `aaaf7ac`, after the staging handover. The runbook was [PROMOTION.md](history/PROMOTION.md).
- **Recovery set:**
  - `data/deploy-recovery/history-20261117/`: `commit-before.txt` = `7c8a29f`, `webroot-before/` (`index-CtZcc-GM.js`), `pointers-before.txt` (12), `alembic-before.txt` (`e6b3a8d0f2c5`), `profiles-before.json`.
  - Private `pg_dump -Fc -n area_pilot` at `/home/john/chip-recovery/20261117T221417Z-history/`: 864 MB; `pg_restore --list` read 264 entries and 38 table-data items.
- **Commands:**
  - `git merge --ff-only aaaf7ac`, then `alembic upgrade head` (to `a8c2e6f0d4b1`).
  - Copied `data/ingest/history/` (2.2 GB) from `chip-claude`. All 18 registry `sha256` pins matched.
  - `history.boundaries --vintage 2020 --vintage 2019`: county 2020 3,221; tract 2020 85,395; tract 2019 74,001 (equal to staging).
  - Per product: `fetch-stage-validate`, `review`, and `approve-publish`. A script stopped on any difference from the staging release's semantic, schema, or metadata digest or row count; none differed, including the API-fetched BRFSS, EPA, ACS, and PLACES.
  - `npm run build` (`VITE_API_BASE_URL=/api`, bundle `index-2Nm0E_1F.js` equal to staging), `rsync --delete` to `/var/www/places`, `systemctl restart places-backend chip-mcp`.
- **Verification:**
  - Pointer diff: only the 9 `:history` rows were added.
  - `profiles-before.json` and the post-restart capture are identical (`lookup.area_values` for 37145, 54039, 06019, district 5401, and state 37).
  - Local Nginx: `/api/health`, `/`, `/area/cms-gv`, and `/ai` returned 200; the anonymous catalog returned 401. MCP `/healthz` returned 200.
  - MCP evaluation through `https://mcp.publicdataobservatory.org/mcp`, with expected values from the live database: 54/54 (p50 15 ms). The worktree `.venv-mcp` was used because the production MCP venv has no `pyyaml`, and the report was written to the scratchpad, not the repository.
- **Observation:** `https://publicdataobservatory.org/` returns an HTTP 403 challenge page to curl, even with a browser user agent. It comes from a front service, not this VM; the VM's Nginx (`server_name _`) answers 200. Not investigated further.
- **Not verified by the agent:** signed-in map pages on live (no live access code). John should check the Year dropdown on live.
- **Next:** John checks the live maps.

## 2026-11-17T21:35:00+00:00 — Historical periods complete on staging; awaiting Gate A (Claude)

- **Request:** John asked for earlier years on every `/area/*` map (Year dropdown) and for the AI assistant, without changing profiles. Plan approved 2026-11-17; Antigravity wrote the parsers (H2a–i) and MCP eval questions (H6), Codex the Year dropdown (H4, H4b, H4c) and MCP Amendment 2 (H5); Claude did sources, schema, store, read layer, review, ingest, and deploy.
- **Data, staging only:** nine `:history` releases published on `places_staging` (IDs and counts in `docs/history/status/claude.md`); the 12 current pointers are unchanged (diffed against the pre-work capture). Spot values equal the archived publisher files for every product.
- **Failures and fixes this session:**
  - A queued ingest never started: its `pgrep -f` wait loop matched its own command line. It was stopped and rerun.
  - ACS income and ACS community were first held with 22,873 unmatched tracts. ACS 2016–2020 uses 2020 tracts; the registries were fixed and the rerun passed.
  - CLH was held on 11,389 and 10,480 unmatched tracts and 8–9 Connecticut counties. These were blank placeholder rows in AHRQ's own files. New opt-in store flag `drop_unbounded_blank_areas` (commit `8d715cf`) drops only blank area-periods with no boundary in their own vintage; 22,709 were dropped and counted, and real blank areas are kept.
  - The legend said "colour classes are for this year only" on fixed-break maps. Backend `colour_note` (`1942f0d`) and Codex H4c (`bc03d4e`) fixed it.
  - The `.venv-mcp` symlinks in the agent worktrees had become a loop. The venv was rebuilt in `chip-claude` and Antigravity's link repointed. `backend/.venv-mcp` had been committed by mistake in `5e7ae79`; it is untracked now and the ignore rule matches symlinks.
  - A hard reset of Codex's worktree was blocked by the permission classifier; it was not needed, because Codex's files already equalled Claude's branch.
- **Commands:** `history.cli --product <p> fetch-stage-validate`, then `review` and `approve-publish` with digests for acs, acs_profile, and clh; `infra/staging/deploy-staging.sh claude/history-h0` (twice; now `bc03d4e`).
- **Verification:**
  - Signed-in Playwright walkthrough: 18/18 (nine maps at 1365 px and 375 px; shapes, legend and table period, `?period=` reload, no overflow, no page errors).
  - MCP eval 54/54, both `--expected-only` and via `chip-mcp-staging`.
  - Frontend 169/169, MCP 34/34, backend 735 passed. 13 funding and recon tests fail only because untracked `data/recon` and `data/chipfunding` files are absent from worktrees.
- **Not done:** nothing is on live. No merge to `main`.
- **Next:** John tries the Year dropdown and the AI connector on staging (Gate A); on approval, run [PROMOTION.md](history/PROMOTION.md) (Gate B).

## 2026-11-17T17:10:00+00:00 — Mobile menu and map-panel drawer promoted to live (Claude)

- **Approval:** John checked MOBILE-1 on staging ("everything looks good") and approved promotion.
- **Built:** Codex MOBILE-1 (task `docs/beta/tasks/MOBILE-1-codex.md`). On mobile only: the menu button is in the top-right corner and opens the full menu. Map pages open showing only the map. A "Panels" button or a swipe from the left edge opens a drawer with all the legends and panels, and a first-visit hint explains this. The drawer is `MobileMapPanels.jsx`, used on the home page, `/area/*` maps, and county tract maps. Frontend 164 tests passed (rerun by Claude).
- **Promotion:** application only, frontend. Rollback pair: `data/deploy-recovery/mobile-1-20261117/` (`commit-before.txt` = `baf5498`, `webroot-before/`). Commands: `git merge --ff-only beta` (to `bbd42a0`), `npm run build` with `VITE_API_BASE_URL=/api`, `rsync --delete` to `/var/www/places`. No backend restart, no migration; pointers untouched.
- **Verification:** live and staging bundles are equal (`index-CtZcc-GM.js`). `/`, `/ai`, `/explore/map`, `/area/places-2025`, and `/api/health` returned 200 on live; MCP `/healthz` returned 200. Signed-in pages on live were not checked by the agent; John reviewed the same build on staging.

## 2026-11-17T16:55:00+00:00 — "Use CHIP in your AI assistant" page promoted to live (Claude)

- **Approval:** John reviewed `/ai` on staging ("looks great") and approved promotion.
- **Built:** Codex M6 and M6b. The `/ai` page has a copyable connector URL (`https://mcp.publicdataobservatory.org`), Claude and ChatGPT setup steps, coverage, and interpretation rules, and is linked from the header and About. README section added. Frontend 160 tests passed (rerun by Claude).
- **Also live:** the bare production host is an MCP endpoint (Nginx `location = /` proxies to `/mcp`; a browser GET gets a plain-text note). It was verified with `mcp.Client` against `/`, `/` with trailing slash, and `/mcp`.
- **Promotion:** application only, frontend.
  - Rollback pair: `data/deploy-recovery/ai-page-20261117/` (`commit-before.txt` = `35e25c5`, `webroot-before/` with `index-D7zfOmSk.js`).
  - Commands: `git merge --ff-only beta` (to `66bb495`), `npm run build` with `VITE_API_BASE_URL=/api`, `rsync --delete` to `/var/www/places`.
  - No backend restart (no backend change), no migration; pointers untouched.
- **Verification:**
  - Live and staging bundles are equal (`index-DxwxITqQ.js`).
  - `/`, `/ai`, `/explore/map`, `/area/places-2025`, and `/api/health` returned 200; the anonymous community catalog returned 401; MCP `/healthz` returned 200.
  - Signed-in pages on live were not checked by the agent (it has no live access code); John reviewed the same build on staging.
- **Open:** ChatGPT Developer mode not yet tested against production.

## 2026-11-17T16:51:46+00:00 — MOBILE-1 responsive menu and map panels implemented (Codex)

- **Request and outcome:** Implemented a mobile-only full header menu and one reusable left drawer for all shared `/area/*` maps, including facility overlay panels, and the county tract inset. The drawer starts closed, supports button and edge-swipe opening, button/close/left-swipe closing, a guarded persistent first-use hint, and Leaflet resize. The CDC funding pages in this branch have charts and profiles but no geographic map. Desktop layout remains in its existing mode.
- **Files:** `frontend/src/components/SiteHeader.*`, `MobileMapPanels.*`, `Header.test.jsx`, `frontend/src/pages/Places2025Pilot.jsx`, `frontend/src/community/TractPatternMap.jsx`, `community.css`, and `docs/mcp/status/codex.md`. No dataset, release, migration, setting, or backend change.
- **Verification:** 164 frontend tests passed; Vite production build passed with the existing large-chunk warning; `git diff --check` passed. Authenticated 375×812 local-build browser checks of home, PLACES, ACS community, and Person County tract map found rendered shapes, hidden initial drawers, working controls, zero page errors, and zero horizontal overflow. A 360 px mobile and 1365 px desktop check also found zero horizontal overflow and the intended navigation/panel modes. An initial test/build run failed from a JSX wrapper boundary; corrected before the passing runs.
- **Status and next:** Uncommitted and undeployed on `codex/mobile-1`; no database, service, or publication change. Claude reviews, commits and deploys if approved. The handbook was not edited because Claude owns it; this branch-only behavior and the needed post-deployment handbook update are recorded in the status file.

## 2026-11-17T16:32:00+00:00 — MCP server live at mcp.publicdataobservatory.org (Claude, Gate B)

- **Approval:** John tested the staging connector in Claude ("works perfectly"), added the DNS record for `mcp.publicdataobservatory.org`, and approved Gate B.
- **Rollback pair:** `data/deploy-recovery/mcp-promotion-20261117/` holds `commit-before.txt` (`51d0d7e`), `webroot-bundle-before.txt` (`index-D7zfOmSk.js`), and `pointers-before.txt` (12 pointers).
- **State-changing commands on live:**
  - `git merge --ff-only beta` in `/home/john/places-app` (to `2347b88`; no frontend or migration changes), then `systemctl restart places-backend`.
  - Created role `chip_mcp_ro` on the `places` database and set default privileges. No data changed.
  - Wrote `~/.config/chip/mcp-live.env` (mode 600) and built `.venv-mcp` in the live checkout.
  - Installed and enabled `chip-mcp.service`.
  - Obtained a certbot webroot certificate for `mcp.publicdataobservatory.org` (expires 2027-02-15).
  - Added Nginx site `chip-mcp`, enabled as `zz-chip-mcp`.
- **Incident:**
  - **What happened:** at about 16:22Z I enabled the site as `sites-enabled/chip-mcp`. Because it sorted before `places-demo`, its port-80 block became Nginx's implicit default, and `http://<IP>/` returned a 301 to the MCP host for about 2 minutes. Requests by hostname were not affected, and the staging host was not affected.
  - **Fix:** renamed the link to `zz-chip-mcp`. Live by IP and `/api/health` returned 200 again.
  - **Earlier near-miss:** a truncated config failed `nginx -t`, but piping that test into `tail` let the reload run. Nginx rejected the reload and kept serving the old config, so there was no outage. Reloads are now gated on the test result (README updated).
- **Side effect fixed:** Postgres roles are cluster-wide, so setting the password for live also changed the staging role's password. I synced `mcp-staging.env`, restarted `chip-mcp-staging`, and checked it.
- **Verification:**
  - The 44-question evaluation through `https://mcp.publicdataobservatory.org/mcp`, with expected values from the live database: 44/44, p50 14 ms, p95 101 ms.
  - Live role: UPDATE refused, `demo_access_codes` denied, 5 s timeout.
  - `/mcp`: no Set-Cookie, `Cache-Control: no-store`. Everything except `/mcp` and `/healthz` returns 404.
  - The 120/min rate limit returns 429 on a burst.
  - Live site 200; anonymous community catalog 401; pointers unchanged.
- **Not verified by the agent:** ChatGPT Developer mode against production (John tested Claude on staging).
- **Next:** M6, a "Use CHIP in your AI assistant" page (Codex). John to try ChatGPT. Decide later whether to list the server in directories.

## 2026-11-17T16:30:20+00:00 — M6 connector URL follow-up (Codex)

- **Request and outcome:** Changed the uncommitted `/ai` page, its Copy action and test, and the README section to use the bare host `https://mcp.publicdataobservatory.org`. The page also names `/mcp` as an alternate endpoint. John requested the change and reported Claude's `mcp.Client` verification; Codex did not repeat the live client check.
- **Verification:** `npm test` passed 160/160; `npm run build` passed with a bundle-size warning. No database, service, publication, deployment, commit, or push. The page remains uncommitted and undeployed on `codex/mcp-m6`.
- **Next:** Claude reviews and incorporates M6 through the MCP workflow. The handbook was not changed because this follow-up does not change deployed state; the M6 URL decision is recorded in `docs/mcp/status/codex.md` for Claude.

## 2026-11-17T15:37:00+00:00 — MCP server built, evaluated, and public on staging; Gate A open (Claude)

- **Built by the agents (dispatched headlessly; Claude reviewed and committed):**
  - Codex M2: seven tools, 13 tests.
  - Codex M2b: 50 KB size rule, compact list rows, withheld AHRF explained, 18 tests.
  - Antigravity M3, M3b, M3c: 44-question deterministic evaluation with 12 traps.
  - Contract amendment 1 settled the size rule and Antigravity's seven ambiguities. Item 2a was accepted from Codex.
- **System changes (staging):**
  - Role `chip_mcp_ro` on `places_staging` only: read-only, 5 s statement timeout, SELECT on `area_pilot` plus `dim_county` and `dim_county_boundary`. Default privileges for future `area_pilot` tables.
  - Env file `~/.config/chip/mcp-staging.env` (mode 600).
  - `.venv-mcp` in `/home/john/chip-beta`.
  - `chip-mcp-staging.service` installed and enabled.
  - `/etc/nginx/conf.d/chip-mcp-ratelimit.conf`, and an include of `infra/mcp/nginx-mcp.conf` in `/etc/nginx/sites-available/chip-beta` (the `nginx -t` test passed; reloaded). The repo copy is updated.
  - `/etc/apparmor.d/antigravity-agy` (approved by John).
  - `chip-dispatch` and `chip-watch` in `/usr/local/bin`.
  - `deploy-staging.sh` now refreshes and restarts the MCP service; it did so at 15:17:50Z.
- **Verification:**
  - Evaluation 44/44 (65 calls, p50 53 ms, p95 125 ms).
  - All seven tools work through the public HTTPS URL.
  - The role refuses UPDATE and CREATE, is denied `demo_access_codes`, and cancels `pg_sleep(6)` at 5 s.
  - `/mcp` sets no cookie and sends `Cache-Control: no-store`.
  - The website catalog still returns 401.
  - A burst of 40 requests gave 13 × 200 and 27 × 429.
- **Open:**
  - The 30 requests per minute per IP limit is too tight for production, because ChatGPT and Claude call from shared cloud IPs. Raise it at M5.
  - Antigravity's sandbox has no network, so Claude runs its database-dependent steps.
  - Merging Codex's 2026-11-16 entries put them below older Claude entries in this file. Order is otherwise preserved.
- **Correction:** the 2026-11-17T18:30Z entry below was stamped ahead of the clock; that work finished at about 14:35Z.
- **Live:** nothing changed. **Next:** Gate A, John tries the connector in Claude and ChatGPT. After that: M5 (production hostname, live role, rate limit) and M6 (Codex: "Use CHIP with AI" page).

## 2026-11-17T18:30:00+00:00 — MCP server planned; M0 setup and M1 read layer (Claude)

- **Request (John):** build a public CHIP MCP server so ChatGPT, Claude, and other AI assistants can query published CHIP data; Claude manages and hands work to Codex and Google Antigravity without copy-paste. **Decisions with John:** sort one measure across areas (no composite scores); open, no login, read-only, AHRF excluded; staging at `chip-beta.publicdataobservatory.org`, production at `mcp.publicdataobservatory.org` (DNS record pending); John approves only Gate A (staging tryout) and Gate B (go public). Plan: [docs/mcp/PLAN.md](mcp/PLAN.md); contract: [docs/mcp/TOOL_CONTRACT.md](mcp/TOOL_CONTRACT.md).
- **Built on `claude/mcp-m0`:**
  - `lookup.measure_values_within`, which returns one measure for every area inside a parent, keeps areas without rows with their read-time status, and keeps source-only areas.
  - Four unit tests.
  - The tool contract, the plan with M0 amendments, and the status files.
  - An `AGENTS.md` MCP ownership section.
  - `infra/mcp/` (two units, the read-only role script, the Nginx snippet, and a README; **none installed**).
  - `infra/staging/nginx-chip-beta.conf` (a copy of the active system site, per Codex's TLS handoff).
  - A handbook correction on the public beta host.
- **System changes:**
  - With John's approval, installed `/etc/apparmor.d/codex-bwrap` (source `infra/agents/apparmor-codex-bwrap`) and loaded it with `apparmor_parser -r`. Without it, Ubuntu blocked Codex's bundled bubblewrap (`setting up uid map: Permission denied`).
  - Added the launcher `~/.local/bin/codex-cli`, outside the repository.
- **Findings:**
  - `mcp` 2.3.0 has no `FastMCP`; the class is `MCPServer`. Installing it would upgrade Starlette to 1.10 and break FastAPI 0.115, so the MCP server gets its own venv.
  - The SDK checks Host headers, so the public hostnames must be in the allowed list.
  - Codex and Antigravity cannot commit from the sandbox (worktree git metadata sits outside it), so Claude commits after review.
  - The Antigravity CLI needs John to sign in once.
- **Verification:**
  - A spike `MCPServer` served `lookup.area_values` from `places_staging` to the SDK client: Person County diabetes 14.9 (ci95 12.7–17.2), about 30 ms.
  - A headless Codex dry run reached `places_staging` (12 pointers), passed 8 community tests, and was refused a write outside its worktree.
  - `measure_values_within` on staging returned 67 Alabama counties, 254 Texas counties, 2,498 Los Angeles tracts in 0.41 s, and BRFSS `not_published` for KY and PA.
  - Area, community, and lookup tests: 252 passed. The 7 `test_federal_account_lookup` failures and the `test_profile_scope` collection error are the known missing-input cases in this worktree.
- **Live:** nothing changed. **Next:** merge to `beta` and deploy staging; dispatch Codex for M2; Antigravity M3 after John signs in to `agy`.

## 2026-11-16T15:40:00+00:00 — CHIP slide library deck (Claude)

- **Request (John):** a PDO-branded "library" deck covering all of CHIP, with screenshots of every part (maps, comparisons, profiles, and so on), to pull slides from for any audience.
- **Outcome:** `/home/john/CHIP_Slide_Library.pptx`, 71 slides in nine PowerPoint sections (guide, core story, product tour, data maps, data sources, trust and methods, funding views, audiences, under the hood, roadmap and close), outside the repository. Every slide's notes start with "Use for:" and a talk track.
- **Screenshots:** 40 fresh captures from staging (`http://127.0.0.1:8080`, same commit as live, `51d0d7e`), signed in with the existing staging access-code file used by `npm run test:beta`; read-only browsing plus GETs of the Kanawha County PDF and CSV. The code was not printed or stored elsewhere. The standalone map would not open at tract level from a URL (`geography=tract` with `focus=county:54039` still showed county shapes); the tract slide uses the profile's tract map instead. **Possible product gap, not investigated.**
- **Unconfirmed content:** "What's next" is proposed direction, as in the funder deck. The state funding profile screenshot shows a staging dollar total; notes say to check live before quoting it.
- **Verification:** skill validator passed; every slide checked for text, table, and image overflow in an HTML mirror with Roboto Slab loaded, and reviewed visually. Not opened in PowerPoint or LibreOffice (not installed on this VM).
- **No application, data, staging, or live change.** Handbook unchanged.

## 2026-11-16T00:30:00+00:00 — Funder slide deck for CHIP (Claude)

- **Request (John):** a PowerPoint deck on CHIP in the PDO brand for future funder presentations; plain language, Smart Brevity.
- **Outcome:** `/home/john/CHIP_Funder_Deck.pptx` (12 slides, 16:9, speaker notes on every slide), outside the repository. Built with pptxgenjs to match `PDO_Presentation_Template.pptx` (navy cover and title band, peach rule, Roboto Slab headings, Arial body, brand theme colors). Uses three Gate 3 staging screenshots from `deliverables/beta/screenshots/` (landing, Person County profile, three-county comparison); they predate the 2026-11-15 map polish but show the current page design.
- **Unconfirmed content:** the "What's next" slide (public site, mortality and more measures, scheduled source checks, user testing) is proposed direction drawn from the execution plan and handbook, not an approved roadmap; its notes say to confirm before presenting.
- **Verification:** skill validator passed; text checked for overflow in an HTML mirror of every slide with Roboto Slab loaded. Not opened in PowerPoint or LibreOffice (not installed on this VM).
- **No application, data, staging, or live change.** Handbook unchanged.

## 2026-11-16T00:05:00+00:00 — Internal team brief on place-first CHIP (Claude)

- **Request (John):** a two-page (front and back) Word brief for the internal team on the move from data maps to place pages, the public health measures CHIP shows, and how it serves the intended users; in brand, plain language.
- **Outcome:** `/home/john/CHIP_Place_First_Team_Brief.docx`, outside the repository. Built with docx-js in the PDO Fact Sheet layout (navy header with PDO mark, 2-inch stat cards beside narrative, Roboto Slab only for title and stat numbers, Arial elsewhere, brand palette). Figures taken from the topic and product registries and the coverage matrix: 66 measures, 7 agencies, 12 active releases, 4 geography levels, 54,560 mapped facilities (19,200 + 13,878 + 21,482).
- **Verification:** rendered with docx-preview in Chromium; both pages fit with about 0.5 inch to spare. Not checked in Word or LibreOffice (neither is installed on this VM), and Roboto Slab was substituted in the preview.
- **No application, data, staging, or live change.** Handbook unchanged.
## 2026-11-16T14:31:03+00:00 — Beta access-code retrieval question (Codex)

- **Request/finding:** John asked where to find the renewed CHIP access code. Verified that `/home/john/.local/share/chip/staging-beta-access-code` exists on the VM, is owned by `john`, and has mode 600; `cat` can display the beta plaintext code to John locally. The admin database stores hashes and code metadata, so other plaintext codes cannot be listed from it.
- **State/verification:** Read-only file metadata and documentation/code inspection; no code value was displayed, no application or database changes were made. The beta code extension remains recorded in the preceding entry. Handbook unchanged because this did not change documented current state; no further action or commit.

## 2026-11-16T14:29:17+00:00 — Beta access code expiry extended (Codex)

- **Request/outcome:** John chose to extend the existing CHIP beta verification code by 30 days, keeping the same code. Staging code ID 22 (`Beta staging verification`) now expires 2026-12-22T00:13:50.676282+00:00 (December 21, 6:13 p.m. CST), 30 days after its previous expiry.
- **State/verification:** Patched only `expires_at` through the staging demo-access admin API. The code remains active with unlimited uses; the restricted local code file still matches its staging database hash, and the use count stayed 137. Public beta HTTPS health returned 200 and an anonymous protected request returned 401. The live database, application code, services, and deployment were unchanged. No test suite was needed for this metadata update.
- **Documentation/next:** Recorded the new expiry in Codex status. The Claude-owned handbook was not edited; it does not track individual code expiries. No unresolved issue for this renewal; revisit the expiry before December 21 if beta access is still needed. No commit or push.

## 2026-11-16T14:24:02+00:00 — Beta HTTPS and redirect rechecked (Codex)

- **Request/finding:** John asked to serve HTTPS and redirect HTTP for `chip-beta.publicdataobservatory.org`. The active Nginx beta vhost already does both: port 80 returns 301 to the same HTTPS host (while retaining the ACME challenge route), and port 443 serves the staging webroot and API through the Let's Encrypt certificate.
- **Verification:** `nginx -t` passed; public HTTP returned 301 with the expected `Location`; HTTPS returned 200 for `/` and GET `/api/health`; the certificate subject matches the hostname and expires 2027-02-14T13:13:19+00:00. UFW allows 443/tcp. No application or server changes were needed or made in this follow-up.
- **Documentation/next:** The handbook remains Claude-owned and was not edited; the prior TLS handoff below and Codex status request that Claude add the active vhost to maintained infrastructure documentation. No commit or push.

## 2026-11-16T14:13:33+00:00 — Beta hostname TLS certificate issued (Codex)

- **Request/outcome:** John asked for a Let's Encrypt certificate for `chip-beta.publicdataobservatory.org`. DNS resolves to this VM. Before the change, the hostname reached the live port-80 default site and port 443 was closed. It now redirects HTTP to HTTPS and serves the staging application on HTTPS.
- **System changes:** Installed Ubuntu's `certbot` package; obtained an ECDSA certificate using an HTTP-01 webroot at `/var/lib/letsencrypt` without stopping Nginx. Added `/etc/nginx/sites-available/chip-beta` (enabled as `zz-chip-beta`): port 80 serves ACME challenges and redirects other requests; port 443 serves `/var/www/places-staging` and proxies APIs directly to staging backend `127.0.0.1:8001`, following the existing port-8080 routing. Opened UFW 443/tcp. Added `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx`; the package enabled `certbot.timer`. The certificate expires 2027-02-14T13:13:19+00:00. Registration used no contact email, so expiry email is unavailable.
- **Verification:** Nginx syntax and reload passed; public ACME probe passed; HTTP redirects 301; trusted HTTPS returns 200 for `/` and `/api/health`, and anonymous `/api/community/catalog` returns 401. The live port-80 default site still serves its original webroot. `certbot renew --dry-run` succeeded; the reload hook also passed when run directly. No application code, database, live webroot, or backend service changed. No commit or push.
- **Documentation/next:** The handbook and `infra/staging` guide/config are Claude-owned under the beta plan and were not edited. Claude should record the new public beta URL in the handbook and maintain the beta TLS vhost in `infra/`; the active port-443 route block currently copies the port-8080 staging config and could drift when that source changes. Codex recorded the handoff in its status file.

## 2026-11-15T23:58:00+00:00 — Instant map tooltips; map polish promoted to live (Claude)

- **Request (John):** make hover tooltips on the county maps instant with no animation, because the fade looked janky, and then go live.
- **Change:** `Places2025Pilot.css` now sets `animation: none; transition: none` on `.pilot-map .leaflet-tooltip`. Leaflet's CSS has no tooltip fade of its own. Commit `63cd261`, deployed to staging. On staging a hovered Cape Girardeau tooltip had `animationName: none` and a `0s` transition. Map page tests: 30 passed.
- **Live promotion (application only):** rollback pair `data/deploy-recovery/map-polish-20261115/` (`webroot-before/` with `index-1wNr5RpJ.js`, `commit-before.txt` = `7c188c6`); `git merge --ff-only 63cd261` in `/home/john/places-app`; `npm run build`; `sudo rsync -a --delete dist/ /var/www/places/` at 23:51Z. No backend restart (no backend change), no migration, pointers untouched.
- **Verification:** live and staging bundles are equal (`index-D7zfOmSk.js`). `/`, `/explore/map`, `/area/places-2025`, `/area/acs-community`, `/cdc-funding`, and `/api/health` returned 200; the anonymous community catalog returned 401. Signed-in pages on live were not checked by the agent (it has no live access code); the same build passed the signed-in walkthrough and the tooltip check on staging.
- **Correction:** the 23:55Z entry below was stamped ahead of the clock; that work finished at about 23:45Z. **Open:** `origin` not pushed for this change.

## 2026-11-15T23:55:00+00:00 — Map loading animations and motion polish on staging (Claude)

- **Request (John):** subtle animations and polish; an animated loading screen with the Public Data Observatory logo on a map's first load only (not on zoom or Home), and a loading animation under the search bar instead of "Loading legend…" while shapes load.
- **Ownership:** `frontend/**` is Codex-owned; John confirmed in this session that Claude makes this change. Codex's worktree had no uncommitted changes.
- **Built on `claude/map-polish` (`dcbc867`):** `frontend/src/components/MapLoading.{jsx,css}` with the observatory mark redrawn as SVG (geometry and colours `#3576BA`/`#FFD5B0` read from `pdo-observatory-mark.png`). Its constellation lines draw in, the stars twinkle, the data blocks stack up, and the telescope sweeps. The first-load overlay, the loading pill, and the legend skeleton are wired into `Places2025Pilot.jsx`; panel, shape, tooltip, legend, and button motion is in `Places2025Pilot.css`. All motion is off under `prefers-reduced-motion`. Backend untouched.
- **Verification:** frontend 158 tests (one new: overlay on first load only, pill and legend skeleton on a later load); Vite build. `infra/staging/deploy-staging.sh claude/map-polish` deployed `beta` `dcbc867`. A Playwright check on staging `/area/places-2025` at 1365×900 and 390×844 (signed in with the staging code, map requests slowed by 1.5 s) found the overlay on load, no overlay after Zoom In, the pill shown and then cleared, no page errors, and no horizontal overflow. Screenshots checked. `npm run test:beta` against staging `5be7bee` passed every leg.
- **Live:** nothing changed. **Next:** John reviews staging; promotion would be application-only (webroot rebuild; no backend restart needed).

## 2026-11-15T23:25:00+00:00 — main and beta pushed to GitHub (Claude)

- At John's request: `git push origin main beta` from `/home/john/places-app`, fast-forward `33925a0..80abfab` for both, no force. `origin/main` and `origin/beta` now equal the live checkout. This closes the "push origin" item in earlier entries and the handbook. No application or data change.

## 2026-11-15T23:20:00+00:00 — Correction and live result for the legacy map retirement (Claude)

- **Correction:** the entry below and the handbook note were stamped 2026-11-16T00:10Z by mistake; the VM clock read 2026-11-15T23:17Z at promotion. The rollback directory keeps the mistyped name `legacy-map-retirement-20261116`.
- **Live promotion:** rollback pair saved (`webroot-before/` with `index-SHd_oIOA.js`, `commit-before.txt` = `28ff6ef`); `git merge --ff-only 740507e` in `/home/john/places-app`; `npm run build`; `sudo rsync -a --delete dist/ /var/www/places/` at 23:17Z. No backend restart (no backend change); Alembic still `e6b3a8d0f2c5`; pointers untouched.
- **Verification:** live and staging bundles equal (`index-1wNr5RpJ.js`); `/`, `/explore/map`, `/area/places-2025`, `/cdc-funding`, `/api/health` 200; anonymous community catalog 401. Signed-in pages on live not checked by the agent (no live access code); the same build passed the signed-in walkthrough on staging.
- **Next:** John's look at live; `git push origin main beta` still outstanding.

## 2026-11-16T00:10:00+00:00 — Legacy map retired and promoted to live (Claude)

- **Request (John):** remove all the legacy maps from `/explore/map` and from the Data source menu; push live when done.
- **Interpretation (Claude's, stated here so it can be corrected):** every layer on `/explore/map` was a legacy map, so the page now opens the published-release area map instead of an empty legacy page. "Legacy" was taken to include the CDC funding state map that lived only in that menu; funding remains on `/cdc-funding` and the state funding profiles. The SVI, FEMA NRI, HPSA, ACS non-medical-factor, and older PLACES, CMS, and USDA layers are no longer on any map.
- **Changes on branch `claude/retire-legacy-map`:** deleted `App.jsx`, `SearchBar.jsx`, `mapContext.js`, `sviCatalog.js`, `components/FullProfilePanel.jsx`, `components/AskMapChat.jsx`, `content/hpsaLegendCopy.js`, `hooks/useSelectedAreaProfileTarget.js`; `main.jsx` renders the area map for `/explore/map` and unknown paths; removed the "Legacy CHIP map" option, the "Legacy map with older layers" link, two "legacy import" sentences, and the county profile's legacy-map link. Backend untouched. Bundle 872 KB to 628 KB.
- **Verification:** frontend 157 tests and build; staging `56223cb` walkthrough passed every leg, including new checks that `/explore/map` shows nine published sources, no legacy entries, and no legacy panels, and that `/explore/map?focus=county:54039` selects Kanawha; screenshot checked.
- **Live:** see the promotion lines below this entry's commit in the handbook note. Rollback: restore `webroot-before/` from `data/deploy-recovery/legacy-map-retirement-20261116/` and check out `commit-before.txt`.

## 2026-11-15T23:08:00+00:00 — Map consistency package promoted to live (Claude, M8)

- **Approval:** John reviewed staging, asked for the county-shape fix, and said the package could go to live once it was fixed; after the fix he said to finish up.
- **Promoted:** `beta` `e7e8e68`. Application only. No step failed; no rollback used.
- **Before any change:** rollback pair `data/deploy-recovery/map-consistency-20261115/` (`webroot-before/` with bundle `index-D7hePjXM.js`, `commit-before.txt` = `33925a0`). **No new database dump was taken**, because this promotion writes nothing to the database: no migration in the diff, live Alembic already at head `e6b3a8d0f2c5`. The 17:13Z recovery set predates the BRFSS release, so a current full recovery set is still outstanding work.
- **State-changing commands on live:** `git merge --ff-only e7e8e68` in `/home/john/places-app`; `npm run build`; `sudo rsync -a --delete dist/ /var/www/places/`; `sudo systemctl restart places-backend` (active 23:02:39Z).
- **Verification:** live and staging bundle names equal (`index-SHd_oIOA.js`); `/`, `/api/health`, `/explore/map`, `/area/acs-community`, `/cdc-funding`, `/methodology` 200; anonymous community and area catalogs and the new area endpoint 401; twelve active pointers, BRFSS still `5c61bade-…`; on the live database the fitted shape query returns 295 points for Pike County, Alabama at the zoom-9 grid and zero gap area across Alabama counties; no errors in the backend journal after restart.
- **Not verified:** signed-in pages on live (no live access code for the agent). The same commit passed the signed-in walkthrough on staging.
- **Open:** John's signed-in look at live; `git push origin main beta`; the lopsided fixed breaks (proposal in the handbook); refreshed `deliverables/` screenshots; a current recovery set and the off-VM backup.

## 2026-11-15T22:58:00+00:00 — County shapes made to fit together on every map; staging verified (Claude, M7)

- **Request (John, after reviewing staging):** county shapes did not line up when zoomed in (example: ACS community map around Pike County, Alabama). Fix it on every county map; then the package can go to live.
- **Cause:** every map query simplified each polygon separately (`ST_SimplifyPreserveTopology`), and the `/area/*` pages sent one tolerance sized for the national view (0.04°, about 15 pixels at zoom 9).
- **Fix:** [geometry_sql.py](../backend/app/geometry_sql.py) snaps vertices to a common grid and removes only collinear points; applied to 9 area and 13 legacy shape queries (not the funding or TAGGS state maps). Both map generations send about one pixel for the current zoom. The selection outline follows the drawn shape. Two legacy-map faults found on the way and fixed: it did not redraw when newly loaded shapes arrived under the same view, and it dropped a response when a selection re-ran the load.
- **Verification on staging `e5335d0`:** gap area between Alabama, Georgia, and North Carolina counties 0.87 square degrees before and 0 after (read-only SQL); national county payload about 1.1 MB (0.8 MB before); screenshots of Alabama, Virginia, Kansas, and New Orleans tracts on new and legacy maps; frontend 156 tests; backend 674 passed, 5 failed (funding source tests that also fail without these changes in this worktree); `npm run test:beta` all legs.
- **Also corrected:** `tests/test_taggs_methodology_copy.py` read the old header file for the funding methodology text; it now reads `frontend/src/content/fundingMethodology.js`. This was a miss in M1 that the earlier, narrower test run did not catch.
- **State-changing commands:** branch commits; `infra/staging/deploy-staging.sh claude/map-consistency` four more times. Nothing on live in this entry.
- **Next:** promotion to live, approved by John on condition of this fix.

## 2026-11-15T22:10:00+00:00 — Map consistency package built and deployed to staging (Claude, M1–M6)

- **Outcome:** all six packages of [MAP_CONSISTENCY_PLAN.md](beta/MAP_CONSISTENCY_PLAN.md) are on staging at `beta` `5fb2720` (branch `claude/map-consistency`, fast-forward merges). **Nothing was changed on live**: checked `main` `33925a0`, live bundle `index-D7hePjXM.js`, `places-backend` start time 17:35:58Z. No migration, release, or pointer change; staging database read only.
- **Built:** shared `SiteHeader` on every page; funding methodology text moved to `/methodology`; brand tokens and 229 legacy chrome colours; one Blues ramp; release-wide quintile breaks from the legend API for PLACES, ACS income, AHRF, and CLH; `GET /community/area/{level}/{geoid}`; hover tooltip, selection outline, legend "Selected area" block, Map Tools, and place search on `/area/*`; `focus=<level>:<geoid>` links from county, state, and district profiles; phone layout for the map panels.
- **State-changing commands:** `git commit` on the branch (10 commits before this correction, including this entry's documentation commit); `infra/staging/deploy-staging.sh claude/map-consistency` six times, plus once more for this correction (each: merge to `beta`, Alembic no-op, build, `rsync` to `/var/www/places-staging`, restart `places-backend-staging`).
- **Verification:** frontend 155 tests and build passed; backend area/community/lookup selection 241 passed; `npm run test:beta` passed every leg on staging, including new legs for the header on five legacy page types, county/state/district focus, tooltip format, no popup, Escape, tools, map search, and the legacy focus link. Screenshots checked at 1365, 1000, and 390 px.
- **Failures and fixes along the way:** a map-ready hook looped under two test mocks (now registers once); the walkthrough's first hover target sat under the table panel (now points at open map); the legacy focus link ran before the first data load cleared it (now waits for the layer); phone panels overlapped because `index.css` height rules outranked the page's (specificity raised).
- **Not related, not fixed:** `tests/test_profile_scope.py` cannot be collected and seven `test_federal_account_lookup.py` tests fail in `/home/john/chip-claude` because ignored source inputs are absent there; the latter pass in `/home/john/places-app`.
- **Decisions made by Claude that John has not confirmed:** (1) quintiles are computed over the whole release at the displayed level, not the viewport; (2) the legacy map's sequential, FEMA rating, and USDA heat ramps were also moved to the shared Blues ramp, because John's contrast note applied there and its old ramp started near white. This goes beyond his earlier "legacy ramps stay" answer and is one constant block in `App.jsx` to revert; (3) the phone table starts closed.
- **Open:** fixed registry breaks are lopsided for EPA `median_aqi` (85% of counties in one class), `p90_aqi` (77%), `days_with_aqi` (81%), and ACS community poverty, age 65+, and disability at state level (65–75%). **Proposal:** revise those breaks in a separate reviewed change. The `deliverables/` screenshots and source audit were not rerun.
- **Next:** John reviews staging. On approval, application-only promotion by the runbook (recovery pair, fast-forward `main`, build, webroot, backend restart); no data steps.

## 2026-11-15T21:45:00+00:00 — Map consistency package planned and approved (Claude)

- **Request (John):** align the header on the maps, funding pages, and other legacy pages with the home page; follow the brand guide on the maps; give the `/area/*` maps the home-page search, the legacy tooltip, legend behaviour, selection highlight, and Map Tools bar; zoom to a searched place; open maps from a county, state, or district profile already zoomed to it. After approval John added: fix ramp contrast, because outliers make most counties light.
- **Decisions with John:** Claude builds it, including Codex-owned `frontend/**` and `backend/app/community/**` (one-off exception). Recolour the CMS, USDA, and AQI ramps on `/area/*` to brand Blues; legacy-map data ramps stay. Shared header keeps Log out and the gated Funding Model Builder link; the funding methodology text moves to `/methodology`; Data Sources, Download, and Help pop-ups are retired. Map tools: all except "Analyze this area".
- **Finding:** PLACES, ACS income, AHRF, and CLH legends return only min and max in view and the page cuts equal-width classes, which is the outlier skew. **Claude's choice, not yet confirmed by John:** quintiles over the whole release at the displayed level rather than over the viewport.
- **Outcome so far:** read-only exploration; plan written as [MAP_CONSISTENCY_PLAN.md](beta/MAP_CONSISTENCY_PLAN.md); execution plan amended; status table added. Branch `claude/map-consistency` created from `beta` `33925a0` in `/home/john/chip-claude`. No application, data, staging, or live change in this entry.
- **Next:** M1–M6 on the branch, then staging deploy and John's review. Nothing goes to live without approval.

## 2026-11-15T17:40:00+00:00 — BRFSS, state maps, and state profiles promoted to live (Claude, B4)

- **Approval/outcome:** John reviewed staging and approved promotion after Codex finished Y1–Y5. Promoted `beta` commit `2d35117`. No step failed; no rollback used. Before promoting, Claude reran on staging at that commit: area/community tests 233 passed, frontend 150, `npm run test:beta` passed every leg including the new state leg, and the source audit passed 59 checks. Codex's commits touched no Claude-owned paths and added no migration.
- **Recovery before any change:** `/home/john/chip-recovery/20261115T171328Z/` (11,713,951,402-byte dump, 17:13:28–17:34:03 UTC, empty stderr, 70-line validation baseline, source archive verified, `SHA256SUMS` passed). Isolated restore test **skipped**. Application rollback pair: `data/deploy-recovery/brfss-promotion-20261115/` (`webroot-before/`, `commit-before.txt` = `9201431`, pointer lists before and after).
- **State-changing commands on live:** `git merge --ff-only 2d35117`; `alembic upgrade head` (`d5a2f7c9e1b4` → `e6b3a8d0f2c5`); `brfss_cli fetch-stage-validate`, `review`, `approve-publish` for `5c61bade-38bb-41dd-8728-ce5f4921975f`; `npm run build`; `rsync --delete` to `/var/www/places`; `systemctl restart places-backend` (17:35Z).
- **Digests:** the live candidate passed all six checks and reproduced the staging semantic, schema, and metadata digests; approval used the runbook's literal values.
- **Verification:** twelve pointers, the previous eleven unchanged; live asset names equal the staging bundle (`index-D7hePjXM.js`); `/`, `/api/health`, `/explore/map`, `/community/state/37`, `/area/brfss` 200; anonymous community and BRFSS catalogs 401; read-only `lookup` output is identical on live and staging apart from release IDs for three states (99 rows), three counties (138), North Carolina's 13 companions, and the 20 medians; catalog 66 measures.
- **Not verified:** signed-in pages, PDFs, and the BRFSS map on live (no live access code for the agent). `origin/main` not pushed by this session.
- **Timestamp note:** this entry uses the VM clock. The B1–B3 entry below was stamped 18:30Z ahead of the clock and precedes this entry in fact.
- **Next:** John's signed-in check on live and `git push origin main`. Open: HRSA's answer on AHRF; off-VM encrypted backup.

## 2026-11-15T18:30:00+00:00 — BRFSS state prevalence published on staging; state read layer (Claude, B1–B3)

- **Request/plan:** John asked for BRFSS statewide figures beside PLACES measures on county profiles, state maps of that data, and state profiles. Decisions: years match PLACES (2023; 2022 for dental visits); the 13 PLACES measures plus seven state-only ones; state profiles use only sources already published for states plus BRFSS; same two-agent split and staging-first route. Plan: [BRFSS_STATE_PLAN.md](beta/BRFSS_STATE_PLAN.md).
- **Source verified at CDC (dataset `dttw-5yxu`):** question and response IDs and texts for all 20 measures; 54 locations in 2023 and 56 in 2022; Kentucky and Pennsylvania have zero 2023 rows; two median rows (`98`, `99`) carry footnote `**` and no confidence limits; the sample-size column is the count of respondents giving the response (jurisdiction count on median rows); dental visits are `_DENVST3` in 2022.
- **Changes:** registry `brfss_state_2023.json`; `brfss.py`, `brfss_cli.py`, `brfss_api.py`; router dispatch for catalog, map, legend, table; additive migration `e6b3a8d0f2c5`; `lookup` product `brfss` (state only) with `paired_measure`, `state_survey_companions`, `brfss_medians`, `state_counties`, `states`; tests `test_area_brfss.py` and one updated lookup test; [guide](../backend/docs/chip_brfss_state_prevalence.md); contract section and examples; runbook section; status tables for B and Y packages.
- **State-changing commands (staging only):** `infra/staging/deploy-staging.sh claude/brfss-b1` (Alembic `d5a2f7c9e1b4` → `e6b3a8d0f2c5`); `brfss_cli fetch-stage-validate`, `review`, `approve-publish` for `8ca50183-0b61-4302-8e3b-6e06cc8a35dd`; `deactivate` then `rollback` as a pointer drill; one repeat `fetch-stage-validate` (reported duplicate); `systemctl restart places-backend-staging`.
- **Verification:** all six validation checks passed; 1,082 observations, all available; twelve values across twelve measures and ten locations equal separate CDC API queries including limits and counts; a published row rejected an update; the other eleven staging pointers are unchanged; lookups return 66 catalog measures, 33 state rows, 13 companions for North Carolina, `not_published` for Kentucky in 2023; Nginx map, legend, and table return 52 states, reject county geography with 400, and return 401 anonymously; area and community tests 230 passed; the existing staging walkthrough passed with the wider catalog.
- **Deployment status:** staging only. Live is unchanged (eleven pointers, Alembic `d5a2f7c9e1b4`, `main` at `9201431`).
- **Decision recorded:** the metadata digest excludes Socrata revision timestamps because the dataset covers 2011 to the present and changes when CDC adds any year; selected content is pinned by the semantic digest, and the revision is kept as provenance.
- **Next:** Codex builds Y1–Y5 (state profile, county-card state line, state map, search, walkthrough, audit). Then John's staging review and B4 promotion.

## 2026-11-15T17:00:00+00:00 — AHRF owner credits deployed to live (Claude)

- **Approval/outcome:** John said to deploy the credits. Fast-forwarded the live checkout from `a0d1ff7` to `992c0d2`, ran `npm run build`, synced `/var/www/places`, and restarted `places-backend`. No schema, registry, or release change; eleven pointers.
- **Verification:** live asset names equal the staging bundle that passed the walkthrough; `/`, `/api/health`, `/explore/map` 200; anonymous community catalog 401; service active; read-only `lookup` on live returns 46 Person County values, five with `source_credit`. The signed-in page, PDF, and CSV were not viewed on live by the agent.
- **Rollback pair:** `data/deploy-recovery/ahrf-credits-20261115/`.
- **Next:** John sends the question to HRSA NCHWA and pushes `main`; record HRSA's answer in the AHRF guide.

## 2026-11-15T16:50:00+00:00 — AHRF redistribution decision and owner credits on staging (Claude)

- **Decision (John):** keep the five AHRF measures, behind the access code, credit the copyright owners beside HRSA, and ask HRSA's NCHWA in writing. Basis read from the archived source: HRSA's download page says “Usage limitations: None”; the bundled 2024–2025 County User Guide says reproduction for reuse needs the Bureau's permission and that ADA, AHA, and AMA data may not be reproduced without the owner's consent. All five CHIP fields come from those owners (AMA: primary care physicians, psychiatrists; ADA: dentists; AHA: hospitals, hospital beds). This is a reading of the documents, not legal advice.
- **Change:** `lookup` adds `source_credit` to catalog measures and value rows (five AHRF measures; `null` elsewhere); community API passes it as `source.credit`; county CSV gains an `underlying_source_credit` column; profile cards, the PDF, the comparison table, and the AHRF source map show the credit. Frontend files are Codex-owned and were edited by Claude at John's request. [AHRF guide](../backend/docs/chip_ahrf_2024_2025.md) records the decision and corrects the hospital-beds note (the user guide defines beds as set up and staffed). [Data contract](beta/DATA_CONTRACT.md) documents the field. No registry, schema, or release change.
- **Verification on staging (`383b4e9`):** backend area/community tests 209 passed, frontend 149, full `npm run test:beta` passed; Person County CSV has five credited rows and the PDF (11 pages) prints five credits.
- **Status:** staging only; live deploy (webroot and backend restart) waits for John. The email to HRSA is John's to send; no reply is recorded. Do not remove the access code or add bulk AHRF export until HRSA's answer is recorded in the AHRF guide.

## 2026-11-15T16:59:31+00:00 — Final Y1–Y5 staging handoff check (Codex)

- **Outcome:** Final Y5 evidence and status commit `2ca19ab` is on both the product branch and local `beta`; the staging deploy script completed its build, Alembic-head, health, anonymous-access, and page checks. All Y packages remain staging-only and ready for Gate 3 review of that commit. No live system, migration, or published release was changed.
- **Read-only verification:** Staging Nginx returned health 200, anonymous catalog 401, and state page 200. `app.area_pilot.lookup.catalog` returned 66 measures; `lookup.area_values` returned 40 BRFSS rows across North Carolina and Kentucky on one release, including 19 Kentucky `not_published` rows. The first lookup command was launched from the repository root without `PYTHONPATH`, failed to import `app`, and was rerun successfully from `backend/`.
- **Unresolved/next:** John reviews the specific staging `beta` commit at Gate 3. Claude owns B4 promotion and the handbook update after approval; Codex stops here. The handbook was not edited because it is Claude-owned under the beta plan.

## 2026-11-15T16:58:02+00:00 — Y5 state walkthrough and evidence deployed to staging (Codex)

- **Request/outcome:** Completed Y5 on `codex/brfss-y5-evidence`; code commits `8643f8f` and `9d9069f` merged into local `beta` and deployed to staging. Landing search accepts state names and two-digit FIPS, and North Carolina is an example state. The walkthrough covers state search, North Carolina and Kentucky profiles, state PDF, BRFSS map, and mobile layout. Refreshed 11 screenshots and extended the archived-source audit to 59 checks including BRFSS in North Carolina, West Virginia, and Kentucky. No live changes, migrations, or direct published-data table reads in product code.
- **Verification:** Full frontend 150 tests passed; backend area/community 233 tests passed; Vite build and staging deploy checks passed. Authenticated `npm run test:beta` passed every leg on staging; anonymous catalog still returns 401. The source audit verified release-linked archived SHA-256 files and 59 source/API/page/PDF checks, including BRFSS confidence limits, response counts, and Kentucky's three absent 2023 sample rows. One initial mobile state screenshot captured the loading state; the walkthrough now waits for profile readiness and the refreshed capture was visually checked.
- **Files/state:** Community landing, walkthrough, source audit and report, 11 screenshots, evidence README, Codex status, and diary. The handbook is Claude-owned under the beta plan and was not edited. Staging has twelve published pointers including BRFSS release `8ca50183-0b61-4302-8e3b-6e06cc8a35dd` and Alembic `e6b3a8d0f2c5`; no publication was performed by Codex.
- **Unresolved/next:** All Y packages are deployed on staging. Stop at Gate 3 for John's review of the specific `beta` commit. Claude owns B4 live promotion and the handbook update after approval.

## 2026-11-15T16:51:05+00:00 — Y4 BRFSS state map and topic links deployed to staging (Codex)

- **Request/outcome:** Completed Y4 on `codex/brfss-y4-state-map`; commit `5edec8c` merged into local `beta` and deployed to staging. Added `/area/brfss` to the route and both data-source selectors. The existing source-map page now pins BRFSS to state geography, shows CDC's fixed prevalence classes, confidence limits, response counts, source status, and the CDC-published median of states and DC as a reference only. Added all 20 BRFSS measures to the two health topics with preselected map links. No live changes, migrations, or direct published-data table reads in product code.
- **Verification:** Focused source-map and route tests 28 passed, focused community API tests 9 passed, Vite build and staging deploy checks passed. Authenticated staging browser showed 52 state shapes and table rows, not-published status, median label, 2022 dental selection, and 13 health plus seven prevention topic map links. Two initial browser verification attempts failed on ambiguous/exact label locators in the check script; the corrected locator run passed without page errors.
- **Files/state:** `Places2025Pilot.jsx` and test, `App.jsx`, community topic JSON and map route, route resolver and test, Codex status, and diary. The handbook is Claude-owned and was not edited; staging releases and pointers were unchanged.
- **Unresolved/next:** Complete Y5 landing state search, walkthrough, three-state source audit, and screenshots; then hand off at staging for John's review. B4 promotion remains Claude-owned.

## 2026-11-15T16:45:58+00:00 — Y3 county BRFSS companions deployed to staging (Codex)

- **Request/outcome:** Completed Y3 on `codex/brfss-y3-county-companion`; commit `21e11f7` merged into local `beta` and deployed to staging. County PLACES cards and the comparison table show paired direct state BRFSS values with the exact survey label, year, confidence interval, and source; the county CSV has companion columns and the profile links to its state. Comparison API obtains each state companion through `lookup.state_survey_companions`. No live changes, migrations, or direct published-data table reads.
- **Verification:** Area/community tests 233 passed; focused frontend community/route tests 11 passed; Vite build and staging deploy checks passed. Authenticated staging Person County showed 13 paired cards and CSV companion rows, a two-county comparison showed 26 paired cells, and its 13-page PDF contained the BRFSS label, interval, source, and state link. Kentucky county `21001` returned 12 `not_published` 2023 companions and one published 2022 dental companion.
- **Files/state:** Community router and tests, county and comparison components, CSS, Codex status, and this diary. The handbook is Claude-owned and was not edited; staging releases and pointers were unchanged.
- **Unresolved/next:** Implement and deploy Y4 state BRFSS map and topic links, then Y5 evidence. B4 promotion remains Claude-owned and waits for John's staging review.

## 2026-11-15T16:42:58+00:00 — Y2 state profile page deployed to staging (Codex)

- **Request/outcome:** Completed the next product package Y2 on `codex/brfss-y2-state-profile`, merged commit `c1569a1` into local `beta`, and deployed to staging. The state page reuses community indicator, facility, brand, and print components; it shows ACS, BRFSS, CMS, facility counts, county and district links, and the existing state funding profile. No live changes, migrations, or direct published-data table reads.
- **Verification:** Route test (5 passed), Vite build, and staging deploy checks passed. Authenticated staging rendered North Carolina and Kentucky with 33 indicators each, including 20 BRFSS cards; Kentucky displays not-published statuses. State funding and county links resolved. North Carolina PDF returned HTTP 200 and a valid seven-page PDF containing the state heading, BRFSS diabetes, confidence interval, facilities, and limits. The PDF rendering validates the Y1 state PDF route end to end.
- **Files/state:** `CommunityState.jsx`, community print/places CSS, `main.jsx`, route resolver and test, Codex status, and this diary. The handbook is Claude-owned under the beta plan and was not edited; staging BRFSS release and other pointers were not changed.
- **Unresolved/next:** Implement and deploy Y3 county and comparison BRFSS companion presentation. B4 promotion is Claude-owned and awaits John's staging review after Y5.

## 2026-11-15T16:39:03+00:00 — Y1 state community API deployed to staging (Codex)

- **Request/outcome:** Merged `beta` into the clean product branch, then implemented Y1 in `backend/app/community/router.py`: state-name search through `lookup.states`, a state profile from `lookup.area_info`, `area_values`, `area_facilities`, `state_counties`, and `state_districts`, state CSV and PDF routes, and 13 BRFSS companion rows keyed to PLACES measures on county API responses. Commit `bd7e4db` merged into local `beta` and deployed to staging. No live changes, migrations, or direct published-data table reads.
- **Verification:** Eight focused community tests and 232 area/community tests passed. Authenticated staging Nginx returned 200 for state search, North Carolina state profile (33 rows: 20 BRFSS), CSV (33 rows), and Person County profile (13 companion rows). Deploy passed Alembic head, Vite build, backend health 200, anonymous catalog 401, and page 200. State PDF route and session propagation have a passing contract test; rendered PDF content awaits the Y2 page.
- **Files/state:** community router, `test_community_state.py`, existing community test fixture, product status, and this diary. Staging has the BRFSS release `8ca50183-0b61-4302-8e3b-6e06cc8a35dd`; no publication change. The handbook is Claude-owned under the beta plan and was not edited.
- **Unresolved/next:** Build Y2 state profile page and verify state PDF, then continue Y3–Y5. B4 promotion remains Claude-owned and waits for John's staging review.

## 2026-11-15T16:20:00+00:00 — PDF pagination fix deployed to live (Claude)

- **Approval/outcome:** John said to deploy the PDF fix. Fast-forwarded the live checkout from `5e95ee5` to `abc2e37` (print CSS plus documentation), ran `npm run build`, and synced `/var/www/places`. No backend restart, schema, or data change; eleven pointers untouched.
- **Verification:** live asset names equal the staging bundle that passed the walkthrough (`index-Dz3pCAA8.js`, `index-_Q27BhdI.css`); the deployed stylesheet contains the new print rule; `/` and `/api/health` 200, anonymous community catalog 401. A PDF was **not** downloaded from live by the agent (no live access code); the same bundle produced the checked 11-page PDFs on staging.
- **Rollback pair:** `data/deploy-recovery/pdf-fix-20261115/` (`webroot-before/`, `commit-before.txt`).
- **Next:** John pushes `main`; AHRF redistribution terms remain open.

## 2026-11-15T16:10:00+00:00 — Live check passed by John; profile PDF pagination fix on staging (Claude)

- **Live verification:** John opened the live site with his own access code after promotion and reported that everything works as intended, and supplied the Person County PDF downloaded from live (13 pages, all 46 indicators, facility counts 4/2/6). This closes the authenticated live walkthrough left open in the promotion entry; the automated `beta-walkthrough.mjs` script was not run against live.
- **Defect John reported:** the PDF's first page was almost empty. Cause: the print rule `break-inside: avoid` on every `.community-profile-section` pushed each section that could not fit to a new page; the last page also showed a screen-height tinted filler.
- **Change (frontend print CSS, a Codex-owned file, edited by Claude at John's request while Codex was idle):** `frontend/src/community/community.css` print block only: sections flow across pages, cards stay whole, section headings stay with their first row, the limitations section stays on one page, and the page background and minimum height are reset for print. Commits `522f2a6` and `ae68c3f` on `beta`, deployed to **staging** by `infra/staging/deploy-staging.sh`.
- **Verification on staging:** Person and Fresno PDFs are 11 pages with page 1 carrying the title and the first four indicators and no filler on the last page (pages rasterized and inspected); frontend 149 tests and the full `npm run test:beta` walkthrough passed.
- **Deployment status:** staging only. Live still serves the promoted bundle `index-BYohp3_t.js`; the fix goes to live when John approves. `origin/main` push is still John's.

## 2026-11-15T15:40:00+00:00 — Beta promoted to live after Gate 3 approval (Claude)

- **Approval/outcome:** John reviewed staging and approved promotion; `beta` commit `f48704e` was named to him beforehand. The funder beta is now the live application. Followed the [promotion runbook](beta/PROMOTION_RUNBOOK.md) in order; no step failed and no rollback was used.
- **Recovery before any change:** new live set `/home/john/chip-recovery/20261115T150507Z/` (11,605,125,370-byte dump, 15:05:07–15:25:00 UTC, empty stderr, 66-line validation baseline, source archive verified, `SHA256SUMS` passed). The isolated restore test was **skipped** for this set; the same procedure passed at 02:24Z on the earlier set taken from the same pre-beta live state. Application rollback pair: `data/deploy-recovery/beta-promotion-20261115/` (`webroot-before/`, `commit-before.txt` = `0195959`, `pointers-before.txt`, `pointers-after.txt`).
- **State-changing commands on live:** `git merge --ff-only f48704e` in `/home/john/places-app`; `alembic upgrade head` (`c8f1e4a7d3b6` → `d5a2f7c9e1b4`); `cli fetch-stage-validate`, `review`, `approve-publish` for PLACES county `2cdffcf4-3c72-4f5d-abaa-9f8708472922` (15:27Z) and tract `b44a4645-9f2e-48a6-810b-48c45ae2469e` (15:31Z); `acs_profile_cli load-cd-boundaries` (52 files, 437 valid shapes); `acs_profile_cli fetch-stage-validate`, `review`, `approve-publish` for `ee45e615-43ab-4071-8da3-f1731d4b1efa` (15:32Z); `npm run build`; `rsync --delete` to `/var/www/places`; appended `PROFILE_FRONTEND_BASE_URL` to the private live `backend/.env`; `systemctl restart places-backend` (15:32Z).
- **Digests:** all three candidates passed every validation check and reproduced the semantic, schema, metadata, and measure-set digests recorded in the runbook; approvals were given with the runbook's literal values. PLACES tract maps were county-only for about four minutes (15:27–15:31Z).
- **Verification:** eleven pointers; the nine untouched pointers equal `pointers-before.txt`. Live bundle file names and hashes equal the staging bundle. Health 200 direct and through Nginx, `/` and `/explore/map` 200, anonymous area and community catalogs 401. Read-only `lookup` output on live versus staging is identical apart from release IDs for the three showcase counties (138 values), their states, district `5401` (seven values, 347/56/60 facilities, county relations), and Person County diabetes tracts; active ACS community rows 623,651 on both; 14 published releases on both.
- **Not verified:** the authenticated live browser walkthrough and a live PDF. Creating a live access code for the check was denied by the session's permission system and was not retried another way. `origin/main` has not been pushed by this session.
- **Next:** John supplies or creates a live access code (or runs the walkthrough himself) for the outstanding check; push `main`. AHRF redistribution terms and the off-VM encrypted backup remain open. Staging stays in place for further beta work.

## 2026-11-15T15:05:00+00:00 — Gate 3 readiness recheck of the product track (Claude)

- **Outcome:** independently rechecked Codex's X5/X6 handoff at staging `beta` `4633cad` and pushed `beta` to origin. No application code changed; documentation only (handbook, runbook open items, Claude status). No live change: live checkout clean on `main` `0195959`, ten pointers, Alembic `c8f1e4a7d3b6`, backend not restarted since 2026-11-14T22:29Z.
- **Verification rerun on staging:** `npm run test:beta` passed all legs (landing/search/profile/PDF, comparison, topics, three showcase profiles, legacy and area pages, HRSA Details pointer clicks at desktop and mobile widths, mobile overflow, district `5401`); `deliverables/beta/verify_source_samples.py` passed 47 archived-source checks; frontend 149 tests and backend area/community 208 tests passed. Authenticated API: Person County profile returns 46 indicators with the ACS and PLACES insurance measures separate; district `5401` returns seven ACS estimates, facilities, and county relations. The full backend suite was not rerun here. The audit rerun rewrote only the timestamp in `gate3_source_samples.json` in the staging checkout; that change was discarded.
- **Ownership note:** the 02:27 and 02:29 entries record Codex completing C4 and C5 on the data/platform track at John's instruction; the recovery set's 37 checksums were re-verified by Claude, the isolated restore was not repeated.
- **Timestamp note:** this entry uses the VM clock. The C1–C3 entries stamped 15:30 and 17:40 on this date were stamped ahead of the clock and precede this entry in fact.
- **Next:** John's Gate 3 review on staging and approval of a specific `beta` commit. Promotion then follows the runbook with a fresh live recovery set. AHRF redistribution terms remain open.

## 2026-11-15T17:40:00+00:00 — ACS community characteristics and 119th Congress districts published on staging (Claude, C2 and C3)

- **Outcome:** new independent shared product `census_acs5_2024_community_profile` is published on **staging** as release `d90070e6-0358-499b-b992-4ca6b8b42eb3`: seven Census-published measures (total population; percent in poverty, 65 and over, under 18, with a disability, uninsured, limited English) for 52 states, 3,222 counties, 85,382 tracts, and 437 congressional districts. Live is unchanged. The B19013 income product was not touched.
- **Design decisions:** a separate product rather than widening B19013, so the published income release keeps its own pointer; subject-table variables only, so every percentage and margin is the Census Bureau's own; district estimates fetched in the same run because they come from the same endpoint (this merges C3's data into C2).
- **Source verified:** variable labels and concepts pinned in the registry; summary levels 040/050/140/500 at reference date 2024-01-01; districts named "(119th Congress)"; three zero-population "not defined" (`ZZ`) rows in CT, IL, NH excluded and recorded; TIGER/Line 2024 district shapes exist only as per-state archives (the national file URL returns 404).
- **Changes:** registry `acs_2024_profile.json`; modules `acs_profile.py`, `acs_profile_cli.py`, `acs_profile_api.py`; router dispatch; additive migration `d5a2f7c9e1b4` (`cd_boundary_119`, `stage_acs_profile`, `observation_acs_profile`, immutability triggers); `lookup` gains product `acs_profile`, level `cd`, `district_counties`, `county_districts`, `state_districts`, and facilities inside a district; operator guide `backend/docs/chip_acs_community_profile.md`; inventory record (now 99); data contract and examples under `docs/beta/contract-examples/after-c3/`.
- **State-changing commands (staging only):** `alembic upgrade head` (`c8f1e4a7d3b6` → `d5a2f7c9e1b4`); `acs_profile_cli load-cd-boundaries` (52 archives, 437 shapes, all valid); `fetch-stage-validate` (11/11 checks, 623,651 observations, ready on the first run); `review` (221 archived files, 89,093 staged rows, 623,651 observations re-derived); `approve-publish` with semantic `227317d9…3443`, schema `b0c8a7f7…56e0`, metadata `897472a5…e41c`; drill: `deactivate`, a refused rollback to a PLACES release ID, `rollback` to the release.
- **Verification:**
  - 13 values each for Kanawha County, WV-01, West Virginia, and tract `54039000100` equal a separate Census API request.
  - A direct `UPDATE` of a published row was rejected by the immutability trigger. Eleven active pointers afterwards; only the new product was added.
  - `lookup` on staging: 46 catalog measures; Person, Kanawha, and Fresno counties 46 of 46 available; WV-01 returns 28 counties, all wholly inside; Fresno County overlaps four districts; facilities in WV-01 returned in 0.1 s.
  - Tests: 14 new unit tests for the product, 2 new lookup tests; all 207 area and community tests pass. Full backend suite: 651 passed, 12 failed, plus one module that cannot be collected; all 13 need untracked funding data files that exist only in the live checkout (`data/recon/*.csv`, `data/chipfunding/*`), none touch this change.
  - **Not done:** no PostGIS lifecycle test was written for this product (the unit tests and the staging run cover it); no browser check, because no frontend page for the product exists yet.
- **Next action:** Codex builds the district briefing (X5) and adds the new measures to topics and profiles. Claude: C4 (fresh recovery set and promotion runbook), then C5.

## 2026-11-15T15:30:00+00:00 — Staging live; PLACES widened to 13 measures on staging (Claude, C0.3 and C1)

- **Outcome:** the staging stack is running, and the shared PLACES product on **staging** now publishes 13 measures at county and tract level. Live is unchanged: database `places`, its ten pointers, `/var/www/places`, and `places-backend` were not touched.
- **Staging:** the `pg_dump | pg_restore` copy finished with exit 0. Live and staging matched on Alembic revision `c8f1e4a7d3b6`, 203 tables, 863 indexes, 12,572 PLACES county observations, 10,149,572 rows in the largest table, and all ten active pointers. Ran `ANALYZE`, `systemctl enable --now places-backend-staging`, and the first `deploy-staging.sh` (health 200, anonymous catalog 401, page 200).
- **C1 source check:** the eleven added columns and their interval columns exist in both CDC files with 2023 definitions. All are blank for every Kentucky (120 counties, 1,299 tracts) and Pennsylvania (67 counties, 3,408 tracts) area and nowhere else.
- **C1 code:** registries widened; `measure_set_sha256` added to release identity and to approval (`--measure-set-sha256`), because unchanged source bytes made a wider registry look like a duplicate; tract publication's hard-coded county row count replaced by 3,143 × measures; new `county_parent_measure_set` check.
- **Defect found and fixed while staging:** the tract `metadata_matches_active` check compared tract-file metadata with the active release, which during a county-then-tract rollout is the county-only parent (a different CDC file), so the first tract candidate `8c1be061-166c-4420-9b68-12d5773298a1` was held. The check now compares with the most recently published tract release. The held candidate is retained.
- **State-changing commands (staging only):** `cli fetch-stage-validate` (county candidate `6f265cd8-809b-402d-a7c2-415301f93ba9`, 8/8 checks, 40,859 observations); `review`; `approve-publish` with semantic `5cdc0b64…dea5`, schema `728eda33…64dc`, metadata `ae469fd6…fb28`, measure set `4184fbed…54a4`; `fetch-stage-validate --geography tract` twice (held candidate above, then `7bf96574-ac68-4d2f-9db8-95b07fbbf622`, 11/11 checks, 1,085,786 observations, 56,484 `not_published`); `review` (252 sampled tracts, 84 pages, 209,917,627 source bytes verified); `approve-publish` with semantic `2eebfa92…ca34`, schema `93a997e5…af34`, metadata `c3290529…02ac`; pointer drill `rollback f735c524…` then `rollback 7bf96574…`.
- **Verification:** 12 county cells and one tract's values for three measures equal the CDC API. All 6,286 county and 167,044 tract rows of the two original measures are identical between the old and new releases. After the drill only the PLACES pointer differs from the copy-time pointers. `lookup` on staging: 39 catalog measures; Person, Kanawha, and Fresno have 39 of 39 available; a Kentucky and a Pennsylvania county show 12 `not_published`; Person County returns 7 tracts for diabetes. Unit tests for PLACES, lookup, operations, and the community API pass (38). The full backend suite and an authenticated browser check of `/area/places-2025` with 13 measures were **not** run in this step.
- **Coordination:** Codex's API tests assert the original 28-measure example files, so those files were left unchanged and refreshed examples were added under `docs/beta/contract-examples/after-c1/`. Requests to Codex are in `docs/beta/status/claude.md`.
- **Unresolved / next:** promotion to live needs the same county-then-tract sequence, during which tract values are briefly unavailable. Next: C2 (ACS subject-table measures), then C3 (congressional districts).

## 2026-11-15T14:58:18+00:00 — X6 facility source citation and final staging recheck (Codex)

- **Correction/follow-up:** After the initial Gate 3 evidence entry, added each mapped facility block's published source release label and ID beside its count in county and district briefings. Commit `c714d3c` was merged into `beta` and deployed to staging. No live changes, migrations, or data publication.
- **Verification:** Frontend 149/149 and build passed. The complete authenticated X6 staging walkthrough passed again on `c714d3c`, including district, PDF, PLACES tracts, HRSA pointer clicks at both widths, mobile overflow, and contrast checks. The 47-check archived-source audit passed again and refreshed `deliverables/beta/gate3_source_samples.json`; active release IDs were unchanged. Deploy checks passed backend health 200, anonymous catalog 401, and page 200.
- **Status/next:** Product track is complete on staging; this documentation and report refresh remains to be merged/deployed. Gate 3 review by John is the next action. The handbook remains Claude-owned and was not edited; no live promotion was attempted.

## 2026-11-15T14:56:00+00:00 — X6 Gate 3 product walkthrough and source evidence (Codex)

- **Request/outcome:** Completed the remaining X6 work on `codex/beta-x6-gate3`: added district, expanded-measure, PLACES tract, insurance-definition, ACS source-map, ordinary HRSA pointer, keyboard, mobile, and contrast assertions to the repeatable staging walkthrough; refreshed seven review images; extended the source audit to 47 checks across eight products and WV-01. Merged/deployed code and images as `08ead46` to staging only; no live application, database, service, or deployment changes and no migrations or source publication.
- **Verification:** Authenticated staging walkthrough passed landing/search, 46 indicators in each showcase county, seven ACS and seven PLACES Person County tracts, three-county comparison/PDF, seven topics, district picker/WV-01 briefing (seven district estimates, 28 county links), ACS district source map, legacy/area/funding routes, HRSA Details pointer clicks at 1365 × 900 and 390 × 844, mobile overflow, browser errors, and sampled contrast. Frontend 149/149 and build passed; audit script syntax checks passed. The refreshed archive audit matched 47 raw values to release-linked SHA-256 source files, lookup-backed API, county profile/PDF, and district page; report `deliverables/beta/gate3_source_samples.json` records exact active release IDs, including PLACES `7bf96574…` and ACS community `d90070e6…`. The first audit attempt failed because the combined PLACES release holds county source pages under its reviewed parent; the script now follows that provenance. Early walkthrough timing/selector assertions were corrected, then the full check passed. The X5 full backend run remains 676 passed and one known unrelated FY2026 funding natural-key mismatch; no backend code changed in X6.
- **Files/state:** `frontend/scripts/beta-walkthrough.mjs`, `deliverables/beta/` screenshots, source-audit script/report/review guide, product status, and diary. Staging `beta` at `08ead46` before this documentation/evidence follow-up; deployment checks passed Alembic head, build, backend health 200, anonymous catalog 401, page 200. The handbook is Claude-owned under the beta plan and was not edited by the product track; this entry gives its next update the verified staging facts.
- **Unresolved/next:** Gate 3 product review by John is pending for the final staging commit. Live promotion is not approved or attempted; the separate runbook requires a fresh live recovery set and digest-matched publication. Rerun the source audit if any staging pointer changes.

## 2026-11-15T14:48:07+00:00 — X5 district briefing and expanded measures deployed to staging (Codex)

- **Request/outcome:** Merged current `beta` into the product branch, then built X5 against the C1–C3 published lookup contract. District API/page and state picker show seven Census-published WV-01 estimates, 347 mapped HRSA sites, 56 nursing homes, 60 TRI reporting facilities, and 28 named overlapping counties as context. Added ACS community source map with explicit 119th Congress district geography, and updated seven topic pages and county profile sections with C1/C2 measures and separate ACS/PLACES insurance definitions. Fixed the HRSA site-panel scroll layout so ordinary pointer clicks reach Details. Commits `4cedd3a` and `631a8ca` were fast-forwarded into `beta` and deployed to staging; no live changes, migrations, or published-data writes.
- **Verification:** Focused backend community tests 6 passed; frontend 148 tests and production build passed before the final CSS correction, and staging deploy rebuilt successfully afterwards. Full backend suite: 676 passed, one known unrelated FY2026 funding source natural-key mismatch. Authenticated staging browser: district picker found both West Virginia districts; WV-01 displayed seven indicators and 28 county links; ACS district map rendered 129 features in the tested viewport; normal HRSA Details clicks passed at 1365 × 900 and 390 × 844 with no document overflow. Staging deploy passed Alembic head, backend health 200, anonymous catalog 401, and page 200.
- **Files/state:** `backend/app/community`, community and map frontend pages/styles, focused tests, product status, and this diary. Staging `beta` code at `631a8ca` before this documentation follow-up. The handbook is Claude-owned under the execution plan; these staging facts are recorded here for its next update.
- **Unresolved/next:** X6 must run the complete district walkthrough, verify C1 PLACES tract rows and all 46 county indicators, refresh screenshots, and rerun the archived-source audit against current pointers. Gate 3 remains for John to review; no live promotion is approved or attempted.

## 2026-11-15T02:29:45+00:00 — C4 staging deploy and C5 beta handbook/browser handoff (Codex, data/platform track)

- **Outcome:** C4 commit `6993096` and C5 guide commit `0833d11` were each fast-forwarded into local `beta` by `infra/staging/deploy-staging.sh` and deployed to staging. Both deploys passed Alembic, Vite build, staging backend restart/health 200, anonymous catalog 401, and page 200. Live checkout `main` remained clean; live and staging `/api/health` returned 200. No live application, database, webroot, or service change; no staging source-data publication change.
- **C5 documentation:** rewrote the handbook's current beta route, staging-versus-live state, 46-measure and district data inventory, recovery status, deployment workflow, and next actions. Added authenticated staging follow-ups to the PLACES, USDA FEA, EPA AQI, and HRSA site guides; updated the [Claude status](beta/status/claude.md) with the remaining product-track work and Gate 3 hold.
- **Authenticated browser verification on staging:** all 13 PLACES measures rendered county polygons/table; a Person-area diabetes tract viewport rendered 49 table rows. All five USDA and five EPA AQI measures rendered; USDA national/tract messages, a county popup, and all three overlay toggles worked. Tables showed USDA Capitol CT `09110` as boundary-incomparable, Mayagüez PR `72097` outside Atlas coverage, Anchorage AK `02020` published; EPA Baltimore city `24510` median AQI 43/364 days, Capitol CT no reported value, Mayagüez median AQI 9/227 days with source spelling. USDA and EPA pages had no document overflow at 390 px. HRSA filter changes and keyboard Enter opened a populated site detail at desktop and mobile widths.
- **Failure/open product issue:** ordinary pointer click on the HRSA table “Details” button was intercepted by overlapping panel content at 1365 × 900 and 390 × 844. This needs a frontend fix and a fresh normal-click check; the Claude track did not edit Codex-owned frontend files. The repeat `frontend/scripts/beta-walkthrough.mjs` passed landing/search, profile, comparison/PDF, topics, source-map link, legacy/area/funding pages, About/Methodology, and mobile routes; its district leg only prints a stale C3-pending message. X5 district page/search, expanded-measure presentation, refreshed source audit, and meaningful district walkthrough remain with the product track.
- **Publication/deployment/next:** C1–C3 data remain on staging only (eleven pointers); the C4 recovery set is a verified local live baseline, and the runbook is a draft. No promotion was attempted. Gate 3 requires product fixes, John's review and approval of a specific beta commit, a fresh live backup, and digest-matched live ingest. An independent encrypted off-VM backup remains outstanding.

## 2026-11-15T02:27:23+00:00 — C4 fresh local recovery set and promotion preparation (Codex, data/platform track)

- **Request/outcome:** Resumed the approved beta execution plan from Claude's C3 handoff. Created `/home/john/chip-recovery/20261115T011923Z/`, a new private pre-beta live recovery set. The live database was only read by `pg_dump`, source-manifest queries, and validation SQL; no live application, database, service, webroot, or checkout changes were made.
- **Set contents:** 11,605,083,277-byte consistent PostgreSQL custom dump (20m29s), 1,690 TOC entries, password-free role definitions, live code/config and deployed-webroot snapshots, raw-ingest archive, 1,405 published source files verified inside that archive (1,830 release-source references), and manifest/checksums. All ten live pointers and Alembic `c8f1e4a7d3b6` were captured. Expanded `backend/scripts/chip_recovery/restore_validation.sql` with counts for the currently active AHRF, CLH, EPA AQI, CMS GV, USDA FEA, HRSA, TRI, and nursing-home products; its 66-line live baseline was read-only.
- **Restore verification:** a network-isolated temporary PostGIS 16 container restored the dump with `--exit-on-error` in 42m40s and an empty error log. All 66 restored validation lines matched the live baseline byte for byte; final manifest says `restore_test: passed`, and all 37 final SHA-256 checks passed. The temporary container and volume were removed; root free space returned to about 205 GiB. The first final-manifest pass failed because the temporary test script used nonstandard marker names and placed a checksum log inside the set; corrected the names, removed that transient log, rebuilt the manifest, and reran all checks without a restore retry.
- **Files/next:** added the [C4 recovery guide](../backend/docs/chip_beta_c4_recovery_set.md), corrected the older guide's current-state note, and tightened the [promotion runbook](beta/PROMOTION_RUNBOOK.md) for the live PDF URL, Census key availability, source-audit gate, and district/HRSA checks. A fresh Gate 3 backup is still required before promotion; an independent encrypted off-VM copy and credential-recovery process remain outstanding. This entry precedes the C4 commit and staging documentation deploy.
- **Timestamp note:** the existing C1/C2/C3 entries stamped 15:30 and 17:40 UTC on this date are later than this VM's current UTC clock. Their history was preserved; the staging releases were checked directly in this session.

## 2026-11-15T02:20:00+00:00 — `main` and `beta` pushed (John); live checkout switched to `main` (Claude)

- John fast-forwarded and pushed `main` to `0195959` and pushed `beta` at `1e859e6`; verified with `git ls-remote`. `main` now contains the HRSA, TRI, nursing-home, CMS GV, and USDA FEA work that was already deployed.
- `git checkout main` in `/home/john/places-app` (same commit as before, no file changes); live `/api/health` returned 200. No application, data, or deployment change.
- Staging database copy still running (60 GB of about 70). Next: finish staging, then stage and publish the wider PLACES release there.

## 2026-11-15T01:10:00+00:00 — Beta Phase 0: staging files, single-place read module, data contract, coverage matrix (Claude)

- **Outcome:** on branch `claude/beta-phase0` (local only): staging environment files, `app.area_pilot.lookup`, the [data contract](beta/DATA_CONTRACT.md) with real examples, and the [coverage matrix](beta/COVERAGE_MATRIX.md). No live application, data, or deployment change. Codex can start its API and pages against the contract examples.
- **Hazard found and fixed:** `backend/alembic.ini` hard-codes the live database and `alembic/env.py` ignored `DATABASE_URL`, so a migration run from any worktree would have changed live. `env.py` now uses `DATABASE_URL` when it is set. The live service sets none and behaves as before.
- **Staging (in progress):**
  - Created database `places_staging` and started `pg_dump -Fc places | pg_restore` into it (read-only on live; 70 GB, half of it `usaspending_fed_account.fact_award_account_breakdown`). Still running at the time of this entry.
  - Installed `/etc/systemd/system/places-backend-staging.service` (not started, not enabled) and Nginx site `places-staging` on port 8080 (`nginx -t` passed, reloaded). Port 8080 has no UFW rule. Live `/api/health` returned 200 afterwards.
  - Wrote `backend/.env` in `chip-beta`, `chip-claude`, and `chip-codex` with `DATABASE_URL` for `places_staging` and newly generated staging-only demo-access secrets (not printed, not committed). Built virtual environments in `chip-beta` and `chip-claude` and `node_modules` in `chip-beta`.
  - `infra/staging/deploy-staging.sh [branch]` merges into `beta` without force and deploys; it refuses unless `DATABASE_URL` ends in `/places_staging`. Not yet run.
- **`area_pilot/lookup.py`:** `catalog`, `area_info`, `area_values`, `national_reference`, `county_tract_values`, `area_facilities`. Active releases only; no aggregation; areas without a stored row get the same read-time status as the product's map API, or `not_in_release`.
  - Verification: 9 unit tests pass. Read-only run against the live releases: 28 measures in the catalog; Etowah County returns 28 rows in 0.05 s and 10 health center sites, 6 nursing homes, 10 TRI reporting facilities in 0.1 s; Connecticut, Puerto Rico, and DC return the expected distinct statuses; state level returns ACS and CMS only.
  - Not yet verified on staging; full backend suite not run for this change.
- **Coverage findings:** 586 counties have all 28 released measures (EPA AQI is the limit). No released chronic-disease measure exists yet. Showcase counties chosen: Person NC `37145`, Kanawha WV `54039`, Fresno CA `06019` (28 of 28 each).
- **Corrections to the plan** (made in `docs/beta/EXECUTION_PLAN.md`): `/api/area/*` is stripped to `/area/*` by Nginx, so the community router needs prefix `/community` and no Nginx change; `gh` is not signed in on the VM, so "pull requests" into `beta` are local merges through the deploy script.
- **Unresolved:** `main` and `beta` are not pushed (blocked by session policy). No staging access code yet.
- **Next action:** when the copy finishes, analyze the database, start the staging service, run the first staging deploy, recheck `lookup` there, then begin C1 (PLACES expansion).

## 2026-11-15T00:57:41+00:00 — X6 core walkthrough and Gate 1 source evidence on staging (Codex)

- **Request/outcome:** Continued the approved beta plan after the staging copy completed. Added About and methodology pages, release listings, shareable source-map links that preserve measure and view, a repeatable staging Playwright walkthrough, and five review screenshots. Deployed X6 commits `528e7f1` and `7ff78fd` to local `beta` and staging only. No live application, database, or deployment changes; no source-data writes.
- **Verification:** Frontend 148/148 tests and Vite build passed. Authenticated staging walkthrough passed landing/search, three showcase profiles, seven ACS Person County tract shapes, three-county comparison, PDF, topics and source-map selection, shareable map reopening, About/methodology, legacy map, seven area pages, funding, keyboard skip link, and five mobile routes without document overflow or page errors. Anonymous community API returned 401. Person PDF returned 200, nine pages, source text, and no empty print-only tract section.
- **Gate 1 source evidence:** `deliverables/beta/verify_source_samples.py` checked ten indicators per showcase county across all seven active area products. Thirty values matched release-linked archived files with verified SHA-256, the staging API, profile page, and PDF. The point-in-time report and review images are in `deliverables/beta/`. The current PLACES active release still returns zero Person County tracts; ACS returns seven.
- **Unresolved/next:** Gate 1 is ready for John's staging review. Recheck the source report after any publication. X5 district API/page and the X6 district walkthrough await C3's district release and lookup contract; C1/C2 publication will require topic-list updates and tract recheck. Staging deploys still require `VITE_API_BASE_URL=/api` until Claude makes the default durable; PDF needs a live-appropriate frontend URL at promotion. The handbook is Claude-owned by the execution plan; this entry records the changed staging state for its next update.

## 2026-11-15T00:39:47+00:00 — X4 topics and tract patterns deployed to staging (Codex)

- **Request/outcome:** After confirming the staging copy had ended successfully, continued the approved beta product track. Added `/topics` and seven topic detail pages with source-published measure descriptions, limits, and links that preselect the measure on its source map. Added a release-pinned within-county tract map to the county profile. Merged `e08e290` into local `beta` and deployed staging only; no live application, database, or deployment changes.
- **Verification:** Frontend 147 tests and Vite build passed. Authenticated Nginx and browser checks showed seven topic cards, six food-environment measures, successful map measure preselection, and seven ACS tract polygons for Person County from the same active release as the profile. No browser errors or mobile document overflow. Direct staging API checks confirmed ACS seven tract rows and PLACES zero under its current county-only active release; the UI gives an explicit PLACES empty state.
- **Files/state:** Product UI and route files under `frontend/src/community`, `frontend/src/main.jsx`, `frontend/src/pages/Places2025Pilot.jsx`, and route resolver. Staging `beta` at `e08e290`. No migrations or source data changed. The handbook remains Claude-owned under the execution plan; these operational facts are recorded here for Claude to fold into it.
- **Unresolved/next:** Recheck the PLACES tract view after C1 publishes a combined release. Add C1/C2 measures to topic definitions after publication. X5 district data depends on C3; proceed with independent X6 walkthrough and polish meanwhile.

## 2026-11-15T00:31:20+00:00 — X3 comparison and PDF briefing deployed to staging (Codex)

- **Outcome:** On `codex/beta-x3-comparison-pdf`, added `/compare?counties=…` with up to four aligned county columns, URL state, county search, distinct missing-status display, and no ranking or score. Added `/api/community/county/{geoid}/pdf`, reusing the existing Playwright profile renderer with the validated demo-session cookie. Added print layout for the profile. Merged `ab5dbcb` to `beta` and deployed staging only; no live changes.
- **Configuration:** Set `PROFILE_FRONTEND_BASE_URL=http://127.0.0.1:8080` in the ignored staging backend `.env` (mode 600), so the PDF renderer opens staging. `VITE_API_BASE_URL=/api` was supplied to the staging build. These settings need durable staging configuration and a live-appropriate PDF URL at promotion; no secrets were recorded.
- **Verification:** Backend 656 tests passed with two unrelated source-dependent acceptance cases deselected (one has the documented FY2026 natural-key mismatch). Frontend 146/146 tests and Vite build passed. Authenticated Nginx comparison of Person NC, Kanawha WV, and Fresno CA displayed 28 aligned indicator rows, no page errors, and a horizontally scrollable table without document overflow at 390 px. Authenticated PDF returned 200 (107,961 bytes, nine pages); extracted text included Person County, `$63,300` income, source lines, and no access gate.
- **Unresolved/next:** Gate 1 archived-source checks (ten indicators per showcase county) and broader legacy-route regression remain. C1's active staging PLACES county release still has no tract rows; X4 tract patterns depend on its combined release. Continue X4 topic pages and tract views while coordinating the data dependency through status files.

## 2026-11-15T00:25:20+00:00 — X2 landing and county profile deployed to staging (Codex)

- **Outcome:** Merged X2 (`9f4cd4b`, then unit-display correction `8cd7412`) to `beta`; staging backend and webroot deployed. Root is now the place-first landing, `/explore/map` serves the legacy map, and `/community/county/{geoid}` shows released indicators, source period/population/release, uncertainty, state estimates only where published, facility inventories, CSV, and limitations. PDO brand tokens follow the supplied guide. Topic cards lead to existing source maps until X4.
- **Verification:** Frontend suite 144/144 passed and Vite build passed. Through authenticated staging Nginx, the landing rendered seven topic cards; search opened Person County; its profile rendered 28 indicator cards; the legacy map loaded at `/explore/map`; desktop and 390 px mobile had no page errors or horizontal overflow. Visual review found unit formatting problems; correction `8cd7412` now displays ACS income as `$63,300`, percentages with `%`, and long units on a separate line. Focused format tests and rebuild passed after that correction.
- **Staging setting:** The first X2 bundle used the fallback browser `localhost:8000` because the staging build had no `VITE_API_BASE_URL`. Redeployed with `VITE_API_BASE_URL=/api`, then the browser walkthrough passed. Claude-owned deploy script needs that staging default made durable before future unqualified deploys.
- **No live change. Unresolved:** C1's current staging PLACES county pointer still has no tract rows; X4 tract patterns depend on the combined release. Comparison and PDF remain X3. Next: X3 comparison and PDF on a separate branch.

## 2026-11-15T00:21:02+00:00 — Staging restored; X1 deployed; X2 underway (Codex)

- **Request/outcome:** Verified the `places_staging` restore ended with `exit=0`; staging backend is active and `/api/health` returned 200. Read-only staging lookup found 10 active releases, 28 county indicators for Person County NC (`37145`), and mapped facility counts of 4 HRSA sites, 2 nursing homes, and 6 TRI reporting facilities. Merged X1 (`6f76e0d`) into `beta` with `infra/staging/deploy-staging.sh`, which ran Alembic, built the frontend, restarted staging, and passed its health, anonymous 401, and page checks. No live changes.
- **Authenticated check:** Created a staging-only demo code in staging DB (ID 22), stored plaintext outside the repository at `/home/john/.local/share/chip/staging-beta-access-code` (directory 700, file 600; no code in documentation). Through Nginx on port 8080, validation and the community catalog, Person County profile, three-county comparison, facilities, search, topics, and CSV returned 200. Person profile had 28 values and six source-published state values.
- **Data dependency:** The staging PLACES pointer moved during C1 to county release `6f265cd8-809b-402d-a7c2-415301f93ba9`, so `lookup.county_tract_values` returned zero Person County rows; retained tract releases each contain seven. Codex left the pointer untouched. Claude's C1 combined-release publication must restore tract availability before the tract-pattern UI is verified.
- **X2 progress:** On `codex/beta-x2-landing-profile`, built the new landing, county search and profile, navigation to `/explore/map`, source and uncertainty display, facility lists, CSV link, and PDO tokens. Topic cards currently lead to existing maps; topic pages are X4. Frontend verification: 144/144 tests and Vite build passed after updating a route test for the intentional home change. X2 is not yet merged or deployed; browser review remains.
- **Next action:** Commit and deploy X2 to staging, run an authenticated browser walkthrough, and continue X3. Recheck the PLACES pointer after C1 completes.

## 2026-11-14T23:56:16+00:00 — Began X1 community API while staging copy continues (Codex)

- **Request/outcome:** John asked whether the beta plan could start now. C0.5 and the data contract were merged to `beta`, so the Codex product track began on `codex/beta-x1-community-api` while the staging restore continued. Added `/community` routes for county search, catalog, release-pinned county profile, comparison of up to four counties, facilities, tract values, seven topic descriptions, and county indicator CSV. Routes read published indicator and facility data through `app.area_pilot.lookup`; the existing county-name search handles names only.
- **Files affected:** `backend/app/community/{router.py,topics.json}`, router registration in `backend/app/main.py`, `backend/tests/test_community_api.py`, and `docs/beta/status/codex.md`. No migrations, live application changes, database writes, or deployments.
- **Verification:** Community and lookup tests: 13 passed. Full backend suite after linking the worktree's ignored local `data/recon` inputs to the live checkout for read-only test use: 655 passed, two source-dependent failures. With the ignored `data/chipfunding` folder linked for read-only use, the known `test_all_six_real_source_years_match_acceptance_totals` failure was confirmed (FY2026 source natural-key mismatch); the other source-directory acceptance test was interrupted to avoid competing with the staging index build. Staging restore still ran at about 64 GB of 70 GB, building an index; no staging API verification yet.
- **Next action:** Finish the restore and staging service, run X1 against staging, then merge and deploy this branch to `beta`; continue X2. The seven topic descriptions are initial product copy and need C1/C2 measure additions when those releases publish.

## 2026-11-14T23:48:45+00:00 — Beta execution gate check (Codex)

- **Request/outcome:** Checked whether the staging database copy had finished before running the beta execution plan. It was still restoring: `places_staging` was 58 GB versus 70 GB for `places`, and `pg_restore` was running. The staging backend was inactive and `/api/health` on port 8080 returned 502. The product data contract was already merged into local `beta`, so X1 is ready for independent development once work resumes.
- **Verification:** Read the plan, handbook, recent diary, both track status files, data contract, relevant router and lookup code; checked worktree state, database sizes, process state, and staging HTTP health. No application, database, deployment, or live checkout changes were made.
- **Next action:** Confirm `pg_restore` exits successfully, validate staging, then start the next Codex product package in `/home/john/chip-codex`.

## 2026-11-14T23:40:00+00:00 — Funder beta plan approved; Phase 0 git base and repository setup (Claude)

- **Decision:** John approved the [funder beta execution plan](beta/EXECUTION_PLAN.md): community profile, comparison, topics, exports, wider PLACES and ACS measures, and congressional district briefings in about 4–6 weeks. Claude takes the data and platform track, Codex the product track, on a staging copy with three review gates. New pages follow the PDO Brand & Style Guide v1.0.
- **AHRF branch check (read-only):** `codex/ahrf-county-five-measures` is not an ancestor of the deployed stack, but all 39 files it changed are present there: 30 byte-identical, 9 with later edits from the products added afterwards. Nothing is unmerged.
- **State-changing commands:** created local branch `beta` at `0195959` and worktrees `/home/john/chip-beta` (`beta`), `/home/john/chip-claude` (`claude/beta-phase0`), and `/home/john/chip-codex` (`codex/beta-start`). The live checkout was not modified.
- **Changes on `claude/beta-phase0`:** `frontend/src/config/apiBase.js` is now tracked (the `config/` ignore rule gets an exception; the file holds no secrets), which closes the clean-checkout gap; `.gitattributes` merges this diary by union; `AGENTS.md` gains the two-agent ownership rules; `docs/beta/` holds the plan and status files.
- **Not done:** fast-forwarding and pushing `main`, and pushing `beta`, were blocked by this session's permission policy. `main` and `origin/main` are still `e35aee2`. No staging environment exists yet. No application, data, or deployment changes were made.
- **Next action:** John fast-forwards and pushes `main` and pushes `beta`; then C0.3 (staging), C0.4 (coverage matrix), C0.5 (`area_pilot/lookup.py` and data contract).

## 2026-11-14T22:55:00+00:00 — USDA FEA commit and push (Claude)

- Commit `cd21d55` (application, migration, tests, operator guide, inventory, handbook, diary) pushed as new branch `origin/claude/usda-food-environment-atlas` without force; `git diff --cached --check` passed. No application, data, or deployment changes in this step. Not merged to `main`. The authenticated browser check remains pending.

## 2026-11-14T22:50:00+00:00 — USDA Food Environment Atlas five county measures published and deployed (Claude)

- **Objective/outcome:** Added the USDA ERS Food Environment Atlas as the independent shared area product `usda_ers_food_environment_atlas`. It has five county-only measures and its own release pointer, and is published and deployed at `/area/usda-fea`.
  - The legacy `usda_food_env.*` integration was inspected and not run. Its tables and `/api/usda/food-environment/*` routes are unchanged; only the main-map option label changed, to "legacy import, all variables".
  - The weekly timer, backups, access controls, and funding methodology were not changed. The Codex sibling worktree was not touched.
  - **Not completed:** the authenticated browser check. See *Verification* below.
- **Source verified:**
  - The downloads page's "Current Version" CSV ZIP is `/media/5570/food-environment-atlas-csv-files.zip?v=40916`, "Last Updated 7/30/2025". The readme says the "original release date of this file is July 2025", and the ZIP member timestamps are 2025-07-30.
  - The landing page ("Updated 8/12/2026") and the documentation page ("Updated 7/28/2026") are page revisions, not a new data release.
  - ZIP SHA-256 `99750f54…3b8d` (6,501,079 bytes); `StateAndCountyData.csv` `03aa52c9…cd`: 957,753 rows and 304 variables.
  - The files contain no state rows. State-level `*` variables repeat on county rows.
  - Documentation confirms `-9999`/N/A (not available) and `-8888` (county did not exist), and the 5-year boundary policy with CT and Valdez-Cordova exceptions.
- **Measures and periods:**
  - `PCT_LACCESS_LOWI19` (2019): the denominator is the total county population, not low-income residents.
  - `SNAPSPTH23` (2023).
  - `WICSPTH22` (2022).
  - `FMRKTPTH18` (2018).
  - `PCT_LACCESS_HHNV19` (2019): housing units; substituted for grocery density.
  - **Substitution reason:** `GROCPTH20` duplicates the published CLH `CCBP_SOGS_RATE` (same CBP NAICS 445110 per-1,000 concept, 2023), and 909 of 3,144 counties are `-9999`. `DSPTH20` is mislabelled "Dollar stores" (it covers NAICS 452319) and was not used.
- **Geography and coverage:**
  - Matched 2024 TIGER counties: 3,135 (3,144 for farmers' markets).
  - Documented source-only rows, staged with reasons: the 8 former CT counties, Valdez-Cordova, and for 2018 also Wade Hampton, Shannon, Bedford city, and 5 FIPS-less Alaska "Area" rows.
  - Read-time statuses: 9 CT planning regions as `boundary_not_comparable` for four measures, and 78 PR municipios as `not_covered`. No unexplained mismatches.
  - Status counts:
    - Low-income access: available 3,094, zero 39, n/a 2.
    - SNAP: 3,114 and 21.
    - WIC: 3,028 and 107.
    - Farmers' markets: 2,259, zero 872, n/a 2, did-not-exist 11.
    - No-car access: 3,121, zero 12, n/a 2.
- **Changes:**
  - Registry `usda_fea_2025.json`; modules `usda_fea.py`, `usda_fea_cli.py`, `usda_fea_api.py`; router dispatch.
  - Additive migration `c8f1e4a7d3b6` (`stage_usda_fea`, `observation_usda_fea`, immutability triggers).
  - Frontend: `/area/usda-fea` branch in `Places2025Pilot.jsx` and CSS, route, main-map option and relabel.
  - Unit and PostGIS lifecycle tests; frontend tests.
  - Operator guide `backend/docs/chip_usda_food_environment_atlas.md`; inventory child record `usda-food-environment-atlas` (now 98 records); handbook.
- **State-changing commands:**
  - `alembic upgrade head` (`b7e3c5a9d2f4` → `c8f1e4a7d3b6`).
  - `usda_fea_cli fetch-stage-validate` twice: ready candidate `28a4824f-d403-454b-bc85-998fdd64bf92` (7/7 checks, 15,684 observations), then a duplicate.
  - `review`, then `approve-publish` at 22:28:55Z (semantic `d15804aa…3343`, schema `23b4ddb1…56d9`, metadata `89722389…8ed6`).
  - Pointer drill: `deactivate`, a refused rollback to the CMS GV release, then `rollback 28a4824f…`. All ten pointers were identical afterwards.
  - Webroot backed up to `data/deploy-recovery/usda-fea-20261114/webroot-before/`, then `rsync -a --delete frontend/dist/ /var/www/places/`.
  - `sudo -n systemctl restart places-backend` at 22:29:13Z.
- **Verification:**
  - Backend:
    - 24 unit tests covering sentinels, lookup changes, ZIP safety, parsing, boundary classification, and API selection.
    - 1 isolated PostGIS lifecycle test covering idempotency, failed retrieval, unexplained geography, undocumented values, source-total change, same-label revision hold and release, publication isolation, rollback and deactivate, immutability, the 413 cap, and map/legend/table parity.
    - Focused area tests 175/175. Full suite: 643 passed, 1 failed (the known `test_all_six_real_source_years_match_acceptance_totals`).
  - Frontend: 141/141, including sentinel colours and text, county-at-national-view, exact selection across zooms, and map/table parity. The build passed with the existing chunk-size warning.
  - Review re-derived all observations. An independent check of 54 cells against both the archived CSV and the separate XLSX had 0 mismatches. All 15,684 values equal the legacy raw values.
  - In-process router checks: 32/33. The single failure was my wrong expected literal (`13.02099800`); the CSV text is `13.020998`, which is what is stored. They covered:
    - all five measures with national parity;
    - state, tract, and release-year requests refused;
    - CT, PR, and Alaska statuses;
    - Kalawao not available rather than zero;
    - the full world view of 3,222 counties within the cap.
  - Regression: 21/21. All ten catalogs are on unchanged pointers; HRSA, TRI, and nursing-home maps work; CMS GV and AQI work; legacy USDA variables, map, legend, and county detail work; funding map and legend return 200.
  - Nginx: anonymous FEA catalog, map, legend, and table return 401; pages return 200; the deployed bundle contains the new product.
  - Benchmarks: national desktop viewport map 3.3 s / 1.8 MB, legend about 0.2 s, table 0.12 s; local views 15–37 ms.
  - **The authenticated browser check was not performed.** The scripted run, which would mint a temporary demo code from backend secrets and deactivate it afterwards, was blocked by this session's permission classifier. No code was created.
- **Git/next action:** Committed on new branch `claude/usda-food-environment-atlas` (from `75df32a`) and pushed without force; see the next entry for the push outcome. Not merged to `main`.
  - Next: an operator runs the authenticated browser checklist in the guide.
  - Separately: add USDA FEA to a fresh recovery set; decide on historical backfill, tract products, and legacy retirement.

## 2026-11-14T22:01:00+00:00 — CMS OM GV commit and push (Claude)

- Commit `3a98647` (application, migration, tests, operator guide, inventory, handbook, diary) pushed as new branch `origin/claude/cms-geographic-variation` without force; `git diff --cached --check` passed. No application, data, or deployment changes in this step. Not merged to `main`.

## 2026-11-14T21:58:00+00:00 — CMS Original Medicare Geographic Variation 2024 shared product published and deployed (Claude)

- **Objective/outcome:** Added CMS Original Medicare Geographic Variation (OM GV) as an independent shared area product, `cms_om_geographic_variation`. It has five 2024 measures at state and county level for the `All` age category, with its own release pointer. Published, deployed, and browser-verified. The legacy `cms.gv_*` integration was inspected and not run; its tables, routes, and behavior are unchanged, and only the main-map selector label changed. The weekly timer, backups, access controls, and funding methodology were not changed. The Codex sibling worktree was not touched.
- **Source verified:**
  - CMS catalog series `6219697b-…`, modified 2026-05-15, temporal 2024; methods paper "May 2026 Update" (data 2007–2024).
  - CSV `2014-2024 … Public Use File.csv`: 57,865,948 bytes, SHA-256 `10c83040…6fad`, 36,994 rows, latest `YEAR` 2024. The data API showed no 2025 rows; its totals (36,994; 3,253 for 2024/All) and 7 sampled cells match the CSV.
  - Dictionary and methods PDFs archived with checksums.
- **Variables:** `BENES_OM_CNT`, `TOT_MDCR_STDZD_PYMT_PC`, `IP_CVRD_STAYS_PER_1000_BENES`, `ER_VISITS_PER_1000_BENES` (CMS term "Emergency Room"), and `ACUTE_HOSP_READMSN_PCT`. The readmission denominator is index admissions discharged alive.
  - `_PCT` fields are 0–1, verified from methods tables: female 54.6% ↔ `0.546`, OM count 27,732,177. Values are stored as published and multiplied by 100 only for display.
  - The suppression code is `*` (<11). The earlier inventory note about "." was not supported and was corrected.
  - **Documentation conflict:** the methods paper mentions health-status adjustment; the catalog says standardization does not adjust for health status. CHIP never labels the measure risk- or inflation-adjusted.
- **Geography:**
  - Matched 52 states (50, DC, PR) and 3,143 counties (CT planning regions already in source); the national row is reference only.
  - Excluded: VI state and 3 VI counties (no CHIP boundary), the `Territory` and `ZZ` state aggregates, and 51 `XX000` unknown-county rows.
  - DC county 11001 and 78 PR municipios have no CMS county row and show "not published". No unexplained mismatches.
  - Suppressed matched-county values per measure: 2/2/13/3/146. Six true-zero county readmission rates.
- **Changes:**
  - Registry `cms_om_gv.json`; modules `cms_gv.py`, `cms_gv_cli.py`, `cms_gv_api.py`; router dispatch.
  - Additive migration `b7e3c5a9d2f4` (`stage_cms_gv`, `observation_cms_gv`, immutability triggers).
  - Frontend `/area/cms-gv`: state below zoom 6, counties from zoom 6, an explicit no-tract message, a national reference line, and distinct status swatches. Main-map selector: a new entry plus the legacy option relabelled "legacy import, through 2023".
  - Tests; operator guide `backend/docs/chip_cms_om_geographic_variation.md`; inventory row `cms-original-medicare-gv` updated in place (still 97 records); handbook.
- **State-changing commands:**
  - `alembic upgrade head` (`a4d9e7c2b6f1` → `b7e3c5a9d2f4`).
  - `cms_gv_cli fetch-stage-validate` twice: ready candidate `73d93c74-7d59-4723-a862-25ecf7a6bc92` (12/12 checks), then a duplicate.
  - `review`, then `approve-publish` at 21:47:59Z (semantic `1b5e4e68…5800`, schema `48209de5…325b`, metadata `25a54bab…9fc1`).
  - Pointer drill: `deactivate`, a refused rollback to the AQI release, then `rollback 73d93c74…`. All nine pointers were rechecked.
  - Webroot backed up to `data/deploy-recovery/cms-om-gv-20261114/webroot-before/`, then `rsync -a --delete frontend/dist/ /var/www/places/`.
  - `sudo -n systemctl restart places-backend` at 21:48:25Z.
  - Three temporary demo codes (ids 19–21, `agent-verification-cms-gv-20261114`) were created and deactivated, each used once; no plaintext was printed or stored.
- **Verification:**
  - Backend: 16 unit tests and 1 isolated PostGIS lifecycle test covering idempotency, same-label revision hold and release, failed and unexplained candidates, pointer isolation, rollback, immutability, and API parity. 153/153 focused area and CMS tests passed. Full suite: 618 passed, 1 failed (the known `test_all_six_real_source_years_match_acceptance_totals`).
  - Frontend: 139/139; the build passed with the existing chunk-size warning.
  - Review re-derived all 15,980 observations; an independent CSV-to-DB check of 50 cells had 0 mismatches. An update to a published row was refused.
  - Authenticated Nginx browser check: 88/88. It covered all five measures at both levels, legacy CMS selector and routes, the HRSA, TRI, and nursing-home overlays, six shared catalogs, and the 390-pixel layout. Funding map/legend returned 200, and anonymous CMS GV routes returned 401.
  - Benchmarks: national states 0.55–0.61 s; national counties 3.1–4.3 s / 1.8 MB, comparable to the AQI national county view at 3.1 s; local county views 16–18 ms.
- **Git/next action:** Committed on new branch `claude/cms-geographic-variation` (from `ed42254`) and pushed to `origin` without force; the push outcome is recorded in the next entry. Not merged to `main`. Next: decide on merging the stacked branches, add GV to a fresh recovery set, and decide on legacy CMS retirement separately.

## 2026-11-14T20:39:45+00:00 — CMS nursing-home integration commit and push (Codex)

- **Objective/outcome:** Complete the requested Git handoff for the CMS nursing-home integration documented below. Commit `115733d` includes application, migration, tests, source inventory, operator guide, handbook, and diary; pushed to `origin/claude/epa-tri-facilities` without force. No new application, database, or deployment changes were made in this handoff step.
- **Verification/next action:** Staged diff passed `git diff --cached --check`; the push succeeded. This diary outcome entry follows that commit and will be pushed separately. The published release and deployed service are unchanged. Future refreshes remain manual with reviewed checksums; merging the branch is a separate decision.

## 2026-11-14T20:37:30+00:00 — CMS Nursing Home Provider Information integrated, published, and deployed (Codex)

- **Objective:** Add CMS nursing homes as an independent optional point overlay with certified beds, four published star ratings, facility characteristics, filters, accessible table/detail, and source limitations. No geographic averages, vacancy estimates, inspections, penalties, staffing-hour measures, timer, backups policy, access controls, or funding methodology changed.
- **Official source:** CMS Provider Information dataset 4pq5-n9py; metadata identifies the complete October 2026 CSV, released 2026-10-28 with processing/modified date 2026-10-01. Archived 9,218,563-byte CSV SHA-256 ab70309ae6f0ee86b19fe9acb61a6d2953f970d3b09e80bb9b090e4b19ce35a2, metadata JSON, CMS API count, and October 2026 dictionary PDF. The PDF defines CCN as six-character text and one row per nursing home. CCN is preserved with leading zeroes. Public access is recorded in CMS metadata.
- **Coverage and semantics:** 14,686 unique CCNs across 50 states, DC, Puerto Rico (9), and Guam (1). 13,878 points mapped; 808 CMS footnote-22 ZIP-based coordinates retained but excluded. There are 91 colocated mapped coordinate groups. Overall/health inspection/staffing/QM missing ratings: 126/126/203/198, with CMS footnotes retained; 11 certified-bed values missing. Stars remain 1–5 or unrated, never zero or averaged. The processing date is not a common observation year; certified beds do not imply vacancy. SSA county code is not treated as Census FIPS.
- **Changes:** Registry cms_nursing_homes.json; source, CLI, and read API modules; additive migration a4d9e7c2b6f1 with staged raw rows, typed point rows, indexes, and published immutability triggers; route include; NursingHomes.jsx, area-map integration, CSS, tests, source-inventory child record (97 records now), CMS operator guide, and handbook. The independent active release pointer is cms_nursing_home_provider_info.
- **Publication:** Migration applied. Candidate 13e56c1b-320f-4217-8955-8bb813055216 passed six checks, full four-archive/raw/read-model review, and checksum-bound publication at 20:11:30Z. Semantic/schema/metadata/keyset SHA-256 respectively: fa4830eddcf4b5923058aa134b1bd27f54ea3301b7e64304a156bde4cb20c765 / 20436b3a028cdb5150065366040fe53c6a6c8487e1e4a302ae3e88e4736cca52 / e635990727468df71b3b96f07312f3e13bda95c4cfd75fe29c12fb560b1dfe72 / 556beb0dc75aa275a5ef9be4b8a3a648ba2873c081da89b5f79efb8d1baa0e9b. Re-fetch recorded a duplicate. A live deactivate/rollback drill restored the exact eight pointers; cross-product rollback and published-row mutation were refused.
- **Tests:** Focused backend suite 84/84 including isolated PostGIS idempotency, same-label semantic and metadata holds, failed-candidate preservation, and pointer recovery. Full frontend suite 136/136, including rapid-filter debounce regression. Production build passed with the existing bundle-size warning. Git diff check passed. Authenticated Nginx browser verified rated and unrated details, all five attributes, footnotes, Care Compare link, ownership/provider/overall filters, cluster click to points, keyboard table detail and focus, rapid overlay switching, 390-pixel layout, and no page errors. CMS map/table parity: unrated national 118; NYC points 589; filtered Los Angeles 35. High-zoom national request returned 413. Anonymous CMS routes returned 401. Existing five area catalogs, HRSA/TRI catalogs and maps, PLACES map, and funding map/legend returned 200 on unchanged pointers. Warm local CMS national clusters: 67 ms, 8.5 KB; Los Angeles points: 34 ms, 318 KB.
- **Deployment and fixes:** Backed up the previous webroot to data/deploy-recovery/cms-nursing-homes-20261114/webroot-before, installed the build under /var/www/places, and restarted places-backend. The initial restart without sudo failed for interactive authentication; sudo noninteractive restart succeeded. Browser inspection exposed a collapsed wide table; fixed panel scrolling and redeployed. A rapid 14-checkbox sequence then temporarily exhausted the backend database pool and caused 500s; added 400 ms filter debounce and explicit CMS API session close, redeployed, and restarted. The repeated sequence sent two map requests total, resolved to 4,223 filtered facilities and 50 table rows, and left health at 200 with no new pool errors. Temporary demo verification codes were deactivated; no credentials were committed.
- **Git/next action:** Intended code and documentation commit and push are pending at this entry. After push, record its outcome. On the next CMS release, refresh manually with the operator guide; keep auto-publish off and review any hold before moving this product's pointer.

## 2026-11-14T19:16:00+00:00 — EPA TRI reporting-facility point overlay integrated, published, and deployed (Claude)

- **Agent/objective:** Claude implemented CHIP's second point layer, EPA Toxics Release Inventory reporting facilities with reported chemicals, reusing the HRSA point-layer framework. The Codex sibling worktree (`codex/ahrf-county-five-measures`) was not touched.
- **Source/year/status:**
  - EPA TRI basic data file, national, **reporting year 2024**; the page states forms "processed as of November 5, 2025" (page last updated 2026-01-28).
  - The RY2025 URL returned HTTP 404. EPA's preliminary-dataset page also calls 2024 the most current year.
  - Treated as the latest complete annual basic file, subject to EPA revision, and **not** the frozen National Analysis dataset.
  - CSV SHA-256 `06dfa3a6…1506` (60,550,684 bytes); retrieved 19:01:48Z.
  - The documentation PDF is the August 2024 edition ("Updated for RY 2023"); the RY2024 header was reviewed exactly.
- **Grain and findings:**
  - 77,295 forms (unique `DOC_CTRL_NUM`; 68,567 Form R, 8,728 Form A) and 21,482 facilities (TRIFD).
  - 562 chemical IDs and 76,381 facility-chemical relationships. 637 pairs have more than one form; these are distinct submissions, and all are kept.
  - Facility attributes conflict for 0 facilities. Industry sector is form-level (41 multi-sector facilities), so facilities carry a set of sectors.
  - 15 chemical IDs have more than one published name; all names are kept.
  - All facilities are mapped (6-decimal FRS coordinates). `HORIZONTAL DATUM` is blank on every row, so the coordinates are drawn as EPSG:4326 without transformation.
  - Boundary checks: 2 points lie outside the reported state (FL/GA and KS/MO state lines) and 19 lie in island areas outside the CHIP layer. All stay mapped, with the derived county stored separately.
  - 213 colocated coordinate groups (472 facilities) are kept distinct.
  - No revision or withdrawal flag exists in the file; refresh change reports count forms that are no longer present.
- **Changes:**
  - Registry `epa_tri_facilities.json`; modules `tri.py`, `tri_cli.py`, `tri_api.py`; one router include in `main.py`.
  - Additive migration `f2c8d4a6b1e3` (`stage_tri_report`, `tri_report`, `tri_chemical`, `tri_facility`, `tri_facility_chemical`, with immutability triggers).
  - Frontend `TriFacilities.jsx`, wired into `Places2025Pilot.jsx`. The HRSA and TRI panels now stack in a shared `.pilot-overlays` column.
  - Tests; operator guide `backend/docs/chip_epa_tri_facilities.md`; inventory row `epa-tri-facilities` updated in place (still 96 records); handbook.
- **State-changing commands:**
  - `alembic upgrade head` (`e9b3f6a2c4d8` → `f2c8d4a6b1e3`).
  - `tri_cli fetch-stage-validate` twice: candidate `3b6ecfb1-bf58-4122-a71f-432027994bd7` ready with 11/11 checks, then a duplicate run.
  - `review`, then `approve-publish` at 19:03:10Z (semantic `b0d831fc…f0ae`, schema `5a37e707…e143`, metadata `71b6ea27…a77`).
  - Pointer drill: `deactivate`, then a refused rollback to the HRSA release, then `rollback 3b6ecfb1…`.
  - Webroot backed up to `data/deploy-recovery/tri-facilities-20261114/`, then `rsync -a --delete frontend/dist/ /var/www/places/` three times (two layout fixes); the final webroot matches the build by SHA-256.
  - `sudo -n systemctl restart places-backend` at 19:04:11Z.
  - For verification: six temporary demo access codes (label `agent-verification-tri-20261114`, 2 uses, 30-minute expiry; 6 runs, three of which stopped at the marker-click step before the script fix), each deactivated by the script in a `finally` block. A DB check confirmed all 6 are inactive with one use each. The plaintext was never printed or stored.
- **Verification:**
  - Backend: 21 unit tests and 7 PostGIS integration tests (scratch DB `chip_tri_facilities_test`, created and dropped by the tests). They cover multi-form pairs, revision and withdrawal holds, colocated facilities, coordinate conflicts, missing locations, chemical and sector filters, cluster and table parity, caps and 413s, publication isolation, failed candidates, authentication, and tamper detection.
  - Full backend suite: 595 passed, 1 failed (the known `test_all_six_real_source_years_match_acceptance_totals`).
  - Frontend: 133/133 tests (7 new: chemical filter, sector filter, keyboard detail, stale responses during rapid switching, release mismatch, simultaneous overlays). The build succeeds with the existing chunk-size warning.
  - `review` re-verified 3 archives and every staged and read-model row plus the geometries. An independent raw-CSV comparison matched for 3 facilities.
  - Benchmarks: national clusters 88 ms in-process (95–110 ms through Nginx), urban points ≤3 ms (Houston 323, Chicago 449), rural ≤10 ms. Details are in the guide.
  - Anonymous requests to all `/api/area/tri/*` routes return 401.
- **Authenticated browser check (real session through Nginx, 23/23):**
  - Clusters, then points, then a marker detail with the FRS link and no area popup.
  - Keyboard detail focus.
  - TRI and HRSA shown together.
  - Ethylene-oxide filter (no HRSA refetch).
  - Rapid sector switching.
  - Measure switching that refetches only the area map.
  - `/area/epa-aqi` and `/area/acs-2024` with both overlays.
  - All area catalogs and the HRSA catalog on unchanged pointers.
  - Funding map and legend returning 200.
  - No page errors; mobile without horizontal scroll.
  - Two layout bugs found by screenshot were fixed: an open panel collapsed and spilled below the map, and a long detail label squeezed the values.
- **Not done / limits:**
  - No release quantities, totals, toxicity, risk, aggregates, distance zones, historical years, or enforcement joins (deferred by design).
  - HRSA marker detail and HRSA filters were not exercised in the authenticated run.
  - On narrow screens the overlay column overlaps the open area table, as the HRSA toggle did before this change.
  - The timer and backup configuration were not changed. TRI is not in the recovery set.
- **Git:** committed on new branch `claude/epa-tri-facilities`, created from `claude/hrsa-health-center-sites` (`9666f71`) because the deployed tree contains both overlays. Pushed to `origin` without force. `main` contains neither. Raw source files, archives, and the webroot backup (`data/`) are gitignored and not committed.
- **Next action:** an operator decides whether to merge the HRSA and TRI branches into `main`, then refreshes the recovery set to include the site and TRI tables.

## 2026-11-14T18:21:16+00:00 — HRSA health center site point overlay integrated, published, and deployed (Claude)

- **Objective:** CHIP's first point layer: HRSA Health Center Service Delivery and Look-Alike Sites as an optional overlay on the area maps. The Codex sibling worktree was not touched.
- **Source:** HRSA BPHC/Data Warehouse HCSD CSV plus metadata XLSX. Usage limitations: "None"; refreshed daily.
  - Snapshot 2026-11-14, from `Data Warehouse Record Create Date`; retrieval was 18:07Z.
  - CSV SHA-256 `08b01537…a436`.
  - CMS FQHC ownership records and UDS organization-level data were not used.
- **Product rules:**
  - Key: `BPHC Assigned Number` (19,616 unique site IDs). Organizations (1,593 health center numbers) are attributes and are never merged with sites.
  - Default filter: Active service-delivery sites, so administrative-only sites are opt-in.
  - Location statuses: 19,200 mapped (19,186 inside their published county; 14 island-area points without a CHIP boundary).
  - Excluded from the map: 14 domestic-violence locations (suppressed by HRSA policy; no coordinates, address, or phone kept in the read model), 363 rows with no coordinates, 38 shared place-level geocodes (AS, FM, MH, PW), and 1 coarse coordinate.
  - Colocated sites are retained (up to 15 at one point).
  - The "Site Added to Scope" date is marked Restricted in HRSA metadata and is never exposed.
- **Changes:**
  - Registry `hrsa_hc_sites.json`; modules `hrsa_sites.py`, `hrsa_sites_cli.py`, `hrsa_sites_api.py`; one router include in `main.py`.
  - Additive migration `e9b3f6a2c4d8` (`stage_hrsa_site`, `site_hrsa` with PostGIS points, GiST index, constraints, and the published-immutability trigger).
  - Frontend `HealthCenterSites.jsx`, wired into `Places2025Pilot.jsx` and CSS.
  - Tests; operator guide `backend/docs/chip_hrsa_health_center_sites.md`; inventory record 96; handbook.
- **State-changing commands:**
  - `alembic upgrade head` (`d3a7e5c1b9f2` → `e9b3f6a2c4d8`).
  - `fetch-stage-validate` three times:
    - Run 1 was held (`38f71065…`) because my new Content-Length check misread a gzip-encoded page. This was a code bug, fixed; the held row is kept.
    - Run 2 produced `e5cdea05-6518-454c-9418-353410c2309d`, ready with all 8 checks passing.
    - Run 3 was recorded as a duplicate.
  - `review`, then `approve-publish e5cdea05…` (semantic `31859595…b90a`, schema `2096dab1…e0ab`, metadata `2cb368bf…48d2f9`).
  - Pointer drill: `deactivate`, then a refused cross-product rollback, then `rollback e5cdea05…`.
  - Webroot backed up to `data/deploy-recovery/hrsa-sites-20261114/`, then `rsync -a --delete frontend/dist/ /var/www/places/` (repeated twice for a layout fix), then `systemctl restart places-backend`.
- **Verification:**
  - Backend: 23 unit tests, plus 7 PostGIS integration tests in a scratch DB (`chip_hrsa_sites_test`, created and dropped by the tests). The full suite had 567 passed and 1 failed; the failure is the known `test_all_six_real_source_years_match_acceptance_totals`.
  - Frontend: 126/126 tests (7 new); build OK with the existing bundle-size warning.
  - Review rechecked 4 archives and all 19,616 rows, plus 19,200 geometries to 1e-9.
  - Map and table totals were equal in 8 benchmark views:

    | View | Result | Time |
    | --- | --- | --- |
    | National clusters | 53 clusters | ~70–90 ms, ~10 KB |
    | Los Angeles, zoom 11 | 347 points | ≤15 ms, ~200 KB |
    | NYC, zoom 9 | 543 points | ~300 KB |
    | Rural views | points | ≤4 ms |

  - Through Nginx, all site routes return 401 anonymously, and published site rows reject writes.
  - Area regression: all five area catalogs resolve unchanged pointers, and an AQI map read returns 200.
  - Funding regression: public map and legend return 200 through Nginx. The map took 25.8 s cold after the restart and 4.9 s warm. Four funding v1 routes return 200 in-process.
- **Browser check:** headless Chromium loaded the deployed bundle against a loopback-only verification backend (live DB, gate off, port 8765, stopped). It covered:
  - Clusters, then points, and colocated lists.
  - Marker clicks without area popups, while polygon popups still work in every mode.
  - Keyboard detail from the table.
  - Filters.
  - Measure switching with no site refetch.
  - Persistence across PLACES, EPA AQI, and ACS.
  - A layout fix so the site panel no longer covers the legend on desktop; it starts collapsed on mobile.
- **Not done:**
  - No authenticated real-session browser check: creating a temporary demo access code was denied by the session permission policy.
  - Timer, backups, access controls, funding code, and other facility datasets were not changed.
- **Git:** committed on new branch `claude/hrsa-health-center-sites` (based on `e35aee2`) and pushed to `origin` without force; `main` is unchanged. The deployed webroot and backend correspond to this branch's tree. Raw source files and archives (`data/`) are gitignored and not committed.
- **Next action:** an operator runs an authenticated browser check of the overlay on `/area/places-2025` and `/area/epa-aqi`, then refreshes the recovery set to include the site tables.

## 2026-11-14T17:45:20+00:00 — EPA AQI branch merged to main (Claude)

- **Outcome:** At the user's request, local `main` was fast-forwarded from `d45fed6` to `a17cf77` (branch `claude/epa-aqi-county-2025`) and pushed to `origin/main` without force. `origin/main` had not moved since the branch was created. This entry and the handbook Git-status line are a follow-up documentation commit. They correct the earlier entry's statement that `main` was unchanged.
- **Deployment:** No new deployment, data, pointer, or service change. The deployed webroot and backend already correspond to this code.

## 2026-11-14T16:55:41+00:00 — EPA AirData annual county AQI integrated, published, and deployed (Claude)

- **Agent/objective:** Claude implemented the EPA AirData annual AQI-by-county product in the shared area pipeline, as assigned. Codex's sibling worktree (`codex/ahrf-county-five-measures`) was not touched.
- **Source/year:** `annual_aqi_by_county_2025.zip` (EPA build 2026-06-25; ZIP SHA-256 `72b022b3…7130`) is the latest completed calendar year. The partial 2026 file was skipped. Definitions come from EPA's About AirData Reports page.
- **Measures:** five published fields: Median, 90th percentile, and Max AQI; Days with AQI; Good days. Days with AQI is stored on every observation row. Nothing is derived, and no CI or MOE is invented.
- **Identifiers:** the file has names only. GEOIDs come from EPA's site-listing State+County codes and are cross-checked against TIGER 2024 names by documented rules, with 8 reviewed spelling variants. No fuzzy matching is used.
- **Coverage:** 985 source rows; 975 mapped. 10 excluded with reasons: 8 legacy Connecticut counties not forced onto planning regions, Sonora (Mexico), and USVI St. John. 2,247 of 3,222 boundary counties are shown as `no_reported_value` at read time; no rows are stored for them. Eight beyond-scale maxima (>500) are kept and flagged.
- **Changes:**
  - Registry `epa_aqi_county_2025.json`; modules `epa_aqi.py`, `epa_aqi_cli.py`, and `epa_aqi_api.py`.
  - Additive migration `d3a7e5c1b9f2`.
  - Narrow branches in the shared `router.py`.
  - Frontend `/area/epa-aqi`, with a neutral legend (no daily health-category colors), Days with AQI in popups and the table, visible limitations, and selector entries.
  - Tests; operator guide `backend/docs/chip_epa_aqi_county_2025.md`; inventory row 44; handbook.
- **State-changing commands:**
  - `alembic upgrade head` (`c9f76d3a51e2` → `d3a7e5c1b9f2`).
  - `epa_aqi_cli fetch-stage-validate` twice: the first run was ready with all six checks passing; the second was a duplicate.
  - `review` and `approve-publish 70e78172-da21-4782-91e2-d3b97896863f` (semantic `d29d432f…da54`, schema `e753e547…577e`, metadata `c71d063d…fd17`).
  - Pointer drill: `deactivate`, then `rollback` to the same release. A cross-product rollback was refused.
  - Webroot backed up to `data/deploy-recovery/epa-aqi-20261114/`, then `rsync -a --delete frontend/dist/ /var/www/places/`.
  - `systemctl restart places-backend`.
- **Verification:**
  - New AQI tests: 29 backend and 2 frontend.
  - Focused backend suite: 308 passed, 1 failed. The failure is `test_all_six_real_source_years_match_acceptance_totals`, a FY2026 CDC account-summary natural-key change in local data. It fails identically on pre-task `d45fed6`, so it is pre-existing and unrelated.
  - Frontend: 119/119 tests; production build OK (existing bundle-size warning).
  - Review re-hashed 20 archived files and matched all 4,875 observations; spot checks matched the raw CSV.
  - In-process API checks against the live release covered all five measures in four viewports with map, table, and legend parity. The national view returned 3,109 counties in ~1.6 MB in ~3.1 s. Tract and 2026 requests returned 400.
  - Through Nginx, the anonymous catalog returned 401. PLACES, ACS, AHRF, and CLH reads and three funding v1 reads returned 200, with pointers unchanged. Published AQI rows reject writes.
- **Not done:** no authenticated browser check. Creating a temporary demo access code was denied by the session's permission policy. The timer, backups, access controls, funding methodology, and legacy integrations were not changed.
- **Discrepancies found:**
  - The deployed webroot before this task matched neither `89fc4d8` nor `d45fed6` byte-for-byte; it was built from the pre-commit tree. This deploy therefore also shipped the committed `main` funding and demo-access code.
  - `frontend/src/config/apiBase.js` is git-ignored, so a clean checkout cannot build.
  - Nginx `/health` serves the SPA; use `/api/health`.
  - The handbook's "72-row" inventory is 95 records.
- **Git:** committed on new branch `claude/epa-aqi-county-2025`, based on `d45fed6`, and pushed to `origin` without force. `main` is unchanged; merging is a separate decision. The deployed webroot and backend correspond to this branch's tree.
- **Next action:** an operator with access performs the authenticated browser check of `/area/epa-aqi`, covering Baltimore city (data), a CT planning region (no value), and Mayagüez (exception). Then refresh the recovery set.

## 2026-11-14T16:30:31+00:00 — Main branch push completed

- **Objective/outcome:** All 30 nonignored pending paths were committed as `23b79c6` on `claude/improvements`. Local `main` fast-forwarded from `b1a0eba` to `23b79c6`; `git push origin main` succeeded without force. The push carried the branch's 14 commits beyond the former `origin/main`, including earlier CHIP work and the new consolidated commit. The existing sibling AHRF branch was not merged: its AHRF source and guide files matched the integrated versions, while its history lacked the later CLH work.
- **Verification:** The staged diff passed `git diff --check` and a scan of staged files found no private-key or token patterns. Focused backend tests passed 50/50 after the import-path correction, frontend tests passed 117/117, production frontend build passed with a bundle-size warning, and Bash/Python syntax plus PowerPoint archive integrity passed. No full backend suite, deployed browser check, data publication, migration, service restart, or production deployment was performed.
- **Files and next action:** Main now contains the funding trend/API/UI changes, demo startup fix, dossier and recovery scripts, presentation, agent notes, and project documentation. Git ignores source data, caches, environments, and generated frontend assets; they were not forced into version control. This entry and the handbook branch-status correction are the final documentation follow-up. A fresh AHRF/CLH-inclusive recovery set and off-host copy remain outstanding.

## 2026-11-14T16:28:50+00:00 — Consolidate approved work onto main

- **Objective/outcome:** User approved committing all pending work and asked for the current branch to become `main` and be pushed. `origin/main` is an ancestor of `claude/improvements`, so a fast-forward is available; commit and push remain pending at this entry's creation.
- **Changes reviewed for commit:** CDC funding API outlay trends and frontend redesign/tests, demo-access session handling and demo startup readiness check, recipient dossier/subawardee report scripts, local recovery helpers, a hypothetical CHIP use-case deck and notes, Claude orientation, and the prior uncommitted diary entry. Updated this handbook for the new code and recovery-helper status. Dataset pointers, migrations, services, timers, storage, and deployed assets were not changed by this task.
- **Verification:** Read the branch and remote history after `git fetch origin`; `origin/main` had zero commits outside current `HEAD`. Focused backend tests passed 50/50 with `PYTHONPATH=. .venv/bin/python -m pytest`; the first direct `.venv/bin/pytest` invocation failed collection because `app` was not on its import path. Frontend tests passed 117/117 and `npm run build` succeeded with a bundle-size warning. Bash syntax, Python compilation, and PowerPoint ZIP integrity checks passed. No data import or destructive recovery command was run. Full backend suite and deployed browser verification were not run.
- **Publication/next action:** Commit all nonignored work, fast-forward local `main`, push `origin/main` without force, then record the final branch and push result. The older local recovery set still predates AHRF/CLH and requires a new isolated restore plus independent copy.

## 2026-11-14T16:24:34+00:00 — Claude Code orientation alongside Codex

- **Objective/outcome:** Read-only orientation for Claude Code. No application code, data, migration, pointer, service, or deployment change. Added root `CLAUDE.md`, which imports `@AGENTS.md` (none existed before), and this entry; both are uncommitted.
- **Verified state:** Host `chip-app`, user `john`, repo `/home/john/places-app`, branch `claude/improvements` at `0b9372b`, level with `origin/claude/improvements`. Uncommitted funding/demo-access edits, `backend/scripts/chip_recovery/`, three other untracked scripts, `backend/docs/chip_phase1_next_codex_prompt.md`, and `deliverables/` were left untouched. Only root `AGENTS.md` exists in-repo; no nested instruction files. Codex app-server was running; Codex also uses its global `~/.codex/AGENTS.md`, which matches this workflow. `places-backend`, Nginx, and `chip-area-refresh.timer` were active.
- **Discrepancy:** Sibling worktree `/home/john/places-app-ahrf-push` holds `codex/ahrf-county-five-measures` (`ec6dddd`). Its two commits are not ancestors of `HEAD`, but AHRF code is on this branch through `89fc4d8`. Treat that branch as superseded unless someone confirms otherwise. This is unverified at the content level.
- **Next action:** Unchanged from the handbook priorities. Commit `CLAUDE.md` with the next authorized documentation commit.

## 2026-11-14T16:11:48+00:00 — Documentation publication handoff

- **Objective/outcome:** Committed the handbook, diary, root `AGENTS.md`, and three supporting operator documents as `0b03cc8`; pushed `claude/improvements` to `origin` successfully without force. The push also carried four pre-existing local commits already ahead of the branch upstream. This follow-up diary record is a separate documentation-only change.
- **Verification:** `git diff --cached --check` passed before the first commit; all handbook and supporting-document local links resolved, and documented Python command targets existed. The push reported `5b4dcda..0b03cc8`. No application tests, deployment, data import, migration, pointer change, or service restart occurred for the documentation task.
- **Next action:** Push this diary follow-up entry, then inspect final branch/working-tree status. A new recovery set and off-host copy, CLH source retry, and the untracked recovery helpers remain separate work.

## 2026-11-14T16:07:50+00:00 — Central documentation and agent workflow

- **Objective/outcome:** Created the canonical handbook and this diary, plus root `AGENTS.md` task-start and handoff rules. No application code, data, release pointer, service, timer, or deployed asset was changed for this request.
- **Files and decisions:** `docs/PROJECT_HANDBOOK.md` records current architecture, per-integration inventory, shared versus legacy/funding boundaries, commands, decisions, and gaps. `docs/PROJECT_DIARY.md` starts the evidence-backed history. `AGENTS.md` requires future agents to read and maintain them. Existing untracked audit, pipeline-plan, and local-recovery guides were included so handbook references resolve in Git; the maintained broader source inventory remains `backend/docs/chip_source_inventory.csv`.
- **Verification:** Inspected repository manifests, registries, migrations, routes, operator guides, and git state. Read-only `area_pilot` queries showed four independent published pointers and DB revision `c9f76d3a51e2`; budget, federal-account, and TAGGS table counts were also read. `app.area_pilot.operations status` showed PLACES/ACS content checks current; `systemctl` showed backend, Nginx, and weekly area timer active/enabled. Local and Nginx health returned 200; anonymous area catalog returned 401. All local Markdown links and documented command target files resolved; the four shared CLI `--help` entry points succeeded. Bare `python` was unavailable in the host shell, so subsequent checks used `python3` or `backend/.venv/bin/python`; a pre-existing `requests` dependency warning appeared. No full ingestion, migration, build, or test suite was run because this is a documentation-only change.
- **Deployment/publication:** No deployment or data publication. Commit and push are pending at this entry's creation.
- **Issue/next action:** Earlier local recovery set predates active AHRF/CLH releases and must be refreshed and copied off-host. Its helper scripts are untracked and unavailable from a clean remote checkout. CLH source re-fetch had held HTTP 202 responses per its guide. Review the staged documentation diff, then commit only intended documentation and push without force. Preserve unrelated working-tree changes.

## 2026-11-14T15:55:10+00:00 — CLH integration milestone (Git evidence)

- **Objective/outcome:** Commit `89fc4d8` adds curated AHRQ CLH to the shared area pipeline. The [CLH guide](../backend/docs/chip_clh_2023_curated.md) reports checksum-bound publication and deployment on November 14, with authenticated browser/API checks and a supervised pointer recovery; the author-time timestamp here is from Git, not the deployment time.
- **Files/data:** `backend/app/area_pilot/clh*`, the CLH registry/migration, shared area routes and UI, and five curated indicators from September 2025 v2.0 files. Live read-only DB inspection at this diary's creation found active CLH release `168ec07d-c7ef-4e46-b01a-ec72c00c3d88` and three held CLH candidates.
- **Issue/next action:** The guide records empty HTTP 202 responses on repeat source fetch; replay of archived workbooks matched published content. Recheck source availability before a new candidate. Existing weekly timer does not include CLH.

## 2026-11-13T23:46:15.861150+00:00 — Shared area releases (ACS publication time from live DB)

- **Objective/outcome:** [PLACES](../backend/docs/chip_places_2025_pilot.md) and [ACS](../backend/docs/chip_acs5_2024_phase3.md) guides report published/deployed releases, release-pinned map/legend/table parity, authenticated browser checks, and pointer recovery. Live DB publication times were 2026-11-13T23:14:56.930499+00:00 for combined PLACES and the heading timestamp for ACS. The [operations guide](../backend/docs/chip_area_phase4_operations.md) records a weekly PLACES/ACS verification timer and supervised full-content checks completed early November 14. These are historical actions, not operations performed for this diary.
- **Files/data:** `area_pilot` releases, 2023/2020 PLACES-compatible boundaries, isolated 2024 ACS boundaries, raw archives, API and React area page. Live pointers were rechecked on November 14; see handbook for current values.
- **Issue/next action:** No automatic publication. Source endpoint/schema drift and archive growth need operator review. The [local recovery guide](../backend/docs/chip_current_recovery_set.md) reports an isolated restore of a pre-AHRF/CLH snapshot; its proposed nightly schedule has not been commissioned.

## 2026-08-22T21:21:41+00:00 — Funding trend code milestone (Git evidence)

- **Objective/outcome:** Commit `ad3a667` added CDC funding trend analysis. Earlier commits `a3de3b1` and `e309a0d` on July 27 added summary outlay backfill and restored the all-account overview; `04efb55` on July 3 added the v1 funding map model. This summary establishes code history only; corresponding deployment dates and full data validation were not reconstructed here.
- **Files/data:** [CDC funding API guide](../backend/docs/cdc_funding_api_v1.md), [source ingestion guide](../backend/docs/cdc_funding_source_ingestion.md), funding database/schema and frontend funding pages. Later uncommitted funding edits were present at this diary's creation and remain outside this documentation task.

## 2026-04-24T14:31:30+00:00 — Demo access and funding base (Git evidence)

- **Objective/outcome:** Commit `ec97672` added demo access and budget-grounded funding; `9b71dd1` later that day added USAspending federal-account ingestion. March 2026 commits introduced CMS, USDA, FEMA, CDC funding, and model components. Dates are commit author times; ingestion/publication completeness for those legacy products is described cautiously in the [November 13 audit](../backend/docs/chip_federal_data_current_state_audit.md).
- **Files/data:** [access middleware](../backend/app/demo_access/middleware.py), funding and legacy importers, migrations, and [scripts guide](../backend/scripts/README.md). The shared area release system did not apply to these earlier integrations.
