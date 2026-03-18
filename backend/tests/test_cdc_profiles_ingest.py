from __future__ import annotations

from decimal import Decimal

from app.cdc_profiles import ingest as cdc_profiles_ingest


def test_parse_profile_csv_file_normalizes_header_variants(tmp_path) -> None:
    csv_path = tmp_path / "2023 CSV Data.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Fiscal Year,Project Number,Reference Number,NOFO Number,NOFO Title,Funding Opportunity Title,Amount,Category,Sub-Category,GranteeName,Address,City,County,State,ZipCode,Congressional District,Geography,GrantTypeDesc",
                '2023,NU50CD300866,5 NU50CD300866-02-00,CD22-2201,Example NOFO,"Example Funding Opportunity"," $812,633 ",Public Health Social Services Emergency Fund (PHSSEF),PHSSEF COVID-19 Activities,Example Grantee,707 N Broadway,Baltimore,Baltimore City,Maryland,212051832,7,UNITED STATES OF AMERICA,Other Nonprofit',
                '2023,NU50CD300900,5 NU50CD300900-02-00,CD22-2202,Another NOFO,"Vaccines for Children Program","$(25,000)",Vaccines for Children,Vaccines for Children,Example Grantee,1 Main St,Atlanta,Fulton,Georgia,30308,5,UNITED STATES OF AMERICA,State Government',
            ]
        ),
        encoding="cp1252",
    )

    rows, encoding = cdc_profiles_ingest.parse_profile_csv_file(csv_path, fiscal_year=2023)

    assert encoding == "utf-8-sig" or encoding == "cp1252"
    assert len(rows) == 2
    assert rows[0]["funding_opportunity_title"] == "Example Funding Opportunity"
    assert rows[0]["project_title"] == "Example Funding Opportunity"
    assert rows[0]["grantee_name"] == "Example Grantee"
    assert rows[0]["state_name"] == "Maryland"
    assert rows[0]["state_code"] == "MD"
    assert rows[0]["amount"] == Decimal("812633")
    assert rows[1]["amount"] == Decimal("-25000")
    assert rows[1]["state_code"] == "GA"


def test_build_state_year_totals_aggregates_by_state_and_year() -> None:
    rows = [
        {
            "fiscal_year": 2020,
            "state_code": "AL",
            "state_name": "Alabama",
            "amount": Decimal("100.25"),
        },
        {
            "fiscal_year": 2020,
            "state_code": "AL",
            "state_name": "Alabama",
            "amount": Decimal("20.75"),
        },
        {
            "fiscal_year": 2021,
            "state_code": "GA",
            "state_name": "Georgia",
            "amount": Decimal("10"),
        },
        {
            "fiscal_year": 2021,
            "state_code": None,
            "state_name": None,
            "amount": Decimal("999"),
        },
    ]

    totals = cdc_profiles_ingest.build_state_year_totals(rows)

    assert totals == [
        {
            "fiscal_year": 2020,
            "state_code": "AL",
            "state_name": "Alabama",
            "amount": Decimal("121.00"),
            "row_count": 2,
            "methodology_version": cdc_profiles_ingest.METHODOLOGY_VERSION,
        },
        {
            "fiscal_year": 2021,
            "state_code": "GA",
            "state_name": "Georgia",
            "amount": Decimal("10"),
            "row_count": 1,
            "methodology_version": cdc_profiles_ingest.METHODOLOGY_VERSION,
        },
    ]


def test_discover_methodology_documents_extracts_type_and_year(tmp_path) -> None:
    about_path = tmp_path / "About the Data 2020.pdf"
    faq_path = tmp_path / "FAQs 2023.pdf"
    about_path.write_bytes(b"about")
    faq_path.write_bytes(b"faq")

    documents = cdc_profiles_ingest.discover_methodology_documents(tmp_path)

    assert [
        (document["fiscal_year"], document["document_type"], document["source_file_name"])
        for document in documents
    ] == [
        (2020, "about_the_data", "About the Data 2020.pdf"),
        (2023, "faqs", "FAQs 2023.pdf"),
    ]
