"""Retrieve or reuse history source files and record their provenance.

Source entry fields (registry ``sources``):
  role            unique name the parser asks for
  archived_path   reuse a file CHIP already archived (relative to data/ingest); needs sha256
  sha256          expected checksum of an archived file (also allowed as a pin for a URL)
  url             official URL; ``params`` are added as the query string
  census_key      add the Census API key at request time (never stored in the URL record)
  per_state       expand into one file per ``config['state_fips']`` entry; ``{state}`` in params
  socrata_paged   page a Socrata resource CSV with $limit/$offset (``page_size``, default 50000)
  filename        local file name (default: role + extension of the URL path)
  user_agent      override the default user agent (AHRQ refuses non-browser agents)
"""
from __future__ import annotations

import csv
import hashlib
import io
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

INGEST_ROOT = Path(__file__).resolve().parents[4] / 'data' / 'ingest'
HISTORY_ROOT = INGEST_ROOT / 'history'
USER_AGENT = 'CHIP-area-ingest/1.0'


def sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            sha.update(block)
    return sha.hexdigest()


def evidence(path: Path, role: str, url: str) -> dict:
    return {'role': role, 'path': str(path), 'url': url, 'sha256': sha256_file(path),
            'byte_count': Path(path).stat().st_size, 'retrieved_at': datetime.now(timezone.utc)}


def expand(config: dict) -> list[dict]:
    """Source entries with per-state entries expanded; roles stay unique."""
    result = []
    for source in config['sources']:
        if source.get('per_state'):
            for state in config['state_fips']:
                params = {k: str(v).replace('{state}', state) for k, v in source.get('params', {}).items()}
                result.append(source | {'role': f"{source['role']}_{state}", 'params': params,
                                        'per_state': False, 'state': state})
        else:
            result.append(source)
    return result


def _filename(source: dict) -> str:
    if source.get('filename'):
        return source['filename'].replace('{state}', source.get('state', ''))
    suffix = Path(urlparse(source['url']).path).suffix or '.json'
    return source['role'] + suffix


def _get(session, url, params, user_agent, stream=False):
    for attempt in range(4):
        try:
            response = session.get(url, params=params, timeout=(15, 300), stream=stream,
                                   headers={'User-Agent': user_agent})
            if response.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f'HTTP {response.status_code}')
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def _download(session, source: dict, path: Path, census_key) -> None:
    params = dict(source.get('params', {}))
    if source.get('census_key'):
        if not census_key:
            raise RuntimeError('CENSUS_API_KEY is not configured')
        params['key'] = census_key
    agent = source.get('user_agent', USER_AGENT)
    temporary = path.with_suffix(path.suffix + '.part')
    if source.get('socrata_paged'):
        size, offset, header = int(source.get('page_size', 50000)), 0, None
        with temporary.open('w', encoding='utf-8', newline='') as out:
            writer = csv.writer(out)
            while True:
                page = _get(session, source['url'], params | {'$limit': size, '$offset': offset, '$order': ':id'}, agent)
                rows = list(csv.reader(io.StringIO(page.content.decode('utf-8'))))
                if not rows:
                    raise RuntimeError(f'{source["role"]}: empty Socrata page')
                if header is None:
                    header = rows[0]
                    writer.writerow(header)
                elif rows[0] != header:
                    raise RuntimeError(f'{source["role"]}: Socrata header changed between pages')
                writer.writerows(rows[1:])
                if len(rows) - 1 < size:
                    break
                offset += size
    else:
        response = _get(session, source['url'], params, agent, stream=True)
        with temporary.open('wb') as out:
            for block in response.iter_content(1 << 20):
                out.write(block)
    temporary.replace(path)


def retrieve(config: dict, run_dir: Path, census_key=None) -> tuple[dict[str, Path], list[dict]]:
    """Return {role: local path} and file evidence rows. Raises on any checksum mismatch."""
    run_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    paths, files = {}, []
    for source in expand(config):
        role = source['role']
        if source.get('archived_path'):
            path = (INGEST_ROOT / source['archived_path']).resolve()
            if INGEST_ROOT.resolve() not in path.parents or not path.is_file():
                raise RuntimeError(f'{role}: archived file missing')
            url = source.get('url', f'archived:{source["archived_path"]}')
        else:
            path = run_dir / _filename(source)
            _download(session, source, path, census_key)
            url = source['url']      # the key, if any, was a request parameter and is not recorded
        item = evidence(path, role, url)
        if source.get('sha256') and item['sha256'] != source['sha256']:
            raise RuntimeError(f'{role}: checksum differs from the registry pin')
        paths[role] = path
        files.append(item)
    return paths, files
