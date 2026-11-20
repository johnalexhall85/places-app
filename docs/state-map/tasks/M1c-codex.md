# Task M1c (Codex): Puerto Rico inset and review screenshots

Assigned by Claude on 2026-11-20 after reviewing M1 and M1b. Same worktree, branch, owned paths, and rules as [M1-codex.md](M1-codex.md): no commits, no diary or handbook edits, normally formatted source. Frontend only; do not change the backend.

1. **Puerto Rico inset.** In Claude's 1280 px screenshot, Puerto Rico is drawn about the size of a state and floats between Hawaii and Texas with only a label. Draw it at the **same scale as the contiguous states**, in its own inset at the bottom right of the map (east of Florida, below the Atlantic coast), with a thin `--pdo-border` frame and a small "Puerto Rico" label inside the frame. It must not overlap any state, Hawaii, or Alaska at 1280 or 375 px. Keep its PR tile.
2. **Screenshots** with staging-captured data, saved in `/tmp/`:
   - 1280 px, FY2026 defaults, with the California panel open (both links visible);
   - 1280 px with "Exclude deobligations" checked and the Supplemental funding type;
   - 375 px with the panel open, scrolled to show both links.
   Fix anything cramped or overlapping that you see in them.
3. Run `npm test` and `npm run build`. Record the screenshot paths and results in `docs/state-map/status/codex.md`, then stop.
