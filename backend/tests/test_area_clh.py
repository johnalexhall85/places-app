from types import SimpleNamespace

import openpyxl
import pytest
from fastapi import HTTPException

from app.area_pilot import clh_api, clh_cli
from app.area_pilot.clh import download, load_registry, parse_file, parse_value, semantic_sha


def test_clh_value_codes_and_measure_geography():
    config = load_registry()
    assert len(config['measures']) == 5
    assert [m['measure_id'] for m in config['measures'] if 'tract' in m['geographies']] == [
        'ACS_PCT_HH_BROADBAND_ANY', 'ACS_PCT_HU_NO_VEH', 'ACS_PCT_RENTER_HU_COST_30PCT']
    assert parse_value(0, '%') == (0.0, 'true_zero', None)
    assert parse_value(None, '%') == (None, 'missing', None)
    assert parse_value(25.5, '%') == (25.5, 'available', None)
    for value in ('*', '-1', -1, 101, True):
        with pytest.raises(ValueError):
            parse_value(value, '%')


def test_clh_reader_uses_data_sheet_and_rejects_formula(tmp_path):
    config = load_registry() | {'expected_source_rows': {'county': 2, 'tract': 2}}
    workbook = openpyxl.Workbook()
    layout = workbook.active
    layout.title = 'Layout'
    layout.append(['name','label','type','length','format'])
    layout.append(['COUNTYFIPS','State-county FIPS Code (5-digit)','char',5,'$5.'])
    selected = [m for m in config['measures'] if 'county' in m['geographies']]
    for measure in selected:
        layout.append([measure['measure_id'],measure['official_label'],'num',8,'6.2'])
    data = workbook.create_sheet('Data')
    data.append(['YEAR','COUNTYFIPS',*[m['measure_id'] for m in selected]])
    data.append([2023,'01001',0,12,25,None,0.13])
    data.append([2023,'01003',80,None,50,0.2,None])
    path = tmp_path / 'county.xlsx'
    workbook.save(path)
    records, layout_meta = parse_file(path, 'county', config)
    assert records['01001']['ACS_PCT_HH_BROADBAND_ANY'] == 0
    assert records['01003']['ACS_PCT_HU_NO_VEH'] is None
    assert layout_meta['sheet'] == 'Data'
    assert semantic_sha({'county': records}) == semantic_sha({'county': dict(reversed(list(records.items())))})
    data['C2'] = '=1+1'
    workbook.save(path)
    with pytest.raises(ValueError, match='Formula'):
        parse_file(path, 'county', config)


def test_clh_empty_http_202_never_becomes_a_source_file(tmp_path, monkeypatch):
    class EmptyResponse:
        status_code = 202
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def raise_for_status(self): return None
    monkeypatch.setattr('app.area_pilot.clh.requests.get', lambda *_args, **_kwargs: EmptyResponse())
    monkeypatch.setattr('app.area_pilot.clh.time.sleep', lambda *_: None)
    monkeypatch.setattr('app.area_pilot.clh.shutil.disk_usage', lambda *_: SimpleNamespace(free=10 * 1024**3))
    target = tmp_path / 'landing.html'
    with pytest.raises(RuntimeError, match='download failed'):
        download('https://example.invalid/landing', target, 'landing')
    assert not target.exists()


def test_clh_unsupported_tract_and_period_do_not_query_release():
    config = load_registry()
    class DB:
        def execute(self, *_):
            raise AssertionError('unsupported selection queried release')
    grocery = next(m for m in config['measures'] if m['measure_id'] == 'CCBP_SOGS_RATE')
    for geography, period in [('tract', '2023'), ('county', '2019–2023')]:
        with pytest.raises(HTTPException) as error:
            clh_api.selection(DB(), config['dataset_id'], 'release', grocery['measure_id'],
                              period, grocery['population'], config['value_type'], geography)
        assert error.value.status_code == 400


def test_clh_failed_candidate_cannot_switch_active_pointer():
    statements = []
    class Conn:
        def execute(self, sql, params=None):
            statements.append(str(sql))
            return SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: {
                'dataset_id': load_registry()['dataset_id'], 'status': 'held'}))
    class Engine:
        def begin(self):
            class Context:
                def __enter__(self): return Conn()
                def __exit__(self, *_): return False
            return Context()
    with pytest.raises(ValueError, match='not ready'):
        clh_cli.publish(Engine(), load_registry(), 'candidate', 'a', 'b', 'c')
    assert not any('INSERT INTO area_pilot.active_release' in statement for statement in statements)


def test_clh_map_legend_table_parity_and_cap():
    class Result:
        def __init__(self, rows): self.rows = rows
        def mappings(self): return self
        def all(self): return self.rows
        def scalar_one(self): return 1
        def one(self): return self.rows[0]
    class DB:
        def execute(self, sql, params):
            query = str(sql)
            if 'percentile_cont' in query:   # release-wide quintile breaks: no viewport, no boundary join
                assert 'observation_clh' in query and 'ST_MakeEnvelope' not in query
                return Result([{'n': 1, 'cuts': None}])
            assert 'observation_clh' in query and 'acs_boundary_2024' in query
            if 'GROUP BY' in query:
                return Result([{'status':'true_zero','n':1,'low':0,'high':0}])
            if 'count(*)' in query:
                return Result([])
            row = {'geography_id':'01001','name':'Autauga County','value':0,
                   'status':'true_zero','source_code':None}
            if 'ST_AsGeoJSON' in query:
                row['geometry'] = {'type':'Polygon','coordinates':[]}
            return Result([row])
    config = load_registry(); measure = config['measures'][0]
    base = clh_api.metadata(config, measure, 'release', 'county', '-87,31,-86,33')
    params = {'level':'county'}
    assert clh_api.ensure_cap(DB(), params) == 1
    mapped = clh_api.map_data(DB(), params, 1, base, 0.04)
    table = clh_api.table(DB(), params, base, 1, 100, 0)
    legend = clh_api.legend(DB(), params, base)
    assert mapped['features'][0]['properties']['value'] == table['rows'][0]['value'] == 0
    assert mapped['features'][0]['properties']['status'] == table['rows'][0]['status'] == 'true_zero'
    assert legend['statuses'][0]['n'] == mapped['count'] == table['total'] == 1
    assert legend['quantile_breaks'] is None and legend['quantile_basis'] == 'quintiles_of_published_values_in_release'
