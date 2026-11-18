"""Produce the branded Word recipient dossier from the shipped template."""
from collections import defaultdict
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from common import MISSING, STATES, dollars, shown, integer, period, fiscal_range, short_abstract, short_fon

NAVY='003F61'; BLUE='0277BD'; LIGHT='F4F7FB'; PEACH='F0B97D'; MUTED='546E7A'


def rgb(hexcode):
    return RGBColor.from_string(hexcode)


def shade(cell, color):
    tcPr=cell._tc.get_or_add_tcPr(); shd=OxmlElement('w:shd'); shd.set(qn('w:fill'),color);tcPr.append(shd)


def border_left(cell, color):
    tcPr=cell._tc.get_or_add_tcPr(); borders=tcPr.first_child_found_in('w:tcBorders')
    if borders is None:
        borders=OxmlElement('w:tcBorders');tcPr.append(borders)
    side=OxmlElement('w:left');side.set(qn('w:val'),'single');side.set(qn('w:sz'),'24');side.set(qn('w:color'),color);borders.append(side)


def table_borders(table):
    tblPr=table._tbl.tblPr
    borders=OxmlElement('w:tblBorders')
    for side_name in ('top','left','bottom','right','insideH','insideV'):
        side=OxmlElement('w:'+side_name)
        side.set(qn('w:val'),'single');side.set(qn('w:sz'),'3');side.set(qn('w:color'),'CFD8DC')
        borders.append(side)
    tblPr.append(borders)


def keep_row(row, repeat=False):
    trPr=row._tr.get_or_add_trPr(); el=OxmlElement('w:cantSplit');trPr.append(el)
    if repeat:
        el=OxmlElement('w:tblHeader');el.set(qn('w:val'),'true');trPr.append(el)


def keep_next(paragraph):
    paragraph.paragraph_format.keep_with_next=True


def cell_text(cell, value, *, bold=False, color=None, size=9):
    cell.text=shown(value)
    cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for p in cell.paragraphs:
        p.paragraph_format.space_after=Pt(0)
        for run in p.runs:
            run.font.name='Arial';run.font.size=Pt(size);run.font.bold=bold
            if color: run.font.color.rgb=rgb(color)


def grid(doc, headers, rows, widths=None):
    t=doc.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER
    if widths:t.autofit=False
    table_borders(t)
    for i,h in enumerate(headers):
        c=t.rows[0].cells[i];cell_text(c,h,bold=True,color='FFFFFF');shade(c,NAVY)
        for paragraph in c.paragraphs:keep_next(paragraph)
    keep_row(t.rows[0],True)
    for k,row in enumerate(rows):
        cells=t.add_row().cells
        for i,val in enumerate(row):
            cell_text(cells[i],val)
            if k%2==1:shade(cells[i],LIGHT)
        keep_row(t.rows[-1])
    if widths:
        for row in t.rows:
            for c,width in zip(row.cells,widths):c.width=Inches(width)
    doc.add_paragraph().paragraph_format.space_after=Pt(1)
    return t


def label_table(doc, pairs):
    t=doc.add_table(rows=0,cols=2);table_borders(t);t.autofit=False
    for name,value in pairs:
        a,b=t.add_row().cells;cell_text(a,name,bold=True,color=NAVY);cell_text(b,value)
        shade(a,LIGHT);a.width=Inches(1.7);b.width=Inches(4.8);keep_row(t.rows[-1])
    doc.add_paragraph().paragraph_format.space_after=Pt(1)
    return t


def add_field(paragraph, instruction):
    run=paragraph.add_run();start=OxmlElement('w:fldChar');start.set(qn('w:fldCharType'),'begin')
    text=OxmlElement('w:instrText');text.set(qn('xml:space'),'preserve');text.text=instruction
    sep=OxmlElement('w:fldChar');sep.set(qn('w:fldCharType'),'separate')
    end=OxmlElement('w:fldChar');end.set(qn('w:fldCharType'),'end')
    for el in (start,text,sep,end):run._r.append(el)


