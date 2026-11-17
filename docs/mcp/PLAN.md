# CHIP MCP server: development plan

## Context

John wants AI assistants (ChatGPT, Claude, and any other MCP client) to answer questions from CHIP's published data, so nobody has to hunt through datasets by hand. Version 1 does retrieval and simple comparison, not deep analysis. John's draft proposed eight tools that call the FastAPI backend over HTTP. This plan keeps the idea but fits it to what the repository actually contains. Claude remains the project manager and hands work to Codex and Google Antigravity without copy-pasted prompts.

**Decisions made with John (2026-11-17):**

| Question | Decision |
|---|---|
| Ranking | One tool may **sort a single published measure** across the areas of a state. Ties, uncertainty, and missing or suppressed rows stay visible. No composite scores and no "best" or "worst" labels. This amends the beta "no ranking" rule for the MCP only. |
| Access | **Open, no login.** The server is read-only and rate-limited. AHRF is excluded until HRSA answers the redistribution question. |
| HTTPS | John owns `publicdataobservatory.org`. `chip-beta.publicdataobservatory.org` already has a Let's Encrypt certificate on this VM (Nginx `zz-chip-beta`) and fronts **staging** (backend 8001). |
| Autonomy | **Gates only.** Claude writes the tasks, dispatches Codex and Antigravity headlessly, reviews, merges to `beta`, and deploys staging. John approves Gate A (try it on staging) and Gate B (go public on live data). |

**Findings that change John's draft:**

- **The read layer already exists.** [lookup.py](backend/app/area_pilot/lookup.py) returns release-pinned values with explicit statuses, uncertainty, population, period, boundary vintage, and source credit for 66 measures in 9 area products, plus facility lists. The tools call it in-process. They do not go through HTTP, which would hit the demo-access cookie gate, so no second query implementation is needed.
- **No time series.** Each shared product publishes one period. `get_time_series` is dropped from v1, and the tool descriptions say plainly that the data has one period per measure.
- **`area_values` caps requests at 200 GEOIDs.** Texas has 254 counties, so "every county in a state" needs one small new lookup function.
- **The three gaps in John's draft are now settled.** HTTPS comes from the domain row, the AHRF exclusion from the access row, and sorting from the ranking row.
- **Funding uses its own methodology** ([cdc_funding_api](backend/app/cdc_funding_api/)). It is deferred to a later phase, and v1 does not touch it.
- **Handbook gap:** HTTPS for staging at `chip-beta.publicdataobservatory.org` (set up 2026-11-16 on `codex/beta-tls-handoff`, which has no commits beyond `main`) is not in the handbook, which still calls staging private on port 8080. M0 corrects this.

## Architecture

```
ChatGPT / Claude / other MCP clients
        │  HTTPS, Streamable HTTP, no auth
Nginx  /mcp  (limit_req, body and time caps)
        │
chip-mcp service (FastAPI process separate from the website; official `mcp` SDK, stateless HTTP)
        │  in-process Python calls
app.area_pilot.lookup  (+ one new function)  +  community/topics.json
        │  read-only DB role (SELECT on area_pilot only, statement_timeout 5 s)
PostgreSQL/PostGIS: active published releases only
```

- **Separate process and systemd unit.** A spike in AI traffic cannot slow the website, and the server can be restarted or turned off alone.
- **Read-only database role** `chip_mcp_ro`, created by an infra SQL script, not a migration. Even a bug cannot write.
- **Public product allowlist** in the server config: every `lookup.SPECS` product except `ahrf`. Facility overlays (HRSA sites, TRI, nursing homes) appear as counts and short lists through `area_facilities`.
- **SDK:** the official `mcp` package. PyPI's latest is 2.3.0; M0 confirms the v2 server API before any code is written. Use stateless Streamable HTTP with JSON responses.

## Tools (v1: seven, all read-only)

Every value row keeps `lookup`'s fields (status, status_text, uncertainty, period, population, release_id, boundary_vintage) and adds a one-line `citation` ("Source: Publisher · Product · Period · Release"). Every response carries a short `interpretation_rules` block. It says values are never aggregated across areas, that Medicare measures cover Original Medicare beneficiaries only, that TRI facilities are reporting facilities, that missing is not zero, and it holds the product's limitations.

