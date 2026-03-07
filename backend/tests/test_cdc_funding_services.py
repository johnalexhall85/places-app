from __future__ import annotations

import csv
from datetime import date

from app.cdc_funding import ingest as cdc_ingest
from app.cdc_funding import services as cdc_services


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def one(self):
        if not self._rows:
            raise RuntimeError("No rows")
        return self._rows[0]

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeSessionForSearch:
    def __init__(self):
        self.sql_calls: list[str] = []
        self.params_calls: list[dict] = []

    def execute(self, statement, params=None):
        sql_text = str(statement)
        self.sql_calls.append(sql_text)
        self.params_calls.append(dict(params or {}))

        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])
        if "SELECT *" in sql_text and "FROM (" in sql_text:
            return _FakeResult(
                [
                    {
                        "record_id": "PRIME-1",
                        "record_type": "prime_award",
                        "fain": "FAIN-PRIME-1",
                        "entity_name": "Prime Recipient",
                        "assistance_type_description": "Project Grants",
                        "amount": 1500.00,
                        "latest_action_date": date(2025, 10, 1),
                        "state_code": "AL",
                        "state_name": "Alabama",
                        "county_fips": "01001",
                        "county_name": "Autauga",
                        "description": "Prime description",
                        "usaspending_permalink": "https://example.com/prime",
                        "fiscal_year": 2026,
                        "center_name": "NCIRD",
                        "awarding_office_name": "Office A",
                        "funding_office_name": "Office B",
                    },
                    {
                        "record_id": "2",
                        "record_type": "subaward",
                        "fain": "FAIN-PRIME-1",
                        "entity_name": "Subaward Entity",
                        "assistance_type_description": None,
                        "amount": 250.50,
                        "latest_action_date": date(2025, 11, 3),
                        "state_code": "AL",
                        "state_name": "Alabama",
                        "county_fips": None,
                        "county_name": None,
                        "description": "Subaward description",
                        "usaspending_permalink": "https://example.com/sub",
                        "fiscal_year": 2026,
                        "center_name": "NCIRD",
                        "awarding_office_name": "Office A",
                        "funding_office_name": "Office B",
                    },
                ]
            )
        if "SELECT COUNT(*)::integer AS total_count" in sql_text:
            return _FakeResult([{"total_count": 2}])
        return _FakeResult([])


class _CaptureConnection:
    def __init__(self):
        self.sqls: list[str] = []

    def execute(self, statement, _params=None):
        sql_text = str(statement)
        self.sqls.append(sql_text)

        class _Result:
            rowcount = 0

        return _Result()


class _FakeSessionForTop:
    def __init__(self):
        self.last_sql = ""
        self.last_params = {}

    def execute(self, statement, params=None):
        sql_text = str(statement)
        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])
        self.last_sql = sql_text
        self.last_params = dict(params or {})
        return _FakeResult(
            [
                {
                    "record_id": "PRIME-1",
                    "record_type": "prime_award",
                    "fain": "FAIN-PRIME-1",
                    "entity_name": "Prime Recipient",
                    "assistance_type_description": "Project Grants",
                    "amount": 2000.00,
                    "latest_action_date": date(2025, 12, 12),
                    "state_code": "AL",
                    "state_name": "Alabama",
                    "county_fips": "01001",
                    "county_name": "Autauga",
                    "description": "Prime description",
                    "usaspending_permalink": "https://example.com/prime",
                }
            ]
        )


