"""Synthetic EPA TRI inputs for tests: full reviewed header, fake page, and a minimal text PDF.

Every facility, chemical form, and coordinate here is invented. Nothing is copied from the EPA file.
"""
import copy
import csv
from pathlib import Path

from app.area_pilot.tri import file_evidence, load_registry, profile_csv, verify_basic_page, verify_documentation

BASE = load_registry()
HEADER = BASE['expected_header']
F = BASE['fields']
SECTOR_LABELS = {s['code']: s['label'] for s in BASE['industry_sectors']}
_doc_counter = [0]


def config(**overrides):
    result = copy.deepcopy(BASE) | {'expected_report_rows': {'min': 1, 'max': 10000},
                                    'expected_facilities': {'min': 1, 'max': 10000}}
    return result | overrides


def doc_number(n):
    return f'1324{n:09d}'


def form(facility_id, chemical_id='0000050000', doc=None, chemical=None, form_type='R', sector='325',
         lat='32.512345', lon='-86.512345', state='AL', name=None, city='Testville', naics='325199', **extra):
    """One TRI form (row) with every reviewed column; quantity columns carry synthetic numbers."""
    _doc_counter[0] += 1
    row = {h: '' for h in HEADER}
    for column in HEADER[50:]:
        row[column] = '0' if form_type == 'A' else '1.000'
    row |= {F['year']: '2024', F['facility_id']: facility_id, F['frs_id']: '110000000001',
            F['facility_name']: name or f'SYNTHETIC FACILITY {facility_id[-4:]}', F['street_address']: '1 TEST RD',
            F['city']: city, F['county']: 'TEST', F['state']: state, F['zip']: '00000', F['latitude']: lat,
            F['longitude']: lon, F['federal_facility']: 'NO', F['industry_sector_code']: sector,
            F['industry_sector']: SECTOR_LABELS.get(sector, 'Unreviewed'), F['primary_naics']: naics,
            F['doc_ctrl_num']: doc or doc_number(_doc_counter[0]), F['chemical']: chemical or f'Synthetic chemical {chemical_id}',
            F['elemental_metal_included']: 'NO', F['chemical_id']: chemical_id, F['cas']: chemical_id,
            F['srs_id']: '1', F['clean_air_act']: 'NO', F['classification']: 'TRI', F['metal']: 'NO',
            F['metal_category']: 'Non_Metal', F['carcinogen']: 'NO', F['pbt']: 'NO', F['pfas']: 'NO',
            F['form_type']: form_type, F['unit_of_measure']: 'Pounds'}
    return row | extra


def write_csv(path, rows, header=HEADER):
    with Path(path).open('w', newline='', encoding='utf-8') as out:
        writer = csv.writer(out, lineterminator='\r\n')
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(h, '') for h in header])
    return Path(path)


def page_html(cfg=BASE, processed='November 5, 2025', years=(2024, 2023), omit=None):
    phrases = ' '.join(p for p in cfg['basic_page_phrases'] if p != omit)
    template = '' if omit == 'template' else cfg['basic_page_template']
    options = ''.join(f'<option value="{y}">{y}</option>' for y in years)
    return (f'<html><main><p>Update Status Includes reporting forms processed as of: {processed}</p>'
            f'<p>{phrases}</p><label>Select year</label><select>{options}</select>'
            f'<a href="{cfg["basic_page_links"][0]}">Guide</a><script>var url = `{template}`;</script>'
            f'<p>Last updated on January 28, 2026</p></main></html>')


def write_pdf(path, lines):
    """Smallest text PDF pypdf can extract: one page, Helvetica, one line per phrase."""
    def esc(value):
        return value.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    content = 'BT /F1 8 Tf 20 800 Td 10 TL ' + ' '.join(f'({esc(line)}) Tj T*' for line in lines) + ' ET'
    objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 2400 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
               f'<< /Length {len(content)} >>\nstream\n{content}\nendstream',
               '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offsets = b'%PDF-1.4\n', []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f'{number} 0 obj\n{body}\nendobj\n'.encode('latin-1')
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode()
    out += ''.join(f'{o:010d} 00000 n \n' for o in offsets).encode()
    out += f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    Path(path).write_bytes(out)
    return Path(path)


def write_inputs(directory, rows, cfg=BASE, processed='November 5, 2025'):
    """Archive synthetic inputs and return the (profile, files, provenance) tuple fetch_stage accepts."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    page = directory / 'tri_basic_data_files.html'
    page.write_text(page_html(cfg, processed), encoding='utf-8')
    pdf = write_pdf(directory / 'documentation.pdf', ['TOXICS RELEASE INVENTORY Updated for RY 2023', *cfg['documentation_phrases']])
    data = write_csv(directory / '2024_us.csv', rows)
    files = [file_evidence(page, 'u', 'basic_page'), file_evidence(pdf, 'u', 'documentation_pdf'),
             file_evidence(data, 'u', 'basic_csv')]
    provenance = {'http': {'basic_csv': {}}, 'page': verify_basic_page(page.read_text(encoding='utf-8'), cfg),
                  'documentation': verify_documentation(pdf, cfg), 'retrieved_at': '2026-11-14T00:00:00+00:00',
                  'csv_path': str(data.resolve())}
    return profile_csv(data, cfg), files, provenance