| Tool | Purpose | Built on |
|---|---|---|
| `find_places(query, levels?)` | Name to GEOID for states, counties, and 119th Congress districts | `lookup.states`, `routers.search.search_counties`, `lookup.state_districts` |
| `search_measures(query?, topic?, level?)` | Keyword and topic search over the catalog, with compact results | `lookup.catalog`, `community/topics.json` |
| `get_measure_details(measure_keys)` | Definition, denominator, unit, levels, period, population, uncertainty kind, limitations, landing page, active release | `lookup.catalog` |
| `get_area_values(level, geoids, measure_keys? \| topic?)` | Values for up to 25 areas, for comparisons and profiles | `lookup.area_values` |
| `get_measure_across_areas(measure_key, level, state, sort?, limit?)` | All counties (or districts, or states) for one measure, sortable. Missing and suppressed rows are listed apart, never dropped. Tracts are only available within one county. | **new** `lookup.measure_values_within` |
| `get_area_context(level, geoid)` | Containing and overlapping areas (counties in a district, districts in a county, counties in a state) and facility counts with short lists | `lookup.area_info`, `district_counties`, `county_districts`, `state_counties`, `area_facilities` |
| `list_data_sources()` | Products, publishers, active releases and dates, levels, limitations, and the status glossary | `lookup.catalog`, `active_releases` |

Measure keys are `product:measure_id`, for example `places:diabetes_crudeprev`.

**Limits:** at most 25 areas × 40 measures per call, about 60 KB per response, clear error text an LLM can act on (for example, "use find_places first"), and a 5 s database timeout. A small in-process cache, keyed by tool, arguments, and active release IDs, means a new publication invalidates it automatically.

## Who does what

The work is split by directory so no two agents edit the same file. `AGENTS.md` gets an "MCP server" ownership section in M0.

| Agent | Owns | Role |
|---|---|---|
| **Claude Code** (project manager) | `backend/app/area_pilot/**` (incl. the new lookup function), `infra/**` (systemd unit, Nginx, DB role script), `docs/mcp/**` (plan, task files, Claude status), handbook, diary folding | Writes task files, dispatches, reviews diffs, merges to `beta`, deploys staging and live, runs gates |
| **Codex** | `backend/app/mcp_server/**`, `backend/tests/test_mcp_*`, later the frontend "Use CHIP with AI" page | Builds the server and tools: the largest continuous build, and Codex has the larger allowance |
| **Antigravity** | `backend/tests/mcp_eval/**`, `deliverables/mcp/**`, `docs/mcp/status/antigravity.md` | Independent evaluation: a gold-standard question set, an eval runner, and client compatibility reports. Using a different model to test than to build avoids self-grading. |

New worktree `/home/john/chip-agy` (branch `agy/mcp-*`). Codex keeps `/home/john/chip-codex`; Claude keeps `/home/john/chip-claude`.

## How the handoffs run without copy-paste

Both tools have headless modes on this VM:

- **Codex:** `codex exec -C /home/john/chip-codex -s workspace-write -c sandbox_workspace_write.network_access=true -o docs/mcp/runs/<pkg>.codex.md "Do the task in docs/mcp/tasks/<pkg>.md"`. The binary ships with the VS Code extension (`~/.vscode-server/extensions/openai.chatgpt-*/bin/linux-x86_64/codex`). M0 adds a stable symlink.
- **Antigravity:** `~/.gemini/bin/agy -p --mode auto --output-format json "Do the task in docs/mcp/tasks/<pkg>.md"`, run from `/home/john/chip-agy`. **One-time step for John:** run `agy` once in a terminal and sign in, because the CLI currently says "Please sign in".

The loop for each work package:

1. Claude writes `docs/mcp/tasks/<pkg>.md`: goal, owned paths, the contract to code against, acceptance tests, and "commit on branch X; do not deploy; update your status file".
2. Claude starts the agent as a background Bash command and is notified when it exits. Two external agents can run at once (for example, Codex on M2 while Antigravity writes M3).
3. Claude reviews:
   - `git diff --name-only` against the owned paths. A file outside them is rejected and sent back.
   - The run report, the status file, and the tests, which Claude reruns itself.
4. Claude merges and deploys with `infra/staging/deploy-staging.sh <branch>`. Agents never run deploys, never use sudo, and never touch live systems; their sandbox enforces most of that.
5. If the review fails, Claude writes a follow-up task and dispatches again with `codex exec resume --last` or `agy --continue`.

**Limits:**

- Claude's own session must be open for the loop to advance; work pauses between sessions.
- Usage limits pause an agent. The status files let any agent resume where it stopped.
- M0 adds permission allowlist entries so dispatching does not prompt each time.

## Work packages

**M0: Setup (Claude, about 1 day)**
- Dry-run both dispatch commands on a trivial task. Confirm that Codex's sandbox can reach Postgres on localhost for tests, and that `agy` reads `AGENTS.md`; if it doesn't, add a pointer file.
- Create `/home/john/chip-agy`, `docs/mcp/{PLAN.md,tasks/,runs/,status/}`, the `AGENTS.md` section, and the permission allowlist.
- Confirm the `mcp` 2.x server API and current ChatGPT and Claude connector requirements (authless Streamable HTTP; whether ChatGPT still needs `search`/`fetch` tools for any mode).
- Correct the handbook on chip-beta HTTPS.
- Write `docs/mcp/TOOL_CONTRACT.md`: the seven tool signatures, the response envelope, and one real JSON example per tool from staging.