def test_read_prime_and_subaward_rows_counts_and_normalization(tmp_path) -> None:
    prime_path = tmp_path / "prime.csv"
    sub_path = tmp_path / "sub.csv"

    with prime_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "assistance_award_unique_key",
                "award_id_fain",
                "recipient_state_code",
                "prime_award_summary_recipient_county_fips_code",
                "award_latest_action_date_fiscal_year",
                "total_funding_amount",
                "cfda_numbers_and_titles",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "assistance_award_unique_key": "PRIME-KEY-1",
                "award_id_fain": "FAIN-1",
                "recipient_state_code": "al",
                "prime_award_summary_recipient_county_fips_code": "1001",
                "award_latest_action_date_fiscal_year": "2026",
                "total_funding_amount": "1234.56",
                "cfda_numbers_and_titles": "93.354: Public Health Emergency Response",
            }
        )
        writer.writerow(
            {
                "assistance_award_unique_key": "",
                "award_id_fain": "FAIN-SKIP",
            }
        )

    with sub_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "prime_award_unique_key",
                "prime_award_fain",
                "subaward_amount",
                "subaward_action_date_fiscal_year",
                "subawardee_state_code",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "prime_award_unique_key": "PRIME-KEY-1",
                "prime_award_fain": "FAIN-1",
                "subaward_amount": "150.25",
                "subaward_action_date_fiscal_year": "2026",
                "subawardee_state_code": "al",
            }
        )
        writer.writerow(
            {
                "prime_award_unique_key": "",
                "prime_award_fain": "FAIN-SKIP",
            }
        )

    prime_rows = cdc_ingest._read_prime_rows(prime_path)
    sub_rows = cdc_ingest._read_subaward_rows(sub_path)

    assert len(prime_rows) == 1
    assert prime_rows[0]["recipient_state_code"] == "AL"
    assert prime_rows[0]["recipient_county_fips"] == "01001"
    assert prime_rows[0]["award_latest_action_date_fiscal_year"] == 2026
    assert str(prime_rows[0]["total_funding_amount"]) == "1234.56"
    assert prime_rows[0]["cfda_program_num"] == "93.354"

    assert len(sub_rows) == 1
    assert sub_rows[0]["subawardee_state_code"] == "AL"
    assert sub_rows[0]["subaward_action_date_fiscal_year"] == 2026
    assert str(sub_rows[0]["subaward_amount"]) == "150.25"


def test_refresh_summary_tables_uses_recipient_and_subawardee_geography() -> None:
    connection = _CaptureConnection()
    cdc_ingest._refresh_summary_tables(connection)
    sql_blob = "\n".join(connection.sqls)

    assert "FROM cdc_funding.prime_awards AS p" in sql_blob
    assert "p.recipient_state_code AS geography_id" in sql_blob
    assert "p.recipient_county_fips AS geography_id" in sql_blob
    assert "WHERE p.recipient_county_fips IS NOT NULL" in sql_blob

    assert "FROM cdc_funding.subawards AS s" in sql_blob
    assert "s.subawardee_state_code AS geography_id" in sql_blob
    assert "s.subawardee_county_fips AS geography_id" in sql_blob
    assert "WHERE s.subawardee_county_fips IS NOT NULL" in sql_blob


def test_search_returns_prime_and_subaward_rows() -> None:
    fake_db = _FakeSessionForSearch()
    payload = cdc_services.search_awards(
        fake_db,
        q="recipient",
        basis="all",
        assistance_type="Project Grants",
        fiscal_year=2026,
        state="AL",
        page=1,
        page_size=25,
    )

    assert payload["basis"] == "all"
    assert payload["total"] == 2
    assert [row["record_type"] for row in payload["results"]] == ["prime_award", "subaward"]
    assert payload["results"][0]["latest_action_date"] == "2025-10-01"
    assert payload["results"][1]["latest_action_date"] == "2025-11-03"

    combined_sql = next(sql for sql in fake_db.sql_calls if "SELECT *" in sql and "FROM (" in sql)
    assert "p.assistance_type_description = :assistance_type" in combined_sql
    assert "p.award_latest_action_date_fiscal_year = :fiscal_year" in combined_sql
    assert "s.subaward_action_date_fiscal_year = :fiscal_year" in combined_sql
    assert "p.recipient_state_code = :state_code" in combined_sql
    assert "s.subawardee_state_code = :state_code" in combined_sql


def test_top_awards_applies_filters_for_prime_state_query() -> None:
    fake_db = _FakeSessionForTop()
    payload = cdc_services.fetch_top_awards(
        fake_db,
        basis="prime",
        geography="state",
        geography_id="AL",
        metric="total_funding",
        assistance_type="Project Grants",
        fiscal_year=2026,
        awarding_office="Office A",
        funding_office="Office B",
        center="NCIRD",
        limit=5,
    )

    assert payload["basis"] == "prime"
    assert payload["geography"] == "state"
    assert payload["geography_id"] == "AL"
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["record_type"] == "prime_award"

    assert "p.recipient_state_code = :geography_id" in fake_db.last_sql
    assert "p.assistance_type_description = :assistance_type" in fake_db.last_sql
    assert "p.award_latest_action_date_fiscal_year = :fiscal_year" in fake_db.last_sql
    assert "p.awarding_office_name = :awarding_office" in fake_db.last_sql
    assert "p.funding_office_name = :funding_office" in fake_db.last_sql
    assert "p.awarding_sub_agency_name = :center OR p.funding_sub_agency_name = :center" in fake_db.last_sql
