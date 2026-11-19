"""Build and publish CHIP's national reference values.

    python -m app.area_pilot.national_cli build              # fetch + validate; stages a 'ready' release
    python -m app.area_pilot.national_cli publish <id> <sha> # move the chip_national_reference pointer
    python -m app.area_pilot.national_cli deactivate
"""
from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import create_engine, text

from app.area_pilot import national
from app.area_pilot.acs import census_api_key
from app.db import DATABASE_URL


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db-url', default=os.getenv('DATABASE_URL', DATABASE_URL))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('build')
    pub = sub.add_parser('publish')
    pub.add_argument('release_id')
    pub.add_argument('semantic_sha256')
    sub.add_parser('deactivate')
    args = parser.parse_args(argv)
    engine = create_engine(args.db_url, pool_pre_ping=True)
    if args.action == 'build':
        print(json.dumps(national.build(engine, census_api_key()), indent=2))
    elif args.action == 'publish':
        national.publish(engine, args.release_id, args.semantic_sha256)
        print(f'published {args.release_id}')
    else:
        with engine.begin() as conn:
            conn.execute(text(f'DELETE FROM {national.S}.active_release WHERE dataset_id=:d'), {'d': national.DATASET_ID})
        print('deactivated')


if __name__ == '__main__':
    main()
