from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from numbers import Real
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from app.recon.normalization import (
    NORMALIZATION_LOOKUP_VARIANT_LEGACY_V1,
    NORMALIZATION_LOOKUP_VARIANT_V11_EMERGENCY,
    build_normalization_note,
    fetch_state_normalization_lookup,
)


class CDCFundingMode(str, Enum):
    RAW_TOTAL = "raw_total"
    CHIP_NORMALIZED = "chip_normalized"
    CHIP_NORMALIZED_V11 = "chip_normalized_v1_1"


FUNDING_MODE_LABELS = {
    CDCFundingMode.RAW_TOTAL.value: "Raw total funding",
    CDCFundingMode.CHIP_NORMALIZED.value: "CHIP Normalized Funding (Legacy)",
    CDCFundingMode.CHIP_NORMALIZED_V11.value: "CHIP Normalized Funding v1.1",
}
FUNDING_MODEL_VERSION = "cdc_funding_mode_v1"
DEFAULT_FUNDING_MODE = CDCFundingMode.CHIP_NORMALIZED_V11.value
NORMALIZED_FUNDING_MODES = {
    CDCFundingMode.CHIP_NORMALIZED.value,
    CDCFundingMode.CHIP_NORMALIZED_V11.value,
}


def is_normalized_funding_mode(value: str | None) -> bool:
    token = str(value or "").strip().lower()
    return token in NORMALIZED_FUNDING_MODES


def normalization_lookup_variant_for_mode(value: str | None) -> str:
    token = str(value or "").strip().lower()
    if token == CDCFundingMode.CHIP_NORMALIZED_V11.value:
        return NORMALIZATION_LOOKUP_VARIANT_V11_EMERGENCY
    return NORMALIZATION_LOOKUP_VARIANT_LEGACY_V1


@dataclass(frozen=True)
class CHIPFundingResult:
    total_funding: float | None
    per_capita_funding: float | None
    per_100k_funding: float | None
    share_of_national: float | None
    equity_adjusted_metrics: dict[str, Any]


@dataclass(frozen=True)
class CHIPFundingCacheContext:
    scope: str
    geography_level: str
    fiscal_year: int | None
    time_aggregation: str
    funding_type: str
    program_area: str | None
    mechanism: str | None
    recipient_type: str | None
    funding_mode: str
    bbox: str | None = None
    limit: int | None = None
    state: str | None = None


@dataclass(frozen=True)
class CHIPFundingModeContext:
    requested_mode: str
    effective_mode: str
    funding_mode_label: str
    normalization_supported: bool
    normalization_applied: bool
    normalization_note: str | None
    normalization_reason: str | None
    methodology_version: str | None
    normalization_method: str | None
    funding_stream_logic_version: str | None
    normalized_amount_type: str | None
    normalization_status_label: str | None
    normalization_confidence_note: str | None
    lookup_signature: tuple[tuple[str, float | None, float | None], ...]
    lookup: Mapping[str, Mapping[str, Any]]


