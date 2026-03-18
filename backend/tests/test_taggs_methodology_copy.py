from __future__ import annotations

from pathlib import Path

from app.taggs import services as taggs_services


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_taggs_backend_methodology_notes_describe_profile_assisted_mapping() -> None:
    notes = taggs_services._build_methodology_notes(domestic_only=True)  # noqa: SLF001
    blob = " ".join(notes)

    assert "CDC Funding Profiles FY2020-FY2023 are the primary reference dataset for CAN mapping" in blob
    assert "FY2024-FY2026 TAGGS classifications reuse learned CAN mappings" in blob
    assert "same funding-stream framework used for USA Spending" in blob
    assert "Low-confidence CANs remain in unknown or unclassified buckets" in blob


def test_header_methodology_modal_mentions_funding_scope_normalization() -> None:
    header_path = PROJECT_ROOT / "frontend" / "src" / "components" / "Header.jsx"
    content = header_path.read_text(encoding="utf-8")

    assert "CHIP uses CDC Funding Profiles FY2020-FY2023 as a reference dataset" in content
    assert "funding scopes such as core public health funding" in content
    assert "biomedical research, and international health assistance" in content
    assert "verified federal account mapping CSV now overrides fallback agency and ratio heuristics" in content
    assert "Some USAspending rows list multiple federal accounts in a single raw field" in content
    assert "single-account rows, multi-account same-scope rows, and multi-account mixed-scope rows" in content
    assert "handles the normalized interpretation conservatively instead of fabricating precise splits" in content
    assert "Medicaid-like federal health financing transfers are not treated as core CDC public health investment" in content
    assert "Other public health, biomedical research, and international health assistance remain visible in diagnostics" in content
    assert "FY2020-FY2023 use observed CDC Funding Profiles totals as calibration references" in content
    assert "FY2024-FY2026 reuse the same profile-scope rules and are estimates" in content
    assert "profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics_calibration_v1" in content
    assert "taggs_cdc_profile_can_mapping_v2026_03_13" in content


def test_taggs_funding_profile_ui_prioritizes_interpreted_label_over_raw_can() -> None:
    profile_path = PROJECT_ROOT / "frontend" / "src" / "pages" / "TaggsFundingProfile.jsx"
    content = profile_path.read_text(encoding="utf-8")

    assert "Funding Stream / CAN Mapping Breakdown" in content
    assert "Interpreted label" in content
    assert "Raw CAN" in content
    assert "summary?.mapping_notice" in content


def test_taggs_map_filters_prioritize_funding_stream_over_raw_can() -> None:
    app_path = PROJECT_ROOT / "frontend" / "src" / "App.jsx"
    content = app_path.read_text(encoding="utf-8")

    assert content.index("Funding stream filter") < content.index("Raw CAN filter")
    assert "Funding stream is the preferred TAGGS interpretation filter" in content
