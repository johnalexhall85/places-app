from __future__ import annotations

import csv
import json
from pathlib import Path

from app.usda_food_env import ingest as env_ingest
from app.usda_food_env import services as env_services


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
        class _Result:
            rowcount = 0

        return _Result()


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


class _FakeVariablesSession:
    def execute(self, statement, _params=None):
        sql_text = str(statement)
        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])
        return _FakeResult(
            [
                {
                    "var_name": "PCT_LACCESS_POP19",
                    "display_name": "Low access population (%)",
                    "description": "County-level measure",
                    "category": "Access and Proximity to Foodstore",
                    "unit": "Percent",
                    "level": "county",
                    "sort_order": 1,
                },
                {
                    "var_name": "PCT_SNAP22",
                    "display_name": "SNAP participants (% pop), 2022",
                    "description": "State-level measure",
                    "category": "Food Assistance",
                    "unit": "Percent",
                    "level": "state",
                    "sort_order": 2,
                },
            ]
        )


class _FakeVariablesFilterSession:
    def execute(self, statement, _params=None):
        sql_text = str(statement)
        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])
        return _FakeResult(
            [
                {
                    "var_name": "PCT_LACCESS_POP19",
                    "display_name": "Low access population (%), 2019",
                    "description": "County-level measure",
                    "category": "Access",
                    "unit": "Percent",
                    "level": "county",
                    "year_end": 2019,
                    "sort_order": 1,
                    "raw": {},
                },
                {
                    "var_name": "PCT_LACCESS_POP22",
                    "display_name": "Low access population (%), 2022",
                    "description": "County-level measure",
                    "category": "Access",
                    "unit": "Percent",
                    "level": "county",
                    "year_end": 2022,
                    "sort_order": 2,
                    "raw": {},
                },
                {
                    "var_name": "PCT_SNAP22",
                    "display_name": "SNAP participants (% pop), 2022",
                    "description": "State-level measure",
                    "category": "Food Assistance",
                    "unit": "Percent",
                    "level": "state",
                    "year_end": 2022,
                    "sort_order": 3,
                    "raw": {},
                },
            ]
        )


class _FakeCountyMapSession:
    def __init__(self):
        self.last_map_params = None

    def execute(self, statement, _params=None):
        sql_text = str(statement)
        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])
        if "variable_lookup" in sql_text:
            return _FakeResult(
                [
                    {
                        "var_name": "PCT_LACCESS_POP19",
                        "display_name": "Low access population (%)",
                        "description": "County-level measure",
                        "category": "Access",
                        "unit": "Percent",
                        "level": "county",
                    }
                ]
            )
        self.last_map_params = dict(_params or {})
        return _FakeResult(
            [
                {
                    "id": "01001",
                    "name": "Autauga, AL",
                    "value": 33.9,
                    "geometry": {"type": "Polygon", "coordinates": []},
                }
            ]
        )


class _FakeStateMapSession:
    def execute(self, statement, _params=None):
        sql_text = str(statement)
        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])
        if "variable_lookup" in sql_text:
            return _FakeResult(
                [
                    {
                        "var_name": "PCT_SNAP22",
                        "display_name": "SNAP participants (% pop), 2022",
                        "description": "State-level measure",
                        "category": "Food Assistance",
                        "unit": "Percent",
                        "level": "state",
                    }
                ]
            )
        return _FakeResult(
            [
                {
                    "id": "01",
                    "name": "Alabama",
                    "value": 12.3,
                    "geometry": {"type": "Polygon", "coordinates": []},
                }
            ]
        )


class _FakeZoomFallbackSession:
    def __init__(self):
        self.last_map_params = None

    def execute(self, statement, _params=None):
        sql_text = str(statement)
        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])
        if "variable_lookup" in sql_text:
            return _FakeResult(
                [
                    {
                        "var_name": "PCT_LACCESS_POP19",
                        "display_name": "Low access population (%)",
                        "description": "County-level measure",
                        "category": "Access",
                        "unit": "Percent",
                        "level": "county",
                    }
                ]
            )

        self.last_map_params = dict(_params or {})
        limit = int((_params or {}).get("limit") or 60)
        row_count = min(limit, 60)
        rows = [
            {
                "id": f"{idx:02d}",
                "name": f"State {idx:02d}",
                "value": float(idx),
                "geometry": {"type": "Polygon", "coordinates": []},
            }
            for idx in range(1, row_count + 1)
        ]
        return _FakeResult(rows)


