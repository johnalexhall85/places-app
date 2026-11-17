# Task M3c (Antigravity): accept contract item 2a

Assigned by Claude, 2026-11-17. Same rules as before (owned paths only, no commits). This task is small.

Claude reran your M3b suite against staging: 31/44 passed. **Every failure is one cause.** Claude accepted this change from Codex as amendment item 2a:

> **2a.** In `get_measure_across_areas`, `uncertainty.kind` and `uncertainty.label` also move into `data.measure`, as the keys `uncertainty_kind` and `uncertainty_label`. Each row keeps only its own interval values (`low`/`high` or `moe`).

Update `run_eval.py` and `test_checks.py` to expect exactly this:
- `data.measure` must contain `uncertainty_kind` and `uncertainty_label`;
- compact rows must not repeat `kind`/`label`;
- check the row's interval keys against `data.measure.uncertainty_kind` (`ci95` → `low`/`high`; `moe90` → `moe`; `none` → no interval keys).

Keep `--validate` and `test_checks.py` passing. Add one line to your status file. Report in three lines or fewer.
