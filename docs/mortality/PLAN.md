# Mortality: plan

Started 2026-11-21 by Claude, at John's request. The plan adds published death rates to the shared `area_pilot` release pipeline, so that they appear on `/area/*` maps and in the MCP server. The [contract](CONTRACT.md) sets the data rules. Mortality was the top remaining item from the RWJF/CODE "Essential Health Data" review in the [vulnerability plan](../vulnerability/PLAN.md). The coverage matrix row "Major health conditions" had no death data.

## Sources (checked by Claude on 2026-11-21)

Each source was downloaded by script from this server and archived under `data/ingest/`.

| Product | Source | Period | Levels | Uncertainty |
|---|---|---|---|---|
| `cdc_hds_mortality` | CDC Interactive Atlas of Heart Disease and Stroke, data.cdc.gov `mri7-5jtw` (heart disease) and `y5ii-knwc` (stroke) | 2022–2024, 3-year average | national, state, county | none published |
| `nci_cancer_mortality` | NCI/CDC State Cancer Profiles death rate exports | 2020–2024 | national, state, county | 95% confidence interval |
| `nchs_drug_poisoning` | NCHS Drug Poisoning Mortality by County, data.cdc.gov `rpvx-m2md` (model-based) | 2021, with 2003–2020 for history | county | 95% interval |

**Not used:**
- **CDC WONDER:** its API returns only national data, and county queries require the web form. Its data-use terms also limit use to statistical reporting and analysis.
- **VSRR provisional county overdose counts:** provisional, and understated relative to final data.
- **IHME county estimates:** their licence is not a public-domain federal release.

## Tasks

| Task | Owner | What |
|---|---|---|
| M0 | Claude | This plan, the contract, migration `c3e7a1f5b9d2` (applied to `places_staging` 2026-11-21), source archive |
| M1 | Antigravity | `cdc_hds_mortality`: backend, `/area/heart-stroke-mortality` map, MCP listing |
| M2 | Antigravity | `nci_cancer_mortality`, the same pattern, `/area/cancer-mortality` |
| M3 | Antigravity | `nchs_drug_poisoning` 2021, `/area/drug-poisoning-mortality` |
| M4 | Claude | Staging ingests and publications, tool contract amendment 6, commit, merge to `beta`, staging deploy, then **Gate A** (John's tryout) |
| M5 | Claude | Live ingest after **Gate B**; handbook, coverage matrix, diary |

Codex was at about 20% of its weekly allowance on 2026-11-20, so Antigravity writes the code. Codex does at most one read-only review.

## Out of scope for this package
- Profile sections for death rates. These need John's decision and a new endpoint like `/hazards`, because existing profile endpoints must stay byte-identical.
- Drug poisoning history 2003–2020, and heart disease and stroke 2018–2020 (`jiwm-ppbh` and its stroke twin), through the history machinery.
- Sex and race/ethnicity strata. Only the "Overall" rows are published.
- Female breast and prostate cancer. 47–48% of counties are suppressed.
- NCI trend (AAPC) and CI*Rank fields. CHIP shows no ranks or trends that it did not choose to publish.
