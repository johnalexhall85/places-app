# Codex status: CHIP MCP server

Updated by Codex at the end of each task. Claude reads this file before reviewing.

| Package | State | Branch | Notes |
|---|---|---|---|
| M2 MCP server | Implemented; review pending | `codex/mcp-m2` | Seven typed, read-only tools and Streamable HTTP app; 13 MCP tests passed with staging integration run, plus 26 website lookup/community tests. Uncommitted and undeployed. |

## M2 handoff — 2026-11-17T14:42:51+00:00

- **Objective and result:** Built the seven tools in `backend/app/mcp_server/` to the public tool contract, including exact value rows and citations, release-aware caching, source and interpretation metadata, host allowlist, JSON call logs, 60,000-byte cap, and actionable errors. The server uses only `lookup`, `search_counties`, and `community/topics.json` for data. AHRF keys are rejected; AHRF catalog and topic measures are filtered. The explicit AHRF entry in `list_data_sources.excluded` follows the contract.
- **Verification:** `PYTHONPATH=. .venv-mcp/bin/python -m pytest -q tests/test_mcp_*.py`: 13 passed; staging integration was not skipped. The tests checked the contract's Person, Alabama, Texas, EPA AQI, BRFSS, and Los Angeles tract examples; the HTTP test started temporary uvicorn on loopback, checked `/healthz`, listed seven tools with output schemas and read-only annotations, called through `mcp.Client`, then stopped uvicorn. `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_area_lookup.py tests/test_community_api.py`: 26 passed with three dependency/deprecation warnings. `git diff --check` passed.
- **State:** Requirements are pinned in `backend/app/mcp_server/requirements.txt`; no migration, database write, service change, deployment, commit, or push. The M2 implementation exists only as uncommitted files in this worktree. Claude should review and commit on this branch before M4 integration.
- **Contract questions and next action:** None blocking. The source contract's ACS example has 42 null `missing` rows and 16 `open_ended` rows with published values; the tool puts only null rows in `without_value`, as specified. Claude should review this interpretation and the implementation, then merge/deploy through its M4 process. Handbook-worthy state: the MCP server is implemented on this branch but has not been published or deployed.