def hyperlink(paragraph, text, url):
    if not url:return paragraph.add_run(MISSING)
    part=paragraph.part;rid=part.relate_to(url,'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink',is_external=True)
    h=OxmlElement('w:hyperlink');h.set(qn('r:id'),rid)
    run=OxmlElement('w:r');props=OxmlElement('w:rPr');col=OxmlElement('w:color');col.set(qn('w:val'),BLUE);props.append(col)
    underline=OxmlElement('w:u');underline.set(qn('w:val'),'single');props.append(underline);run.append(props)
    txt=OxmlElement('w:t');txt.text=text;run.append(txt);h.append(run);paragraph._p.append(h)


def p(doc, text='', *, style=None, muted=False):
    para=doc.add_paragraph(style=style);run=para.add_run(text)
    run.font.name='Arial';run.font.size=Pt(9)
    if muted:run.font.color.rgb=rgb(MUTED)
    para.paragraph_format.space_after=Pt(6)
    return para


def heading(doc, text, level=1):
    para=doc.add_heading(text,level=level);keep_next(para)
    for run in para.runs:
        run.font.name='Arial';run.font.bold=True;run.font.color.rgb=rgb(NAVY if level==1 else BLUE)
        run.font.size=Pt(15 if level==1 else 11)
    para.paragraph_format.space_before=Pt(12 if level==1 else 8)
    para.paragraph_format.space_after=Pt(6)
    return para


def chart(data, source):
    years=[str(x['fiscal_year'])+('*' if not x['is_complete'] else '') for x in data['nofo']['fiscal_years']]
    vals=[(x.get('account_obligation') or 0)/1_000_000 for x in data['nofo']['fiscal_years']]
    fig,ax=plt.subplots(figsize=(6.25,2.5),dpi=145)
    bars=ax.bar(years,vals,color='#'+BLUE,width=.62)
    ax.set_ylabel('Account obligations ($ millions)',fontsize=8)
    ax.set_xlabel('Fiscal year',fontsize=8)
    ax.grid(axis='y',color='#CFD8DC',linewidth=.5);ax.set_axisbelow(True)
    ax.spines[['top','right']].set_visible(False)
    ax.tick_params(labelsize=8)
    fig.tight_layout();buf=BytesIO();fig.savefig(buf,format='png',bbox_inches='tight');plt.close(fig);buf.seek(0)
    return buf


def reset_template(doc):
    body=doc._body._body
    for child in list(body):
        if child.tag!=qn('w:sectPr'):body.remove(child)
    styles=doc.styles
    for name in ('Normal','Heading 1','Heading 2'):
        if name in styles:
            styles[name].font.name='Arial';styles[name].font.color.rgb=rgb(NAVY if name.startswith('Heading') else '1A2F3F')
    next(s for s in styles if s.name and s.name.lower() == 'normal').font.size=Pt(9)
    sec=doc.sections[0];sec.page_width=Inches(8.5);sec.page_height=Inches(11)
    sec.top_margin=Inches(.7);sec.bottom_margin=Inches(.65)
    sec.left_margin=Inches(.7);sec.right_margin=Inches(.7)
    settings=doc.settings._element
    upd=OxmlElement('w:updateFields');upd.set(qn('w:val'),'true');settings.append(upd)