def _json_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        return float(value)
    if isinstance(value, Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return None


class CHIPFundingModel:
    def __init__(self, *, max_cache_size: int = 64, ttl_seconds: int = 300) -> None:
        self._max_cache_size = max(1, int(max_cache_size))
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._cache: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()

    def normalize_funding_mode(self, value: str | None) -> str:
        token = str(value or DEFAULT_FUNDING_MODE).strip().lower()
        if token not in {mode.value for mode in CDCFundingMode}:
            allowed = ", ".join(mode.value for mode in CDCFundingMode)
            raise ValueError(f"funding_mode must be one of {allowed}")
        return token

    def build_mode_context(self, db: Session, *, cache_context: CHIPFundingCacheContext) -> CHIPFundingModeContext:
        requested_mode = self.normalize_funding_mode(cache_context.funding_mode)
        if requested_mode == CDCFundingMode.RAW_TOTAL.value:
            return CHIPFundingModeContext(
                requested_mode=requested_mode,
                effective_mode=CDCFundingMode.RAW_TOTAL.value,
                funding_mode_label=FUNDING_MODE_LABELS[CDCFundingMode.RAW_TOTAL.value],
                normalization_supported=True,
                normalization_applied=False,
                normalization_note=None,
                normalization_reason=None,
                methodology_version=None,
                normalization_method=None,
                funding_stream_logic_version=None,
                normalized_amount_type=None,
                normalization_status_label=None,
                normalization_confidence_note=None,
                lookup_signature=(),
                lookup={},
            )

        normalization_reason = self._normalization_support_reason(cache_context)
        if normalization_reason is not None:
            return CHIPFundingModeContext(
                requested_mode=requested_mode,
                effective_mode=CDCFundingMode.RAW_TOTAL.value,
                funding_mode_label=FUNDING_MODE_LABELS[CDCFundingMode.RAW_TOTAL.value],
                normalization_supported=False,
                normalization_applied=False,
                normalization_note=normalization_reason,
                normalization_reason=normalization_reason,
                methodology_version=None,
                normalization_method=None,
                funding_stream_logic_version=None,
                normalized_amount_type=None,
                normalization_status_label=None,
                normalization_confidence_note=None,
                lookup_signature=(),
                lookup={},
            )

        lookup = fetch_state_normalization_lookup(
            db,
            source_system="usaspending",
            fiscal_year=int(cache_context.fiscal_year),
            lookup_variant=normalization_lookup_variant_for_mode(requested_mode),
        )
        if not lookup:
            normalization_reason = (
                f"{FUNDING_MODE_LABELS[requested_mode]} is unavailable because no reconstructed state benchmarks were found "
                f"for FY{int(cache_context.fiscal_year)}."
            )
            return CHIPFundingModeContext(
                requested_mode=requested_mode,
                effective_mode=CDCFundingMode.RAW_TOTAL.value,
                funding_mode_label=FUNDING_MODE_LABELS[CDCFundingMode.RAW_TOTAL.value],
                normalization_supported=False,
                normalization_applied=False,
                normalization_note=normalization_reason,
                normalization_reason=normalization_reason,
                methodology_version=None,
                normalization_method=None,
                funding_stream_logic_version=None,
                normalized_amount_type=None,
                normalization_status_label=None,
                normalization_confidence_note=None,
                lookup_signature=(),
                lookup={},
            )

        sample_row = next(iter(lookup.values()))
        normalization_note = build_normalization_note(
            fiscal_year=int(cache_context.fiscal_year),
            normalization_applied=True,
            reason=(
                (
                    "County values preserve the raw within-state distribution and are rescaled by CHIP's v1.1 emergency-classification state benchmark."
                    if requested_mode == CDCFundingMode.CHIP_NORMALIZED_V11.value
                    else "County values preserve the raw within-state distribution and are rescaled by CHIP's normalized state benchmark factor."
                )
                if cache_context.geography_level == "county"
                else None
            ),
        )
        lookup_signature = tuple(
            sorted(
                (
                    str(state_code),
                    _json_number(row.get("normalized_amount")),
                    _json_number(row.get("normalization_factor")),
                )
                for state_code, row in lookup.items()
            )
        )
        return CHIPFundingModeContext(
            requested_mode=requested_mode,
            effective_mode=requested_mode,
            funding_mode_label=FUNDING_MODE_LABELS[requested_mode],
            normalization_supported=True,
            normalization_applied=True,
            normalization_note=normalization_note,
            normalization_reason=None,
            methodology_version=str(sample_row.get("methodology_version") or "").strip() or None,
            normalization_method=str(sample_row.get("normalization_method") or "").strip() or None,
            funding_stream_logic_version=str(sample_row.get("funding_stream_logic_version") or "").strip() or None,
            normalized_amount_type=str(sample_row.get("normalized_amount_type") or "").strip() or None,
            normalization_status_label=str(sample_row.get("status_label") or "").strip() or None,
            normalization_confidence_note=str(sample_row.get("confidence_note") or "").strip() or None,
            lookup_signature=lookup_signature,
            lookup=lookup,
        )

    def calculate(
        self,
        funding_records: Sequence[Mapping[str, Any]] | None = None,
        population: Any = None,
        fiscal_year: int | None = None,
        *,
        total_funding: Any = None,
        national_total_funding: Any = None,
    ) -> CHIPFundingResult:
        del fiscal_year
        resolved_total = _json_number(total_funding)
        if resolved_total is None and funding_records is not None:
            resolved_total = sum(
                float(_json_number(record.get("amount")) or 0.0)
                for record in funding_records
            )

        resolved_population = _json_number(population)
        resolved_national_total = _json_number(national_total_funding)
        per_capita = (
            resolved_total / resolved_population
            if resolved_total is not None and resolved_population not in (None, 0)
            else None
        )
        per_100k = per_capita * 100000 if per_capita is not None else None
        share_of_national = (
            (resolved_total / resolved_national_total) * 100
            if resolved_total is not None and resolved_national_total not in (None, 0)
            else None
        )
        return CHIPFundingResult(
            total_funding=resolved_total,
            per_capita_funding=per_capita,
            per_100k_funding=per_100k,
            share_of_national=share_of_national,
            equity_adjusted_metrics={},
        )

    def calculate_many(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        cache_context: CHIPFundingCacheContext,
        mode_context: CHIPFundingModeContext,
        amount_field: str = "raw_total_funding_amount",
        population_field: str = "population",
    ) -> list[dict[str, Any]]:
        cache_key = self._cache_key(
            rows,
            cache_context=cache_context,
            mode_context=mode_context,
            amount_field=amount_field,
            population_field=population_field,
        )
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        raw_national_total = sum(
            float(_json_number(row.get(amount_field)) or 0.0)
            for row in rows
            if _json_number(row.get(amount_field)) is not None
        )
        normalized_totals = self._normalized_totals_by_row(
            rows,
            cache_context=cache_context,
            mode_context=mode_context,
            amount_field=amount_field,
        )
        normalized_national_total = sum(
            float(value)
            for value in normalized_totals.values()
            if value is not None and math.isfinite(float(value))
        )

        output: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            payload = dict(row)
            raw_total = _json_number(row.get(amount_field))
            population = row.get(population_field)
            raw_result = self.calculate(
                total_funding=raw_total,
                population=population,
                fiscal_year=cache_context.fiscal_year,
                national_total_funding=raw_national_total,
            )
            normalized_total = normalized_totals.get(index)
            normalized_result = self.calculate(
                total_funding=normalized_total,
                population=population,
                fiscal_year=cache_context.fiscal_year,
                national_total_funding=normalized_national_total,
            )

            state_code = self._row_state_code(row, geography_level=cache_context.geography_level)
            normalization_row = mode_context.lookup.get(state_code) if state_code else None
            normalization_factor = (
                _json_number(normalization_row.get("normalization_factor"))
                if normalization_row is not None
                else None
            )
            row_effective_mode = (
                mode_context.requested_mode
                if is_normalized_funding_mode(mode_context.requested_mode) and normalized_total is not None
                else CDCFundingMode.RAW_TOTAL.value
            )
            selected_result = normalized_result if is_normalized_funding_mode(row_effective_mode) else raw_result
            payload.update(
                self._row_payload(
                    raw_result=raw_result,
                    normalized_result=normalized_result,
                    selected_result=selected_result,
                    row=row,
                    mode_context=mode_context,
                    row_effective_mode=row_effective_mode,
                    normalization_row=normalization_row,
                    normalization_factor=normalization_factor,
                    geography_level=cache_context.geography_level,
                )
            )
            output.append(payload)

        self._set_cached(cache_key, output)
        return copy.deepcopy(output)

    def _normalization_support_reason(self, cache_context: CHIPFundingCacheContext) -> str | None:
        mode_label = FUNDING_MODE_LABELS.get(
            self.normalize_funding_mode(cache_context.funding_mode),
            "CHIP normalized funding",
        )
        if cache_context.fiscal_year is None:
            return f"{mode_label} requires an explicit fiscal year."
        if cache_context.time_aggregation != "single_fiscal_year":
            return f"{mode_label} is only available for single fiscal-year CDC totals."
        if cache_context.funding_type != "total_cdc_funding":
            return f"{mode_label} is calibrated to the Total CDC Funding view and is not applied to alternate funding-type slices."
        if any(
            str(value or "").strip()
            for value in (
                cache_context.program_area,
                cache_context.mechanism,
                cache_context.recipient_type,
            )
        ):
            return (
                f"{mode_label} is calibrated to statewide overall CDC totals and is not applied to filtered "
                "program-area, mechanism, or recipient-type subsets."
            )
        return None

    def _normalized_totals_by_row(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        cache_context: CHIPFundingCacheContext,
        mode_context: CHIPFundingModeContext,
        amount_field: str,
    ) -> dict[int, float | None]:
        if not mode_context.normalization_applied:
            return {index: None for index, _row in enumerate(rows)}

        if cache_context.geography_level == "national":
            normalized_total = sum(
                float(_json_number(row.get("normalized_amount")) or 0.0)
                for row in mode_context.lookup.values()
                if _json_number(row.get("normalized_amount")) is not None
            )
            return {
                index: normalized_total if index == 0 else None
                for index, _row in enumerate(rows)
            }

        output: dict[int, float | None] = {}
        for index, row in enumerate(rows):
            state_code = self._row_state_code(row, geography_level=cache_context.geography_level)
            normalization_row = mode_context.lookup.get(state_code) if state_code else None
            if normalization_row is None:
                output[index] = None
                continue
            if cache_context.geography_level == "state":
                output[index] = _json_number(normalization_row.get("normalized_amount"))
                continue
            normalization_factor = _json_number(normalization_row.get("normalization_factor"))
            raw_total = _json_number(row.get(amount_field))
            output[index] = (
                float(raw_total) * float(normalization_factor)
                if raw_total is not None and normalization_factor is not None
                else None
            )
        return output

    def _row_payload(
        self,
        *,
        raw_result: CHIPFundingResult,
        normalized_result: CHIPFundingResult,
        selected_result: CHIPFundingResult,
        row: Mapping[str, Any],
        mode_context: CHIPFundingModeContext,
        row_effective_mode: str,
        normalization_row: Mapping[str, Any] | None,
        normalization_factor: float | None,
        geography_level: str,
    ) -> dict[str, Any]:
        funding_mode_label = FUNDING_MODE_LABELS[row_effective_mode]
        methodology_version = (
            str(normalization_row.get("methodology_version") or "").strip() or None
            if normalization_row is not None and is_normalized_funding_mode(row_effective_mode)
            else mode_context.methodology_version
        )
        component_payload = self._component_payload(
            normalization_row=normalization_row,
            geography_level=geography_level,
            row_effective_mode=row_effective_mode,
            mode_context=mode_context,
        )
        return {
            "raw_total_funding": raw_result.total_funding,
            "raw_funding_per_capita": raw_result.per_capita_funding,
            "raw_funding_per_100k": raw_result.per_100k_funding,
            "raw_share_of_national": raw_result.share_of_national,
            "chip_normalized_funding": normalized_result.total_funding,
            "chip_normalized_funding_per_capita": normalized_result.per_capita_funding,
            "chip_normalized_funding_per_100k": normalized_result.per_100k_funding,
            "chip_normalized_share_of_national": normalized_result.share_of_national,
            "chip_total_funding": normalized_result.total_funding,
            "chip_per_capita_funding": normalized_result.per_capita_funding,
            "chip_per_100k_funding": normalized_result.per_100k_funding,
            "chip_share_of_national": normalized_result.share_of_national,
            "chip_equity_adjusted_metrics": selected_result.equity_adjusted_metrics,
            "funding_mode_requested": mode_context.requested_mode,
            "funding_mode_effective": row_effective_mode,
            "funding_mode_label": funding_mode_label,
            "funding_mode_requested_label": FUNDING_MODE_LABELS[mode_context.requested_mode],
            "normalization_supported": mode_context.normalization_supported,
            "normalization_applied": is_normalized_funding_mode(row_effective_mode),
            "normalization_note": mode_context.normalization_note,
            "normalization_reason": mode_context.normalization_reason,
            "normalization_factor": normalization_factor,
            "normalized_amount_type": (
                normalization_row.get("normalized_amount_type")
                if normalization_row is not None and is_normalized_funding_mode(row_effective_mode)
                else None
            ),
            "normalization_status_label": (
                normalization_row.get("status_label")
                if normalization_row is not None and is_normalized_funding_mode(row_effective_mode)
                else None
            ),
            "normalization_method": (
                normalization_row.get("normalization_method")
                if normalization_row is not None and is_normalized_funding_mode(row_effective_mode)
                else mode_context.normalization_method
            ),
            "funding_stream_logic_version": (
                normalization_row.get("funding_stream_logic_version")
                if normalization_row is not None and is_normalized_funding_mode(row_effective_mode)
                else mode_context.funding_stream_logic_version
            ),
            "methodology_version": methodology_version,
            "normalization_confidence_note": (
                normalization_row.get("confidence_note")
                if normalization_row is not None and is_normalized_funding_mode(row_effective_mode)
                else mode_context.normalization_confidence_note
            ),
            "funding_model_version": FUNDING_MODEL_VERSION,
            "total_funding_amount": selected_result.total_funding,
            "funding_per_capita": selected_result.per_capita_funding,
            "funding_per_100k": selected_result.per_100k_funding,
            "share_national_pct": selected_result.share_of_national,
            **component_payload,
        }

    def _component_payload(
        self,
        *,
        normalization_row: Mapping[str, Any] | None,
        geography_level: str,
        row_effective_mode: str,
        mode_context: CHIPFundingModeContext,
    ) -> dict[str, Any]:
        component_fields = {
            "core_public_health_amount": "core_public_health_amount",
            "emergency_public_health_amount": "emergency_public_health_amount",
            "federal_health_transfer_amount": "federal_health_transfer_amount",
            "procurement_support_scope_amount": "procurement_support_scope_amount",
            "special_transfer_amount": "special_transfer_amount",
            "other_public_health_amount": "other_public_health_amount",
            "biomedical_research_amount": "biomedical_research_amount",
            "international_health_assistance_amount": "international_health_assistance_amount",
            "unknown_funding_scope_amount": "unknown_funding_scope_amount",
        }
        if not is_normalized_funding_mode(row_effective_mode):
            return {key: None for key in component_fields}
        if geography_level == "state" and normalization_row is not None:
            return {key: _json_number(normalization_row.get(column)) for key, column in component_fields.items()}
        if geography_level == "national":
            payload: dict[str, Any] = {}
            for key, column in component_fields.items():
                total = sum(
                    float(_json_number(row.get(column)) or 0.0)
                    for row in mode_context.lookup.values()
                    if _json_number(row.get(column)) is not None
                )
                payload[key] = total
            return payload
        return {key: None for key in component_fields}

    def _row_state_code(self, row: Mapping[str, Any], *, geography_level: str) -> str | None:
        if geography_level == "state":
            token = str(row.get("geography_id") or row.get("state_code") or "").strip().upper()
            return token or None
        token = str(row.get("state_code") or "").strip().upper()
        return token or None

    def _cache_key(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        cache_context: CHIPFundingCacheContext,
        mode_context: CHIPFundingModeContext,
        amount_field: str,
        population_field: str,
    ) -> str:
        signature_rows = [
            {
                "geography_id": row.get("geography_id"),
                "state_code": row.get("state_code"),
                "amount": _json_number(row.get(amount_field)),
                "population": _json_number(row.get(population_field)),
            }
            for row in rows
        ]
        payload = {
            "cache_context": asdict(cache_context),
            "requested_mode": mode_context.requested_mode,
            "effective_mode": mode_context.effective_mode,
            "normalization_supported": mode_context.normalization_supported,
            "normalization_applied": mode_context.normalization_applied,
            "lookup_signature": mode_context.lookup_signature,
            "amount_field": amount_field,
            "population_field": population_field,
            "rows": signature_rows,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _get_cached(self, cache_key: str) -> list[dict[str, Any]] | None:
        cached = self._cache.get(cache_key)
        if cached is None:
            return None
        cached_at, payload = cached
        if time.time() - cached_at > self._ttl_seconds:
            self._cache.pop(cache_key, None)
            return None
        self._cache.move_to_end(cache_key)
        return copy.deepcopy(payload)

    def _set_cached(self, cache_key: str, payload: list[dict[str, Any]]) -> None:
        self._cache[cache_key] = (time.time(), copy.deepcopy(payload))
        self._cache.move_to_end(cache_key)
        while len(self._cache) > self._max_cache_size:
            self._cache.popitem(last=False)
