# CHIP agent workflow

Follow the requester's instructions and any scoped nested `AGENTS.md` before changing files. The [project handbook](docs/PROJECT_HANDBOOK.md) is the entry point, and the [project diary](docs/PROJECT_DIARY.md) is the handoff record. They guide discovery; inspect implementation and runtime state before relying on a claim.

## At task start

1. Read the handbook, recent relevant diary entries, and linked operator documentation.
2. Inspect relevant code and, where the task depends on it, current database pointers, service state, deployment, or source files.
3. Report discrepancies and correct stale documentation during the task. Preserve historical entries and unrelated work.

## Before finishing

1. Update affected handbook sections when architecture, datasets, commands, deployment, or operational behavior changes. State what is deployed and what exists only in a branch.
2. Add a concise, reverse-chronological diary entry with an ISO 8601 timestamp and explicit timezone for meaningful code, data, deployment, decision, review, or question work. Record actual outcomes, state-changing commands, verification and failures, deployment status, unresolved issues, and next action. Label proposals and unverified claims. For read-only work, say that no application changes were made.
3. Include documentation changes in the task's intended commit when committing is authorized. Do not commit or push solely because of this workflow. Mention the diary and handbook status in the completion report.

Never put secrets, access codes, cookies, or secret-bearing URLs in these documents. Preserve existing entries; add explicit corrections instead of rewriting history. If either document is missing, create a minimal version and record the gap.
