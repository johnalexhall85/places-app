# HRSA health center service-delivery and look-alike sites (point overlay)

CHIP's first point layer. It is an optional overlay on every `/area/*` page, published through the shared `area_pilot` release, review, and pointer controls. It does not use the area observation tables. Registry: [hrsa_hc_sites.json](../app/area_pilot/registry/hrsa_hc_sites.json). Code: [hrsa_sites.py](../app/area_pilot/hrsa_sites.py) (retrieval, validation, location policy), [hrsa_sites_cli.py](../app/area_pilot/hrsa_sites_cli.py) (candidate, review, publish, pointer), [hrsa_sites_api.py](../app/area_pilot/hrsa_sites_api.py) (read API), [HealthCenterSites.jsx](../../frontend/src/components/HealthCenterSites.jsx) (overlay). Migration `e9b3f6a2c4d8`.

## Source product

| Item | Value (verified 2026-11-14) |
| --- | --- |
| Product | HRSA *Health Center Service Delivery and Look-Alike Sites* (HCSD), published by HRSA BPHC through the HRSA Data Warehouse |
| Landing pages | https://data.hrsa.gov/topics/health-centers/ and https://data.hrsa.gov/data/download |
| Files | `https://data.hrsa.gov/DataDownload/DD_Files/Health_Center_Service_Delivery_and_LookAlike_Sites.csv` and `..._Data_Download_Metadata.xlsx` (data dictionary, sheet `SITE_FQHC_FQHC_LAL_DD_META_VX`) |
| Use conditions | Download page, HCSD terms: "Published by: HRSA, Bureau of Primary Health Care (BPHC). Usage limitations: None." Re-verified on every fetch. |
| Refresh | Topic page: "Refresh Cycle: Daily". CHIP refresh is manual. |
| Snapshot date | `Data Warehouse Record Create Date` (one value for all rows, required). It is stored as `source_after.snapshot_date` and in the release label `HCSD site snapshot YYYY-MM-DD`. The retrieval time is recorded separately (`report.retrieved_at`, `source_file.retrieved_at`). There is no annual observation period. |
| Not used | CMS FQHC ownership records and UDS organization-level performance data. These are different products. |

### Sites versus organizations

- **One row is one site.** `BPHC Assigned Number` (`BPS-H80-nnnnnn` or `BPS-LAL-nnnnnn`) is the key. It must be unique; duplicates or malformed IDs block staging.
- **The parent organization is an attribute.** It comes from `Health Center Number` (H80CS…/LALCS…) and `Health Center Name`. It is never merged with the site. The 2026-11-14 file has 19,616 sites, 1,593 health center numbers, and 1,523 organization names.
- **Program consistency.** The program must agree with both identifiers: `BPS-H80` with FQHC and `H80CS`, and `BPS-LAL` with Look-Alike and `LALCS`. Any conflict holds the candidate.
- **Excluded from display.** Organization (awardee) addresses, Medicare billing numbers, NPI numbers, congressional and senator fields, and `Site Added to Scope this Date` (marked **Restricted** in the metadata) are never exposed. They remain only in the raw staging record.

### Classifications and the default

| Filter | Source field | Values (code) | Default |
| --- | --- | --- | --- |
| Program | Health Center Type | FQHC awardee (`fqhc`), FQHC Look-Alike (`look_alike`) | both |
| Site type | Health Center Type Description | Service Delivery Site, Administrative/Service Delivery Site, Administrative | **service-delivery types only**; administrative-only is opt-in |
| Location type | Health Center Location Type Description | Permanent, Seasonal, Mobile Van (published base address), Unknown | all |
| Setting | Health Center Service Delivery Site Location Setting Description | All other clinic types, School, Hospital, Nursing home, Tribal, Correctional facility, Transitional care in carceral setting, Unknown | all; Domestic Violence is never selectable |

- **Eligibility.** Only `Site Status Description = Active` is eligible (every row on 2026-11-14 was Active). Pending Verification, Terminated, and Unknown rows are retained but never displayed.
- **Vocabulary.** The live file has three values missing from the HRSA metadata valid-value lists: "Transitional Care in Carceral Setting", "Health Center/Applicant", and "Subrecipient". They were reviewed and registered. Any other unreviewed value holds the candidate.
- **Not in this file.** The file does not list services offered or new-patient acceptance, and the UI says so. School, hospital, and correctional sites may serve only that institution's population.

## Location policy (suppression and coordinate quality)

