# CHIP MCP server: operations

Plan: [docs/mcp/PLAN.md](../../docs/mcp/PLAN.md). Contract: [docs/mcp/TOOL_CONTRACT.md](../../docs/mcp/TOOL_CONTRACT.md).

| | Staging | Production |
|---|---|---|
| Unit | `chip-mcp-staging.service` | `chip-mcp.service` |
| Code | `/home/john/chip-beta` (branch `beta`) | `/home/john/places-app` (branch `main`) |
| Port (loopback only) | 8011 | 8012 |
| Database | `places_staging` as `chip_mcp_ro` | live database as `chip_mcp_ro` |
| Env file (mode 600, not in git) | `~/.config/chip/mcp-staging.env` | `~/.config/chip/mcp-live.env` |
| Public URL | `https://chip-beta.publicdataobservatory.org/mcp` | `https://mcp.publicdataobservatory.org/mcp` (DNS record pending) |

The env file holds `DATABASE_URL=postgresql+psycopg://chip_mcp_ro:<password>@localhost:5432/<db>` and `CHIP_MCP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*,<public host>`.

## Install (staging)

1. **Venv:** `cd /home/john/chip-beta/backend && python3 -m venv .venv-mcp && .venv-mcp/bin/pip install -r app/mcp_server/requirements.txt`. Use a separate venv, because `mcp` 2.x needs a newer Starlette than the website's FastAPI pin allows.
2. **Role:** run [mcp_readonly_role.sql](mcp_readonly_role.sql) against `places_staging` (see its header).
3. **Env file:** write it, then install and start the unit (`sudo install -m 644 infra/mcp/chip-mcp-staging.service /etc/systemd/system/`, `daemon-reload`, `enable --now`).
4. **Nginx:** put the `limit_req_zone` line in `/etc/nginx/conf.d/chip-mcp-ratelimit.conf`, include [nginx-mcp.conf](nginx-mcp.conf) in the 443 block of `/etc/nginx/sites-available/chip-beta`, then `nginx -t` and reload.

## Turn it off

Remove the `include` line, run `nginx -t` and reload, then `sudo systemctl disable --now chip-mcp-staging` (or `chip-mcp`). The website is not affected: separate process, separate venv, read-only role.
