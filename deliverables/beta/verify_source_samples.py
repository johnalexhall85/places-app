"""Check current staging county and district values against release-linked source archives.

Run from the repository root with backend/.venv/bin/python. Reads staging and archive
metadata only; it does not publish or modify application data.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from decimal import Decimal
from pathlib import Path

import requests
from dotenv import dotenv_values
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright
from pypdf import PdfReader
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8080"
CODE_FILE = Path("/home/john/.local/share/chip/staging-beta-access-code")
REPORT = Path(__file__).with_name("gate3_source_samples.json")
COUNTIES = ("37145", "54039", "06019")
SAMPLES = {
    "places": ("dental_crudeprev", "access2_crudeprev", "diabetes_crudeprev", "obesity_crudeprev"),
    "acs": ("B19013_001E",),
    "acs_profile": ("total_population", "poverty_pct", "uninsured_pct"),
    "ahrf": ("phys_nf_prim_care_pc_exc_rsdt_23",),
    "clh": ("ACS_PCT_HH_BROADBAND_ANY",),
    "cms_gv": ("om_beneficiaries",),
    "epa_aqi": ("median_aqi", "days_with_aqi"),
    "usda_fea": ("low_income_low_access_pct", "snap_stores_per_1000"),
}


def number(value):
    return Decimal(str(value))


def csv_rows(path):
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as source:
        yield from csv.DictReader(source)


def main():
    session = requests.Session()
    code = CODE_FILE.read_text().strip()
    auth = session.post(f"{BASE}/api/demo-access/validate", json={"access_code": code}, timeout=20)
    auth.raise_for_status()
    profiles = {}
    for geoid in COUNTIES:
        response = session.get(f"{BASE}/api/community/county/{geoid}", timeout=40)
        response.raise_for_status()
        profiles[geoid] = response.json()
    releases = {row["product"]: row["release_id"] for row in profiles[COUNTIES[0]]["values"]}
    if any({row["product"]: row["release_id"] for row in profiles[g]["values"]} != releases for g in COUNTIES):
        raise AssertionError("The showcase profiles use different active releases")

    source_files = {}
    engine = create_engine(dotenv_values(ROOT / "backend/.env")["DATABASE_URL"])
    with engine.connect() as db:
        # The active PLACES tract release carries county observations from its reviewed parent.
        # This reads release provenance only; published values continue to come from lookup via the API.
        places_parent = db.execute(text("SELECT parent_county_release_id FROM area_pilot.release WHERE id=:release"),
                                   {"release": releases["places"]}).scalar_one()
        if not places_parent:
            raise AssertionError("Active PLACES release has no county source parent")
        def archive(product, role):
            key = (product, role)
            if key in source_files:
                return Path(source_files[key]["path"])
            source_release = str(places_parent) if product == "places" and role.startswith("page_") else releases[product]
            rows = db.execute(text("SELECT path, sha256 FROM area_pilot.source_file "
                                   "WHERE release_id=:release AND role=:role ORDER BY path"),
                              {"release": source_release, "role": role}).mappings().all()
            for row in rows:
                path = Path(row["path"])
                if not path.is_file():
                    continue
                with path.open("rb") as source_file:
                    digest = hashlib.file_digest(source_file, "sha256").hexdigest()
                if digest != row["sha256"]:
                    raise AssertionError(f"Archived source checksum mismatch: {product} {role}")
                source_files[key] = {"path": str(path), "sha256": digest, "release_id": source_release}
                return path
            raise AssertionError(f"No intact archive tied to active release: {product} {role}")

        source = {}
        # CDC PLACES API pages retained with the active county release.
        for page in range(4):
            for record in json.loads(archive("places", f"page_{page:03d}").read_text()):
                geoid = record.get("countyfips")
                if geoid in COUNTIES:
                    for measure in SAMPLES["places"]:
                        source[(geoid, "places", measure)] = number(record[measure])
        # ACS 2020-2024 API responses, one county request per state.
        for state in {geoid[:2] for geoid in COUNTIES}:
            response = json.loads(archive("acs", f"county_{state}").read_text())
            headers = response[0]
            for values in response[1:]:
                row = dict(zip(headers, values))
                geoid = row["state"] + row["county"]
                if geoid in COUNTIES:
                    source[(geoid, "acs", "B19013_001E")] = number(row["B19013_001E"])
        # The new ACS community profile uses published subject-table estimates, not calculated percentages.
        profile_variables = {"total_population": "S0101_C01_001E", "poverty_pct": "S1701_C03_001E",
                             "uninsured_pct": "S2701_C05_001E"}
        for state in {geoid[:2] for geoid in COUNTIES}:
            response = json.loads(archive("acs_profile", f"county_{state}").read_text())
            headers = response[0]
            for values in response[1:]:
                row = dict(zip(headers, values))
                geoid = row["state"] + row["county"]
                if geoid in COUNTIES:
                    for measure, variable in profile_variables.items():
                        source[(geoid, "acs_profile", measure)] = number(row[variable])
        district_source = {}
        response = json.loads(archive("acs_profile", "cd_54").read_text())
        headers = response[0]
        for values in response[1:]:
            row = dict(zip(headers, values))
            if row["state"] + row["congressional district"] == "5401":
                for measure in ("total_population", "poverty_pct"):
                    district_source[measure] = number(row[profile_variables[measure]])
        # AHRF's unmodified person and physician CSV.
        for row in csv_rows(archive("ahrf", "AHRF2025hp.csv")):
            geoid = row["fips_st_cnty"]
            if geoid in COUNTIES:
                measure = SAMPLES["ahrf"][0]
                source[(geoid, "ahrf", measure)] = number(row[measure])
        # AHRQ CLH's county workbook, Data sheet.
        workbook = load_workbook(archive("clh", "county"), read_only=True, data_only=True)
        rows = workbook["Data"].iter_rows(values_only=True)
        headers = next(rows)
        fips_index = headers.index("COUNTYFIPS")
        measure = SAMPLES["clh"][0]
        value_index = headers.index(measure)
        for row in rows:
            geoid = row[fips_index]
            if geoid in COUNTIES:
                source[(geoid, "clh", measure)] = number(row[value_index])
        workbook.close()
        # CMS Original Medicare PUF: year, county geography, all ages.
        for row in csv_rows(archive("cms_gv", "gv_csv")):
            geoid = row["BENE_GEO_CD"]
            if geoid in COUNTIES and row["YEAR"] == "2024" and row["BENE_GEO_LVL"] == "County" and row["BENE_AGE_LVL"] == "All":
                source[(geoid, "cms_gv", "om_beneficiaries")] = number(row["BENES_OM_CNT"])
        # EPA annual AQI CSV identifies the same counties by state and county name.
        epa_columns = {"median_aqi": "Median AQI", "days_with_aqi": "Days with AQI"}
        for row in csv_rows(archive("epa_aqi", "county_csv")):
            for geoid in COUNTIES:
                area = profiles[geoid]["area"]
                if row["Year"] == "2025" and row["State"] == area["state_name"] and row["County"] == area["name"]:
                    for measure, column in epa_columns.items():
                        source[(geoid, "epa_aqi", measure)] = number(row[column])
        # USDA ERS long CSV; each selected variable has its own observation year.
        usda_codes = {"PCT_LACCESS_LOWI19": "low_income_low_access_pct", "SNAPSPTH23": "snap_stores_per_1000"}
        for row in csv_rows(archive("usda_fea", "values_csv")):
            geoid = row["FIPS"]
            if geoid in COUNTIES and row["Variable_Code"] in usda_codes:
                measure = usda_codes[row["Variable_Code"]]
                source[(geoid, "usda_fea", measure)] = number(row["Value"])

    rendered = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        browser_auth = context.request.post(f"{BASE}/api/demo-access/validate", data={"access_code": code})
        assert browser_auth.status == 200
        page = context.new_page()
        for geoid in COUNTIES:
            page.goto(f"{BASE}/community/county/{geoid}")
            page.locator("article.community-indicator").first.wait_for()
            values = {card.locator("h3").inner_text(): card.locator(".community-value").inner_text()
                      for card in page.locator("article.community-indicator").all()}
            pdf_response = session.get(f"{BASE}/api/community/county/{geoid}/pdf", timeout=90)
            pdf_response.raise_for_status()
            pdf_text = re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf_response.content)).pages))
            rendered[geoid] = (values, pdf_text)
        page.goto(f"{BASE}/district/cd/5401")
        page.locator("[data-testid=district-ready]").wait_for()
        district_display = {card.locator("h3").inner_text(): card.locator(".community-value").inner_text()
                            for card in page.locator("article.community-indicator").all()}
        browser.close()

    checks = []
    for geoid in COUNTIES:
        profile = profiles[geoid]
        html_values, pdf_text = rendered[geoid]
        by_key = {(row["product"], row["measure_id"]): row for row in profile["values"]}
        for product, measures in SAMPLES.items():
            for measure in measures:
                row = by_key[(product, measure)]
                key = (geoid, product, measure)
                raw = source[key]
                api = number(row["value"])
                if raw != api:
                    raise AssertionError(f"Archive/API mismatch: {key}: {raw} != {api}")
                display = html_values[row["label"]]
                displayed_number = number(display.replace(",", "").replace("$", "").replace("%", ""))
                if abs(displayed_number - raw) > Decimal("0.0051"):
                    raise AssertionError(f"Archive/profile display mismatch: {key}: {raw} vs {display}")
                locations = [match.start() for match in re.finditer(re.escape(row["label"]), pdf_text)]
                if not any(display in pdf_text[location:location + len(row["label"]) + 40] for location in locations):
                    raise AssertionError(f"Profile/PDF mismatch: {key}: {display}")
                checks.append({"geoid": geoid, "county": profile["area"]["name"], "product": product,
                               "measure_id": measure, "archive_value": str(raw), "api_value": str(api),
                               "profile_and_pdf_value": display, "release_id": row["release_id"]})
    district_response = session.get(f"{BASE}/api/community/district/5401", timeout=40)
    district_response.raise_for_status()
    district = district_response.json()
    district_values = {row["measure_id"]: row for row in district["values"]}
    for measure, raw in district_source.items():
        row = district_values[measure]
        api = number(row["value"])
        display = district_display[row["label"]]
        if api != raw or number(display.replace(",", "").replace("%", "")) != raw:
            raise AssertionError(f"District archive/API/page mismatch: {measure}")
        checks.append({"geoid": "5401", "district": district["area"]["name"], "product": "acs_profile",
                       "measure_id": measure, "archive_value": str(raw), "api_value": str(api),
                       "profile_and_pdf_value": display, "release_id": row["release_id"], "surface": "district page"})
    if len(checks) != 47:
        raise AssertionError(f"Expected 47 checks, got {len(checks)}")
    # Catch publication while the report was being assembled.
    latest = session.get(f"{BASE}/api/community/county/{COUNTIES[0]}", timeout=40).json()
    if {row["product"]: row["release_id"] for row in latest["values"]} != releases:
        raise AssertionError("A published release changed during the source check; rerun")
    REPORT.write_text(json.dumps({"checked_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                                  "staging_base": BASE, "count": len(checks),
                                  "source_archives": [dict(product=p, role=r, **data) for (p, r), data in sorted(source_files.items())],
                                  "checks": checks}, indent=2) + "\n")
    print(f"{len(checks)} archived-source checks passed across {len(COUNTIES)} counties, one district, and {len(SAMPLES)} products; wrote {REPORT}")


if __name__ == "__main__":
    main()