**M1: Read layer and infra (Claude)**
- `lookup.measure_values_within(db, product, measure_id, level, state_geoid=None, county_geoid=None)`: every area at a level within a parent, active release only, with the same row shape as `area_values`. Tracts require a county. Add tests beside the existing lookup tests.
- `infra/mcp/`: `chip-mcp-staging.service` on `127.0.0.1:8011` running from `/home/john/chip-beta`, the `chip_mcp_ro` role script, and an Nginx snippet (`location /mcp` with `limit_req` of about 30 requests per minute per IP and burst 20, a 60 s timeout, and no cookies forwarded). The snippet is **not enabled yet**.

**M2: MCP server (Codex, parallel with M3)**
- `backend/app/mcp_server/`: the app, the seven tools, the envelope and citation builder, the allowlist, limits, cache, and structured logging (tool, arguments, latency, row count, no IP).
- Tool descriptions are written for an LLM: when to use the tool, which tool to call first, and what statuses mean.
- `backend/tests/test_mcp_*`: unit tests per tool against `places_staging`, AHRF exclusion, limits, and error text.

**M3: Evaluation suite (Antigravity, parallel with M2, against TOOL_CONTRACT.md)**
- `backend/tests/mcp_eval/questions.yaml`: about 40 questions drawn from the topics and showcase places (Person NC, Kanawha WV, Fresno CA, WV-01, Alabama counties). Each has expected tool calls and expected values taken directly from `lookup`.
- `run_eval.py` drives the server through the official MCP client. It checks values against `lookup`, preserved statuses, a citation on every row, no AHRF, sort order with missing rows listed apart, and response size.
- `deliverables/mcp/eval_report.md`.

**M4: Staging integration (Claude) → Gate A**
- Deploy `chip-mcp-staging`, then pass the eval and MCP Inspector.
- Connect Claude Code locally (`claude mcp add --transport http chip http://127.0.0.1:8011/mcp`) and run 10 of the eval questions end to end.
- Enable the `/mcp` location on `chip-beta.publicdataobservatory.org`.
- **Gate A:** John adds `https://chip-beta.publicdataobservatory.org/mcp` as a custom connector in Claude and in ChatGPT (developer mode) and tries his own questions. Antigravity records cross-client results in `deliverables/mcp/client_report.md`.

**M5: Production on live data (Claude) → Gate B**
- Promote through the promotion runbook as an application-only promotion: no migration, and the new lookup function is additive.
- Install `chip-mcp.service` on `127.0.0.1:8012` (internal only) from `/home/john/places-app` with the `chip_mcp_ro` role on the live database.
- New hostname `mcp.publicdataobservatory.org`: **John adds the DNS A record `mcp` → 96.30.196.165**. A DNS record has no port: clients connect on standard HTTPS 443, and port 80 stays open for Let's Encrypt renewals, as it already does for chip-beta. Claude runs certbot and adds an Nginx server on 443 that exposes only `/mcp` and proxies it to 8012. Public URL: `https://mcp.publicdataobservatory.org/mcp`.
- Rerun the eval through the public URL.
- **Gate B:** John approves going public. Staging's `/mcp` stays available for testing.

**M6: Public documentation (Codex, after Gate A)**
- A "Use CHIP in your AI assistant" page on the site: the connector URL, setup steps for ChatGPT and Claude, what the data covers, what it does not cover, and the interpretation rules.
- A setup section in `README.md`.

**Later (not in this plan; each needs its own decision):** a CDC funding tool through `cdc_funding_api.service`; AHRF once HRSA answers; legacy SVI, FEMA, and HPSA (unpinned); multi-period data as sources add it; interactive in-chat maps (OpenAI Apps SDK widgets); a `search`/`fetch` pair if ChatGPT deep research needs it; a directory or app-store listing.

**Rough schedule:** M0–M1 days 1–2; M2 and M3 days 2–6; M4 and Gate A around day 7; M5 and M6 and Gate B in week 2, depending on John's review time.

## Files

- **New:** `backend/app/mcp_server/{__init__,app,tools,envelope,config}.py`, `backend/tests/test_mcp_*.py`, `backend/tests/mcp_eval/`, `infra/mcp/{chip-mcp.service,chip-mcp-staging.service,mcp_readonly_role.sql,nginx-mcp.conf}`, `docs/mcp/{PLAN.md,TOOL_CONTRACT.md,tasks/,status/}`, `deliverables/mcp/`
- **Modified:**
  - `backend/app/area_pilot/lookup.py`: one new function; existing shapes unchanged
  - `backend/requirements.txt`: `mcp==2.3.0`, or whatever M0 confirms
  - `AGENTS.md`
  - `docs/PROJECT_HANDBOOK.md`
  - `docs/PROJECT_DIARY.md`
  - `/etc/nginx/sites-available/chip-beta`: include the snippet at M4
