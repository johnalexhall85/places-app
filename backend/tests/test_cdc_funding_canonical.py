from __future__ import annotations

from app.cdc_funding import canonical


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def one(self):
        if len(self._rows) != 1:
            raise AssertionError(f"expected one row, received {len(self._rows)}")
        return self._rows[0]

    def one_or_none(self):
        if not self._rows:
            return None
        return self.one()


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _FakeMappingsResult(self._rows)


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):
        return _FakeExecuteResult(self._rows)


class _NationalGeometrySession:
    def execute(self, statement, params=None):
        sql_text = str(statement)
        if "ST_UnaryUnion(ST_Collect(geom))" in sql_text:
            return _FakeExecuteResult([{"geometry": {"type": "Polygon", "coordinates": []}}])
        raise AssertionError(f"unexpected SQL: {sql_text}")


def test_available_fiscal_years_by_geography_reflects_canonical_row_coverage(monkeypatch) -> None:
    monkeypatch.setattr(canonical, "_ensure_required_views", lambda _db: None)
    db = _FakeSession(
        [
            {"fiscal_year": 2026, "state_row_count": 59, "county_row_count": 382},
            {"fiscal_year": 2025, "state_row_count": 59, "county_row_count": 648},
            {"fiscal_year": 2024, "state_row_count": 59, "county_row_count": 745},
            {"fiscal_year": 2020, "state_row_count": 56, "county_row_count": 423},
            {"fiscal_year": 2019, "state_row_count": 0, "county_row_count": 0},
        ]
    )

    availability = canonical.available_fiscal_years_by_geography(db)

    assert availability == {
        "state": [2026, 2025, 2024, 2020],
        "county": [2026, 2025, 2024, 2020],
        "national": [2026, 2025, 2024, 2020],
    }


def test_default_fiscal_year_uses_requested_geography(monkeypatch) -> None:
    monkeypatch.setattr(
        canonical,
        "available_fiscal_years_by_geography",
        lambda _db: {
            "state": [2026, 2025, 2024],
            "county": [2025, 2024],
            "national": [2026, 2025, 2024],
        },
    )
    monkeypatch.setattr(canonical, "_latest_completed_federal_fiscal_year", lambda *_args, **_kwargs: 2025)

    assert canonical.default_fiscal_year(object(), geography_level="state") == 2025
    assert canonical.default_fiscal_year(object(), geography_level="county") == 2025
    assert canonical.default_fiscal_year(object(), geography_level="national") == 2025


def test_canonical_mode_helpers_expose_expected_defaults() -> None:
    assert canonical.is_canonical_mode("canonical_v1") is True
    assert canonical.is_canonical_mode("budget_grounded_v1") is False
    assert canonical.filter_defaults() == {
        "include_mandatory": True,
        "include_emergency": False,
        "include_supplemental": False,
        "include_pphf": True,
        "include_transfers": True,
        "review_mode": "all_master_universe",
    }
    assert canonical.review_mode_options() == [
        {"value": "all_master_universe", "label": "All canonical-universe rows"},
        {"value": "trusted_auto", "label": "Trusted auto + analyst reviewed"},
        {"value": "analyst_only", "label": "Analyst reviewed only"},
    ]


def test_normalize_bbox_ignores_malformed_or_national_extent_inputs() -> None:
    malformed = canonical._normalize_bbox("bad-value", geography_level="county")
    assert malformed.applied is False
    assert malformed.ignored_reason == "Malformed bbox ignored."

    national = canonical._normalize_bbox("-125,24,-66,49", geography_level="national")
    assert national.applied is False
    assert national.ignored_reason == "National bbox ignored."


def test_normalize_bbox_ignores_broad_county_extent() -> None:
    bbox = canonical._normalize_bbox("-180,-24,21,81", geography_level="county")

    assert bbox.applied is False
    assert bbox.ignored_reason == "Broad county bbox ignored until the map is zoomed in further."


def test_fetch_map_geojson_returns_national_feature(monkeypatch) -> None:
    monkeypatch.setattr(canonical, "_ensure_required_views", lambda _db: None)

    def fake_fetch_national_summary(*_args, **_kwargs):
        return {
            "funding_profile": {
                "metric_value": 42.0,
                "funding_per_capita": 1.0,
                "funding_per_100k": 100.0,
                "national_share": 100.0,
            },
            "total_funding_amount": 42.0,
            "population": 330.0,
            "metadata": {
                "timeframe_label": "FY2025",
                "legend_title": "FY2025 Total CDC Funding",
                "filter_context": {"total_included_rows": 7},
                "total_included_rows": 7,
                "min_fiscal_year": 2025,
                "max_fiscal_year": 2025,
            },
        }

    monkeypatch.setattr(canonical, "fetch_national_summary", fake_fetch_national_summary)

    payload = canonical.fetch_map_geojson(
        _NationalGeometrySession(),
        fiscal_year=2025,
        geography_level="national",
        bbox="-125,24,-66,49",
    )

    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 1
    feature = payload["features"][0]
    assert feature["properties"]["id"] == "US"
    assert feature["properties"]["geo_level"] == "national"
    assert feature["properties"]["value"] == 42.0
    assert payload["meta"]["mapped_geographies"] == 1
    assert "National bbox ignored." in payload["meta"]["note"]


