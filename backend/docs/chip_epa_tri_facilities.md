# EPA Toxics Release Inventory (TRI) reporting facilities (point overlay)

CHIP's second point layer, labelled **"TRI reporting facilities"** (not "pollution sources"). It is an optional overlay on every `/area/*` page. It is published through the shared `area_pilot` release, run, source-file, validation, review, and pointer controls under its own product identity, `epa_tri_facilities`. It does not use the area observation tables or the HRSA site tables.

- Registry: [epa_tri_facilities.json](../app/area_pilot/registry/epa_tri_facilities.json).
- Code: [tri.py](../app/area_pilot/tri.py) (retrieval, streaming parse, validation, location policy), [tri_cli.py](../app/area_pilot/tri_cli.py) (candidate, review, publish, pointer), [tri_api.py](../app/area_pilot/tri_api.py) (read API), and [TriFacilities.jsx](../../frontend/src/components/TriFacilities.jsx) (overlay).
- Migration: `f2c8d4a6b1e3`.

**Scope of this phase:** facilities, the chemicals they reported, and industry sectors. Release and waste quantities, combined totals, toxicity weighting, exposure, risk ranking, geographic aggregates, distance zones, historical backfills, and enforcement joins are **not implemented**. They are deferred to later tasks.

## Source product and reporting-year selection

