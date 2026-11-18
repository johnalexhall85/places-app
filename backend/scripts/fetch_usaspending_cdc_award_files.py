#!/usr/bin/env python3
"""Download CDC award-level USAspending files (prime transactions and subawards) for one fiscal year.

Reproduces the manual "Custom Award Data" downloads in data/usaspending/chipfunding/fyNN/:
assistance and contracts, prime transactions and subawards, awarding sub-agency CDC,
action dates within the federal fiscal year. Uses the public bulk download API
(no key). Files are written to a new folder; nothing is ingested.

    python scripts/fetch_usaspending_cdc_award_files.py --fiscal-year 2026 \
        --out ../data/usaspending/chipfunding/fy26_candidate
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

API = "https://api.usaspending.gov/api/v2"
USER_AGENT = "chip-funding-refresh/1.0"
AGENCY = {
    "type": "awarding",
    "tier": "subtier",
    "name": "Centers for Disease Control and Prevention",
    "toptier_name": "Department of Health and Human Services",
}
ASSISTANCE_TYPES = ["02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "-1"]
CONTRACT_TYPES = ["A", "B", "C", "D", "IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"]


def request(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def download(prime_types: list[str], sub_types: list[str], start: str, end: str, out: Path, label: str) -> None:
    payload = {
        "filters": {
            "prime_award_types": prime_types,
            "sub_award_types": sub_types,
            "date_type": "action_date",
            "date_range": {"start_date": start, "end_date": end},
            "agencies": [AGENCY],
        },
        "file_format": "csv",
    }
    job = request("POST", f"{API}/bulk_download/awards/", payload)
    name = job["file_name"]
    print(f"[{label}] requested {name}", flush=True)
    while True:
        status = request("GET", f"{API}/download/status/?file_name={name}")
        if status["status"] == "finished":
            break
        if status["status"] == "failed":
            sys.exit(f"[{label}] failed: {status.get('message')}")
        time.sleep(20)
    zpath = out / name
    req = urllib.request.Request(status["file_url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp, open(zpath, "wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(out)
        print(f"[{label}] extracted {zf.namelist()}", flush=True)
    zpath.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fiscal-year", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--end-date", help="default: end of fiscal year or today, whichever is earlier")
    args = parser.parse_args()
    start = f"{args.fiscal_year - 1}-10-01"
    end = args.end_date or min(f"{args.fiscal_year}-09-30", date.today().isoformat())
    args.out.mkdir(parents=True, exist_ok=False)
    download(ASSISTANCE_TYPES, ["grant"], start, end, args.out, "assistance")
    download(CONTRACT_TYPES, ["procurement"], start, end, args.out, "contracts")
    (args.out / "fetch_manifest.json").write_text(json.dumps(
        {"fiscal_year": args.fiscal_year, "start_date": start, "end_date": end, "agency": AGENCY,
         "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "files": sorted(p.name for p in args.out.glob("*.csv"))}, indent=2) + "\n")


if __name__ == "__main__":
    main()