HRSA's X/Y are documented as Esri-geocoded longitude and latitude in decimal degrees. No datum or quality score is published. CHIP stores the published strings exactly. It builds `geometry(Point,4326)` from them without transformation, recording WGS 84 longitude/latitude as the interpretation. CHIP never geocodes an address, reconstructs a withheld location, or substitutes a city, ZIP, or county centroid.

Each site gets exactly one `location_status`. Only `mapped` rows have geometry (enforced by DB constraints).

| Status | Rule | 2026-11-14 |
| --- | --- | --- |
| `mapped` | none of the below; `boundary_check` = `within_published_county` (19,186) or `outside_chip_boundary_layer` (14 island-area sites: GU, MP, VI, FM) | 19,200 |
| `suppressed_source_policy` | Location setting "Domestic Violence" (HRSA suppresses street, number, and ZIP). No coordinate, address, ZIP, or phone is kept in the read model, even if the file carried them. | 14 |
| `no_published_coordinates` | X and Y blank (361 rows have state `XX` / "Not Determined"; 1 CA, 1 PW) | 363 |
| `invalid_coordinates` | one of X/Y missing, nonnumeric, out of range, or 0,0 | 0 |
| `approximate_shared_coordinate` | the same X/Y is shared by sites in different normalized cities, or a pair with ≤3 decimals is shared by sites with different street addresses (a place-level geocode) | 38 (AS 8, FM 14, MH 6, PW 10) |
| `coarse_coordinate` | X or Y has ≤2 decimal places | 1 (FM) |
| `published_county_not_in_boundary_layer` | state is in the TIGER 2024 layer but the published county FIPS is blank or absent | 0 |
| `outside_published_county` | point does not intersect the TIGER 2024 county matching its published FIPS (hold if >100) | 0 |

Distinct sites at identical coordinates are kept: 1,547 coordinate groups, with up to 15 sites at one point. The map draws each group as one square marker that lists every site.

## Validation (holds the candidate on failure)

**Retrieval checks:**
- Download-page links, the usage terms, and the DV suppression note are present.
- The topic-page description and its "Updated / Refresh Cycle" text are present.
- The metadata header is unchanged, and all 55 CSV columns are documented.
- Definition phrases for X/Y, the site ID, the status, the site type, and the snapshot date are unchanged.
- Every exposed attribute is marked `Public`.
- The CSV header matches exactly (the header ends with a comma; data rows have 55 values).
- Downloads are byte-capped with bounded retries. `Content-Length` is compared only for unencoded bodies, because the HTML pages are gzip-encoded.

**Candidate checks** (stored in `area_pilot.validation`):
- `source_row_bounds` (15,000–26,000)
- `site_ids_valid_unique`
- `site_program_consistency`
- `classification_vocabulary`
- `single_snapshot_date`
- `location_accounting`
- `suppression_enforced`
- `boundary_cross_check`

**Hold reasons:**
- `blocking_validation_failed` — duplicate or malformed IDs, or a mixed snapshot date. Nothing is staged.
- `validation_failed`
- `same_label_semantic_revision` — the same snapshot label with different content.
- `large_change_vs_active` — more than 10% of the active sites are added, removed, or changed. The report lists counts and samples.

**Checksums:**
- `semantic_sha256` covers all published columns except the HRSA processing date, ordered by site ID.
- `keyset_sha256` covers the sorted site IDs.
- `schema_sha256` covers the header, vocabularies, exposed fields, and metadata-dictionary digest.
- `metadata_sha256` covers the location policy and per-site location classification. It excludes the snapshot date.

Identical content fetched on a later day is recorded as a `duplicate` run with `confirmed_snapshot_date`. The catalog reports this as `last_confirmed_snapshot_date`.

**`review`:**
- re-hashes the four archived files (`download_page`, `topic_page`, `metadata_xlsx`, `sites_csv`);
- re-parses the archived CSV and metadata;
- reruns the location rules and the PostGIS boundary check;
- requires every raw staging row, read-model row, attribute set, and geometry (to 1e-9 degrees) to match.

`approve-publish` reruns `review` inside the publishing transaction and requires the exact three reviewed checksums.

## Storage and API

- **Storage.**
  - `area_pilot.stage_hrsa_site`: the verbatim JSON source row; the API never reads it.
  - `area_pilot.site_hrsa`: the typed read model, with `geom geometry(Point,4326)`, a partial GiST index on mapped rows, and selection and table-order indexes.
  - Both tables use the shared trigger that makes published-release rows immutable. Raw archives live in `data/ingest/hrsa_hc_sites/<run UUID>/`, which is gitignored.
