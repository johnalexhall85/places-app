"""Manual history candidate, review, publication, and pointer recovery for one product.

  python -m app.area_pilot.history.cli --product cms_gv fetch-stage-validate
  python -m app.area_pilot.history.cli --product cms_gv review <candidate>
  python -m app.area_pilot.history.cli --product cms_gv approve-publish <candidate> --semantic-sha256 ... \
      --schema-sha256 ... --metadata-sha256 ...
  python -m app.area_pilot.history.cli --product cms_gv rollback <release> | deactivate
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import uuid

from sqlalchemy import create_engine

from app.area_pilot.history import store
from app.area_pilot.history.fetch import HISTORY_ROOT
from app.area_pilot.history.registry import load_history_registry, products
from app.db import DATABASE_URL

SUMMARY_KEYS = ('status', 'hold_reason', 'checks', 'observation_count', 'missing_pairs', 'undeclared_pairs',
                'row_problems', 'unmatched_boundary', 'semantic_sha256', 'schema_sha256', 'metadata_sha256',
                'keyset_sha256', 'duration_seconds', 'existing_status')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db-url', default=os.getenv('DATABASE_URL', DATABASE_URL))
    parser.add_argument('--product', required=True, choices=products())
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('fetch-stage-validate')
    review_cmd = sub.add_parser('review'); review_cmd.add_argument('candidate_id', type=uuid.UUID)
    for name in ('approve-publish', 'release-reviewed-hold'):
        cmd = sub.add_parser(name); cmd.add_argument('candidate_id', type=uuid.UUID)
        for field in ('semantic_sha256', 'schema_sha256', 'metadata_sha256'):
            cmd.add_argument('--' + field.replace('_', '-'), required=True)
        if name == 'release-reviewed-hold':
            cmd.add_argument('--operator-note', required=True)
    rollback = sub.add_parser('rollback'); rollback.add_argument('release_id', type=uuid.UUID)
    sub.add_parser('deactivate')
    args = parser.parse_args()
    config = load_history_registry(args.product)
    engine = create_engine(args.db_url, pool_pre_ping=True)
    lock_dir = HISTORY_ROOT / args.product
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / 'ingest.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'fetch-stage-validate':
            from app.area_pilot.acs import census_api_key
            key = census_api_key() if any(s.get('census_key') for s in config['sources']) else None
            candidate, report = store.fetch_stage(engine, config, census_key=key)
            print(json.dumps({'candidate_id': str(candidate),
                              'report': {k: report[k] for k in SUMMARY_KEYS if k in report}}, indent=2, default=str))
        elif args.action == 'review':
            result = store.review(engine, args.candidate_id, config)
            result['report'] = {k: result['report'][k] for k in ('checks', 'hold_reason', 'observation_count',
                                                                  'unmatched_boundary') if k in result['report']}
            print(json.dumps(result, indent=2, default=str))
        elif args.action == 'approve-publish':
            store.publish(engine, config, args.candidate_id, args.semantic_sha256, args.schema_sha256,
                          args.metadata_sha256)
            print(f'Published {config["dataset_id"]} release {args.candidate_id}')
        elif args.action == 'release-reviewed-hold':
            store.release_reviewed_hold(engine, config, args.candidate_id, args.semantic_sha256,
                                        args.schema_sha256, args.metadata_sha256, args.operator_note)
            print(f'Released reviewed hold {args.candidate_id}')
        else:
            store.set_pointer(engine, config, args.action, getattr(args, 'release_id', None))
            print(f'{config["dataset_id"]} pointer updated')


if __name__ == '__main__':
    main()
