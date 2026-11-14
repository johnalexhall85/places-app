"""Seal a private local CHIP recovery set without exporting credential values."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from app.db import DATABASE_URL


def elapsed_seconds(path: Path):
    if not path.exists():
        return None
    match = re.search(r'Elapsed \(wall clock\) time \(h:mm:ss or m:ss\):\s*(\S+)',
                      path.read_text())
    if not match:
        return None
    parts = [float(part) for part in match.group(1).split(':')]
    return round(sum(part * 60 ** offset for offset, part in enumerate(reversed(parts))), 2)


def file_sha256(path: Path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def main(set_dir: Path):
    set_dir = set_dir.resolve()
    if not set_dir.is_dir() or set_dir.stat().st_mode & 0o077:
        raise SystemExit('Recovery set must be a private directory')
    required = ('places_current.dump', 'database_toc.txt', 'raw_ingest.tar.zst',
                'published_source_manifest.json', 'working_tree_no_env.tar.zst',
                'local_git_history.bundle', 'deployed_webroot.tar.zst')
    if any(not (set_dir / name).is_file() for name in required):
        raise SystemExit('Recovery set is incomplete')
    source_manifest = json.loads((set_dir / 'published_source_manifest.json').read_text())
    with create_engine(DATABASE_URL).connect() as conn:
        version = conn.execute(text("SELECT current_setting('server_version')")).scalar_one()
        db_bytes = conn.execute(text('SELECT pg_database_size(current_database())')).scalar_one()
        migration = conn.execute(text('SELECT version_num FROM public.alembic_version')).scalar_one()
        extensions = [dict(row) for row in conn.execute(text('''SELECT e.extname AS name,
            e.extversion AS version,n.nspname AS schema FROM pg_extension e
            JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname''')).mappings()]
        roles = [dict(row) for row in conn.execute(text('''SELECT rolname AS name,
            rolcanlogin AS can_login,rolsuper AS superuser,rolcreatedb AS can_create_db
            FROM pg_roles WHERE rolname NOT LIKE 'pg_%' ORDER BY rolname''')).mappings()]
        schemas = list(conn.execute(text('''SELECT nspname FROM pg_namespace
            WHERE nspname NOT LIKE 'pg_%' AND nspname<>'information_schema'
            ORDER BY nspname''')).scalars())
        active = {row['dataset_id']: str(row['release_id']) for row in conn.execute(text('''
            SELECT dataset_id,release_id FROM area_pilot.active_release
            ORDER BY dataset_id''')).mappings()}
    files = sorted((path for path in set_dir.rglob('*') if path.is_file()
                    and path.name not in ('SHA256SUMS', 'recovery_manifest.json')),
                   key=lambda path: str(path.relative_to(set_dir)))
    digests = {str(path.relative_to(set_dir)): file_sha256(path) for path in files}
    expected_db_sha = (set_dir / 'database_sha256.txt').read_text().split()[0]
    if digests['places_current.dump'] != expected_db_sha:
        raise SystemExit('Database dump checksum changed')
    remote_heads = dict(line.split('\t', 1)[::-1] for line in
                        (set_dir / 'remote_heads_at_backup.txt').read_text().splitlines())
    local_head = (set_dir / 'local_head.txt').read_text().strip()
    branch = (set_dir / 'local_branch.txt').read_text().strip()
    worktree = (set_dir / 'git_worktree_status.txt').read_text().splitlines()
    ahead = int(subprocess.check_output(['git', '-C', '/home/john/places-app',
                                         'rev-list', '--count', f'origin/{branch}..HEAD'],
                                        text=True).strip())
    toc_match = re.search(r'TOC Entries:\s*(\d+)',
                          (set_dir / 'database_toc.txt').read_text())
    if not toc_match:
        raise SystemExit('Database table of contents lacks an entry count')
    restore_output = set_dir / 'restored_validation.txt'
    baseline = set_dir / 'production_validation_baseline.txt'
    restore_finished = (set_dir / 'database_restore_finished_utc.txt').exists()
    restore_passed = (restore_output.is_file() and baseline.is_file() and
                      restore_output.read_bytes() == baseline.read_bytes() and restore_finished)
    usage = shutil.disk_usage(set_dir)
    main_archives = ('places_current.dump', 'raw_ingest.tar.zst',
                     'working_tree_no_env.tar.zst', 'local_git_history.bundle',
                     'deployed_webroot.tar.zst')
    one_set = sum((set_dir / name).stat().st_size for name in main_archives)
    payload = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'storage': {'block_device': '/dev/vda', 'partition': '/dev/vda2',
                    'filesystem': 'ext4', 'mount': '/', 'separate_volume_present': False,
                    'recovery_set_path': str(set_dir), 'filesystem_total_bytes': usage.total,
                    'filesystem_available_bytes_after_set': usage.free,
                    'copy_type': 'local_on_production_vm', 'independent_copy_complete': False},
        'database': {'name': 'places', 'production_size_bytes_at_manifest': db_bytes,
                     'postgres_version': version, 'extensions': extensions,
                     'required_roles_without_passwords': roles, 'schemas': schemas,
                     'migration_head': migration,
                     'backup': {'file': 'places_current.dump',
                                'format': 'PostgreSQL custom gzip level 6',
                                'consistent_pg_dump_snapshot': True,
                                'started_utc': (set_dir/'database_dump_started_utc.txt').read_text().strip(),
                                'finished_utc': (set_dir/'database_dump_finished_utc.txt').read_text().strip(),
                                'duration_seconds': elapsed_seconds(set_dir/'database_dump_time.txt'),
                                'bytes': (set_dir/'places_current.dump').stat().st_size,
                                'sha256': digests['places_current.dump'],
                                'toc_entries': int(toc_match.group(1))}},
        'active_releases': active,
        'published_sources': {'manifest': 'published_source_manifest.json',
                              'archive': 'raw_ingest.tar.zst',
                              'referenced_rows': source_manifest['published_source_rows'],
                              'verified_unique_files': source_manifest['unique_files'],
                              'verified_unique_bytes': source_manifest['unique_bytes']},
        'git': {'working_tree_base_commit': local_head, 'branch': branch,
                'working_tree_dirty': bool(worktree),
                'local_commits_ahead_of_remote': ahead,
                'remote_branch_head': remote_heads.get('refs/heads/' + branch),
                'chip_paths_untracked': any(line.startswith('??') and any(
                    path in line for path in ('backend/app/area_pilot/',
                                               'backend/docs/chip_',
                                               'infra/systemd/chip-area-refresh'))
                                            for line in worktree),
                'remote_reconstructs_deployment': not worktree and
                    local_head == remote_heads.get('refs/heads/' + branch),
                'local_bundle': 'local_git_history.bundle',
                'working_tree_snapshot': 'working_tree_no_env.tar.zst'},
        'required_recovery_files': {
            'registries': ['registries/places_county_2025.json',
                           'registries/places_tract_2025.json',
                           'registries/acs_2024_b19013.json'],
            'deployment': ['deployment/places-backend.service',
                           'deployment/chip-area-refresh.service',
                           'deployment/chip-area-refresh.timer',
                           'deployment/places-demo.nginx.conf',
                           'deployment/docker-compose.recovery.template.yml',
                           'deployment/alembic.recovery.template.ini',
                           'deployed_webroot.tar.zst'],
            'source_archives': ['raw_ingest.tar.zst', 'published_source_manifest.json'],
            'operator_documentation': ['chip_current_recovery_set.md',
                                       'working_tree_no_env.tar.zst']},
        'separate_secure_recovery_required': [
            'backend/.env and its database and access-control values',
            'frontend/.env.production build configuration',
            '/home/john/.config/places/census-api-key',
            'database role password and any rotated replacement',
            'any external transfer encryption key and demo-access recovery credentials'],
        'restore_test': {'status': 'passed' if restore_passed else
                         ('failed_validation' if restore_finished else 'not_completed'),
                         'isolated_network': 'none', 'application_services_started': False,
                         'temporary_database': 'chip_restore',
                         'validation_baseline_match': bool(restore_passed),
                         'started_utc': ((set_dir/'database_restore_started_utc.txt').read_text().strip()
                                         if (set_dir/'database_restore_started_utc.txt').exists() else None),
                         'finished_utc': ((set_dir/'database_restore_finished_utc.txt').read_text().strip()
                                          if (set_dir/'database_restore_finished_utc.txt').exists() else None),
                         'duration_seconds': elapsed_seconds(set_dir/'database_restore_time.txt'),
                         'initial_template_conflict_corrected':
                             (set_dir/'database_restore_initial_stderr.txt').exists()},
        'capacity_proposal': {'daily_sets': 7, 'weekly_sets': 4,
                              'measured_one_set_archive_bytes': one_set,
                              'eleven_sets_archive_bytes_at_current_sizes': 11 * one_set,
                              'automatic_deletion_enabled': False,
                              'backup_timer_enabled': False},
        'artifact_sha256': digests,
    }
    manifest = set_dir / 'recovery_manifest.json'
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
    manifest.chmod(0o600)
    digests['recovery_manifest.json'] = file_sha256(manifest)
    checksum_file = set_dir / 'SHA256SUMS'
    checksum_file.write_text(''.join(f'{sha}  {path}\n' for path, sha in sorted(digests.items())))
    checksum_file.chmod(0o600)
    print('manifest_created', manifest)
    print('restore_test', payload['restore_test']['status'])
    print('checksum_entries', len(digests))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: build_recovery_manifest.py SET_DIRECTORY')
    main(Path(sys.argv[1]))
