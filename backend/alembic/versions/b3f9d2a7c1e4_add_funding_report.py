"""Funding report read model: CDC NOFO recipients, other HHS awards, and sub-awards.

Rebuilt by `python -m app.funding_report.build`; each build writes rows under a new build_id
and flips funding_report.active_build in one transaction. Read only through app.funding_report.lookup.
"""
from alembic import op

revision = 'b3f9d2a7c1e4'
down_revision = 'a8c2e6f0d4b1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE SCHEMA IF NOT EXISTS funding_report')
    op.execute("""
        CREATE TABLE funding_report.build_run (
            build_id      serial PRIMARY KEY,
            started_at    timestamptz NOT NULL DEFAULT now(),
            finished_at   timestamptz,
            status        text NOT NULL DEFAULT 'running'
                          CHECK (status IN ('running', 'complete', 'failed', 'superseded')),
            method_version text NOT NULL,
            sources       jsonb NOT NULL DEFAULT '{}'::jsonb,
            counts        jsonb NOT NULL DEFAULT '{}'::jsonb,
            notes         text
        )""")
    op.execute("""
        CREATE TABLE funding_report.active_build (
            singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
            build_id  integer NOT NULL REFERENCES funding_report.build_run(build_id),
            activated_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE funding_report.nofo (
            build_id     integer NOT NULL REFERENCES funding_report.build_run(build_id) ON DELETE CASCADE,
            nofo_key     text NOT NULL,
            fon_display  text NOT NULL,
            fon_variants text[] NOT NULL DEFAULT '{}',
            award_count  integer NOT NULL,
            recipient_count integer NOT NULL,
            best_available_total numeric,
            first_fiscal_year integer,
            last_fiscal_year  integer,
            search_text  text NOT NULL DEFAULT '',
            summary      jsonb NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (build_id, nofo_key)
        )""")
    op.execute("""
        CREATE TABLE funding_report.nofo_award (
            build_id          integer NOT NULL REFERENCES funding_report.build_run(build_id) ON DELETE CASCADE,
            nofo_key          text NOT NULL,
            award_unique_key  text NOT NULL,
            fain              text NOT NULL,
            uei               text,
            recipient_name    text NOT NULL,
            state             text,
            best_available_total numeric,
            profile           jsonb NOT NULL,
            PRIMARY KEY (build_id, nofo_key, award_unique_key)
        )""")
    op.execute('CREATE INDEX funding_report_nofo_award_uei_idx ON funding_report.nofo_award (build_id, uei)')
    op.execute('CREATE INDEX funding_report_nofo_award_fain_idx ON funding_report.nofo_award (build_id, fain)')
    op.execute("""
        CREATE TABLE funding_report.uei_award (
            build_id      integer NOT NULL REFERENCES funding_report.build_run(build_id) ON DELETE CASCADE,
            uei           text NOT NULL,
            award_number  text NOT NULL,
            nofo_keys     text[] NOT NULL DEFAULT '{}',
            total_amount  numeric NOT NULL,
            detail        jsonb NOT NULL,
            PRIMARY KEY (build_id, uei, award_number)
        )""")
    op.execute("""
        CREATE TABLE funding_report.nofo_subaward (
            build_id         integer NOT NULL REFERENCES funding_report.build_run(build_id) ON DELETE CASCADE,
            nofo_key         text NOT NULL,
            action_key       text NOT NULL,
            prime_fain       text NOT NULL,
            subawardee_uei   text,
            subawardee_name  text,
            fiscal_year      integer,
            amount           numeric,
            action           jsonb NOT NULL,
            PRIMARY KEY (build_id, nofo_key, action_key)
        )""")
    op.execute('CREATE INDEX funding_report_nofo_subaward_prime_idx ON funding_report.nofo_subaward (build_id, prime_fain)')
    # The MCP server's read-only role (infra/mcp/mcp_readonly_role.sql) reads this schema.
    # Granted here, by the owning application role, so the role's password is not rotated.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'chip_mcp_ro') THEN
            GRANT USAGE ON SCHEMA funding_report TO chip_mcp_ro;
            GRANT SELECT ON ALL TABLES IN SCHEMA funding_report TO chip_mcp_ro;
            ALTER DEFAULT PRIVILEGES IN SCHEMA funding_report GRANT SELECT ON TABLES TO chip_mcp_ro;
          END IF;
        END $$""")


def downgrade():
    op.execute('DROP SCHEMA IF EXISTS funding_report CASCADE')
