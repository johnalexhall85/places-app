import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from app.area_pilot import operations


def test_metadata_policy_holds_schema_and_same_label_revision():
    assert operations.classify_metadata('same', 'same', {'v': 1}, {'v': 1}) == (
        'checked', 'source_metadata_unchanged_no_bulk_download')
    assert operations.classify_metadata('same', 'other', {'v': 1}, {'v': 1}) == (
        'held', 'schema_or_definition_changed')
    assert operations.classify_metadata('same', 'same', {'v': 1}, {'v': 2}) == (
        'held', 'same_label_source_revision_changed')


def test_disk_pressure_refuses_before_retrieval(tmp_path, monkeypatch):
    monkeypatch.setattr(operations.shutil, 'disk_usage', lambda path: SimpleNamespace(free=100))
    monkeypatch.setattr(operations, 'MIN_FREE_BYTES', 90)
    with pytest.raises(RuntimeError, match='Insufficient disk headroom'):
        operations.disk_guard(tmp_path, 11)
    assert operations.disk_guard(tmp_path, 10)['available_bytes'] == 100


def test_secret_in_request_exception_is_redacted(monkeypatch):
    secret = 'sensitive-census-key'

    def fail(*args, **kwargs):
        raise requests.RequestException(f'https://api.census.gov/?key={secret}')

    monkeypatch.setattr(operations.requests, 'get', fail)
    with pytest.raises(RuntimeError) as error:
        operations.get_json('https://api.census.gov/data/2024/acs/acs5')
    assert secret not in str(error.value)
    assert operations.safe_failure_reason(RuntimeError(
        f'https://api.census.gov/data?key={secret}')) == 'RuntimeError'


def test_scheduler_records_one_failure_and_checks_other_product(tmp_path, monkeypatch):
    monkeypatch.setattr(operations, 'ROOT', tmp_path)
    monkeypatch.setattr(operations, 'create_engine', lambda *a, **k: object())
    called = []
    monkeypatch.setattr(operations, 'run_check', lambda engine, product: called.append(product) or
                        ('held' if product == 'places' else 'checked'))
    monkeypatch.setattr(sys, 'argv', ['operations', 'check'])
    assert operations.main() == 1
    assert called == ['places', 'acs']


def test_product_lock_prevents_manual_scheduler_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr(operations, 'ROOT', tmp_path)
    with operations.product_lock('places'):
        with pytest.raises(BlockingIOError):
            with operations.product_lock('places'):
                pass


def test_registry_disables_unreviewed_auto_publication():
    from app.area_pilot.acs import load_registry as acs
    from app.area_pilot.registry import load_registry as places
    for config in (places('county'), places('tract'), acs()):
        policy = config['refresh_policy']
        assert policy['schedule'] == 'weekly_full_content_verification'
        assert policy['auto_publish'] is False
        assert config['source_release_id'] in policy['supported_release_ids']


def test_interrupted_places_retrieval_never_reuses_cached_data_pages(tmp_path, monkeypatch):
    from app.area_pilot.source import SourceClient, digest
    columns = []
    snap = {'revision': {'rowsUpdatedAt': 1}, 'columns': columns,
            'keys': ['00001'], 'count': 1, 'metadata': {}}
    config = {'expected_county_count': 1, 'expected_schema_sha256': digest(columns),
              'measures': [], 'source_api': 'https://example.invalid/data'}
    client = SourceClient(config, tmp_path, pause=0)
    client.checkpoint = {'signature': digest({'revision': snap['revision'],
                                              'columns': columns, 'keys': snap['keys']}),
                         'pages': {'page_000': {'path': str(tmp_path / 'stale.json')}}}
    monkeypatch.setattr(client, 'snapshot', lambda role: snap)
    monkeypatch.setattr(client, 'get', lambda *a, **k: [{'countyfips': '00001'}])
    before, after, records, stable = client.fetch()
    assert stable and len(records) == 1
    assert client.resume_pages is False


def test_values_can_change_without_metadata_revision_and_are_held():
    from app.area_pilot.source import digest, same_label_revision, semantic_digest
    columns = [{'fieldName': 'countyfips', 'dataTypeName': 'text'},
               {'fieldName': 'value', 'dataTypeName': 'number'}]
    before = [{'countyfips': '00001', 'value': '1.0'}]
    changed = [{'countyfips': '00001', 'value': '2.0'}]
    old_sha = semantic_digest(before, columns)
    new_sha = semantic_digest(changed, columns)
    assert old_sha != new_sha
    assert operations.classify_metadata(digest(columns), digest(columns),
                                        {'revision': 1}, {'revision': 1})[0] == 'checked'
    assert same_label_revision({'source_release_id': 'same', 'semantic_sha256': old_sha},
                               'same', new_sha)


def test_serialization_only_change_has_identical_semantic_digest():
    from app.area_pilot.source import semantic_digest
    columns = [{'fieldName': 'countyfips', 'dataTypeName': 'text'},
               {'fieldName': 'value', 'dataTypeName': 'number'}]
    one = [{'countyfips': '00001', 'value': '1.0'}]
    two = [{'value': 1, 'countyfips': '00001'}]
    assert json.dumps(one) != json.dumps(two)
    assert semantic_digest(one, columns) == semantic_digest(two, columns)


