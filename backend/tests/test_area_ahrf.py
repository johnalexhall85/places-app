import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.area_pilot import ahrf_api, ahrf_cli
from app.area_pilot.ahrf import (load_registry, parse_count, parse_selected_files,
                                  safe_members, semantic_sha)
from app.area_pilot.source import same_label_revision


def test_ahrf_count_semantics_and_unexpected_source_code():
    assert parse_count('0') == (0, 'true_zero', None)
    assert parse_count(' 12 ') == (12, 'available', None)
    assert parse_count(' ') == (None, 'missing', '')
    for raw in ('-1', '*', 'NA', '1.0', '100000001'):
        with pytest.raises(ValueError):
            parse_count(raw)


def test_ahrf_selected_files_duplicate_and_exact_geography(tmp_path):
    config = load_registry() | {'expected_source_rows': 2}
    paths = {}
    for filename in ('AHRF2025hp.csv', 'AHRF2025hf.csv'):
        fields = ['fips_st_cnty', *[m['measure_id'] for m in config['measures'] if m['source_file'] == filename]]
        path = tmp_path / filename
        path.write_text(','.join(fields) + '\n' +
                        ','.join(['09110', *(['0'] * (len(fields)-1))]) + '\n' +
                        ','.join(['01001', *([''] * (len(fields)-1))]) + '\n')
        paths[filename] = path
    records, headers = parse_selected_files(paths, config)
    assert list(records) == ['09110', '01001']
    assert records['01001']['hosp_23'] == ''
    assert headers['AHRF2025hf.csv'] == ['fips_st_cnty','hosp_23','hosp_beds_23']
    assert semantic_sha(records) == semantic_sha(dict(reversed(list(records.items()))))
    paths['AHRF2025hf.csv'].write_text(paths['AHRF2025hf.csv'].read_text().replace('01001', '09110'))
    with pytest.raises(ValueError, match='duplicate'):
        parse_selected_files(paths, config)


def test_ahrf_zip_rejects_path_traversal_and_oversize():
    for name in ('../out.csv', '/absolute.csv'):
        memory = io.BytesIO()
        with zipfile.ZipFile(memory,'w') as archive:
            archive.writestr(name, 'bad')
        with zipfile.ZipFile(io.BytesIO(memory.getvalue())) as archive:
            with pytest.raises(ValueError,match='Unsafe'):
                safe_members(archive)


def test_ahrf_revision_hold_and_selection_rejects_tract():
    config = load_registry()
    assert same_label_revision({'source_release_id':config['source_release_id'],'semantic_sha256':'old'},
                               config['source_release_id'],'new')
    class DB:
        def execute(self,*_):
            return SimpleNamespace(scalar_one_or_none=lambda:'published')
    measure=config['measures'][0]
    assert ahrf_api.selection(DB(),config['dataset_id'],'release',measure['measure_id'],
                              '2023',measure['population'],config['value_type'],'county')[1] == measure
    with pytest.raises(HTTPException) as error:
        ahrf_api.selection(DB(),config['dataset_id'],'release',measure['measure_id'],
                           '2023',measure['population'],config['value_type'],'tract')
    assert error.value.status_code == 400


def test_held_ahrf_candidate_cannot_change_active_pointer():
    statements=[]
    class Conn:
        def execute(self,sql,params=None):
            statements.append(str(sql))
            return SimpleNamespace(mappings=lambda:SimpleNamespace(one=lambda:{'dataset_id':load_registry()['dataset_id'],'status':'held'}))
    class Engine:
        def begin(self):
            class Context:
                def __enter__(self):return Conn()
                def __exit__(self,*_):return False
            return Context()
    with pytest.raises(ValueError,match='not ready'):
        ahrf_cli.publish(Engine(),load_registry(),'candidate','a','b','c')
    assert not any('INSERT INTO area_pilot.active_release' in statement for statement in statements)


def test_unexplained_ahrf_hold_cannot_be_released():
    statements=[]
    class Conn:
        def execute(self,sql,params=None):
            statements.append(str(sql))
            return SimpleNamespace(mappings=lambda:SimpleNamespace(one=lambda:{
                'dataset_id':load_registry()['dataset_id'],'status':'held','report':{'hold_reason':'source_retrieval'}}))
    class Engine:
        def begin(self):
            class Context:
                def __enter__(self):return Conn()
                def __exit__(self,*_):return False
            return Context()
    with pytest.raises(ValueError,match='not an eligible'):
        ahrf_cli.release_reviewed_hold(Engine(),load_registry(),'candidate','a','b','c','operator note')
    assert not any('UPDATE area_pilot.release SET status' in statement for statement in statements)


def test_ahrf_map_and_table_share_selected_value_and_status():
    class Results:
        def __init__(self,rows):self.rows=rows
        def mappings(self):return self
        def all(self):return self.rows
    class DB:
        def execute(self,sql,params):
            query=str(sql)
            assert 'observation_ahrf' in query and 'acs_boundary_2024' in query
            row={'geography_id':'09110','name':'Capitol Planning Region','value':None,
                 'status':'missing','source_code':''}
            if 'ST_AsGeoJSON' in query:
                row['geometry']={'type':'Polygon','coordinates':[]}
            return Results([row])
    config=load_registry();measure=config['measures'][0]
    base=ahrf_api.metadata(config,measure,'release','-75,40,-70,43')
    mapped=ahrf_api.map_data(DB(),{},1,base,0.04)
    table=ahrf_api.table(DB(),{},base,1,100,0)
    assert mapped['features'][0]['properties']['value'] is None
    assert mapped['features'][0]['properties']['status']=='missing'
    assert table['rows'][0]['value']==mapped['features'][0]['properties']['value']
    assert table['rows'][0]['status']==mapped['features'][0]['properties']['status']
    assert mapped['period']==table['period']=='2023'
