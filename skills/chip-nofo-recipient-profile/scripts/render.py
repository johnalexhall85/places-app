#!/usr/bin/env python3
"""Render a CHIP NOFO dataset to PDO-branded Word and Excel files."""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--title')
    parser.add_argument('--narrative',type=Path)
    parser.add_argument('--prepared',default=date.today().isoformat())
    args=parser.parse_args()
    if 'MPLCONFIGDIR' not in os.environ:
        config=Path(tempfile.gettempdir())/'chip-nofo-matplotlib'
        config.mkdir(parents=True,exist_ok=True)
        os.environ['MPLCONFIGDIR']=str(config)
    try:
        from common import validate, title_for
        import docx_report, xlsx_report
    except ImportError as exc:
        raise SystemExit(f'Missing report library ({exc}). Run: pip install python-docx openpyxl matplotlib')
    try:
        data=json.loads(args.dataset.read_text(encoding='utf-8'))
        date.fromisoformat(args.prepared)
        data['_prepared']=args.prepared
        validate(data)
        narrative=json.loads(args.narrative.read_text(encoding='utf-8')) if args.narrative else {}
        if not isinstance(narrative,dict) or not isinstance(narrative.get('context',[]),list) or any(not isinstance(x,str) for x in narrative.get('context',[])):
            raise ValueError('Narrative must be a JSON object with an optional list of context strings')
        title=title_for(data,args.title)
        args.out.mkdir(parents=True,exist_ok=True)
        fon=re.sub(r'[^A-Za-z0-9_-]','',data['nofo']['fon_display'])
        stem=fon+'_Recipient_Profile'
        word=args.out/(stem+'.docx');excel=args.out/(stem+'.xlsx')
        assets=Path(__file__).resolve().parent.parent/'assets'
        docx_report.render(data,word,args.prepared,title,narrative,assets)
        xlsx_report.render(data,excel,args.prepared,title)
        sub=data['subawards']['summary'] if data['subawards'] is not None else None
        print(json.dumps({'docx':str(word),'xlsx':str(excel),'recipients':len(data['recipients']),
            'other_awards_shown':data['aggregates'].get('other_award_rows',0),
            'subawardees':sub['distinct_subawardees'] if sub else 0,
            'subaward_actions':sub['actions'] if sub else 0},separators=(',',':')))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise SystemExit(f'Render failed: {exc}')


if __name__=='__main__':
    main()
