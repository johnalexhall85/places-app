"""Stream-check archived published source files against database provenance manifest."""
import hashlib
import json
import sys
import tarfile
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
expected = {f"ingest/{item['path']}": item for item in manifest['files']}
seen = set()
with tarfile.open(fileobj=sys.stdin.buffer, mode='r|') as archive:
    for member in archive:
        if not member.isfile() or member.name not in expected:
            continue
        item = expected[member.name]
        if member.name in seen or member.size != item['bytes']:
            raise SystemExit(f'Duplicate or wrong-sized member: {member.name}')
        source = archive.extractfile(member)
        if source is None:
            raise SystemExit(f'Unreadable member: {member.name}')
        checksum = hashlib.sha256()
        while block := source.read(1024 * 1024):
            checksum.update(block)
        if checksum.hexdigest() != item['sha256']:
            raise SystemExit(f'Checksum mismatch: {member.name}')
        seen.add(member.name)
if seen != set(expected):
    raise SystemExit(f'Missing published source files: {len(set(expected) - seen)}')
print(f'archive_verified_published_files={len(seen)}')
