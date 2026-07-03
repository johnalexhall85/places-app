# CHIP v1 CDC Funding Map Default

## Default Model

The public CDC funding map now defaults to `chip_account_classification_v1`, labeled **CHIP Account Classification v1**.

This model uses `usaspending_fed_account.chip_account_classification` to identify CDC-related federal accounts, then maps award-linked obligations from `usaspending_fed_account.fact_award_account_breakdown` to state and county geographies. Account balance totals remain reconciliation/control totals and are not used as the map geography distribution.

## Legacy Fallback

The only visible fallback in the map UI is `chip_legacy`, labeled **CHIP Legacy**.

`chip_legacy` routes through the existing CHIP normalized funding path and relabels the response for demo clarity. Legacy code, tables, and older diagnostic funding modes remain in the backend for compatibility, but they are hidden from the normal map dropdown.

## Visible Funding Modes

Only two funding models are shown during the demo:

- CHIP Account Classification v1
- CHIP Legacy

Raw totals, canonical/budget-grounded modes, normalization toggles, and experimental modes are intentionally hidden from the CDC map UI to keep the public demo fast and easy to explain.

## Pending-Review Accounts

Accounts with `review_status = 'needs_review'` are included by default when they otherwise qualify for the public CDC map. Rejected rows are excluded.

The UI displays a calm note:

- `* Includes some accounts pending final review.`
- `Pending-review amount included: $X`

The backend response metadata includes `includes_pending_review`, `pending_review_total`, `pending_review_account_count`, `pending_review_award_count`, `unmapped_award_total`, and `last_refreshed_at`.

## Summary Views

The map reads from precomputed materialized views:

- `usaspending_fed_account.mv_chip_v1_state_funding_map`
- `usaspending_fed_account.mv_chip_v1_county_funding_map`
- `usaspending_fed_account.mv_chip_v1_unmapped_funding_map`

These views aggregate award-linked obligations by fiscal year, geography, classification version, source type, and review status. Unlinked records are included only when they have usable geography; unmapped amounts are reported separately in metadata.

## Commands

From the backend directory:

```bash
cd /home/john/places-app/backend
```

Run migrations:

```bash
alembic upgrade head
```

Refresh the new map views:

```bash
python scripts/refresh_chip_v1_funding_map_views.py \
  --classification-version chip_account_classification_v1
```

Validate FY2020-FY2026 totals:

```bash
python scripts/validate_chip_v1_map_model.py \
  --classification-version chip_account_classification_v1
```

Start the backend and frontend using the existing project commands for this repo.

## Demo Safety Notes

- Default geography is state.
- Default funding model is CHIP Account Classification v1.
- FY2025 is preferred when available; otherwise the latest completed available fiscal year is used.
- CHIP Legacy stays selectable as a backup.
- Older funding modes are hidden, not deleted.
- Refresh materialized views before the demo so the map endpoint avoids slow runtime joins.
