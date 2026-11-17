# Task M6 (Codex): "Use CHIP in your AI assistant" page

Assigned by Claude, 2026-11-17. Branch `codex/mcp-m6` (checked out). Owned paths for this task: `frontend/**` and `README.md` (a new section only). The same rules as before: no commits, no deploys; record facts in `docs/mcp/status/codex.md`.

The MCP server is live at `https://mcp.publicdataobservatory.org/mcp` (public, no login, read-only). Build a page at `/ai` (also linked from the shared header's navigation and the About page) that follows the PDO brand rules in `docs/beta/EXECUTION_PLAN.md` ("Visual identity") and uses the existing token CSS and `SiteHeader`. Content, plain and precise, no hype:

1. **What it is:** one paragraph. AI assistants such as Claude and ChatGPT can look up CHIP's published public-health data directly and cite it.
2. **The connector URL** in a copyable code box with a "Copy" button.
3. **Setup steps:**
   - Claude: Settings → Connectors → Add custom connector → paste the URL, leave OAuth blank; available on all plans, the free plan allows one custom connector.
   - ChatGPT: Settings → Apps & Connectors → Advanced → Developer mode on → create a connector with the URL and "No authentication"; paid plans; read-only.
   - Other MCP clients: Streamable HTTP, no auth.
4. **Example questions:** five, taken from `docs/mcp/TOOL_CONTRACT.md` and the showcase places.
5. **What it covers:** the products, levels, and the one-period-per-measure note, read from `GET /api/community/catalog` if the page is signed in. Otherwise use static text naming the 8 public products. **AHRF is not available through the AI connector.**
6. **How to read answers:** the six interpretation rules from `backend/app/mcp_server/config.py` (`RULES`), shown as a short list. Missing is not zero; no composite scores; Medicare means Original Medicare beneficiaries.
7. **Limits:** read-only; rate-limited; data are the same published releases as this site.

Add a route test in the existing frontend test style, and run `npm test` and `npm run build`. Add a short "Use CHIP from AI assistants" section to `README.md` with the URL and a link to `infra/mcp/README.md`. Report in five lines or fewer.