def test_fetch_map_geojson_returns_empty_collection_without_error(monkeypatch) -> None:
    monkeypatch.setattr(canonical, "_ensure_required_views", lambda _db: None)
    monkeypatch.setattr(
        canonical,
        "_fetch_geography_rows",
        lambda *_args, **_kwargs: (
            [],
            {"min_fiscal_year": None, "max_fiscal_year": None, "total_included_rows": 0},
            canonical.NormalizedBbox(0.0, 0.0, 0.0, 0.0, applied=False),
        ),
    )
    monkeypatch.setattr(
        canonical,
        "_build_meta",
        lambda *_args, **_kwargs: {
            "note": "Canonical note.",
            "legend_title": "Legend",
            "filter_context": {},
            "national_summary": {},
        },
    )

    payload = canonical.fetch_map_geojson(
        object(),
        fiscal_year=2025,
        geography_level="state",
    )

    assert payload["type"] == "FeatureCollection"
    assert payload["features"] == []
    assert payload["meta"]["mapped_geographies"] == 0
    assert payload["meta"]["no_data_count"] == 0


def test_fetch_map_geojson_preserves_county_shape(monkeypatch) -> None:
    monkeypatch.setattr(canonical, "_ensure_required_views", lambda _db: None)
    monkeypatch.setattr(
        canonical,
        "_fetch_geography_rows",
        lambda *_args, **_kwargs: (
            [
                {
                    "geography_id": "01001",
                    "geography_name": "Autauga",
                    "state_code": "AL",
                    "state_name": "Alabama",
                    "total_amount": 125.0,
                    "row_count": 2,
                    "population": 100.0,
                    "national_total": 1000.0,
                    "geometry": {"type": "Polygon", "coordinates": []},
                }
            ],
            {"min_fiscal_year": 2025, "max_fiscal_year": 2025, "total_included_rows": 2},
            canonical.NormalizedBbox(0.0, 0.0, 0.0, 0.0, applied=False),
        ),
    )
    monkeypatch.setattr(
        canonical,
        "_build_meta",
        lambda *_args, **_kwargs: {
            "note": "Canonical note.",
            "legend_title": "Legend",
            "filter_context": {},
            "national_summary": {},
        },
    )

    payload = canonical.fetch_map_geojson(
        object(),
        fiscal_year=2025,
        geography_level="county",
    )

    assert len(payload["features"]) == 1
    props = payload["features"][0]["properties"]
    assert props["id"] == "01001"
    assert props["state_abbr"] == "AL"
    assert props["geo_level"] == "county"
    assert props["value"] == 125.0


def test_fetch_legend_stats_avoids_geometry_map_requery(monkeypatch) -> None:
    monkeypatch.setattr(canonical, "_ensure_required_views", lambda _db: None)
    monkeypatch.setattr(
        canonical,
        "fetch_map_geojson",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legend should not call map geojson")),
    )
    monkeypatch.setattr(
        canonical,
        "_fetch_geography_rows",
        lambda *_args, **_kwargs: (
            [
                {
                    "geography_id": "01001",
                    "total_amount": 125.0,
                    "population": 100.0,
                    "national_total": 1000.0,
                }
            ],
            {"min_fiscal_year": 2025, "max_fiscal_year": 2025, "total_included_rows": 1},
            canonical.NormalizedBbox(
                -180.0,
                -24.0,
                21.0,
                81.0,
                applied=False,
                ignored_reason="Broad county bbox ignored until the map is zoomed in further.",
            ),
        ),
    )
    monkeypatch.setattr(
        canonical,
        "_build_meta",
        lambda *_args, **_kwargs: {
            "note": "Canonical note.",
            "legend_title": "Legend",
            "filter_context": {},
            "national_summary": {"funding_profile": {}},
        },
    )

    payload = canonical.fetch_legend_stats(
        object(),
        fiscal_year=2025,
        geography_level="county",
        bbox="-180,-24,21,81",
    )

    assert payload["min"] == 125.0
    assert payload["max"] == 125.0
    assert payload["mapped_geographies"] == 1
    assert payload["noDataCount"] == 0
    assert "Broad county bbox ignored until the map is zoomed in further." in payload["note"]
