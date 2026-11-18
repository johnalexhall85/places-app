"""Build the sortable, numeric NOFO workbook."""
from datetime import date
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.dimensions import ColumnDimension
from common import MISSING, shown, fiscal_range, title_for, display_title, normalize_class

CURRENCY = '$#,##0.00;[Red]($#,##0.00);$0.00'
NAVY = '003F61'
LIGHT = 'F4F7FB'


def sheet(wb, name, headers, rows, money_cols=(), link_col=None, date_cols=()):
    ws = wb.create_sheet(name)
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = PatternFill('solid', fgColor=NAVY)
        cell.font = Font(name='Arial', bold=True, color='FFFFFF', size=10)
        cell.alignment = Alignment(wrap_text=True, vertical='center')
    ws.row_dimensions[1].height = 30
    for idx, row in enumerate(rows, 2):
        ws.append([MISSING if value is None else value for value in row])
        for cell in ws[idx]:
            cell.font = Font(name='Arial', size=10, color='1A2F3F')
            if idx % 2 == 0:
                cell.fill = PatternFill('solid', fgColor=LIGHT)
        for col in money_cols:
            if isinstance(ws.cell(idx, col).value, (int, float)) or str(ws.cell(idx, col).value).startswith('='):
                ws.cell(idx, col).number_format = CURRENCY
        for col in date_cols:
            cell=ws.cell(idx,col)
            if isinstance(cell.value,str) and len(cell.value)==10:
                try: cell.value=date.fromisoformat(cell.value); cell.number_format='yyyy-mm-dd'
                except ValueError: pass
        if link_col and str(ws.cell(idx,link_col).value).startswith('http'):
            ws.cell(idx,link_col).hyperlink = ws.cell(idx,link_col).value
            ws.cell(idx,link_col).font = Font(name='Arial',color='0277BD',underline='single',size=10)
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:{get_column_letter(len(headers))}{max(ws.max_row, 1)}'
    for col, header in enumerate(headers, 1):
        width = 15 if col in money_cols else min(50, max(13, len(str(header)) + 3))
        if header in ('Recipient','Project Title','Award Title','Assistance Listing Title'):
            width = 43
        if header == 'USAspending Link': width = 45
        ws.column_dimensions[get_column_letter(col)].width = width
    return ws


