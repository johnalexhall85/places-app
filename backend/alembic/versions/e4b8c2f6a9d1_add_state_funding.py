"""State funding read model: CDC obligations to recipients in each state, by grant and federal account.

Rebuilt by `python -m app.state_funding.build`; each build writes rows under a new build_id and
flips state_funding.active_build in one transaction. Read only through app.state_funding.lookup.
state_funding.nofo_title is source data loaded by backend/scripts/fetch_grants_gov_cdc_titles.py,
not by the build. Contract: docs/state-funding/CONTRACT.md.
"""
from alembic import op

revision = 'e4b8c2f6a9d1'
down_revision = 'c6d0e4a8b2f7'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE SCHEMA IF NOT EXISTS state_funding')
    op.execute("""
        CREATE TABLE state_funding.nofo_title (
            fon_key            text NOT NULL,
            source             text NOT NULL CHECK (source IN ('grants_gov', 'cdc_funding_profiles')),
            fon_display        text NOT NULL,
            title              text NOT NULL,
            source_url         text,
            source_file_sha256 text,
            retrieved_at       timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (fon_key, source)
        )""")
    op.execute("""
        CREATE TABLE state_funding.build_run (
            build_id       serial PRIMARY KEY,
            started_at     timestamptz NOT NULL DEFAULT now(),
            finished_at    timestamptz,
            status         text NOT NULL DEFAULT 'running'
                           CHECK (status IN ('running', 'complete', 'failed', 'superseded')),
            method_version text NOT NULL,
            sources        jsonb NOT NULL DEFAULT '{}'::jsonb,
            counts         jsonb NOT NULL DEFAULT '{}'::jsonb,
            notes          text
        )""")
    op.execute("""
        CREATE TABLE state_funding.active_build (
            singleton    boolean PRIMARY KEY DEFAULT true CHECK (singleton),
            build_id     integer NOT NULL REFERENCES state_funding.build_run(build_id),
            activated_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE state_funding.award (
            build_id            integer NOT NULL REFERENCES state_funding.build_run(build_id) ON DELETE CASCADE,
            award_unique_key    text NOT NULL,
            award_id            text NOT NULL,
            award_type          text NOT NULL CHECK (award_type IN ('grant', 'contract')),
            recipient_name      text NOT NULL,
            recipient_uei       text,
            is_state_government boolean,
            fon                 text,
            fon_key             text,
            grant_name          text NOT NULL,
            name_source         text NOT NULL CHECK (name_source IN (
                                    'grants_gov_nofo_title', 'cdc_funding_profiles_nofo_title',
                                    'taggs_award_title', 'assistance_listing_title', 'award_description')),
            project_title       text,
            description         text,
            cfda_number         text,
            cfda_title          text,
            usaspending_url     text,
            search_text         text NOT NULL DEFAULT '',
            PRIMARY KEY (build_id, award_unique_key)
        )""")
    op.execute("""
        CREATE TABLE state_funding.obligation (
            build_id              integer NOT NULL REFERENCES state_funding.build_run(build_id) ON DELETE CASCADE,
            fiscal_year           integer NOT NULL,
            state                 text NOT NULL,
            award_unique_key      text NOT NULL,
            federal_account_symbol text NOT NULL,
            federal_account_name  text NOT NULL,
            is_supplemental       boolean NOT NULL,
            amount                numeric NOT NULL,
            PRIMARY KEY (build_id, fiscal_year, state, award_unique_key, federal_account_symbol, is_supplemental)
        )""")
    op.execute('CREATE INDEX state_funding_obligation_state_fy_idx '
               'ON state_funding.obligation (build_id, state, fiscal_year)')
    op.execute('CREATE INDEX state_funding_obligation_award_idx '
               'ON state_funding.obligation (build_id, award_unique_key)')
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'chip_mcp_ro') THEN
            GRANT USAGE ON SCHEMA state_funding TO chip_mcp_ro;
            GRANT SELECT ON ALL TABLES IN SCHEMA state_funding TO chip_mcp_ro;
            ALTER DEFAULT PRIVILEGES IN SCHEMA state_funding GRANT SELECT ON TABLES TO chip_mcp_ro;
          END IF;
        END $$""")


def downgrade():
    op.execute('DROP SCHEMA IF EXISTS state_funding CASCADE')
