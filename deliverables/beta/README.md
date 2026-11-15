# CHIP beta staging review images

Captured 2026-11-15 on the staging service at port 8080 using a validated staging access session. These images show the staging build at `528e7f1`; values and active releases may change after later reviewed publications. No live site or database was changed for these captures.

| Image | View |
|---|---|
| [landing](screenshots/landing.png) | Place search, seven topics, three showcase counties |
| [Person County profile](screenshots/person-profile.png) | Published indicators, ACS tract pattern, facility context |
| [three-county comparison](screenshots/three-county-comparison.png) | Person, Kanawha, and Fresno side by side |
| [food topic](screenshots/food-topic.png) | Published measures, source maps, and limits |
| [Person County mobile](screenshots/person-profile-mobile.png) | 390-pixel profile layout |

The repeatable check is `cd frontend && CHIP_BETA_SCREENSHOT_DIR=../deliverables/beta/screenshots npm run test:beta`. It uses a staging access code file outside the repository. The district view awaits the C3 district release. The archived-source checks are documented below.

## Gate 1 source evidence

[`gate1_source_samples.json`](gate1_source_samples.json) records 30 checks: ten indicators in each of Person, Kanawha, and Fresno counties, covering seven products. [`verify_source_samples.py`](verify_source_samples.py) reads the staging community API, checks each archive against the release-linked SHA-256 recorded in `area_pilot.source_file`, and compares the raw source value with the API, profile page, and PDF. Run it with `backend/.venv/bin/python deliverables/beta/verify_source_samples.py` from the repository root. This is a point-in-time check of the releases in the report; rerun it after later publication.
