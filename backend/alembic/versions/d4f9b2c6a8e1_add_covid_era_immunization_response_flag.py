"""add covid-era immunization response flag

Revision ID: d4f9b2c6a8e1
Revises: c3f8a1d7b6e2
Create Date: 2026-07-04 19:45:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4f9b2c6a8e1"
down_revision: Union[str, None] = "c3f8a1d7b6e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "cdc_funding"
FACT_TABLE = "fact_cdc_funding_prime_transaction"
STATE_MV = "mv_cdc_funding_map_state_all_positive"

STATE_LOOKUP = """
    WITH state_lookup(state_fips, state_code, state_name) AS (
        VALUES
        ('01','AL','Alabama'),('02','AK','Alaska'),('04','AZ','Arizona'),('05','AR','Arkansas'),
        ('06','CA','California'),('08','CO','Colorado'),('09','CT','Connecticut'),('10','DE','Delaware'),
        ('11','DC','District of Columbia'),('12','FL','Florida'),('13','GA','Georgia'),('15','HI','Hawaii'),
        ('16','ID','Idaho'),('17','IL','Illinois'),('18','IN','Indiana'),('19','IA','Iowa'),
        ('20','KS','Kansas'),('21','KY','Kentucky'),('22','LA','Louisiana'),('23','ME','Maine'),
        ('24','MD','Maryland'),('25','MA','Massachusetts'),('26','MI','Michigan'),('27','MN','Minnesota'),
        ('28','MS','Mississippi'),('29','MO','Missouri'),('30','MT','Montana'),('31','NE','Nebraska'),
        ('32','NV','Nevada'),('33','NH','New Hampshire'),('34','NJ','New Jersey'),('35','NM','New Mexico'),
        ('36','NY','New York'),('37','NC','North Carolina'),('38','ND','North Dakota'),('39','OH','Ohio'),
        ('40','OK','Oklahoma'),('41','OR','Oregon'),('42','PA','Pennsylvania'),('44','RI','Rhode Island'),
        ('45','SC','South Carolina'),('46','SD','South Dakota'),('47','TN','Tennessee'),('48','TX','Texas'),
        ('49','UT','Utah'),('50','VT','Vermont'),('51','VA','Virginia'),('53','WA','Washington'),
        ('54','WV','West Virginia'),('55','WI','Wisconsin'),('56','WY','Wyoming'),('60','AS','American Samoa'),
        ('66','GU','Guam'),('69','MP','Northern Mariana Islands'),('72','PR','Puerto Rico'),('78','VI','U.S. Virgin Islands')
    )
