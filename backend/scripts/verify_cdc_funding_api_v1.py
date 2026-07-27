from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("DEMO_ACCESS_ENABLED", "false")
sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


FY2023_EXPECTED = {
    "emergency_grants": "5820366186.77",
    "emergency_contracts": "681288736.13",
    "nonemergency_grants": "4934414807.93",
    "nonemergency_contracts": "7218344733.64",
    "emergency": "6501654922.90",
    "nonemergency": "12152759541.57",
    "grants": "10754780994.70",
    "contracts": "7899633469.77",
    "overall": "18654414464.47",
}


def _get(client: TestClient, path: str) -> dict:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def main() -> None:
    client = TestClient(app)
    fiscal_years = _get(client, "/api/cdc-funding/v1/fiscal-years")
    overview = _get(client, "/api/cdc-funding/v1/overview?fiscal_year=2023")
    accounts = _get(client, "/api/cdc-funding/v1/accounts?fiscal_year=2023")

    classes = {
        f"{item['emergency_status']}_{item['award_type']}": item["obligations"]
        for item in overview["classifications"]
    }
    expected_classes = {
        "emergency_grant": FY2023_EXPECTED["emergency_grants"],
        "emergency_contract": FY2023_EXPECTED["emergency_contracts"],
        "nonemergency_grant": FY2023_EXPECTED["nonemergency_grants"],
        "nonemergency_contract": FY2023_EXPECTED["nonemergency_contracts"],
    }
    if classes != expected_classes:
        raise AssertionError(f"FY2023 classification totals mismatch: {classes}")
    if overview["total_obligations"] != FY2023_EXPECTED["overall"]:
        raise AssertionError(f"FY2023 overview total mismatch: {overview['total_obligations']}")
    if overview["totals"]["emergency"] != FY2023_EXPECTED["emergency"]:
        raise AssertionError("FY2023 emergency total mismatch")
    if overview["totals"]["nonemergency"] != FY2023_EXPECTED["nonemergency"]:
        raise AssertionError("FY2023 nonemergency total mismatch")
    if overview["totals"]["grants"] != FY2023_EXPECTED["grants"]:
        raise AssertionError("FY2023 grant total mismatch")
    if overview["totals"]["contracts"] != FY2023_EXPECTED["contracts"]:
        raise AssertionError("FY2023 contract total mismatch")
    if overview["reconciliation"]["difference"] != "0.00":
        raise AssertionError("FY2023 overview reconciliation failed")
    if accounts["reconciliation"]["difference"] != "0.00":
        raise AssertionError("FY2023 account reconciliation failed")
    if accounts["reconciliation"]["overview_total"] != FY2023_EXPECTED["overall"]:
        raise AssertionError("FY2023 account overview total mismatch")

    unavailable = client.get("/api/cdc-funding/v1/overview?fiscal_year=1999")
    if unavailable.status_code != 404:
        raise AssertionError(f"Expected 404 for unavailable FY1999, got {unavailable.status_code}")

    latest = fiscal_years["latest_fiscal_year"]
    default_overview = _get(client, "/api/cdc-funding/v1/overview")
    if latest is not None and default_overview["fiscal_year"] != latest:
        raise AssertionError("Default overview did not use latest fiscal year")

    print("CDC Funding API v1 verification passed")
    print(f"Available years: {[item['fiscal_year'] for item in fiscal_years['fiscal_years']]}")
    print(f"Latest fiscal year: {latest}")
    print(f"FY2023 overview total: {overview['total_obligations']}")
    print(f"FY2023 accounts: {accounts['total_accounts']}")
    print(f"FY2023 account reconciliation difference: {accounts['reconciliation']['difference']}")


if __name__ == "__main__":
    main()
