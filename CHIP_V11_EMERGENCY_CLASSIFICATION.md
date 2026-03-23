# CHIP v1.1 Emergency Classification

This repo now includes an additive `analytics`-schema layer for CHIP's safer, traceable emergency-funding state-profile methodology.

## What Changed

`v1_1_emergency_classification` is a partial rollout layer that:

- keeps all existing v1 `recon` and `cdc_funding` behavior intact
- reads from `recon.profile_scope_transactions`
- separates:
  - `core_cdc_program`
  - `emergency_distributed`
  - `emergency_centralized`
  - `emergency_unresolved_excluded`
  - `other_explicitly_excluded`
- keeps emergency centralized rows out of state totals while preserving them for transparency
- adds explicit recipient traceability and review fields

## Important Rollout Boundary

This is **not** a full funding-model cutover.

- `raw_total` state-profile requests can opt into the new layer through the feature flag
- `chip_normalized` still uses the legacy v1 normalization path

Key metadata fields:

- `chip_model_version = 'v1_1_emergency_classification'`
- `chip_methodology_version = 'v1.1'`
- `chip_rollout_status = 'partial_raw_total_only'`
- `chip_state_profile_source_version = 'chip_state_profile_v1_1_emergency_classification'`
- `chip_normalization_source_version = 'v1_normalized_state_funding'`

## Recipient Classification

Recipient handling is intentionally reviewable:

- curated overrides live in `analytics.chip_recipient_classification_curated_v11_ec`
- heuristic rules live in `analytics.chip_recipient_classification_rules_v11_ec`
- resolved precedence lives in `analytics.chip_recipient_classification_resolved_v11_ec`

Precedence:

1. curated exact match
2. curated normalized match
3. heuristic rule
4. unresolved default

PHFE-like entities are seeded as curated intermediaries and excluded from state-profile totals when emergency funding routes through them.

Public universities are treated more conservatively than before:

- they can be classified as candidates
- they are not allowed to override intermediary exclusions
- unresolved university-like rows default conservative

## SQL Objects

Core views and tables:

- `analytics.chip_funding_account_classification_v11_ec`
- `analytics.chip_recipient_classification_curated_v11_ec`
- `analytics.chip_recipient_classification_rules_v11_ec`
- `analytics.chip_recipient_classification_resolved_v11_ec`
- `analytics.chip_funding_classification_v11_ec`
- `analytics.chip_state_funding_profile_v11_ec`
- `analytics.chip_centralized_funding_v11_ec`
- `analytics.chip_funding_classification_summary_v11_ec`
- `analytics.chip_state_funding_profile_validation_v11_ec`
- `analytics.chip_transaction_conservation_validation_v11_ec`
- `analytics.chip_recipient_review_queue_v11_ec`

## Validation

The new layer includes explicit conservation validation:

`included_in_profile + emergency_centralized_excluded + other_explicitly_excluded = total classified universe`

Review-oriented views:

- `analytics.chip_transaction_conservation_validation_v11_ec`
- `analytics.chip_state_funding_profile_validation_v11_ec`
- `analytics.chip_recipient_review_queue_v11_ec`

## Feature Flag

Enable raw-total state-profile routing to the new layer with:

```bash
export CDC_STATE_PROFILE_RAW_SOURCE_VERSION=v1_1_emergency_classification
```

When this flag is not set, state-profile endpoints stay on the legacy path.

## Commands

Run migrations:

```bash
cd backend
./.venv/bin/alembic upgrade head
```

Export the classification views:

```bash
cd backend
python scripts/export_chip_emergency_classification.py \
  --output-dir ../exports/chip_v11_emergency
```

## Known Limitations

- partial rollout only: normalized mode is still v1
- raw-total v1.1 state-profile routing is intentionally limited to broad statewide totals and does not replace every legacy subset filter
- unresolved emergency recipients default conservative and surface in the review queue