def render(data, path, prepared, title):
    wb = Workbook()
    wb.remove(wb.active)
    no, ag, people = data['nofo'], data['aggregates'], data['recipients']
    years = sorted(int(x['fiscal_year']) for x in no['fiscal_years'])
    about = [
        ('Recipient Profile', display_title(title)), ('Funding Opportunity',no['fon_display']),
        ('Awarding Agency',display_title(no['awarding_agency'])),
        ('Assistance Listings', '; '.join(f"{x['number']} {shown(display_title(x.get('title')))}" for x in no['cfda'])),
        ('Period',f"{shown(no['period_of_performance']['start_min'])}–{shown(no['period_of_performance']['end_max'])}"),
        ('Recipients',no['recipient_count']), ('Fiscal years',fiscal_range(no['fiscal_years'])),
        ('Best-available total','Account obligations where available; otherwise award-level, then TAGGS.'),
        ('Other HHS awards','TAGGS awards for the same UEI; top 10 per recipient, not a complete federal portfolio.'),
        ('Prepared',f'{prepared} by CHIP, Public Data Observatory'),('Build ID',data['build']['build_id']),
        ('Sources','; '.join(s['citation'] for s in data['sources'])),
        ('Caveats','; '.join(data['caveats'])),
        ('Tabs','Recipient Summary; Funding by FY; FY Comparison; Other HHS Awards; Portfolio Analysis' + ('; Sub-awardees; Sub-award Actions' if data['subawards'] is not None else '')),
    ]
    sheet(wb,'About',['Field','Value'],about)
    wb['About'].column_dimensions['A'].width=28; wb['About'].column_dimensions['B'].width=110
    summary = []
    for n,p in enumerate(people,1):
        a,t,o,period = p['address'],p['totals'],p['other_awards'],p['period_of_performance']
        summary.append((n,p['recipient_name'],a.get('city'),a.get('state'),a.get('county'),p.get('congressional_district'),
            normalize_class(p.get('recipient_class')),p.get('recipient_type'),p.get('metro_status'),p['fain'],p.get('project_title'),
            t.get('best_available'),t.get('best_available_basis'),period.get('start'),period.get('end'),o.get('count'),o.get('top10_total'),p.get('usaspending_url'),p.get('abstract_full')))
    sheet(wb,'Recipient Summary',['#','Recipient','City','State','County','Cong. Dist.','Recipient Class','Org Type','Metro','Award #','Project Title','Total (best available)','Basis','Start','End','# Other Awards','Other Awards Top-10 Total','USAspending Link','Abstract Full'],summary,(12,17),18,(14,15))
    fy_headers=['#','Recipient','State','Award #']+[f'FY{y}' + ('*' if any(x['fiscal_year']==y and not x['is_complete'] for x in no['fiscal_years']) else '') for y in years]+['Total']
    fyrows=[]
    for n,p in enumerate(people,2):
        values={int(x['fiscal_year']):x.get('account_obligation') for x in p['fiscal_years']}
        first=get_column_letter(5); last=get_column_letter(4+len(years))
        fyrows.append((n-1,p['recipient_name'],p['address'].get('state'),p['fain'],*[values.get(y) for y in years],f'=SUM({first}{n}:{last}{n})'))
    ws=sheet(wb,'Funding by FY',fy_headers,fyrows,range(5,len(fy_headers)+1))
    totalrow=ws.max_row+1
    ws.cell(totalrow,2,'TOTAL')
    for col in range(5,len(fy_headers)+1):
        letter=get_column_letter(col); ws.cell(totalrow,col,f'=SUM({letter}2:{letter}{totalrow-1})');ws.cell(totalrow,col).number_format=CURRENCY
    for cell in ws[totalrow]: cell.font=Font(name='Arial',bold=True,color=NAVY)
    incomplete=[str(x['fiscal_year']) for x in no['fiscal_years'] if not x['is_complete']]
    if incomplete: ws.cell(totalrow+1,2,'* Incomplete fiscal year(s): '+', '.join(incomplete))
    comp=[]
    for p in people:
        for x in p['fiscal_years']:
            comp.append((p['recipient_name'],p['fain'],x['fiscal_year'],x.get('account_obligation'),x.get('award_obligation'),x.get('taggs_amount')))
    sheet(wb,'FY Comparison',['Recipient','Award #','Fiscal Year','Account','Award-level','TAGGS'],comp,(4,5,6))
    other=[]
    for p in people:
        for x in p['other_awards']['top']:
            other.append((p['recipient_name'],p['address'].get('state'),p['fain'],x.get('rank'),x.get('award_number'),x.get('amount'),x.get('opdiv'),x.get('aln'),display_title(x.get('aln_title')),x.get('fon'),x.get('first_fiscal_year'),x.get('last_fiscal_year'),x.get('award_title')))
    sheet(wb,'Other HHS Awards',['Recipient','State','Award #','Rank','Other Award #','Amount','OpDiv','ALN','Assistance Listing Title','FON','First FY','Last FY','Award Title'],other,(6,))
    portfolio=[]
    for heading, key, cols in [
        ('By state','by_state',['state','recipients','nofo_total','other_awards_top10_total']),
        ('By recipient class','by_recipient_class',['value','recipients','nofo_total']),
        ('By recipient type','by_recipient_type',['value','recipients']),
        ('By metro','by_metro',['value','recipients']),
        ('Other awards by OpDiv','other_awards_by_opdiv',['opdiv','awards','total']),
        ('Top assistance listings','other_awards_by_aln',['aln','title','awards','total']),
        ('Top recipients by other awards','top_recipients_by_other_awards',['recipient_name','state','other_award_count','other_awards_top10_total'])]:
        for x in ag[key]: portfolio.append((heading,*[normalize_class(x.get(c)) if key=='by_recipient_class' and c=='value' else display_title(x.get(c)) if key=='other_awards_by_aln' and c=='title' else x.get(c) for c in cols]))
    sheet(wb,'Portfolio Analysis',['Group','Item','Count / State','Total / Count','Other Total'],portfolio,(4,5))
    if data['subawards'] is not None:
        sub=data['subawards']
        sheet(wb,'Sub-awardees',['UEI','Name','Name Variants','DBA Names','Business Types','City','State','District','Prime FAINs','Prime Recipients','Actions','Reported Amount','First Date','Last Date'],[
            (x.get('uei'),x.get('name'),'; '.join(x.get('name_variants') or []),'; '.join(x.get('dba_names') or []),'; '.join(x.get('business_types') or []),
             x.get('address',{}).get('city'),x.get('address',{}).get('state'),x.get('congressional_district'),'; '.join(x.get('prime_fains') or []),'; '.join(x.get('prime_recipients') or []),x.get('action_count'),x.get('reported_amount'),x.get('first_action_date'),x.get('last_action_date')) for x in sub['subawardees']],(12,),date_cols=(13,14))
        sheet(wb,'Sub-award Actions',['Prime FAIN','Prime Recipient','Sub-award #','Action Date','Fiscal Year','Amount','Sub-awardee UEI','Sub-awardee Name','Description','SAM Report IDs','USAspending Link'],[
            (x.get('prime_fain'),x.get('prime_recipient'),x.get('subaward_number'),x.get('action_date'),x.get('fiscal_year'),x.get('amount'),x.get('subawardee_uei'),x.get('subawardee_name'),x.get('description'),'; '.join(x.get('sam_report_ids') or []),x.get('usaspending_url')) for x in sub['actions']],(6,),11,(4,))
    wb.save(path)