- **Reused, not changed:**
  - `lookup.catalog`, `area_values`, `area_info`, `area_facilities`, `district_counties`, `state_counties`, `states`, `STATUS_TEXT`
  - `community/topics.json`
  - `routers/search.search_counties`
  - `infra/staging/deploy-staging.sh`
  - `docs/beta/PROMOTION_RUNBOOK.md`

## Verification

- **Per package:** focused tests, then `PYTHONPATH=. .venv/bin/python -m pytest tests/test_mcp_* tests/test_area_lookup*`. Claude reruns these itself before merging. The known FY2026 funding failure is unrelated.
- **Eval (M3 runner):** 100% of value checks match `lookup` exactly. Every row has a status and a citation. No AHRF output. Sorted lists keep missing and suppressed rows apart. Every response is under the size cap and p95 latency is under 2 s on staging.
- **Safety:**
  - A write attempt as `chip_mcp_ro` fails.
  - Requests over the limit return clear errors.
  - Burst traffic gets 429 from Nginx.
  - `/mcp` responses set no cookies, and the website's 401 gate is unchanged.
- **Gate A:** John's own questions in Claude and ChatGPT against staging. Antigravity's client report covers both apps.
- **Gate B:** the eval passes through `https://mcp.publicdataobservatory.org/mcp`. Website pointers and the bundle are unchanged. A rollback (disable the Nginx location and stop `chip-mcp`) is recorded in the diary.

## What John needs to do

1. Sign in to the Antigravity CLI once (`~/.gemini/bin/agy`).
2. At M5, add the DNS A record `mcp.publicdataobservatory.org → 96.30.196.165`.
3. Gate A: add the staging connector URL in Claude and ChatGPT and try it.
4. Gate B: approve going public.

## Amendments from M0 (2026-11-17, Claude)

These were found by running things on the VM, and they replace the matching lines above.

- **SDK API:** `mcp` 2.x has no `FastMCP`. The class is `mcp.server.MCPServer`, and HTTP is served by `streamable_http_app(json_response=True, stateless_http=True, transport_security=...)`. A spike server called `lookup.area_values` on staging through the SDK `Client` and returned in about 30 ms. Tools must return typed models to produce `structured_content`.
- **Separate venv:** installing `mcp` 2.3 would upgrade Starlette to 1.10, which breaks FastAPI 0.115. The MCP server therefore runs from `backend/.venv-mcp` with its own requirements file (`backend/app/mcp_server/requirements.txt`). The website's venv and requirements are unchanged.
- **Host check:** the SDK rejects unknown `Host` headers, so the public hostnames are configured in `CHIP_MCP_ALLOWED_HOSTS`.
- **Codex sandbox:** Ubuntu's AppArmor blocked Codex's bundled bubblewrap. With John's approval, `/etc/apparmor.d/codex-bwrap` (source: `infra/agents/apparmor-codex-bwrap`) grants `userns` to that binary only. Headless Codex then reached `places_staging`, ran tests, and was refused a write outside its worktree.
- **Commits:** a worktree's git metadata lives in `/home/john/places-app/.git`, outside the sandbox, so **Codex and Antigravity do not commit**. They leave changes in their worktree, and Claude reviews the diff and commits on their branch, naming the author agent in the message.
- **Codex launcher:** `~/.local/bin/codex-cli` (not on PATH; call it by full path) runs the newest Codex binary bundled with the VS Code extension.
- **Antigravity:** `agy -p` returns "authentication required" until John signs in once.
- **Read-only role:** `search_counties` reads `public.dim_county` and `public.dim_county_boundary`, so `chip_mcp_ro` also gets SELECT on those two tables.
- **Connectors (checked 2026-11-17):**
  - Claude custom connectors support authless remote servers on every plan (the free plan allows one) and connect from Anthropic's cloud, so the URL must be public.
  - ChatGPT needs Developer mode on a paid plan; Plus and Pro allow read-only connectors.
  - Both use Streamable HTTP.

## Amendment 2026-11-17: work split by allowance (John's plans)

John's plans are ChatGPT Pro (Codex), a Google AI bundle at about $20 (Antigravity), and Claude Pro at $20 (Claude). From now on:

- **Codex** does all code writing, every fix round (batched into one task), and code-quality review.
- **Antigravity** takes small, bounded, independent tasks: evaluation, client reports, proofreading.
- **Claude** writes short task files, checks work with test runs and diff summaries, and handles infra and gates.

Remaining Claude-owned code work, if any, goes to Codex unless it touches migrations or `area_pilot`.
