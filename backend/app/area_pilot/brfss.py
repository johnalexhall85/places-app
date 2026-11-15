"""CDC BRFSS state prevalence: retrieval, parsing, and digests.

An independent shared product (its own registry, tables, and release pointer). It reads CDC's
published crude prevalence, 95% confidence limits, and response counts for the "Overall" breakout
of selected questions, one response per measure. Nothing is derived, combined, or re-based, and
no state value is computed from PLACES counties.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.area_pilot.source import SourceClient, digest, normalize_record, revision, schema_columns

S = 'area_pilot'
NOT_PUBLISHED = 'not_published'
STATUS_TEXT = {
    'available': 'Published estimate', 'true_zero': 'Published zero',
    'not_available': ('Not available from CDC: fewer than 50 respondents in the denominator, relative '
                      'standard error above 30%, or the state did not collect the data that year'),
    NOT_PUBLISHED: 'No result for this state and year in the CDC file',
}
ROW_LIMIT = 5000


def load_registry():
    config = json.loads((Path(__file__).with_name('registry') / 'brfss_state_2023.json').read_text(encoding='utf-8'))
    if config['geographies'] != ['state'] or config['aggregation_method'] != 'none' or config['value_type'] != 'crude_prevalence':
        raise ValueError('BRFSS registry contract is invalid')
    ids = [m['measure_id'] for m in config['measures']]
    selections = [(m['observation_period'], m['question_id'], m['response_id']) for m in config['measures']]
    if len(ids) != len(set(ids)) or len(selections) != len(set(selections)):
        raise ValueError('BRFSS measures must be unique')
    for measure in config['measures']:
        if measure['observation_period'] not in config['expected_locations']:
            raise ValueError(f"{measure['measure_id']}: no expected locations for its year")
        if measure['kind'] != 'percent' or not all(re.fullmatch(r'[A-Za-z0-9_]+', measure[k]) for k in ('question_id', 'response_id')):
            raise ValueError(f"{measure['measure_id']}: unsupported measure definition")
    special = set(config['median_locations']) | set(config['source_only_locations'])
    for year, locations in config['expected_locations'].items():
        if not re.fullmatch(r'\d{4}', year) or not special <= set(locations):
            raise ValueError('BRFSS expected locations are invalid')
    return config


def where_clause(config):
    """The exact source selection: one (year, question, response) per measure, Overall breakout only."""
    parts = [f"(year='{m['observation_period']}' AND questionid='{m['question_id']}' AND responseid='{m['response_id']}')"
             for m in config['measures']]
    return f"break_out='{config['source_filters']['break_out']}' AND (" + ' OR '.join(parts) + ')'


def measure_set(config):
    return [[m['measure_id'], m['observation_period'], m['population'], m['question_id'], m['response_id'],
             m.get('places_measure_id'), sorted(m.get('documented_unavailable_states', []))]
            for m in sorted(config['measures'], key=lambda m: m['measure_id'])]


def location_kind(config, geoid):
    if geoid in config['median_locations']:
        return 'median'
    return 'source_only' if geoid in config['source_only_locations'] else 'state'


def _decimal(raw, field):
    try:
        number = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError(f'{field}: invalid number {raw!r}') from exc
    if not number.is_finite() or not 0 <= number <= 100:
        raise ValueError(f'{field}: outside 0-100')
    return number


def parse_observation(row, measure, config):
    """Validate one source row against the registry and return its published values."""
    filters = config['source_filters']
    where = f"{measure['measure_id']} {row.get('locationabbr')}"
    for field, expected in (('break_out', filters['break_out']), ('data_value_type', filters['data_value_type']),
                            ('data_value_unit', filters['data_value_unit']), ('datasource', filters['datasource']),
                            ('year', measure['observation_period']), ('questionid', measure['question_id']),
                            ('responseid', measure['response_id']), ('response', measure['response']),
                            ('question', measure['source_question']), ('topic', measure['source_topic'])):
        if row.get(field) != expected:
            raise ValueError(f'{where}: source {field} is {row.get(field)!r}, expected {expected!r}')
    geoid = row.get('locationid') or ''
    expected_abbr = config['expected_locations'][measure['observation_period']].get(geoid)
    if expected_abbr is None or row.get('locationabbr') != expected_abbr:
        raise ValueError(f'{where}: unexpected location {geoid!r}')
    kind = location_kind(config, geoid)
    raw, low, high = row.get('data_value'), row.get('confidence_limit_low'), row.get('confidence_limit_high')
    symbol = row.get('data_value_footnote_symbol')
    sample = row.get('sample_size')
    if sample is not None and not re.fullmatch(r'\d+', str(sample)):
        raise ValueError(f'{where}: invalid sample size')
    result = {'value': None, 'ci_low': None, 'ci_high': None, 'sample_size': int(sample) if sample is not None else None,
              'location_kind': kind}
    if kind == 'median':
        if symbol != config['footnotes']['median'] or raw is None or low is not None or high is not None:
            raise ValueError(f'{where}: median row is not in the documented form')
        value = _decimal(raw, where)
        return result | {'value': value, 'status': 'true_zero' if value == 0 else 'available'}
    if raw is None:
        if symbol != config['footnotes']['unavailable'] or low is not None or high is not None:
            raise ValueError(f'{where}: value absent without the CDC unavailability footnote')
        return result | {'status': 'not_available'}
    if symbol is not None:
        raise ValueError(f'{where}: unexpected footnote {symbol!r} on a published value')
    if low is None or high is None:
        raise ValueError(f'{where}: published value without confidence limits')
    value, low, high = _decimal(raw, where), _decimal(low, where), _decimal(high, where)
    if not low <= value <= high:
        raise ValueError(f'{where}: value outside its confidence limits')
    return result | {'value': value, 'ci_low': low, 'ci_high': high, 'status': 'true_zero' if value == 0 else 'available'}


def parse_rows(rows, config, columns):
    """Return {(measure_id, geoid): normalized source row}. Every row must match exactly one measure."""
    by_selection = {(m['observation_period'], m['question_id'], m['response_id']): m for m in config['measures']}
    records = {}
    for row in rows:
        measure = by_selection.get((row.get('year'), row.get('questionid'), row.get('responseid')))
        if measure is None:
            raise ValueError('Source returned a row outside the registered selection')
        parse_observation(row, measure, config)
        key = (measure['measure_id'], row['locationid'])
        if key in records:
            raise ValueError(f'Duplicate source row for {key}')
        records[key] = normalize_record(row, columns)
    return records


def expected_keys(config):
    return sorted((m['measure_id'], geoid) for m in config['measures']
                  for geoid in config['expected_locations'][m['observation_period']])


def semantic_sha(records):
    return digest([[measure, geoid, {field: row.get(field) for field in sorted(row)}]
                   for (measure, geoid), row in sorted(records.items())])


def metadata_payload(config, columns):
    """What a reviewer approves besides the values: dataset, selection, schema, and measure set.

    The Socrata revision timestamps are kept as provenance in `source_before`, not here: this
    dataset spans 2011 to the present and changes whenever CDC adds any year, which says nothing
    about the selected rows. Their content is pinned by the semantic digest.
    """
    return {'dataset_id': config['dataset_id'], 'source_api': config['source_api'],
            'source_dataset_name': config['source_dataset_name'], 'source_release_id': config['source_release_id'],
            'where': where_clause(config), 'schema_sha256': digest(columns), 'measure_set': measure_set(config),
            'expected_locations': config['expected_locations'], 'value_type': config['value_type']}


class BrfssClient(SourceClient):
    """Reuses the reviewed Socrata transport (retries, byte archive) for one filtered selection."""

    def snapshot(self, role):
        metadata = self.get(self.config['source_metadata_api'], {}, f'{role}_metadata')
        if metadata.get('name') != self.config['source_dataset_name']:
            raise ValueError('Official dataset name changed')
        count = self.get(self.config['source_api'], {'$select': 'count(*) as n', '$where': where_clause(self.config)},
                         f'{role}_count')
        return {'revision': revision(metadata), 'columns': schema_columns(metadata), 'count': int(count[0]['n'])}

    def fetch(self):
        config = self.config
        before = self.snapshot('before')
        if digest(before['columns']) != config['expected_schema_sha256']:
            raise ValueError('Official schema differs from reviewed registry')
        expected = len(expected_keys(config))
        if before['count'] != expected or expected >= ROW_LIMIT:
            raise ValueError(f'Source selection has {before["count"]} rows; the registry expects {expected}')
        rows = self.get(config['source_api'], {'$where': where_clause(config),
                                                 '$order': 'year,questionid,responseid,locationid',
                                                 '$limit': ROW_LIMIT}, 'selection')
        if not isinstance(rows, list) or len(rows) != expected:
            raise ValueError('Source selection returned an unexpected number of rows')
        records = parse_rows(rows, config, before['columns'])
        after = self.snapshot('after')
        return before, after, records, before == after