- **API.** Protected by the demo-access gate, read-only. External paths are `/api/area/sites/...`; Nginx strips `/api`. All site requests require an explicit published `release_id`.
  - `GET /area/sites/catalog`: active release, published releases, snapshot and retrieval dates, counts by location status, filter options with mapped counts, limitations, location rules, and usage terms.
  - `GET /area/sites/map?release_id&bbox&zoom[&program&site_type&location_type&setting]`:
    - `bbox` is required. Points are returned only when zoom ≥ 8 and ≤ 2,000 eligible sites are in view.
    - Otherwise it returns Web Mercator grid clusters (64 px cells). Their counts sum exactly to `total`, or the server returns 409.
    - More than 3,000 clusters returns 413. Results are never silently truncated.
    - Each response includes the note that clusters are display groupings, not service areas.
  - `GET /area/sites/table?release_id&bbox[&filters]&limit≤200&offset`: the same WHERE clause as the map, so `total` equals the map's `total`.
  - `GET /area/sites/detail?release_id&site_id`: mapped, eligible sites only (suppressed and unmapped records return 404). Includes published X/Y strings, boundary check, sites at the same location, and the services note.
- **Overlay behavior.**
  - It is off by default.
  - Its state is kept in `sessionStorage`, so it survives switching area datasets.
  - Its release, filters, cache (keyed by release-pinned URL, 150 entries), `AbortController`, and stale-response guard are separate from the area layer.
  - Markers live in their own Leaflet pane with `bubblingMouseEvents: false`, so marker clicks never select area polygons.
  - The table "Details" buttons give keyboard access to the same detail, and focus moves to the detail heading.

## Manual operations (from `backend/`)

```bash
# Candidate (never publishes). Prints candidate_id, checks, counts, and the three checksums.
.venv/bin/python -m app.area_pilot.hrsa_sites_cli fetch-stage-validate
# Re-verify archives and every staged/read-model row; copy the checksums it prints.
.venv/bin/python -m app.area_pilot.hrsa_sites_cli review <CANDIDATE>
.venv/bin/python -m app.area_pilot.hrsa_sites_cli approve-publish <CANDIDATE> \
  --semantic-sha256 <S> --schema-sha256 <C> --metadata-sha256 <M>
# Only for same_label_semantic_revision or large_change_vs_active holds, after reading report.change_vs_active:
.venv/bin/python -m app.area_pilot.hrsa_sites_cli release-reviewed-hold <CANDIDATE> \
  --semantic-sha256 <S> --schema-sha256 <C> --metadata-sha256 <M> --operator-note "<what was reviewed>"
# Pointer recovery (this product only; other products are unaffected):
.venv/bin/python -m app.area_pilot.hrsa_sites_cli rollback <PUBLISHED_RELEASE>
.venv/bin/python -m app.area_pilot.hrsa_sites_cli deactivate      # hides the overlay; data stay queryable by release
```

- **Refresh.** Run `fetch-stage-validate`. Identical content records a duplicate. Changed content yields a new `ready` candidate, or a hold for changes larger than 10%. Then run `review` and `approve-publish`. Do not release holds you cannot explain.
- **Not scheduled.** This product is **not** on `chip-area-refresh.timer`.
- **Disk.** Each fetch archives about 15 MB.
- **Application rollback.** Restore the webroot from `data/deploy-recovery/hrsa-sites-20261114/webroot/` (checksums in `webroot.sha256`), check out the matching code, and restart `places-backend`. Leave migration `e9b3f6a2c4d8` in place; it is additive.

## Limitations

- **Snapshot.** The overlay shows one reviewed HRSA snapshot, not live data. Sites open, close, or move daily.
- **Missing locations.** 416 listed sites are not drawn. The panel states this count.
- **Island areas.** No CHIP boundary covers GU, MP, VI, AS, FM, MH, or PW, so their points cannot be boundary-checked.
- **Geocoding.** Geocodes are HRSA's, and no quality score exists. The approximate-location rule is a CHIP heuristic based on shared coordinates and published precision.
- **Mobile layout.** On narrow screens the panel starts collapsed. The existing area panels already overlap there.
- **Out of scope.** No service areas, travel times, nearest-provider results, county rates, UDS joins, or historical snapshots.

