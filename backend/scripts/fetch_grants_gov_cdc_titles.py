"""Load CDC funding opportunity (NOFO) titles into state_funding.nofo_title.

Two sources, each matched later by exact normalized opportunity number (app.funding_report.keys.nofo_key):
  grants_gov            the Grants.gov XML extract (GrantsDBExtractYYYYMMDDv2.zip), HHS agency codes
                        (CDC also funds under NIH-posted parent announcements such as PA-21-259);
                        a CDC record wins if one number appears under several agencies
  cdc_funding_profiles  cdc_profiles.raw_profile_rows nofo_title / funding_opportunity_title

The extract is downloaded separately and archived with its SHA-256 under data/grantsgov/<date>/:
  curl -o GrantsDBExtract<date>v2.zip https://prod-grants-gov-chatbot.s3.amazonaws.com/extracts/GrantsDBExtract<date>v2.zip

Usage (dry run prints coverage; --apply replaces both sources' rows in one transaction):
  cd backend && python scripts/fetch_grants_gov_cdc_titles.py --zip PATH [--apply] [--allow-live]
"""
from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import iterparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import DATABASE_URL  # noqa: E402
from app.funding_report.keys import nofo_key  # noqa: E402

EXTRACT_URL = 'https://prod-grants-gov-chatbot.s3.amazonaws.com/extracts/{name}'
DETAIL_TAGS = {'OpportunitySynopsisDetail_1_0': 1, 'OpportunityForecastDetail_1_0': 0}


def clean_title(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r'\s+', ' ', html.unescape(html.unescape(value))).strip()
    return value or None


def mmddyyyy(value: str | None) -> str:
    try:
        return datetime.strptime(value or '', '%m%d%Y').strftime('%Y%m%d')
    except ValueError:
        return ''


def read_extract(zip_path: Path) -> dict[str, dict]:
    """Return one title per fon_key: prefer CDC, then a synopsis over a forecast, then the latest update."""
    best: dict[str, tuple] = {}
    with zipfile.ZipFile(zip_path) as archive:
        with archive.open(archive.namelist()[0]) as handle:
            for _event, element in iterparse(handle):
                tag = element.tag.split('}')[-1]
                if tag not in DETAIL_TAGS:
                    continue
                record = {child.tag.split('}')[-1]: child.text for child in element}
                element.clear()
                agency = record.get('AgencyCode') or ''
                if not agency.startswith('HHS'):
                    continue
                number = (record.get('OpportunityNumber') or '').strip()
                key, title = nofo_key(number), clean_title(record.get('OpportunityTitle'))
                if not key or not title:
                    continue
                rank = (agency.startswith('HHS-CDC'), DETAIL_TAGS[tag], mmddyyyy(record.get('LastUpdatedDate')), record.get('OpportunityID') or '')
                if key not in best or rank > best[key][0]:
                    best[key] = (rank, {'fon_key': key, 'fon_display': number, 'title': title,
                                        'source_url': ('https://www.grants.gov/search-results-detail/'
                                                       + record['OpportunityID']) if record.get('OpportunityID') else None})
    return {key: value[1] for key, value in best.items()}


def read_profiles(conn) -> dict[str, dict]:
    rows = conn.execute(text("""
        SELECT nofo_number, coalesce(nullif(trim(nofo_title), ''), nullif(trim(funding_opportunity_title), '')) AS title,
               count(*) AS n
          FROM cdc_profiles.raw_profile_rows
         WHERE nullif(trim(nofo_number), '') IS NOT NULL
         GROUP BY 1, 2""")).mappings()
    best: dict[str, tuple] = {}
    for row in rows:
        key, title = nofo_key(row['nofo_number']), clean_title(row['title'])
        if key and title and (key not in best or (row['n'], title) > best[key][0]):
            best[key] = ((row['n'], title), {'fon_key': key, 'fon_display': row['nofo_number'].strip(),
                                             'title': title, 'source_url': None})
    return {key: value[1] for key, value in best.items()}