"""


def _create_state_mv(*, include_covid_era_immunization: bool) -> None:
    covid_select = (
        "COALESCE(normalized.is_covid_era_immunization_response, false) AS "
        "is_covid_era_immunization_response,"
        if include_covid_era_immunization
        else "false AS is_covid_era_immunization_response,"
    )
    covid_group = (
        "COALESCE(normalized.is_covid_era_immunization_response, false),"
        if include_covid_era_immunization
        else ""
    )
    covid_expr = (
        "COALESCE(normalized.is_covid_era_immunization_response, false)"
        if include_covid_era_immunization
        else "false"
    )
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {SCHEMA}.{STATE_MV} AS
        {STATE_LOOKUP},
        normalized AS (
            SELECT
                fact.*,
                COALESCE(
                    pop_state_lookup.state_fips,
                    CASE WHEN fact.pop_county_fips ~ '^[0-9]{{5}}$' THEN LEFT(fact.pop_county_fips, 2) END,
                    recipient_state_lookup.state_fips,
                    CASE WHEN fact.recipient_county_fips ~ '^[0-9]{{5}}$' THEN LEFT(fact.recipient_county_fips, 2) END,
                    map_state_lookup.state_fips,
                    CASE WHEN fact.map_state_code ~ '^[0-9]{{2}}$' THEN fact.map_state_code END
                ) AS normalized_state_fips
            FROM {SCHEMA}.{FACT_TABLE} AS fact
            LEFT JOIN state_lookup AS pop_state_lookup
              ON pop_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.pop_state_code), ''))
            LEFT JOIN state_lookup AS recipient_state_lookup
              ON recipient_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.recipient_state_code), ''))
            LEFT JOIN state_lookup AS map_state_lookup
              ON map_state_lookup.state_code = UPPER(NULLIF(BTRIM(fact.map_state_code), ''))
            WHERE fact.is_prime_award IS TRUE
              AND fact.is_positive_obligation IS TRUE
              AND fact.is_cdc_funded IS TRUE
              AND fact.federal_action_obligation > 0
        )
        SELECT
            normalized.source_fiscal_year,
            normalized.funding_mechanism,
            state_lookup.state_fips,
            state_lookup.state_code,
            state_lookup.state_name,
            normalized.assistance_listing_number,
            normalized.assistance_listing_title,
            normalized.is_covid_or_emergency_supplemental,
            COALESCE(normalized.has_overall_award_supplemental_history, false) AS has_overall_award_supplemental_history,
            COALESCE(normalized.is_likely_vfc, false) AS is_likely_vfc,
            {covid_select}
            COALESCE(normalized.funding_profiles_comparison_excluded, false) AS funding_profiles_comparison_excluded,
            SUM(COALESCE(normalized.federal_action_obligation, 0)) AS total_obligations,
            COUNT(*)::bigint AS transaction_count,
            COUNT(DISTINCT COALESCE(
                NULLIF(normalized.award_unique_key, ''),
                NULLIF(normalized.generated_unique_award_id, ''),
                NULLIF(normalized.award_id_piid, ''),
                normalized.source_raw_table || ':' || normalized.source_raw_id::text
            ))::bigint AS award_count,
            COUNT(DISTINCT COALESCE(
                NULLIF(normalized.recipient_uei, ''),
                NULLIF(normalized.recipient_name, '')
            ))::bigint AS recipient_count,
            SUM(CASE WHEN COALESCE(normalized.has_overall_award_supplemental_history, false)
                THEN COALESCE(normalized.federal_action_obligation, 0) ELSE 0 END) AS obligations_from_awards_with_supplemental_history,
            SUM(CASE WHEN COALESCE(normalized.is_likely_vfc, false)
                THEN COALESCE(normalized.federal_action_obligation, 0) ELSE 0 END) AS likely_vfc_obligations,
            SUM(CASE WHEN COALESCE(normalized.funding_profiles_comparison_excluded, false)
                THEN COALESCE(normalized.federal_action_obligation, 0) ELSE 0 END) AS funding_profiles_excluded_obligations,
            SUM(CASE WHEN {covid_expr}
                THEN COALESCE(normalized.federal_action_obligation, 0) ELSE 0 END) AS covid_era_immunization_response_obligations,
            COUNT(*) FILTER (WHERE {covid_expr})::bigint
                AS covid_era_immunization_response_transaction_count
        FROM normalized
        JOIN state_lookup ON state_lookup.state_fips = normalized.normalized_state_fips
        GROUP BY
            normalized.source_fiscal_year,
            normalized.funding_mechanism,
            state_lookup.state_fips,
            state_lookup.state_code,
            state_lookup.state_name,
            normalized.assistance_listing_number,
            normalized.assistance_listing_title,
            normalized.is_covid_or_emergency_supplemental,
            COALESCE(normalized.has_overall_award_supplemental_history, false),
            COALESCE(normalized.is_likely_vfc, false),
            {covid_group}
            COALESCE(normalized.funding_profiles_comparison_excluded, false)
        WITH NO DATA
        """
    )
    index_columns = {
        "fy": "source_fiscal_year",
        "mech": "funding_mechanism",
        "state_fips": "state_fips",
        "state_code": "state_code",
        "aln": "assistance_listing_number",
        "supp": "is_covid_or_emergency_supplemental",
        "supp_hist": "has_overall_award_supplemental_history",
        "vfc": "is_likely_vfc",
        "covid_imm": "is_covid_era_immunization_response",
        "fp_excl": "funding_profiles_comparison_excluded",
    }
    if not include_covid_era_immunization:
        index_columns.pop("covid_imm")
    for suffix, column in index_columns.items():
        op.execute(
            f"CREATE INDEX {STATE_MV}_{suffix}_idx "
            f"ON {SCHEMA}.{STATE_MV} ({column})"
        )


def upgrade() -> None:
    op.add_column(
        FACT_TABLE,
        sa.Column(
            "is_covid_era_immunization_response",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "fact_cdc_funding_prime_covid_imm_resp_idx",
        FACT_TABLE,
        ["is_covid_era_immunization_response"],
        schema=SCHEMA,
    )
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {SCHEMA}.{STATE_MV}")
    _create_state_mv(include_covid_era_immunization=True)


def downgrade() -> None:
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {SCHEMA}.{STATE_MV}")
    op.drop_index("fact_cdc_funding_prime_covid_imm_resp_idx", table_name=FACT_TABLE, schema=SCHEMA)
    op.drop_column(FACT_TABLE, "is_covid_era_immunization_response", schema=SCHEMA)
    _create_state_mv(include_covid_era_immunization=False)
