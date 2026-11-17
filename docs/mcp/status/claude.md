# Claude status: MCP project manager

| Package | State | Branch | Notes |
|---|---|---|---|
| M0 Setup | Done | `claude/mcp-m0` | Dispatch tested for Codex (sandboxed, AppArmor profile added). Antigravity waits on John's CLI sign-in. Contract in `docs/mcp/TOOL_CONTRACT.md`. |
| M1 Read layer and infra | Done | `claude/mcp-m0` | `lookup.measure_values_within` with 4 unit tests, checked on staging. `infra/mcp/` unit, role script, and Nginx snippet written; not installed. |
| M4 Staging integration | Not started | | Waits for M2 and M3. |
| M5 Production | Not started | | Waits for Gate A, then John's DNS record and Gate B. |

## What Codex and Antigravity can rely on now

- `app.area_pilot.lookup.measure_values_within(db, product, measure_id, level, parent_geoid)` is on `beta`.
- `docs/mcp/TOOL_CONTRACT.md` is the contract. Ask through your status file if something in it is wrong; do not work around it.
