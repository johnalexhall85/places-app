from __future__ import annotations

import csv
from pathlib import Path

from app.usda_food_access import ingest as usda_ingest
from app.usda_food_access import router as usda_router
from app.usda_food_access import services as usda_services


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        if not self._rows:
            raise RuntimeError("No rows")
        return self._rows[0]

    def all(self):
        return self._rows


class _FakeConnection:
    def execute(self, _statement, _params=None):
        class _RowCountResult:
            rowcount = 0

            def scalar(self):
                return 1

        return _RowCountResult()


class _BeginContext:
    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self._connection

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self):
        self.connection = _FakeConnection()

    def begin(self):
        return _BeginContext(self.connection)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_ingest_upserts_lookup_and_at_least_one_tract_row(monkeypatch, tmp_path):
    food_access_csv = tmp_path / "Food Access Research Atlas.csv"
    variable_lookup_csv = tmp_path / "VariableLookup.csv"
    readme_csv = tmp_path / "ReadMe.csv"

    _write_csv(
        food_access_csv,
        [
            "CensusTract",
            "State",
            "County",
            "Urban",
            "POP2010",
            "LowIncomeTracts",
            "LA1and10",
        ],
        [
            ["1001020100", "AL", "Autauga", "1", "54571", "1", "0.24"],
            ["", "AL", "Autauga", "1", "100", "0", "0.15"],
        ],
    )
    _write_csv(
        variable_lookup_csv,
        ["Field", "LongName", "Description"],
        [["LA1and10", "Low access at 1 mile", "People with low access at 1 mile or 10 miles."]],
    )
    _write_csv(readme_csv, ["Key", "Value"], [["note", "Atlas metadata"]])

    captured = {
        "lookup_rows": [],
        "tract_rows": [],
        "meta_row_count": None,
    }

    monkeypatch.setattr(usda_ingest, "create_engine", lambda *_args, **_kwargs: _FakeEngine())
    monkeypatch.setattr(usda_ingest, "_ensure_target_tables", lambda _connection: None)

    def _capture_lookup(_connection, rows, _batch_size):
        captured["lookup_rows"].extend(rows)
        return len(rows)

    def _capture_tracts(_connection, rows, _batch_size):
        captured["tract_rows"].extend(rows)
        return len(rows)

    def _capture_meta(_connection, *, row_count, notes, source_url):
        captured["meta_row_count"] = row_count
        assert isinstance(source_url, str)
        assert notes is None or isinstance(notes, str)

    monkeypatch.setattr(usda_ingest, "_upsert_variable_lookup_rows", _capture_lookup)
    monkeypatch.setattr(usda_ingest, "_upsert_tract_rows", _capture_tracts)
    monkeypatch.setattr(usda_ingest, "_upsert_dataset_meta", _capture_meta)

    usda_ingest.ingest(
        db_url="postgresql+psycopg://ignored",
        food_access_path=food_access_csv,
        variable_lookup_path=variable_lookup_csv,
        readme_path=readme_csv,
        chunksize=2,
    )

    assert len(captured["lookup_rows"]) == 1
    assert captured["lookup_rows"][0]["field"] == "LA1and10"

    assert len(captured["tract_rows"]) >= 1
    first_tract = captured["tract_rows"][0]
    assert first_tract["geoid"] == "01001020100"
    assert '"CensusTract":"1001020100"' in first_tract["raw_json"]
    assert captured["meta_row_count"] == 1


def test_variables_endpoint_returns_expected_fields(monkeypatch):
    monkeypatch.setattr(
        usda_router.services,
        "list_variables",
        lambda _db, **_kwargs: {
            "variables": [
                {
                    "field": "LA1and10",
                    "long_name": "Low access at 1 mile",
                    "description": "People with low access at 1 mile or 10 miles.",
                }
            ],
            "recommended_fields": ["LA1and10"],
            "notes": "USDA Food Access Research Atlas",
        },
    )

    payload = usda_router.list_variables(q="LA", include_raw_only=False, db=object())
    assert payload["variables"][0]["field"] == "LA1and10"
    assert payload["recommended_fields"] == ["LA1and10"]


class _FakeMapSession:
    def __init__(self):
        self._calls = 0

    def execute(self, statement, _params=None):
        sql_text = str(statement)
        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])

        self._calls += 1
        if self._calls == 1:
            return _FakeResult(
                [
                    {
                        "field": "LA1and10",
                        "long_name": "Low access at 1 mile",
                        "description": "People with low access at 1 mile or 10 miles.",
                    }
                ]
            )

        return _FakeResult(
            [
                {
                    "geoid": "01001020100",
                    "state": "AL",
                    "county": "Autauga",
                    "pop2010": 54571,
                    "value": 0.24,
                    "geometry": {"type": "Polygon", "coordinates": []},
                }
            ]
        )


def test_map_service_returns_geojson_with_value_property():
    payload = usda_services.fetch_map_geojson(
        _FakeMapSession(),
        variable="LA1and10",
        bbox="-87.8,32.2,-86.2,32.9",
        zoom=12,
        limit=5000,
        mode="auto",
    )

    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 1
    feature = payload["features"][0]
    assert feature["properties"]["geoid"] == "01001020100"
    assert feature["properties"]["value"] == 0.24


class _NoQuerySession:
    def execute(self, _statement, _params=None):
        raise AssertionError("Zoom-gated heat response should not query the database.")


class _FakeHeatSession:
    def __init__(self, heat_rows=None):
        self._calls = 0
        self._heat_rows = heat_rows or [
            {"lat": 33.7490, "lon": -84.3880, "value": 52.5, "n": 128},
            {"lat": 33.9200, "lon": -84.1500, "value": 38.0, "n": 96},
        ]

    def execute(self, statement, _params=None):
        sql_text = str(statement)
        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])

        self._calls += 1
        if self._calls == 1:
            return _FakeResult(
                [
                    {
                        "field": "LowIncomeTracts",
                        "long_name": "Low-income tract flag",
                        "description": "Indicates tract-level low-income status.",
                    }
                ]
            )
        return _FakeResult(self._heat_rows)


def test_heat_zoom_gate():
    payload = usda_services.fetch_heat_points(
        _NoQuerySession(),
        variable="LowIncomeTracts",
        bbox="-87.8,32.2,-86.2,32.9",
        zoom=10,
        limit=2000,
        agg="auto",
        mode="auto",
    )

    assert payload["mode"] == "heat"
    assert payload["points"] == []
    assert "Heat disabled at tract zoom" in payload["notes"]


def test_heat_bbox_returns_points_and_auto_agg_selection():
    payload = usda_services.fetch_heat_points(
        _FakeHeatSession(),
        variable="LowIncomeTracts",
        bbox="-84.8,33.4,-84.0,34.2",
        zoom=6,
        limit=2000,
        agg="auto",
        mode="auto",
    )

    assert payload["mode"] == "heat"
    assert payload["cell_km"] == 50
    assert payload["agg"] == "pct_flagged"
    assert isinstance(payload["points"], list)
    assert len(payload["points"]) >= 1
    first_point = payload["points"][0]
    assert {"lat", "lon", "value", "n"}.issubset(first_point.keys())
    assert isinstance(first_point["lat"], float)
    assert isinstance(first_point["lon"], float)
    assert isinstance(first_point["n"], int)
    assert usda_services._resolve_heat_aggregation("LowIncomeTracts", "auto") == "pct_flagged"
    assert usda_services._resolve_heat_aggregation("MedianFamilyIncome", "auto") == "median"