| Item | Value (verified 2026-11-14) |
| --- | --- |
| Product | EPA *TRI Basic Data Files: Calendar Years 1987–Present*, national (`US`) file. It holds the "100 most-used data fields from the TRI Reporting Form R and Form A Certification Statement". |
| Landing page | https://www.epa.gov/toxics-release-inventory-tri-program/tri-basic-data-files-calendar-years-1987-present (page "Last updated on January 28, 2026") |
| Download | The page builds `https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/${year}_${geography}/csv`. CHIP fetches `…/2024_US/csv`, served as `2024_us.csv`. The server sends no `Last-Modified` or `ETag`. |
| Documentation | [Basic data files documentation PDF](https://www.epa.gov/system/files/documents/2025-09/basic_data_files_documentation_august_2024.pdf), linked from the page. It is labelled "Updated for RY 2023, August 2024"; no RY2024 edition is linked. CHIP checks seven definition phrases in it and reviews the RY2024 header exactly. |
| Reporting year | **2024**, the latest year in the page's year list. `…/2025_US/csv` returned HTTP 404 ("full data download file does not exist") on 2026-11-14. EPA's preliminary-dataset page (updated 2026-10-28) also says the most current TRI data are for calendar year 2024. |
| Processing / update date | Page: "Includes reporting forms processed as of: **November 5, 2025**". This date is stored as `processed_as_of` in the release. The reporting year (2024), the processing date (2025-11-05), and the retrieval time (2026-11-14T19:01Z) are separate fields. |
| Status | Post-preliminary basic file. The preliminary dataset is available July–October; this file was processed afterwards. EPA states these files carry the most recent versions, may include later revisions, and "may differ from data used to construct the annual TRI National Analysis". CHIP treats it as **the latest available complete annual basic file, subject to EPA revision**, not as the frozen National Analysis dataset. |
| Use conditions | Public U.S. Government data. The download page states no use restriction. |
| Snapshot | CSV SHA-256 `06dfa3a67bb4c5bd38d9e9f0f7b8bff10b95254a63169423632d7f6f251e1506` (60,550,684 bytes). Page `74b97393…7da42`, PDF `236e15f9…59bf`. Archived under `data/ingest/epa_tri_facilities/9c5856d6-156e-434e-9c2e-3e03520203af/`. |

A new reporting year is **not** picked up automatically. It needs a reviewed registry change: `reporting_year`, `source_urls.basic_csv`, the header, vocabularies, and the sector list. The fetch records `newer_year_listed: true` when the page lists a year after the registry's year.

## Data grain

| Level | Key | RY2024 count | Storage |
| --- | --- | --- | --- |
| Form (report) | `DOC_CTRL_NUM`, 13 digits `13` + `24` + 9 digits; unique required | 77,295 (68,567 Form R, 8,728 Form A) | `stage_tri_report` (raw row as a JSON array in header order) and `tri_report` (typed, **no quantities**) |
| Facility | `TRIFD` (15 characters; EPA: identifies a specific geographic location) | 21,482 | `tri_facility` (one row, one point) |
| Chemical | `TRI CHEMICAL/COMPOUND ID` (10 digits, `N###` category, or EPA generic `MIXTURE` / `TRD SECRT`) | 562 | `tri_chemical`, with **every** published name |
| Facility–chemical | (TRIFD, chemical ID) | 76,381 relationships; 637 have more than one form | `tri_facility_chemical`, with form count, form types, and names as filed |

- **Several forms per facility and chemical are distinct submissions** (different control numbers; usually different NAICS codes or partial-facility quantities; one pair differs only in control number). None is selected, merged, or dropped. The relationship records the number of forms and the form types (`R`, `A`, or both).
- **Revisions and withdrawals.** The basic file has no revision or withdrawal flag. EPA states that revisions are reflected in the file. A withdrawn form is simply absent from a later snapshot, so CHIP cannot see superseded versions. On refresh, `change_vs_active` reports forms added and forms no longer present (`reports_no_longer_present` may be withdrawals or resubmissions), plus facility-level changes.
- **Facility attributes** must be identical on every form of a TRIFD: FRS ID, name, address, city, county, state, ZIP, BIA code, tribe, latitude, longitude, datum, parent companies, and federal flag. Any conflict holds the candidate. RY2024 has 0 conflicts. Distinct facilities at identical coordinates are kept (213 coordinate groups covering 472 facilities, at most 6 at one point).
- **Industry is a form-level field.** 41 facilities have forms in more than one TRI industry sector, and 61 have more than one primary NAICS. `tri_facility.sector_codes` and `naics_codes` hold the sets; no single value is chosen.
- **Chemical names.** 15 chemical IDs carry more than one published name, for example N420 "Lead compounds" and "Lead  And Lead Compounds" on combined elemental-metal forms. All names are kept and shown, with EPA's spacing preserved.
- **Form A** certifications report no quantities; EPA fills zeroes. That is never zero emissions. No quantity is displayed in this phase.
- 529 facilities have no FRS ID in the file. They are still mapped, because the coordinates are present.

## Location policy

The source publishes coordinates as "the value that best represents the facility according to EPA's Facility Registry System (FRS)". All 21,482 RY2024 coordinates have six decimals. **`HORIZONTAL DATUM` is blank on every row**, so the datum is unpublished. CHIP stores the strings exactly as published and draws them as WGS 84 / EPSG:4326 without transformation. No accuracy or method field is published. A non-blank datum would hold the candidate for a reviewed decision.

| Status | Rule | RY2024 |
| --- | --- | --- |
| `mapped` | none of the rules below | 21,482 |
| `no_published_coordinates` | both blank | 0 |
| `invalid_coordinates` | one blank, nonnumeric, out of range, or exactly 0,0 | 0 |
| `coarse_coordinate` | either value has two or fewer decimals | 0 |

Unmapped facilities stay in `tri_facility` with `exclusion_reason` and no geometry. They are counted in the catalog (`not_mapped_by_reason`) and listed in the release report (`excluded_facilities`). Nothing is geocoded, and no city, ZIP, or county centroid is substituted.

**Boundary cross-check.** The cross-check never excludes a point. The point is intersected with TIGER/Line 2024 counties and the result is stored as `derived_county_geoid`, separate from the reported county name. On a shared edge, the lowest GEOID is recorded.

| `boundary_check` | RY2024 |
| --- | --- |
| `within_published_state` | 21,461 |
| `outside_published_state` | 2: 3232WWDRFFPBX96 (Woodruff Dam, published FL, point in GA 13087); 66118CRGLL44EWI (Kansas City, published KS, point in MO 29095). Both are on state lines. |
| `outside_chip_boundary_layer` | 19: AS 1, GU 9, MP 4, VI 5. The CHIP 2024 county layer covers the 50 states, DC, and PR only. |

## Validation

These checks **block staging**: reporting year (every `YEAR` = 2024), unique well-formed control numbers, and valid facility and chemical IDs.

These checks **hold a staged candidate**:

- Report and facility count bounds.
- Facility attribute consistency.
- Chemical attribute consistency (CAS, SRS, classification, flags, unit).
- Reviewed vocabularies: form type, federal flag, datum, unit, classification, elemental-metal flag, and the 30 sector code/label pairs.
- Location accounting.
- Report–facility–chemical relationship totals: form counts sum across relationships and facilities, and the facility and chemical sets match.
- Boundary cross-check: more than 200 `outside_published_state` holds the candidate.

Page and documentation verification fails closed when any of these change: the download template, the documentation link, the revision note, the National Analysis caveat, the processing-date phrase, the listed reporting year, or a documentation phrase.

Identity and checksums:

- **Semantic SHA-256:** the digest of (control number, SHA-256 of the full 122-column row) sorted by control number. Row order does not affect it; any value change does, including quantities that are not displayed.
- **Keyset:** the sorted control numbers.
- **Schema:** the reviewed header, fields, patterns, vocabularies, sectors, reporting year, and documentation phrases.
- **Metadata:** the source URLs, location policy, boundary, state FIPS map, detail-link pattern, usage terms, schema, and a digest of every facility's location status, boundary check, and derived county.

`review` re-hashes all three archives. It re-verifies the page and PDF, re-parses the CSV, and recomputes boundaries. It then compares every staged raw row value for value, and every report, chemical, relationship, and facility row and geometry (to 1e-9 degrees).

## Revision policy

- Release label: `TRI RY2024 basic US file`. The processing date is not part of the label.
- **Identical content** (same semantic, schema, metadata, and keyset digests): a `duplicate` run that records `confirmed_processed_as_of`. The catalog shows `last_confirmed_processed_as_of`.
- **Changed content under the same reporting-year label** (EPA reprocessing, revisions, withdrawals): held as `same_label_semantic_revision`. Read `report.change_vs_active`, then run `release-reviewed-hold` with the exact checksums and an operator note, then `approve-publish`.
- More than 5% of facilities added, removed, or changed (under any label): held as `large_change_vs_active`.
- `auto_publish` is false. The weekly timer does not include TRI.

## Storage and read API

These tables are additive. Each carries the published-release immutability trigger: `stage_tri_report`, `tri_report`, `tri_chemical`, `tri_facility` (`geometry(Point,4326)`, GiST index on mapped rows, constraints that tie geometry, exclusion, and boundary status together), and `tri_facility_chemical` (with foreign keys to both facility and chemical). About 168 MB for one release.

Protected routes (demo gate; Nginx `/api/area/tri/*`), all pinned to an explicit published `release_id`:

| Route | Purpose |
| --- | --- |
| `GET /area/tri/catalog` | Active pointer, published releases, reporting year, processing date, counts, sector options with mapped counts, interpretation, limitations, detail-link pattern |
| `GET /area/tri/map?release_id&bbox&zoom[&sector][&chemical]` | Points at zoom ≥ 8 with ≤ 2,000 facilities; otherwise 64-px Web Mercator grid clusters (cap 3,000 → 413). Cluster counts sum to the table total. |
| `GET /area/tri/table?…&limit≤200&offset` | Paged facilities, same WHERE clause as the map |
| `GET /area/tri/detail?release_id&facility_id[&chemical_limit≤200&chemical_offset]` | Facility, address as reported, sectors, NAICS, form counts, paged chemical list (names as filed, CAS, form types, number of forms), published coordinates, derived county, facilities at the location, EPA link. No quantities. |
| `GET /area/tri/chemicals?release_id[&q][&limit≤200&offset]` | Paged, searchable chemical list (name, CAS, or ID) with facility and mapped-facility counts |

- **Filter semantics.** `sector` is a comma list; omitted means all 30 reviewed sectors. A facility matches if any of its forms is in a selected sector. `chemical` is one TRI chemical ID, tested with an EXISTS on `tri_facility_chemical`, so each facility appears once however many forms it filed. Both filters apply at facility level. An unknown chemical returns 400, and an unpublished release returns 404.
- **EPA link.** The link is the EPA Facility Registry Service program-facility page keyed by the TRI ID: `https://frs-public.epa.gov/ords/frs_public2/fii_query_dtl.disp_program_facility?pgm_sys_id_in={TRIFD}&pgm_sys_acrnm_in=TRIS`. It was verified on 2026-11-14 for six RY2024 IDs, including one with no FRS ID in the file; a made-up ID returns an empty report. It is not checked per facility. Envirofacts' TRI Explorer facility-profile URL redirected to a generic page and was not used.

## Frontend

The overlay is "Show TRI reporting facilities", below the HRSA toggle in a shared right-hand overlay column. It is off by default, and its on/off state, sectors, and chemical (same release only) persist in session storage.

- **Independence.** It has its own catalog, release, cache (150 entries), AbortControllers, request IDs, and release/bbox/filter echo checks, and it rejects responses whose map and table totals differ. Area measure or dataset switching does not refetch it, and its filters do not refetch HRSA sites. **Both overlays can be shown at once**: TRI is in pane `chip-tri-facilities` (z 645) and HRSA in `chip-health-center-sites` (z 640).
- **Symbols.** TRI facilities are purple circles. Colocated facilities form a purple numbered square that opens a list of distinct facilities. Clusters are rounded squares with counts, labelled "display grouping, not an exposure zone".
- **Panel.** The panel shows the interpretation bullets, a paginated chemical search (20 per page), a sector checklist, the table with keyboard **Details** buttons (50 per page), and a detail region that receives focus and pages chemicals 50 at a time.
- **Narrow screens.** The overlay column sits under the controls, as the HRSA toggle did before this change, and can overlap the open area table. Collapse either panel.

## Manual operations (from `backend/`)

```bash
# Candidate (never publishes). Prints candidate_id, checks, counts, and the three checksums.
.venv/bin/python -m app.area_pilot.tri_cli fetch-stage-validate
# Re-verify archives and every staged/read-model row; copy the checksums it prints.
.venv/bin/python -m app.area_pilot.tri_cli review CANDIDATE
.venv/bin/python -m app.area_pilot.tri_cli approve-publish CANDIDATE --semantic-sha256 S --schema-sha256 H --metadata-sha256 M
# Only for same_label_semantic_revision or large_change_vs_active holds, after reading report.change_vs_active:
.venv/bin/python -m app.area_pilot.tri_cli release-reviewed-hold CANDIDATE --semantic-sha256 S --schema-sha256 H --metadata-sha256 M --operator-note "…"
# Pointer recovery (this product only; other products are unaffected):
.venv/bin/python -m app.area_pilot.tri_cli rollback RELEASE      # a retained published TRI release
.venv/bin/python -m app.area_pilot.tri_cli deactivate            # hide the overlay (catalog shows no release)
```

- One run takes about 40 s and about 420 MB RSS. The CSV is streamed; only compact per-form fields are held.
- Downloads use a temporary `.part` file, a byte cap, and three retries. `disk_guard` checks space first, and an `ingest.lock` file lock prevents concurrent runs.
- Failed retrievals and blocking failures record a held release with the retained files and never move the pointer.
- Published rows remain queryable by release ID after a rollback or deactivation. Nothing is deleted automatically.
- **Application rollback:** restore the webroot from `data/deploy-recovery/tri-facilities-20261114/webroot-before/` (`rsync -a --delete`), check out a commit before the TRI change, and restart `places-backend`. Leave migration `f2c8d4a6b1e3` in place; its tables are inert without the router. Prefer `deactivate` to a downgrade.

## Limitations

- TRI covers only facilities in covered sectors above employee and chemical thresholds. Absence does not mean no pollution, and presence does not mean a violation, exposure, or risk.
- A reported chemical was manufactured, processed, or otherwise used above a threshold. It was not necessarily released, or released to air.
- Reporting in 2024 does not show that a facility operates today. The Envirofacts `fac_closed_ind` field is not used.
- The coordinate datum and accuracy are unpublished.
- One reporting year only. The data are not the frozen National Analysis dataset and may change when EPA reprocesses the file.

## 2026-11-14 publication and deployment (Claude; final browser run 19:10:58Z)

- Migration `e9b3f6a2c4d8` → `f2c8d4a6b1e3`.
- Candidate `3b6ecfb1-bf58-4122-a71f-432027994bd7`: ready, 11/11 checks. A re-fetch was recorded as a duplicate.
- `review` verified 3 archives, 77,295 staged forms and reports, 562 chemicals, 76,381 relationships, 21,482 facilities, and the geometries.
- An independent raw-CSV comparison for 3 facilities matched, including Tesoro Carson: 195 forms, 37 chemicals, sectors 324 and 4247.
- Published at 2026-11-14T19:03:10Z with checksums:
  - Semantic `b0d831fcbf3f7bfb3168f208be0cf8bfee4aae61dd5ed11f45a22d684042f0ae`
  - Schema `5a37e7076a689bdd067947080ef7d858aea3d2b9872cd9675e379417a78fe143`
  - Metadata `71b6ea2703502c4fca201e2aed1168f6d4dfa1eb62099a008ebef47a4ea5aa77`
  - Keyset `fae13bd72a936664b39d69873ae6f2b30d1a29e58e8727312a50d8255254f6bc`
- Pointer drill: `deactivate`, then a refused rollback to the HRSA release, then `rollback` to `3b6ecfb1…`. The six other product pointers were unchanged.

Performance (in-process, live DB; map median of 3 runs):

| View | Facilities | Map query | Map response | Table query |
| --- | --- | --- | --- | --- |
| National clusters, zoom 4 (conterminous US) | 21,275 in 55 clusters | 88 ms | 10 KB | 15 ms |
| Same view, chemical filter (ethylene oxide / lead compounds) | | 45–50 ms | | 27–54 ms |
| Through Nginx, authenticated, national | | 95–110 ms | | |
| Houston, zoom 10 | 323 points | 2.5 ms | 92 KB | |
| Chicago, zoom 9 | 449 points | 2.7 ms | 129 KB | |
| Los Angeles, zoom 11 | 206 points | 1.8 ms | | |
| Rural NW Iowa, zoom 9 | 48 points | 10 ms | | |
| Rural SW Georgia, zoom 9 | 23 points | 1.5 ms | | |
| Rural West Texas, zoom 8 | 103 points | 2 ms | | |

Other timings: catalog 50 ms, chemical page 9 ms, chemical search 15 ms, detail 11 ms. Map and table totals matched in every view.

Deployment:

- The webroot was backed up to `data/deploy-recovery/tri-facilities-20261114/`, then `rsync -a --delete frontend/dist/ /var/www/places/` was run, and the installed files match the build by SHA-256. It was redeployed twice for layout fixes, to overlay stacking and detail label width.
- `places-backend` was restarted at 2026-11-14T19:04:11Z. `/openapi.json` lists the five `/area/tri/*` routes.
- Anonymous requests to all five through Nginx and directly return 401.

**Authenticated browser check (real demo session through Nginx; 23/23 passed).** The check used a temporary access code per run (`agent-verification-tri-20261114`, 2 uses, 30-minute expiry), created and deactivated by the verification script. Six runs left six inactive codes, each used once. No code was ever printed or stored. The check covered:

- National clusters, then cluster selection, then points.
- A marker click that opens the detail with chemicals and the FRS link, with no area popup.
- Keyboard Details that moves focus to the heading.
- TRI and HRSA panes shown together.
- The ethylene-oxide filter: it sent `chemical=0000075218`, made no HRSA refetch, and listed unique rows.
- Rapid sector switching without errors.
- Measure switching that refetches only the area map.
- `/area/epa-aqi` and `/area/acs-2024` with both overlays.
- Catalogs for all 5 area products and HRSA returning 200 with their unchanged pointers.
- Funding map and legend returning 200.
- No page errors, and no horizontal scroll at 390 px.