def render(data, path, prepared, title, narrative, assets):
    template=Path(assets)/'PDO_Report_Template.docx';doc=Document(template)
    about=deepcopy(doc.tables[-1]._tbl)
    keyfindings=deepcopy(doc.tables[1]._tbl)
    reset_template(doc)
    no,ag,people=data['nofo'],data['aggregates'],data['recipients']
    fon=no['fon_display'];fy_range=fiscal_range(no['fiscal_years'])
    cover=doc.add_table(rows=1,cols=1);cover.autofit=False
    c=cover.cell(0,0);shade(c,NAVY);c.text=''
    pp=c.paragraphs[0]
    logo=Path(assets)/'chip-logo-fullcolor-light-small.png'
    if logo.exists():
        pp.add_run().add_picture(str(logo),width=Inches(1.9))
    for text,size in [('Recipient Profile',26),(fon,16),(title,12)]:
        pp=c.add_paragraph();rr=pp.add_run(text);rr.font.name='Roboto Slab' if size==26 else 'Arial';rr.font.bold=True
        rr.font.color.rgb=rgb('FFFFFF');rr.font.size=Pt(size)
    doc.add_paragraph()
    sources='; '.join(s['citation'] for s in data['sources'])
    label_table(doc,[('Funding Opportunity',fon),('Awarding Agency',no['awarding_agency']+'; '+', '.join(no['awarding_offices'])),
        ('Assistance Listing(s)','; '.join(f"{x['number']} {shown(x.get('title'))}" for x in no['cfda'])),
        ('Period of Performance',period(no['period_of_performance']['start_min'],no['period_of_performance']['end_max'])),
        ('Recipients Profiled',integer(no['recipient_count'])),
        ('Total obligated (best available)',f"{dollars(no['best_available_total'])} · {fy_range}"),
        ('Data Sources',sources),('Prepared',f'{prepared} by CHIP, Public Data Observatory')])
    incomplete=[f"FY{x['fiscal_year']}" for x in no['fiscal_years'] if not x['is_complete']]
    if incomplete:p(doc,'Incomplete fiscal year(s): '+', '.join(incomplete)+'.',muted=True)
    heading(doc,'Contents')
    para=doc.add_paragraph();add_field(para,'TOC \\o "1-2" \\h \\z \\u')
    doc.add_page_break()
    heading(doc,'Executive Summary')
    heading(doc,'Summary',2)
    avg=(no['best_available_total']/no['recipient_count']) if no['best_available_total'] is not None and no['recipient_count'] else None
    p(doc,f"{integer(no['recipient_count'])} recipients are profiled for {fon} across {period(no['period_of_performance']['start_min'],no['period_of_performance']['end_max'])}. "
      f"Their best-available obligated total is {dollars(no['best_available_total'])} for {fy_range}, or {dollars(avg)} per recipient on average. "
      'The profiles present award identity, annual obligations, funded projects, and other HHS awards recorded in TAGGS.')
    findings=[f"{integer(no['recipient_count'])} recipients; {dollars(no['best_available_total'])} obligated ({fy_range}).",
      f"{integer(len(ag['by_state']))} states or territories represented; {integer(ag['by_state'][0]['recipients']) if ag['by_state'] else MISSING} recipients in the largest state group.",
      f"{integer(ag['recipients_without_other_awards'])} recipients have no other HHS awards recorded in TAGGS."]
    if data['subawards'] is not None:
        summ=data['subawards']['summary'];findings.append(f"{integer(summ['distinct_subawardees'])} distinct sub-awardees and {integer(summ['actions'])} reported actions; these amounts are not additional federal funding.")
    doc._body._body.insert(len(doc._body._body)-1,keyfindings)
    table=doc.tables[-1]
    table.cell(0,1).text='KEY FINDINGS\n'+'\n'.join(findings)
    for row in table.rows:keep_row(row)
    heading(doc,'Obligations by fiscal year',2)
    years=no['fiscal_years']
    grid(doc,[f"FY{x['fiscal_year']}"+('*' if not x['is_complete'] else '') for x in years],[[dollars(x.get('account_obligation')) for x in years]])
    doc.add_picture(chart(data,sources),width=Inches(6.2))
    account_source=next((s for s in data['sources'] if s['id']=='usaspending_account'),{})
    p(doc,f"Source: USAspending.gov · Federal account award data (File C) · {fy_range} "
      f"(through {shown(account_source.get('data_through'))}) · CHIP build {data['build']['build_id']}",muted=True)
    heading(doc,'Where recipients are located',2)
    states=ag['by_state'];metro=next((x['recipients'] for x in ag['by_metro'] if x['value']=='Metro'),0)
    top=', '.join(f"{STATES.get(x['state'],x['state'])} ({integer(x['recipients'])})" for x in states[:3])
    p(doc,f"Recipients are located in {integer(len(states))} states or territories. The largest groups are {top or MISSING}. "
      f"TAGGS classifies {integer(metro)} recipients as Metro.")
    heading(doc,'What kinds of organizations they are',2)
    classes=', '.join(f"{x['value']} ({integer(x['recipients'])})" for x in ag['by_recipient_class'][:5])
    types=', '.join(f"{x['value']} ({integer(x['recipients'])})" for x in ag['by_recipient_type'][:5])
    p(doc,f"Recipient classes include {classes or MISSING}. Organization types include {types or MISSING}.")
    heading(doc,'Their wider HHS funding',2)
    total=ag['other_awards_top10_total'];ratio=(total/no['best_available_total']) if total is not None and no['best_available_total'] else None
    op=ag['other_awards_by_opdiv'][0] if ag['other_awards_by_opdiv'] else None
    aln=ag['other_awards_by_aln'][0] if ag['other_awards_by_aln'] else None
    p(doc,f"The top 10 other HHS awards shown per recipient total {dollars(total)}, or {f'{ratio:.1f}' if ratio is not None else MISSING} times the NOFO best-available total. "
      f"{integer(ag['recipients_without_other_awards'])} recipients have no other HHS award recorded. "
      f"The leading OpDiv is {op['opdiv'] if op else MISSING} ({dollars(op['total']) if op else MISSING}); "
      f"the leading assistance listing is {aln['aln'] if aln else MISSING} ({dollars(aln['total']) if aln else MISSING}).")
    heading(doc,'Data caveats',2)
    box=doc.add_table(rows=1,cols=1);c=box.cell(0,0);shade(c,LIGHT);border_left(c,PEACH)
    c.text='\n'.join('• '+x for x in data['caveats']);keep_row(box.rows[0])
    heading(doc,'How to read the profiles',2)
    p(doc,'Each profile shows the award, best-available total and its basis, annual account obligations, and up to 10 other HHS awards. A dash means a value was not reported; it does not mean zero. Sub-award amounts, when shown, are not added to prime obligations.')
    if narrative.get('context'):
        heading(doc,'Context',2)
        for item in narrative['context']:p(doc,str(item))
    doc.add_page_break();heading(doc,'Profiles')
    grouped=defaultdict(list)
    for x in people:grouped[x['address'].get('state') or MISSING].append(x)
    for state in sorted(grouped):
        heading(doc,STATES.get(state,state))
        for x in sorted(grouped[state],key=lambda a:a['recipient_name'].casefold()):
            heading(doc,x['recipient_name'],2)
            variants=[v for v in x.get('name_variants',[]) if v!=x['recipient_name']]
            if variants:p(doc,'Also known as: '+ '; '.join(variants),muted=True)
            a=x['address'];location=', '.join(z for z in (a.get('line1'),a.get('city'),a.get('state'),a.get('zip')) if z)
            if a.get('county'):location+=f" ({a['county']} County)"
            label_table(doc,[('UEI',shown(x.get('uei'))),('Location',location or MISSING),
                ('Congressional District',shown(x.get('congressional_district'))),('Organization Class',shown(x.get('recipient_class'))),
                ('Organization Type',shown(x.get('recipient_type'))+(' · '+x['metro_status'] if x.get('metro_status') else '')),
                ('Business Type','; '.join(x.get('business_types') or []) or MISSING)])
            heading(doc,short_fon(fon)+' Award',2)
            cfda=x.get('cfda') or {};t=x['totals'];perform=x['period_of_performance']
            label_table(doc,[('Award Number',shown(x.get('fain'))),('Project Title',shown(x.get('project_title'))),
                ('Assistance Listing',f"{shown(cfda.get('number'))} · {shown(cfda.get('title'))}"),
                ('Period of Performance',period(perform.get('start'),perform.get('end'))),
                ('Total Obligated',f"{dollars(t.get('best_available'))} ({shown(t.get('best_available_basis'))} basis)")])
            heading(doc,'Obligations by fiscal year',2)
            fy={int(v['fiscal_year']):v.get('account_obligation') for v in x['fiscal_years']}
            grid(doc,[f'FY{y}' for y in sorted(fy)],[[dollars(fy[y]) for y in sorted(fy)]]) if fy else p(doc,MISSING)
            heading(doc,'Funded project',2);p(doc,short_abstract(x.get('abstract')))
            heading(doc,'Other HHS Awards',2)
            other=x['other_awards']
            if other['count']:
                p(doc,f"{integer(other['count'])} other HHS awards recorded · total {dollars(other.get('total'))} · top 10 shown")
                rows=[]
                for y in other['top']:
                    program=' — '.join(z for z in (y.get('award_title'),y.get('aln_title')) if z) or MISSING
                    if len(program)>140:program=short_abstract(program,140)
                    span=period(y.get('first_fiscal_year'),y.get('last_fiscal_year'))
                    rows.append((shown(y.get('rank')),shown(y.get('award_number')),dollars(y.get('amount')),shown(y.get('opdiv')),program,span,shown(y.get('aln'))))
                grid(doc,['#','Award No.','Amount','OpDiv','Program','FY Range','ALN'],rows,
                     [.3,.85,.75,.5,2.8,.8,.5])
            else:p(doc,'No other HHS awards to this recipient are recorded in TAGGS.')
            if data['subawards'] is not None and x.get('subawards') and x['subawards']['action_count']:
                s=x['subawards'];p(doc,f"Sub-awards reported: {integer(s['subawardee_count'])} sub-awardees · {integer(s['action_count'])} actions · {dollars(s['reported_amount'])} reported (not additional federal funding).")
            source=doc.add_paragraph();source.add_run('Source: ');hyperlink(source,x.get('usaspending_url') or MISSING,x.get('usaspending_url'))
    if data['subawards'] is not None:
        sub=data['subawards'];summ=sub['summary'];doc.add_page_break();heading(doc,'Sub-awardees')
        p(doc,f"{integer(summ['distinct_subawardees'])} distinct sub-awardees; {integer(summ['actions'])} actions; {dollars(summ['reported_amount'])} reported. "
          f"{integer(summ['duplicates_removed'])} duplicate records removed. Sub-award amounts are not additional federal funding.")
        heading(doc,'By fiscal year',2)
        grid(doc,['Fiscal Year','Actions','Sub-awardees','Reported Amount'],[(f"FY{x['fiscal_year']}",integer(x['actions']),integer(x['subawardees']),dollars(x['reported_amount'])) for x in sub['by_fiscal_year']])
        heading(doc,'By state',2)
        grid(doc,['State','Sub-awardees'],[(STATES.get(x['state'],x['state']),integer(x['subawardees'])) for x in sub['by_state']])
        identities={y.get('uei') or y.get('name'):y for y in sub['subawardees']}
        byprime=defaultdict(lambda:defaultdict(list))
        for action in sub['actions']:
            identity=action.get('subawardee_uei') or action.get('subawardee_name')
            byprime[action['prime_fain']][identity].append(action)
        for x in people:
            groups=byprime.get(x['fain'])
            if not groups:continue
            heading(doc,x['recipient_name']+' · '+x['fain'],2)
            rows=[]
            for identity,actions in sorted(groups.items(),key=lambda item: str(item[0])):
                y=identities.get(identity,{})
                dates=[a['action_date'] for a in actions if a.get('action_date')]
                rows.append((shown(y.get('name') or actions[0].get('subawardee_name')),
                    ', '.join(z for z in (y.get('address',{}).get('city'),y.get('address',{}).get('state')) if z) or MISSING,
                    shown(y.get('congressional_district')),integer(len(actions)),
                    dollars(sum(a['amount'] or 0 for a in actions)),period(min(dates) if dates else None,max(dates) if dates else None)))
            grid(doc,['Sub-awardee','City / State','District','Actions','Reported Amount','First–Last Date'],rows)
    heading(doc,'Method and sources')
    p(doc,'CHIP links CDC funding opportunities to awards using USAspending award records and CDC TAGGS FON and award numbers. Account-level File C obligations are primary; award-level and TAGGS amounts are comparisons. For each award, the best-available total uses account data first, then award-level data, then TAGGS. Other HHS awards are TAGGS awards for the same UEI, limited here to the top 10 per recipient. Sub-awards are deduplicated by prime award, sub-award number, action date, sub-awardee UEI, amount, and description.')
    for s in data['sources']:p(doc,s['citation'],muted=True)
    p(doc,f"CHIP build {data['build']['build_id']} · method {data['build']['method_version']} · prepared {prepared}.",muted=True)
    # Preserve the template's closing box exactly, including its logo and styling.
    doc._body._body.insert(len(doc._body._body)-1,about)
    footer=doc.sections[0].footer
    for para in footer.paragraphs:para.text=''
    fp=footer.paragraphs[0];fp.alignment=WD_ALIGN_PARAGRAPH.CENTER
    fp.add_run(f'{fon} — Recipient Profile · Page ');add_field(fp,'PAGE');fp.add_run(' of ');add_field(fp,'NUMPAGES')
    doc.save(path)
