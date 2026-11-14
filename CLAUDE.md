@AGENTS.md

# Claude Code notes

- The root `AGENTS.md` above is the shared workflow for every coding agent on CHIP (Codex reads it directly). Keep project rules there, not here, so Claude and Codex follow one source.
- Codex may be working in this checkout or in sibling worktrees at the same time. Check `git status`, `git worktree list`, and running processes before editing, and never revert or reformat changes you did not make.
