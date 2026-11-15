# CHIP beta Gate 3 staging review

Captured 2026-11-15 on staging port 8080 with a validated staging access session, after C1–C3 publication and the X5 district deployment. Values and release IDs are point-in-time evidence. No live site or database was changed.

| Image | View |
|---|---|
| [landing](screenshots/landing.png) | Place search, seven topics, three showcase counties |
| [Person County profile](screenshots/person-profile.png) | 46 indicators, including the separate ACS all-ages and PLACES adult insurance estimates; PLACES diabetes tract pattern |
| [three-county comparison](screenshots/three-county-comparison.png) | Person, Kanawha, and Fresno side by side |
| [food topic](screenshots/food-topic.png) | Published measures, source maps, and limits |
| [Person County mobile](screenshots/person-profile-mobile.png) | 390-pixel profile layout |
| [WV-01 district briefing](screenshots/wv01-district.png) | Seven Census district estimates, mapped facilities, and 28 county context links |
| [ACS district source map](screenshots/acs-district-map.png) | Census community characteristics at 119th Congress district geography |

## What to review on staging

Use an SSH tunnel to port 8080 and the staging access code stored outside the repository. Start at `/`, search for Person County, then open its profile, the three-county comparison, PDF, topics, and `/district/cd/5401`. On the district page, check that only the seven Census ACS values are labelled district estimates; county links and facilities are context. Open `/area/acs-community?measure_id=poverty_pct&geography=cd` to inspect the source map. On `/area/usda-fea`, enable HRSA sites and use an ordinary pointer click on a site table Details button at desktop and mobile widths.

The repeatable check is `cd frontend && CHIP_BETA_SCREENSHOT_DIR=../deliverables/beta/screenshots npm run test:beta`. It checks anonymous access, authenticated navigation, all 46 showcase indicators, PLACES and ACS tracts, comparison, PDF, seven topics, district briefing and source map, legacy routes, pointer clicks, keyboard skip link, mobile overflow, browser errors, and sampled body/large-text contrast. It passed on staging at `08ead46` before this report update. Gate 3 is a review of the staging beta; live promotion still requires John's approval and the separate runbook.

## Current source evidence

[`gate3_source_samples.json`](gate3_source_samples.json) records 47 checks: 15 indicators in each of Person, Kanawha, and Fresno counties across eight products, plus two WV-01 district estimates. [`verify_source_samples.py`](verify_source_samples.py) checks release-linked archived source bytes against recorded SHA-256, then compares raw source values with the lookup-backed staging API and county profile/PDF or district page. It follows the active PLACES tract release to its reviewed county parent for county source files. Run `backend/.venv/bin/python deliverables/beta/verify_source_samples.py` from the repository root. The earlier [Gate 1 report](gate1_source_samples.json) is retained as historical evidence for its older pointers. Rerun this check if any active release changes.
