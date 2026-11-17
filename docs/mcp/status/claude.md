# Claude status: MCP project manager

| Package | State | Branch | Notes |
|---|---|---|---|
| M0 Setup | Done | `claude/mcp-m0` | Dispatch tested for Codex (sandboxed, AppArmor profile added). Antigravity waits on John's CLI sign-in. Contract in `docs/mcp/TOOL_CONTRACT.md`. |
| M1 Read layer and infra | Done | `claude/mcp-m0` | `lookup.measure_values_within` with 4 unit tests, checked on staging. `infra/mcp/` unit, role script, and Nginx snippet written; not installed. |
| M4 Staging integration | Done; Gate A open | `beta` `93daee8` | `chip-mcp-staging` on 8011 as `chip_mcp_ro`; public at `https://chip-beta.publicdataobservatory.org/mcp` (Nginx include, 30 r/min per IP, burst 20). Eval 44/44, p50 53 ms, p95 125 ms. |
| M5 Production | Done (Gate B approved by John) | `main` `2347b88`+docs | `chip-mcp` on 8012 as `chip_mcp_ro` on `places`; public at `https://mcp.publicdataobservatory.org/mcp`; eval 44/44 through the public URL with live data (p50 14 ms, p95 101 ms). |

## What Codex and Antigravity can rely on now

- `app.area_pilot.lookup.measure_values_within(db, product, measure_id, level, parent_geoid)` is on `beta`.
- `docs/mcp/TOOL_CONTRACT.md` is the contract. Ask through your status file if something in it is wrong; do not work around it.
