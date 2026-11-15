# CHIP beta Gate 3 staging review

Captured 2026-11-15 on staging port 8080 with a validated staging access session, after BRFSS B1–B3 publication and product Y1–Y5 deployment. Values and release IDs are point-in-time evidence. No live site or database was changed.

| Image | View |
|---|---|
| [landing](screenshots/landing.png) | State and county search, seven topics, one example state, three showcase counties |
| [Person County profile](screenshots/person-profile.png) | 46 indicators, including separate ACS all-ages and modeled PLACES adult insurance estimates; 13 direct BRFSS state survey companions; PLACES diabetes tract pattern |
| [three-county comparison](screenshots/three-county-comparison.png) | Person, Kanawha, and Fresno side by side |
| [food topic](screenshots/food-topic.png) | Published measures, source maps, and limits |
| [Person County mobile](screenshots/person-profile-mobile.png) | 390-pixel profile layout |
| [WV-01 district briefing](screenshots/wv01-district.png) | Seven Census district estimates, mapped facilities, and 28 county context links |
| [ACS district source map](screenshots/acs-district-map.png) | Census community characteristics at 119th Congress district geography |
| [North Carolina state profile](screenshots/north-carolina-state-profile.png) | 33 state indicators: ACS, 20 BRFSS, CMS; facilities, county/district links, funding |
| [Kentucky state profile](screenshots/kentucky-state-profile.png) | 2023 BRFSS rows marked not published; 2022 dental visit retained |
| [BRFSS state map](screenshots/brfss-state-map.png) | 52 state shapes, direct survey values, source status, confidence intervals, CDC median reference |
| [North Carolina state mobile](screenshots/north-carolina-state-profile-mobile.png) | State profile header and actions at 390 pixels |

## What to review on staging

Use an SSH tunnel to port 8080 and the staging access code stored outside the repository. Start at `/`, search for North Carolina, then open its 33-indicator state profile, PDF, and `/area/brfss?measure_id=diabetes`. Inspect the 2023 not-published status on `/community/state/21` and the separate 2022 dental visit. Search for Person County to review the 13 labelled BRFSS state survey companions on PLACES cards and its CSV/PDF, then open the three-county comparison, topics, and `/district/cd/5401`. On the district page, only the seven Census ACS values are district estimates; county links and facilities are context. The ACS district source map remains at `/area/acs-community?measure_id=poverty_pct&geography=cd`. On `/area/usda-fea`, enable HRSA sites and click a site table Details button at desktop and mobile widths.

The repeatable check is `cd frontend && CHIP_BETA_SCREENSHOT_DIR=../deliverables/beta/screenshots npm run test:beta`. It checks anonymous access, authenticated state and county search/navigation, 33 state and 46 county indicators, state and county PDFs, BRFSS state map and source status, PLACES and ACS tracts, comparison, seven topics, district briefing and source map, legacy routes, pointer clicks, keyboard skip link, mobile overflow, browser errors, and sampled contrast. It passed on staging after Y5 deployment at `9d9069f`. Gate 3 is a review of the staging beta; live promotion still requires John's approval and the separate runbook.

## Current source evidence

[`gate3_source_samples.json`](gate3_source_samples.json) records 59 checks: 15 indicators in each of Person, Kanawha, and Fresno counties across eight products, two WV-01 district estimates, and four BRFSS measures in each of North Carolina, West Virginia, and Kentucky. Three Kentucky 2023 rows are checked as absent in CDC's archived selection and `not_published` in the state profile/PDF; its 2022 dental row is checked as published. [`verify_source_samples.py`](verify_source_samples.py) checks release-linked archived source bytes against recorded SHA-256, then compares raw source values, BRFSS confidence limits and response counts with the lookup-backed staging API and rendered profiles/PDFs. It follows the active PLACES tract release to its reviewed county parent for county source files. Run `backend/.venv/bin/python deliverables/beta/verify_source_samples.py` from the repository root. The earlier [Gate 1 report](gate1_source_samples.json) is retained as historical evidence for its older pointers. Rerun this check if any active release changes.
