"""History parsers: archived source files -> normalized HistoryRow parts.

Contract (every module in this package; see docs/history/tasks/H2-antigravity.md):

    SCHEMA_VERSION: str
        Bump when the parser's interpretation of the source changes.

    def parse(config: dict, files: dict[str, pathlib.Path], evidence: dict) -> Iterator[tuple[str, list[HistoryRow]]]

    - ``config`` is the loaded history registry (``registry.load_history_registry``).
    - ``files`` maps each ``config['sources'][i]['role']`` to a local, checksum-verified file.
    - Fill ``evidence`` with JSON-serializable facts a reviewer needs (header hashes, row counts per
      period, rows skipped and why). It is stored in the release report and its schema digest.
    - Yield ``(part_name, rows)``. A part is a unit small enough to hold in memory (one source
      file, or one period of one file). Part names are unique and stable across runs.
    - Build every row with ``rows.make_row`` and parse numbers with ``rows.to_decimal``.
    - Emit only (measure, period) pairs the registry declares with ``available`` true, only the
      levels the measure declares, and every area the source publishes for them (including
      suppressed or missing cells, with their own status). Never derive, aggregate, or fill values.
    - Raise ``ValueError`` with a plain message if the source schema, a header, a definition, or a
      year marker differs from what the registry expects. Do not guess.
    - No network, no database, no writes.
"""
from __future__ import annotations

import importlib


def load_parser(name: str):
    if not name.isidentifier():
        raise ValueError(f'Invalid parser name {name!r}')
    module = importlib.import_module(f'{__name__}.{name}')
    if not callable(getattr(module, 'parse', None)) or not isinstance(getattr(module, 'SCHEMA_VERSION', None), str):
        raise ValueError(f'History parser {name} does not follow the contract')
    return module
