#!/usr/bin/env python3
"""Create a clean claude.ai skill zip, with the skill folder as its root."""
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(args.out,'w',ZIP_DEFLATED,compresslevel=9) as archive:
        for folder in ('assets','references','scripts'):
            for path in sorted((ROOT/folder).rglob('*')):
                if path.is_file() and path.suffix != '.pyc' and '__pycache__' not in path.parts:
                    archive.write(path,Path(ROOT.name)/path.relative_to(ROOT))
        archive.write(ROOT/'SKILL.md',Path(ROOT.name)/'SKILL.md')
    print(args.out)


if __name__=='__main__':main()
