# CHIP beta staging review images

Captured 2026-11-15 on the staging service at port 8080 using a validated staging access session. These images show the staging build at `528e7f1`; values and active releases may change after later reviewed publications. No live site or database was changed for these captures.

| Image | View |
|---|---|
| [landing](screenshots/landing.png) | Place search, seven topics, three showcase counties |
| [Person County profile](screenshots/person-profile.png) | Published indicators, ACS tract pattern, facility context |
| [three-county comparison](screenshots/three-county-comparison.png) | Person, Kanawha, and Fresno side by side |
| [food topic](screenshots/food-topic.png) | Published measures, source maps, and limits |
| [Person County mobile](screenshots/person-profile-mobile.png) | 390-pixel profile layout |

The repeatable check is `cd frontend && CHIP_BETA_SCREENSHOT_DIR=../deliverables/beta/screenshots npm run test:beta`. It uses a staging access code file outside the repository. The district view awaits the C3 district release; archived-source checks for the review gate remain separate.