class _FakeSimplificationSession:
    def execute(self, statement, _params=None):
        sql_text = str(statement)
        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])
        if "variable_lookup" in sql_text:
            return _FakeResult(
                [
                    {
                        "var_name": "PCT_LACCESS_POP19",
                        "display_name": "Low access population (%)",
                        "description": "County-level measure",
                        "category": "Access",
                        "unit": "Percent",
                        "level": "county",
                    }
                ]
            )

        simplify_degrees = float((_params or {}).get("simplify_degrees") or 0.0)
        point_count = 6 if simplify_degrees >= 0.03 else 60
        coordinates = []
        for idx in range(point_count):
            x = -87.0 + (idx * 0.01)
            y = 32.0 + ((idx % 2) * 0.01)
            coordinates.append([x, y])
        if coordinates and coordinates[0] != coordinates[-1]:
            coordinates.append(coordinates[0])

        return _FakeResult(
            [
                {
                    "id": "01001",
                    "name": "Autauga, AL",
                    "value": 33.9,
                    "geometry": {"type": "Polygon", "coordinates": [coordinates]},
                }
            ]
        )


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_ingest_loads_variable_and_county_rows(monkeypatch, tmp_path):
    values_csv = tmp_path / "StateAndCountyData.csv"
    variable_list_csv = tmp_path / "VariableList.csv"
    readme_txt = tmp_path / "ReadMeFile2025.txt"

    _write_csv(
        variable_list_csv,
        [
            "Variable_Name",
            "Category_Name",
            "Category_Code",
            "Subcategory_Name",
            "Variable_Code",
            "Units",
        ],
        [
            ["Population, low access to store (%), 2019", "Access", "ACCESS", "Overall", "PCT_LACCESS_POP19", "Percent"],
            ["SNAP participants (% pop), 2022*", "Assistance", "ASSISTANCE", "SNAP", "PCT_SNAP22", "Percent"],
        ],
    )
    _write_csv(
        values_csv,
        ["FIPS", "State", "County", "Variable_Code", "Value"],
        [
            ["01001", "AL", "Autauga", "PCT_LACCESS_POP19", "33.90670013"],
            ["01001", "AL", "Autauga", "PCT_SNAP22", "12.1"],
            ["01003", "AL", "Baldwin", "PCT_LACCESS_POP19", "20.1"],
            ["01003", "AL", "Baldwin", "PCT_SNAP22", "12.1"],
        ],
    )
    readme_txt.write_text("USDA Food Environment Atlas notes", encoding="utf-8")

    captured = {
        "variable_rows": [],
        "county_rows": [],
        "state_rows": [],
        "meta": None,
    }

    monkeypatch.setattr(env_ingest, "create_engine", lambda *_args, **_kwargs: _FakeEngine())
    monkeypatch.setattr(env_ingest, "_ensure_target_tables", lambda _connection: None)

    def _capture_variable_rows(_connection, rows, _chunk_size):
        captured["variable_rows"] = rows
        return len(rows)

    def _capture_county_rows(_connection, rows, _chunk_size):
        captured["county_rows"] = rows
        return len(rows)

    def _capture_state_rows(_connection, rows, _chunk_size):
        captured["state_rows"] = rows
        return len(rows)

    def _capture_meta(_connection, **kwargs):
        captured["meta"] = kwargs

    monkeypatch.setattr(env_ingest, "_upsert_variable_rows", _capture_variable_rows)
    monkeypatch.setattr(env_ingest, "_upsert_county_rows", _capture_county_rows)
    monkeypatch.setattr(env_ingest, "_upsert_state_rows", _capture_state_rows)
    monkeypatch.setattr(env_ingest, "_upsert_dataset_meta", _capture_meta)

    summary = env_ingest.ingest(
        db_url="postgresql+psycopg://ignored",
        values_path=values_csv,
        variable_list_path=variable_list_csv,
        readme_path=readme_txt,
        chunksize=100,
    )

    assert summary["variables_upserted"] == 2
    assert summary["county_rows_upserted"] > 0
    assert summary["state_rows_upserted"] > 0
    assert len(captured["variable_rows"]) == 2
    assert any(row["var_name"] == "PCT_LACCESS_POP19" for row in captured["variable_rows"])
    assert len(captured["county_rows"]) > 0
    assert captured["meta"]["row_count_county"] == summary["county_rows_upserted"]


