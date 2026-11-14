"""Inventory and verify files attached to published area releases."""
import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from app.db import DATABASE_URL

root = Path('/home/john/places-app/data/ingest').resolve()
output = Path(sys.argv[1])
with create_engine(DATABASE_URL).connect() as conn:
    rows = conn.execute(text('''SELECT sf.path,sf.sha256,sf.byte_count,sf.release_id,sf.run_id,sf.role
        FROM area_pilot.source_file sf JOIN area_pilot.release r ON r.id=sf.release_id
        WHERE r.status='published' ORDER BY sf.path,sf.release_id,sf.run_id''')).mappings().all()
files = {}
for row in rows:
    path = Path(row['path']).resolve()
    relative = str(path.relative_to(root))
    item = files.setdefault(relative, {'path': relative, 'sha256': row['sha256'],
                                       'bytes': row['byte_count'], 'references': []})
    if item['sha256'] != row['sha256'] or item['bytes'] != row['byte_count']:
        raise RuntimeError(f'Conflicting provenance for {relative}')
    item['references'].append({'release_id': str(row['release_id']),
                               'run_id': str(row['run_id']), 'role': row['role']})
for item in files.values():
    path = root / item['path']
    if not path.is_file() or path.stat().st_size != item['bytes']:
        raise RuntimeError(f'Missing or wrong-sized archive: {item["path"]}')
    with path.open('rb') as handle:
        actual = hashlib.file_digest(handle, 'sha256').hexdigest()
    if actual != item['sha256']:
        raise RuntimeError(f'Archive checksum mismatch: {item["path"]}')
payload = {'archive_root': str(root), 'published_source_rows': len(rows),
           'unique_files': len(files), 'unique_bytes': sum(x['bytes'] for x in files.values()),
           'files': sorted(files.values(), key=lambda x: x['path'])}
output.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
print(f'verified_published_source_files={len(files)}')
