#!/usr/bin/env python3
"""Build the CDC-RFA-CE23-2301 recipient data package."""

from pathlib import Path

import build_ce24_0027_recipient_dossier as builder


builder.NOFO = "CDC-RFA-CE23-2301"
builder.NOFO_SHORT = "CE23-2301"
builder.NOFO_TITLE = (
    "Domestic Violence Prevention Enhancement and Leadership Through Alliances "
    "(DELTA): Achieving Health Equity through Addressing Disparities (AHEAD)"
)
builder.GRANTS_GOV_ID = "341328"
builder.GRANTS_GOV_URL = "https://www.grants.gov/search-results-detail/341328"
builder.NOFO_PDF_URL = builder.GRANTS_GOV_URL
builder.NOFO_SOURCE_LABEL = "Official NOFO and supporting attachments on Grants.gov"
builder.NOFO_POSTED = "September 22, 2022"
builder.NOFO_DEADLINE = "November 29, 2022"
builder.NOFO_PROGRAM_PERIOD = "five years"
builder.NOFO_EXPECTED_AWARDS = "22"
builder.NOFO_ESTIMATED_FUNDING = "$45,000,000"
builder.NOFO_AWARD_RANGE = "$250,000 to $500,000"
builder.NOFO_ELIGIBILITY = (
    "state domestic-violence coalitions meeting the statutory representation criteria, "
    "or an eligible bona fide agent"
)

builder.OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data/reports/ce23_2301_recipients"
builder.WIDE_CSV = builder.OUTPUT_DIR / "ce23_2301_recipient_organizations.csv"
builder.LONG_CSV = builder.OUTPUT_DIR / "ce23_2301_recipient_top_other_awards_long.csv"
builder.GEOCODE_CSV = builder.OUTPUT_DIR / "ce23_2301_census_geocoder_enrichment.csv"
builder.MARKDOWN = builder.OUTPUT_DIR / "CDC-RFA-CE23-2301_recipient_dossier.md"
builder.PDF = builder.OUTPUT_DIR / "CDC-RFA-CE23-2301_recipient_dossier.pdf"
builder.GEOCODE_COORDINATE_FALLBACKS = {}


if __name__ == "__main__":
    builder.main()
