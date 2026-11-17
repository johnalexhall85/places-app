# CHIP MCP server: operations

Plan: [docs/mcp/PLAN.md](../../docs/mcp/PLAN.md). Contract: [docs/mcp/TOOL_CONTRACT.md](../../docs/mcp/TOOL_CONTRACT.md).

| | Staging | Production |
|---|---|---|
| Unit | `chip-mcp-staging.service` | `chip-mcp.service` |
| Code | `/home/john/chip-beta` (branch `beta`) | `/home/john/places-app` (branch `main`) |
| Port (loopback only) | 8011 | 8012 |
| Database | `places_staging` as `chip_mcp_ro` | live database as `chip_mcp_ro` |
| Env file (mode 600, not in git) | `~/.config/chip/mcp-staging.env` | `~/.config/chip/mcp-live.env` |
| Public URL | `https://chip-beta.publicdataobservatory.org/mcp` | `https://mcp.publicdataobservatory.org/mcp` (live since 2026-11-17) |

The env file holds `DATABASE_URL=postgresql+psycopg://chip_mcp_ro:<password>@localhost:5432/<db>` and `CHIP_MCP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*,<public host>`.

## Install (staging)

1. **Venv:** `cd /home/john/chip-beta/backend && python3 -m venv .venv-mcp && .venv-mcp/bin/pip install -r app/mcp_server/requirements.txt`. Use a separate venv, because `mcp` 2.x needs a newer Starlette than the website's FastAPI pin allows.
2. **Role:** run [mcp_readonly_role.sql](mcp_readonly_role.sql) against `places_staging` (see its header).
3. **Env file:** write it, then install and start the unit (`sudo install -m 644 infra/mcp/chip-mcp-staging.service /etc/systemd/system/`, `daemon-reload`, `enable --now`).
4. **Nginx:** put the `limit_req_zone` line in `/etc/nginx/conf.d/chip-mcp-ratelimit.conf`, include [nginx-mcp.conf](nginx-mcp.conf) in the 443 block of `/etc/nginx/sites-available/chip-beta`, then `nginx -t` and reload.

## Turn it off

Remove the `include` line, run `nginx -t` and reload, then `sudo systemctl disable --now chip-mcp-staging` (or `chip-mcp`). The website is not affected: separate process, separate venv, read-only role.

## Production (live since 2026-11-17)

- **Nginx:** [nginx-mcp-live.conf](nginx-mcp-live.conf) is installed as `/etc/nginx/sites-available/chip-mcp` and **enabled as `sites-enabled/zz-chip-mcp`**.
  - The `zz-` prefix matters: Nginx's implicit default port-80 server is the first site loaded alphabetically. Named `chip-mcp`, it briefly took over requests by bare IP and redirected the live site (2026-11-17, about 2 minutes). Keep `places-demo` first.
  - The site exposes only `/mcp` and `/healthz`.
  - Rate limit: 120 requests per minute per IP, burst 60.
- **Certificate:** Let's Encrypt for `mcp.publicdataobservatory.org`, expires 2027-02-15. Renewed by `certbot.timer`, with the existing Nginx reload hook.
- **One role, one password:** `chip_mcp_ro` is a cluster-wide Postgres role used by both `places` and `places_staging`, so `mcp-live.env` and `mcp-staging.env` hold the same password. Rerunning the role script for either database changes it for both: update both files and restart both services.
- **Reload safely:** always gate the reload on the test, `if sudo nginx -t; then sudo systemctl reload nginx; fi`. Never pipe `nginx -t` into another command before `&&`, because the pipe hides its failure.