## 2026-11-14 publication and deployment (Claude)

- **Migration:** `alembic upgrade head` moved `d3a7e5c1b9f2` to `e9b3f6a2c4d8`.
- **First fetch:** candidate `38f71065-c3b9-4f59-b5f9-7da530da7e6e` was **held**. The cause was a bug in the new length check (gzip-encoded page), not the source. The check was fixed; the held row is retained as evidence.
- **Second fetch:** candidate `e5cdea05-6518-454c-9418-353410c2309d` was **ready**, with all 8 checks passing.
  - Snapshot 2026-11-14 (CSV `Last-Modified` Sat, 14 Nov 2026 12:11:20 GMT); retrieved 2026-11-14T18:07:47Z.
  - CSV SHA-256 `08b01537495bb6a483c0e9805b9eef102e05492ce2ec4f97b6202f03366da436` (14,245,997 bytes); metadata XLSX `6acf53836fe9d581485f609e08797997e79bb1439c8dffa944bf099ce8b2d2b4`.
- **Re-run:** recorded a `duplicate` run on the same candidate.
- **Review:** verified 4 archives, 19,616 staged and read-model rows, and 19,200 geometries.
- **Published** at 2026-11-14T18:08:17Z with these checksums:
  - semantic `318595953d77ad652099281462d1474864ba06d173a25a40f1eebf66aed9b90a`
  - schema `2096dab123ce5952dc1b98041d3ed78b507384de6460cfe5266b39459912e0ab`
  - metadata `2cb368bf33bd75cb86520bbbf9c35faf28a07e1a0e7a52bcb351c470a048d2f9`
  - keyset `91f71bb61a942202bb83aa358a545d2b7cabbb4293ba85da872d30994c658adc`
- **Pointer drill:**
  - `deactivate` left 0 active pointers for this product.
  - A cross-product rollback to the EPA AQI release was refused.
  - `rollback e5cdea05…` restored the pointer.
  - All five area pointers were unchanged. A write to a published site row was rejected.
- **Counts:**

  | Measure | Sites |
  | --- | --- |
  | Source rows | 19,616 |
  | Active (eligible status) | 19,616 |
  | Mapped | 19,200 |
  | Under the default service-delivery filter | 18,231, of which 17,865 mapped |
  | Not mapped: suppressed | 14 |
  | Not mapped: no coordinates | 363 |
  | Not mapped: approximate | 38 |
  | Not mapped: coarse | 1 |

- **Timings** (in-process, warm, default filters, live DB). Map and table totals were equal in every view:

  | View | Result | Time | JSON size |
  | --- | --- | --- | --- |
  | National, zoom 4 | 53 clusters, 17,365 sites | 70–91 ms | ~9–10 KB |
  | World, zoom 2 | 18 clusters | 75 ms | — |
  | Los Angeles, zoom 11 | 347 points | 3–15 ms | ~190–200 KB |
  | NYC metro, zoom 9 | 543 points | 3–19 ms | ~290–310 KB |
  | Rural Montana, zoom 8 | 23 points | — | 14 KB |
  | Western Kansas, zoom 9 | 2 points | — | — |
  | Catalog | — | 25–53 ms | 7 KB |
  | Detail | — | 3–10 ms | — |

- **Deployment:**
  - Webroot backed up to `data/deploy-recovery/hrsa-sites-20261114/`.
  - `rsync -a --delete frontend/dist/ /var/www/places/`, then `systemctl restart places-backend`.
  - Through Nginx, all four `/api/area/sites/*` routes and `/api/area/catalog` return 401 anonymously.
- **Browser verification:** headless Chromium loaded the Nginx-served bundle. Its `/api` calls went to a loopback-only verification instance of the same code against the live DB (demo gate off, port 8765, stopped afterwards). This is **not** an authenticated session: creating a demo access code was denied to the agent. Results:
  - Labeled clusters were shown on the PLACES, EPA AQI, and ACS pages.
  - Cluster clicks drilled down to 176 points and 12 colocated markers.
  - A marker click opened the site detail and no area popup; a colocated marker listed 3 sites.
  - Area polygon popups still worked with the overlay off, with clusters, and with points.
  - Keyboard Enter on a table "Details" button focused the detail.
  - The administrative-only filter changed counts.
  - A measure switch issued no site requests.
  - The overlay persisted across area pages and could be toggled off.
- **Outstanding:** an operator should repeat the check with a real demo session.
