from __future__ import annotations

from datetime import date

import pytest

from app.services.hpsa_summary import (
    assign_hpsa_tier,
    build_hpsa_choropleth_response,
    compute_quartiles_from_scores,
)


def test_compute_quartiles_from_scores_matches_percentile_cont_style():
    q25, q50, q75, n_counties = compute_quartiles_from_scores([1, 2, 3, 4])
    assert n_counties == 4
    assert q25 == pytest.approx(1.75)
    assert q50 == pytest.approx(2.5)
    assert q75 == pytest.approx(3.25)


def test_assign_hpsa_tier_is_tie_safe_and_null_safe():
    assert assign_hpsa_tier(designated=True, value=10, q25=10, q50=15, q75=20) == 1
    assert assign_hpsa_tier(designated=True, value=15, q25=10, q50=15, q75=20) == 2
    assert assign_hpsa_tier(designated=True, value=20, q25=10, q50=15, q75=20) == 3
    assert assign_hpsa_tier(designated=True, value=21, q25=10, q50=15, q75=20) == 4
    assert assign_hpsa_tier(designated=False, value=21, q25=10, q50=15, q75=20) is None
    assert assign_hpsa_tier(designated=True, value=None, q25=10, q50=15, q75=20) is None


def test_build_hpsa_choropleth_response_assigns_tiers_and_preserves_not_designated():
    payload = build_hpsa_choropleth_response(
        domain="pc",
        quartile_row={
            "q25": 10,
            "q50": 15,
            "q75": 20,
            "n_counties": 5,
            "as_of_date": date(2026, 3, 1),
        },
        county_rows=[
            {"county_fips": "01001", "designated": True, "value": 9},
            {"county_fips": "01003", "designated": True, "value": 10},
            {"county_fips": "01005", "designated": True, "value": 15},
            {"county_fips": "01007", "designated": True, "value": 20},
            {"county_fips": "01009", "designated": True, "value": 30},
            {"county_fips": "01011", "designated": False, "value": 99},
            {"county_fips": "01013", "designated": True, "value": None},
        ],
    )

    assert payload["domain"] == "pc"
    assert payload["quartiles"]["q25"] == pytest.approx(10.0)
    assert payload["quartiles"]["q50"] == pytest.approx(15.0)
    assert payload["quartiles"]["q75"] == pytest.approx(20.0)
    assert payload["quartiles"]["n_counties"] == 5
    assert payload["quartiles"]["as_of_date"] == date(2026, 3, 1)

    tiers_by_county = {
        row["county_fips"]: row["tier"]
        for row in payload["features"]
    }
    assert tiers_by_county["01001"] == 1
    assert tiers_by_county["01003"] == 1
    assert tiers_by_county["01005"] == 2
    assert tiers_by_county["01007"] == 3
    assert tiers_by_county["01009"] == 4
    assert tiers_by_county["01011"] is None
    assert tiers_by_county["01013"] is None