def test_acs_metadata_geography_survives_json_tuple_list_round_trip():
    from app.area_pilot.acs_cli import metadata_matches_published
    current = {'variables': {'B19013_001E': {'label': 'same'}},
               'geography': [('040', '2024-01-01')]}
    stored = json.loads(json.dumps(current))
    assert metadata_matches_published(current, stored)


def test_full_content_identical_path_reuses_published_release(monkeypatch, tmp_path):
    import uuid
    from datetime import datetime, timezone
    from app.area_pilot import cli, tract
    active_id, parent_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(operations, 'ROOT', tmp_path)
    monkeypatch.setattr(operations, 'disk_guard', lambda *a, **k: None)
    monkeypatch.setattr(cli, 'fetch_stage', lambda *a: (parent_id, {'duplicate': True}))
    monkeypatch.setattr(tract, 'fetch_stage_tract', lambda *a: (active_id, {'duplicate': True}))

    class Result:
        def __init__(self, value): self.value = value
        def mappings(self): return self
        def one(self): return self.value
        def one_or_none(self): return self.value
        def scalar_one_or_none(self): return self.value
        def all(self): return self.value

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None):
            query = str(sql)
            if 'SELECT a.release_id,r.parent_county_release_id' in query:
                return Result({'release_id': active_id, 'parent_county_release_id': parent_id})
            if 'SELECT status,report FROM area_pilot.release' in query:
                return Result({'status': 'published', 'report': {}})
            if 'SELECT id,status FROM area_pilot.run' in query:
                return Result({'id': run_id, 'status': 'duplicate'})
            if 'SELECT role,byte_count FROM area_pilot.source_file' in query:
                return Result([('page_000', 42)])
            if 'SELECT release_id FROM area_pilot.active_release' in query:
                return Result(active_id)
            raise AssertionError(query)

    class Engine:
        def connect(self): return Connection()

    status, reason, detail = operations.full_product(Engine(), 'places', datetime.now(timezone.utc))
    assert (status, reason) == ('checked', 'identical_semantic_content_verified')
    assert detail['archived_response_count'] == 2
    assert detail['archived_response_bytes'] == 84


def test_status_keeps_metadata_and_content_freshness_separate(monkeypatch):
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc)
    monkeypatch.setattr(operations, 'disk_usage', lambda: {'available_bytes': 100})

    class Result:
        def __init__(self, value): self.value = value
        def mappings(self): return self
        def one_or_none(self): return self.value
        def scalar_one(self): return self.value
        def all(self): return self.value

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None):
            query = str(sql)
            if "mode='metadata' AND status='checked'" in query:
                return Result({'started_at': timestamp, 'finished_at': timestamp,
                               'reason': 'metadata_checked'})
            if "mode='content'" in query:
                return Result(None)
            if 'FROM area_pilot.active_release' in query:
                return Result({'id': 'active', 'source_release_id': 'pinned',
                               'published_at': timestamp})
            if 'FROM area_pilot.source_check' in query:
                return Result({'id': 'metadata-run', 'mode': 'metadata', 'status': 'checked',
                               'reason': 'metadata_checked', 'started_at': timestamp,
                               'finished_at': timestamp}) if query.strip().endswith('LIMIT 1') else Result([])
            if 'FROM area_pilot.release' in query and 'status=' in query:
                return Result([]) if "status='held'" in query else Result({'id': 'active', 'published_at': timestamp})
            if 'FROM area_pilot.run' in query:
                return Result([])
            if 'pg_total_relation_size' in query:
                return Result(0)
            raise AssertionError(query)

    class Engine:
        def connect(self): return Connection()

    result = operations.status_report(Engine())
    for product in result['products'].values():
        assert product['last_successful_metadata_check']['reason'] == 'metadata_checked'
        assert product['last_successful_full_content_verification'] is None
        assert product['refresh_health'] == 'never_verified'


@pytest.mark.parametrize('outcome, expected', [('partial', 'failed'), ('revised', 'held')])
def test_incomplete_or_revised_content_cannot_touch_active_pointer(tmp_path, monkeypatch, outcome, expected):
    monkeypatch.setattr(operations, 'ROOT', tmp_path)
    monkeypatch.setattr(operations, 'disk_usage', lambda: {'archive_bytes': 0})
    statements = []

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None):
            statements.append((str(sql), params))

    class Engine:
        def begin(self): return Connection()

    if outcome == 'partial':
        def adapter(*args):
            raise RuntimeError('partial retrieval; secret-key=do-not-log')
    else:
        def adapter(*args):
            return 'held', 'same_label_semantic_revision', {'candidate_id': 'held-candidate'}
    monkeypatch.setattr(operations, 'full_product', adapter)
    assert operations.run_content_check(Engine(), 'places') == expected
    assert any("'content','running'" in sql for sql, _ in statements)
    assert any(params and params.get('status') == expected for _, params in statements)
    assert all('active_release' not in sql for sql, _ in statements)
    assert 'do-not-log' not in str(statements)