def test_variables_service_returns_county_and_state_variables():
    payload = env_services.list_variables(
        _FakeVariablesSession(),
        q=None,
        level="all",
        include_archival=True,
        year=None,
        category=None,
    )

    assert len(payload["variables"]) == 2
    levels = {row["level"] for row in payload["variables"]}
    assert levels == {"county", "state"}
    assert payload["defaults"]["county"] is not None
    assert isinstance(payload.get("recommended"), list)
    assert isinstance(payload.get("categories"), list)


def test_variables_service_default_filters_to_non_archival_county():
    payload = env_services.list_variables(
        _FakeVariablesFilterSession(),
        q=None,
        level="county",
        include_archival=False,
        year=None,
        category=None,
    )

    assert len(payload["variables"]) == 1
    item = payload["variables"][0]
    assert item["var_name"] == "PCT_LACCESS_POP22"
    assert item["level"] == "county"
    assert item["is_archival"] is False
    assert item["is_default"] is True


def test_map_service_county_level_returns_geojson_numeric_or_null():
    fake_session = _FakeCountyMapSession()
    payload = env_services.fetch_map_geojson(
        fake_session,
        variable="PCT_LACCESS_POP19",
        bbox="-87.8,32.2,-86.2,32.9",
        zoom=6,
        level="auto",
        limit=5000,
    )

    assert payload["type"] == "FeatureCollection"
    assert payload["level"] == "county"
    assert len(payload["features"]) == 1
    assert payload["meta"]["geojson_precision"] == 6
    assert payload["meta"]["simplify_tolerance_degrees"] == 0.03
    assert fake_session.last_map_params is not None
    assert int(fake_session.last_map_params.get("limit")) == 5000
    feature = payload["features"][0]
    assert feature["properties"]["id"] == "01001"
    assert feature["properties"]["value"] == 33.9


def test_map_service_state_level_returns_geojson_with_state_values():
    payload = env_services.fetch_map_geojson(
        _FakeStateMapSession(),
        variable="PCT_SNAP22",
        bbox="-125,24,-66,50",
        zoom=4,
        level="auto",
        limit=5000,
    )

    assert payload["type"] == "FeatureCollection"
    assert payload["level"] == "state"
    assert len(payload["features"]) == 1
    assert payload["meta"]["geojson_precision"] == 6
    assert payload["meta"]["simplify_tolerance_degrees"] == 0.04
    feature = payload["features"][0]
    assert feature["properties"]["id"] == "01"
    assert feature["properties"]["value"] == 12.3


def test_usda_map_zoom4_forces_state_level():
    fake_session = _FakeZoomFallbackSession()

    payload = env_services.fetch_map_geojson(
        fake_session,
        variable="PCT_LACCESS_POP19",
        bbox="-125,24,-66,50",
        zoom=4,
        level="auto",
        limit=5000,
    )

    assert payload["type"] == "FeatureCollection"
    assert payload["level"] == "state"
    assert len(payload["features"]) <= 60
    assert fake_session.last_map_params is not None
    assert int(fake_session.last_map_params.get("limit")) == 60
    assert "meta" in payload
    assert "limited for performance" in payload["meta"]["warning"].lower()
    assert all(len(str(feature["properties"]["id"])) == 2 for feature in payload["features"])


def test_usda_map_simplification_reduces_payload():
    fake_session = _FakeSimplificationSession()

    bbox = "-87.8,32.2,-86.2,32.9"
    zoom6_payload = env_services.fetch_map_geojson(
        fake_session,
        variable="PCT_LACCESS_POP19",
        bbox=bbox,
        zoom=6,
        level="auto",
        limit=5000,
    )
    zoom10_payload = env_services.fetch_map_geojson(
        fake_session,
        variable="PCT_LACCESS_POP19",
        bbox=bbox,
        zoom=10,
        level="auto",
        limit=5000,
    )

    zoom6_size = len(json.dumps(zoom6_payload))
    zoom10_size = len(json.dumps(zoom10_payload))

    assert zoom6_payload["type"] == "FeatureCollection"
    assert zoom10_payload["type"] == "FeatureCollection"
    assert len(zoom6_payload["features"]) > 0
    assert len(zoom10_payload["features"]) > 0
    assert zoom6_size <= zoom10_size