def coverage(conn, keys_by_source: dict[str, set]) -> list[dict]:
    """Share of in-state CDC grants (File C, FY2021+) whose opportunity number has a title, by FY."""
    rows = conn.execute(text("""
        WITH g AS (
          SELECT DISTINCT fiscal_year, award_unique_key, award_id_fain AS fain
            FROM cdc_funding.cdc_funding_awards
           WHERE fiscal_year >= 2021 AND grant_or_contract = 'Grant' AND nullif(trim(recipient_state), '') IS NOT NULL),
        p AS (
          SELECT award_unique_key, max(nullif(raw_record->>'funding_opportunity_number', '')) AS fon
            FROM cdc_funding.fact_cdc_funding_prime_transaction GROUP BY 1),
        t AS (SELECT award_number AS fain, max(nullif(trim(fon), '')) AS fon FROM taggs.raw_awards GROUP BY 1)
        SELECT g.fiscal_year, coalesce(p.fon, t.fon) AS fon, count(*) AS n
          FROM g LEFT JOIN p USING (award_unique_key) LEFT JOIN t ON t.fain = g.fain
         GROUP BY 1, 2""")).mappings()
    by_year: dict[int, dict] = {}
    for row in rows:
        key = nofo_key(row['fon'])
        stats = by_year.setdefault(row['fiscal_year'], {'fiscal_year': row['fiscal_year'], 'grants': 0,
                                                        'grants_gov': 0, 'either': 0})
        stats['grants'] += row['n']
        stats['grants_gov'] += row['n'] if key in keys_by_source['grants_gov'] else 0
        stats['either'] += row['n'] if key in keys_by_source['grants_gov'] | keys_by_source['cdc_funding_profiles'] else 0
    return [by_year[year] for year in sorted(by_year)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--zip', required=True, type=Path, help='Archived Grants.gov extract zip')
    parser.add_argument('--database-url', default=os.environ.get('DATABASE_URL', DATABASE_URL))
    parser.add_argument('--apply', action='store_true', help='Replace state_funding.nofo_title rows')
    parser.add_argument('--allow-live', action='store_true', help='Allow writing outside places_staging (Gate B)')
    args = parser.parse_args(argv)
    database = make_url(args.database_url).database
    if args.apply and database != 'places_staging' and not args.allow_live:
        raise SystemExit('Refusing to write outside places_staging without --allow-live')

    sha256 = hashlib.sha256(args.zip.read_bytes()).hexdigest()
    grants_gov = read_extract(args.zip)
    url = EXTRACT_URL.format(name=args.zip.name)
    engine = create_engine(args.database_url, pool_pre_ping=True)
    with engine.begin() as conn:
        profiles = read_profiles(conn)
        print(f'database={database} extract={args.zip.name} sha256={sha256}')
        print(f'titles: grants_gov={len(grants_gov)} cdc_funding_profiles={len(profiles)}')
        for row in coverage(conn, {'grants_gov': set(grants_gov), 'cdc_funding_profiles': set(profiles)}):
            print('FY{fiscal_year}: in-state grants={grants} with Grants.gov title={grants_gov} '
                  '({p1:.1f}%) with any NOFO title={either} ({p2:.1f}%)'.format(
                      p1=100 * row['grants_gov'] / row['grants'], p2=100 * row['either'] / row['grants'], **row))
        if not args.apply:
            print('dry run: no rows written')
            return 0
        conn.execute(text('DELETE FROM state_funding.nofo_title'))
        insert = text("""INSERT INTO state_funding.nofo_title
                         (fon_key, source, fon_display, title, source_url, source_file_sha256)
                         VALUES (:fon_key, :source, :fon_display, :title, :source_url, :sha)""")
        conn.execute(insert, [dict(row, source='grants_gov', sha=sha256, source_url=row['source_url'] or url)
                              for row in grants_gov.values()])
        if profiles:
            conn.execute(insert, [dict(row, source='cdc_funding_profiles', sha=None) for row in profiles.values()])
        print(f'wrote {len(grants_gov) + len(profiles)} rows to state_funding.nofo_title')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
