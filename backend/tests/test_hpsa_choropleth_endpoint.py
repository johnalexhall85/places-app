from __future__ import annotations

from datetime import date

from app.routers import hpsa as hpsa_router


class _DummySession:
    pass


def test_hpsa_choropleth_endpoint_returns_domain_tiers(monkeypatch):
    monkeypatch.setattr(
        hpsa_router,
        "fetch_hpsa_domain_quartiles",
        lambda _db, _domain: {
            "q25": 8,
            "q50": 12,
            "q75": 16,
            "n_counties": 100,
            "as_of_date": date(2026, 3, 1),
        },
    )
    monkeypatch.setattr(
        hpsa_router,
        "fetch_hpsa_county_rows_for_domain",
        lambda _db, _domain: [
            {"county_fips": "01001", "designated": True, "value": 6},
            {"county_fips": "01003", "designated": True, "value": 8},
            {"county_fips": "01005", "designated": True, "value": 12},
            {"county_fips": "01007", "designated": True, "value": 16},
            {"county_fips": "01009", "designated": True, "value": 20},
            {"county_fips": "01011", "designated": False, "value": 20},
        ],
    )

    payload = hpsa_router.get_hpsa_choropleth_counties(domain="mh", db=_DummySession())
    assert payload["domain"] == "mh"
    assert payload["quartiles"]["n_counties"] == 100
    tiers = {row["county_fips"]: row["tier"] for row in payload["features"]}
    assert tiers["01001"] == 1
    assert tiers["01003"] == 1
    assert tiers["01005"] == 2
    assert tiers["01007"] == 3
    assert tiers["01009"] == 4
    assert tiers["01011"] is None
