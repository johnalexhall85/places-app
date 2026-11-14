from __future__ import annotations

import json
from pathlib import Path

REGISTRY_DIR = Path(__file__).with_name('registry')


def load_registry(geography: str = 'county') -> dict:
    if geography not in ('county', 'tract'):
        raise ValueError('Unsupported pilot geography')
    config = json.loads((REGISTRY_DIR / f'places_{geography}_2025.json').read_text(encoding='utf-8'))
    required = {'dataset_id', 'source_view_id', 'source_api', 'source_metadata_api',
                'source_release_id', f'expected_{geography}_count', 'expected_schema_sha256',
                'geographies', 'measures', 'aggregation_method', 'boundary_vintage'}
    missing = required - config.keys()
    if missing:
        raise ValueError(f'Area registry missing fields: {sorted(missing)}')
    expected_levels = ['county'] if geography == 'county' else ['county', 'tract']
    if config['aggregation_method'] != 'none' or config['geographies'] != expected_levels:
        raise ValueError('Pilot registry geography contract is invalid')
    if not config['expected_schema_sha256'] or len(config['expected_schema_sha256']) != 64:
        raise ValueError('Verified source schema checksum required')
    names = [m['measure_id'] for m in config['measures']]
    if len(names) != len(set(names)) or set(names) != {'dental_crudeprev', 'access2_crudeprev'}:
        raise ValueError('Pilot measure registry is invalid')
    for measure in config['measures']:
        for field in ('measure_id', 'label', 'observation_period', 'population',
                      'source_value_field', 'source_ci_field', 'source_definition_contains'):
            if not measure.get(field):
                raise ValueError(f'{measure.get("measure_id", "?")} missing {field}')
    return config
