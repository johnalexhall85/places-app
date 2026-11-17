"""Curated history registries: registry/history/<product>.json.

Each lists, for every measure, the earlier periods CHIP publishes, where each one comes from, the
boundary vintage for each level, and the comparability note shown with it. ``auto_publish`` is
always false; publication is a reviewed, checksum-bound operator action.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.area_pilot.history.rows import LEVEL_LENGTH, UNCERTAINTY_KINDS

HISTORY_DIR = Path(__file__).resolve().parents[1] / 'registry' / 'history'
VINTAGES = {'state': {'2024'}, 'county': {'2020', '2024'}, 'tract': {'2019', '2020', '2024'}}
MAX_EARLIER_PERIODS = 5
REQUIRED = {'dataset_id', 'current_dataset_id', 'product', 'parser', 'name', 'publisher',
            'source_release_id', 'levels', 'statuses', 'null_statuses', 'sources', 'measures',
            'auto_publish', 'unmatched_tolerance'}


def products() -> list[str]:
    return sorted(p.stem for p in HISTORY_DIR.glob('*.json'))


def load_history_registry(product: str) -> dict:
    path = HISTORY_DIR / f'{product}.json'
    if not path.is_file():
        raise ValueError(f'No history registry for {product}')
    config = json.loads(path.read_text(encoding='utf-8'))
    validate(config, product)
    config['_index'] = {(m['measure_id'], p['period']): (m, p)
                        for m in config['measures'] for p in m['periods']}
    return config


def public_config(config: dict) -> dict:
    """The registry as stored in the metadata digest (without the derived index)."""
    return {k: v for k, v in config.items() if not k.startswith('_')}


def validate(config: dict, product: str) -> None:
    missing = REQUIRED - config.keys()
    if missing:
        raise ValueError(f'History registry {product} missing fields: {sorted(missing)}')
    if config['product'] != product or config['dataset_id'] != config['current_dataset_id'] + ':history':
        raise ValueError(f'History registry {product} identity is inconsistent')
    if config['auto_publish'] is not False:
        raise ValueError('History releases are never auto-published')
    if not set(config['levels']) <= set(LEVEL_LENGTH) or not config['levels']:
        raise ValueError(f'History registry {product} levels invalid')
    if not set(config['null_statuses']) <= set(config['statuses']):
        raise ValueError(f'History registry {product} null statuses must be statuses')
    if config.get('uncertainty_kind', 'none') not in UNCERTAINTY_KINDS:
        raise ValueError(f'History registry {product} uncertainty kind invalid')
    roles = [s['role'] for s in config['sources']]
    if len(roles) != len(set(roles)) or not roles:
        raise ValueError(f'History registry {product} source roles must be unique')
    for source in config['sources']:
        if not (source.get('archived_path') and len(source.get('sha256', '')) == 64) and not source.get('url'):
            raise ValueError(f'Source {source["role"]} needs a url or an archived path with sha256')
    ids = [m['measure_id'] for m in config['measures']]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError(f'History registry {product} measures must be unique')
    for measure in config['measures']:
        for field in ('measure_id', 'current_period', 'population', 'value_type', 'periods'):
            if not measure.get(field):
                raise ValueError(f'{product}:{measure.get("measure_id", "?")} missing {field}')
        if not set(measure.get('levels', config['levels'])) <= set(config['levels']):
            raise ValueError(f'{product}:{measure["measure_id"]} levels outside the product levels')
        if measure.get('uncertainty_kind', 'none') not in UNCERTAINTY_KINDS:
            raise ValueError(f'{product}:{measure["measure_id"]} uncertainty kind invalid')
        periods = [p['period'] for p in measure['periods']]
        if len(periods) != len(set(periods)) or measure['current_period'] in periods:
            raise ValueError(f'{product}:{measure["measure_id"]} periods must be unique and earlier than current')
        if len([p for p in measure['periods'] if p.get('available', True)]) > MAX_EARLIER_PERIODS:
            raise ValueError(f'{product}:{measure["measure_id"]} has more than {MAX_EARLIER_PERIODS} earlier periods')
        for spec in measure['periods']:
            for field in ('period', 'boundary_vintage', 'note'):
                if field not in spec:
                    raise ValueError(f'{product}:{measure["measure_id"]} {spec.get("period")} missing {field}')
            if spec.get('available', True):
                if 'locator' not in spec:
                    raise ValueError(f'{product}:{measure["measure_id"]} {spec["period"]} missing locator')
                for level in measure.get('levels', config['levels']):
                    if spec['boundary_vintage'].get(level) not in VINTAGES[level]:
                        raise ValueError(f'{product}:{measure["measure_id"]} {spec["period"]} '
                                         f'{level} vintage invalid')
