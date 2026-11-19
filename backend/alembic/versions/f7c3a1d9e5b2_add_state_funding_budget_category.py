"""State funding: crosswalk from federal account to CDC budget category.

Each Treasury federal account maps to exactly one category; no amount is split or apportioned.
CDC's appropriation accounts map to the matching top-level line of the CDC Operating Plan
(https://www.cdc.gov/budget/operating-plans/index.html, FY 2026, retrieved 2026-11-19), named as
the plan names them. Accounts outside CDC's Operating Plan get their own labelled categories.
Contract: docs/state-funding/CONTRACT.md, amendment 1. The build fails if a source account has no row.
"""
from alembic import op

revision = 'f7c3a1d9e5b2'
down_revision = 'e4b8c2f6a9d1'
branch_labels = None
depends_on = None

OPLAN = 'cdc_operating_plan'
ATSDR = 'atsdr_operating_plan'
OUTSIDE = 'outside_operating_plan'

# (code, name, sort order, basis, accounts)
CATEGORIES = [
    ('IRD', 'Immunization and Respiratory Diseases', 1, OPLAN, ['075-0951']),
    ('HIV', 'HIV/AIDS, Viral Hepatitis, STI and TB Prevention', 2, OPLAN, ['075-0950']),
    ('EZID', 'Emerging and Zoonotic Infectious Diseases', 3, OPLAN, ['075-0949']),
    ('CHRONIC', 'Chronic Disease Prevention and Health Promotion', 4, OPLAN, ['075-0948']),
    ('BDDD', 'Birth Defects, Developmental Disabilities, Disability and Health', 5, OPLAN, ['075-0958']),
    ('ENV', 'Environmental Health', 6, OPLAN, ['075-0947']),
    ('INJURY', 'Injury Prevention and Control', 7, OPLAN, ['075-0952']),
    ('PHSS', 'Public Health Scientific Services', 8, OPLAN, ['075-0959']),
    ('OSH', 'Occupational Safety and Health', 9, OPLAN, ['075-0953']),
    ('GLOBAL', 'Global Health', 10, OPLAN, ['075-0955']),
    ('PHPR', 'Public Health Preparedness and Response', 11, OPLAN, ['075-0956']),
    ('CROSS', 'Cross-Cutting Activities and Program Support', 12, OPLAN, ['075-0943']),
    ('BF', 'Buildings and Facilities', 13, OPLAN, ['075-0960']),
    ('EEOICPA', 'Energy Employees Occupational Illness Compensation Program Act (EEOICPA)', 14, OPLAN, ['075-0954']),
    ('ATSDR', 'Agency for Toxic Substances and Disease Registry (ATSDR)', 15, ATSDR, ['075-0944']),
    ('VFC', 'Vaccines for Children (Medicaid)', 16, OUTSIDE, ['075-0512']),
    ('WTC', 'World Trade Center Health Program', 17, OUTSIDE, ['075-0946', '075-0961']),
    ('PHSSEF', 'Public Health and Social Services Emergency Fund (HHS)', 18, OUTSIDE, ['075-0140']),
    ('IDRRF', 'Infectious Diseases Rapid Response Reserve Fund', 19, OUTSIDE, ['075-0945']),
    ('NEF', 'Nonrecurring Expenses Fund (HHS)', 20, OUTSIDE, ['075-0125']),
    ('OTHER_CDC', 'Other CDC accounts (Working Capital Fund, gifts, research agreements)', 21, OUTSIDE,
     ['075-4553', '075-8250', '075-5146']),
    ('OTHER_HHS', 'Other HHS accounts', 22, OUTSIDE,
     ['075-0120', '075-0131', '075-0145', '075-0359', '075-0509', '075-0511', '075-0600', '075-0844',
      '075-0846', '075-0849', '075-0872', '075-0884', '075-0885', '075-0886', '075-0892', '075-1000',
      '075-1363', '075-1364', '075-1365', '075-1700', '075-8514']),
]


def upgrade():
    op.execute("""
        CREATE TABLE state_funding.budget_category (
            federal_account_symbol text PRIMARY KEY,
            category_code  text NOT NULL,
            category_name  text NOT NULL,
            category_order integer NOT NULL,
            basis          text NOT NULL CHECK (basis IN ('cdc_operating_plan', 'atsdr_operating_plan',
                                                          'outside_operating_plan')),
            source         text NOT NULL
        )""")
    source = 'CDC FY 2026 Operating Plan top-level lines (retrieved 2026-11-19); CHIP crosswalk v1'
    rows = []
    for code, name, order, basis, accounts in CATEGORIES:
        for symbol in accounts:
            rows.append("('%s','%s','%s',%d,'%s','%s')" % (
                symbol, code, name.replace("'", "''"), order, basis, source))
    op.execute('INSERT INTO state_funding.budget_category VALUES ' + ','.join(rows))
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'chip_mcp_ro') THEN
            GRANT SELECT ON state_funding.budget_category TO chip_mcp_ro;
          END IF;
        END $$""")


def downgrade():
    op.execute('DROP TABLE IF EXISTS state_funding.budget_category')
