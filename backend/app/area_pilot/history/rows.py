"""Normalized history rows: the one format every history parser returns.

A parser never decides population, value type, or boundary vintage on its own: ``make_row`` takes
them from the history registry entry for that measure and period, so they cannot drift.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

LEVEL_LENGTH = {'state': 2, 'county': 5, 'tract': 11}
UNCERTAINTY_KINDS = ('ci95', 'moe90', 'none')
MAX_SCALE = 6          # observation_history numeric(18,6)


@dataclass(frozen=True)
class HistoryRow:
    level: str
    geoid: str
    measure_id: str
    period: str
    population: str
    value_type: str
    value: Decimal | None
    status: str
    uncertainty_kind: str
    low: Decimal | None
    high: Decimal | None
    moe: Decimal | None
    source_value: str
    boundary_vintage: str

    @property
    def key(self):
        return (self.level, self.geoid, self.measure_id, self.period)


def to_decimal(text: str | None) -> Decimal | None:
    """Exact decimal from a source cell, or None for a blank cell. Raises ValueError otherwise."""
    if text is None:
        return None
    text = str(text).strip()
    if text == '':
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f'Not a number: {text!r}') from None
    if not value.is_finite():
        raise ValueError(f'Not a finite number: {text!r}')
    return value


def number_text(value: Decimal | None) -> str:
    """Canonical text for digests; equal for 14.9, 14.90 and the numeric(18,6) round trip."""
    if value is None:
        return ''
    text = format(value.normalize(), 'f')
    return '0' if text in ('-0', '0') else text


def row_line(row: HistoryRow) -> str:
    return '|'.join((row.level, row.geoid, row.measure_id, row.period, row.population, row.value_type,
                     number_text(row.value), row.status, row.uncertainty_kind, number_text(row.low),
                     number_text(row.high), number_text(row.moe), row.source_value, row.boundary_vintage))


def part_digest(rows) -> str:
    """sha256 over rows in C-collation key order; the database recheck streams the same lines."""
    sha = hashlib.sha256()
    for row in sorted(rows, key=lambda r: r.key):
        sha.update(row_line(row).encode('utf-8'))
        sha.update(b'\n')
    return sha.hexdigest()


def make_row(config: dict, measure_id: str, period: str, level: str, geoid: str, *, value=None,
             status: str, source_value: str = '', low=None, high=None, moe=None) -> HistoryRow:
    """Build a row, taking population, value type, uncertainty kind, and vintage from the registry."""
    entry = config['_index'].get((measure_id, period))
    if entry is None:
        raise ValueError(f'{measure_id} {period} is not declared in the history registry')
    measure, spec = entry
    kind = measure.get('uncertainty_kind', config.get('uncertainty_kind', 'none'))
    vintage = spec['boundary_vintage'].get(level)
    if vintage is None:
        raise ValueError(f'{measure_id} {period} declares no {level} boundary vintage')
    return HistoryRow(level=level, geoid=str(geoid), measure_id=measure_id, period=period,
                      population=spec.get('population', measure['population']),
                      value_type=measure['value_type'], value=value, status=status,
                      uncertainty_kind=kind, low=low if kind == 'ci95' else None,
                      high=high if kind == 'ci95' else None, moe=moe if kind == 'moe90' else None,
                      source_value='' if source_value is None else str(source_value),
                      boundary_vintage=vintage)


def row_problems(row: HistoryRow, config: dict) -> list[str]:
    """Contract problems for one row; an empty list means the row may be stored."""
    problems = []
    if row.level not in config['levels']:
        problems.append('level')
    if len(row.geoid) != LEVEL_LENGTH.get(row.level, -1) or not row.geoid.isdigit():
        problems.append('geoid')
    if row.status not in config['statuses']:
        problems.append('status')
    if (row.value is None) != (row.status in config['null_statuses']):
        problems.append('value_status')
    for name in ('value', 'low', 'high', 'moe'):
        number = getattr(row, name)
        if number is not None and (number.as_tuple().exponent < -MAX_SCALE or abs(number) >= Decimal('1e12')):
            problems.append(f'{name}_precision')
    if row.uncertainty_kind == 'ci95' and row.value is not None and (row.low is None) != (row.high is None):
        problems.append('ci_pair')
    return problems
