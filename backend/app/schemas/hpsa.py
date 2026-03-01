from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.methodology import MethodologyNote

HPSADomain = Literal["pc", "mh", "dh"]


class HPSATypeSummary(BaseModel):
    designated: bool | None = None
    score_max: int | None = None
    population_covered: int | None = None
    coverage_pct: float | None = None
    raw_rows_in_county: int | None = None


class HPSASummaryResponse(BaseModel):
    county_fips: str
    state_fips: str | None = None
    primary_care: HPSATypeSummary
    mental_health: HPSATypeSummary
    dental: HPSATypeSummary
    methodology: MethodologyNote


class HPSASummaryResponseWithLegacy(HPSASummaryResponse):
    pc_designated: bool | None = None
    pc_hpsa_score_max: int | None = None
    pc_population_covered: int | None = None
    pc_coverage_pct: float | None = None

    mh_designated: bool | None = None
    mh_hpsa_score_max: int | None = None
    mh_population_covered: int | None = None
    mh_coverage_pct: float | None = None

    dh_designated: bool | None = None
    dh_hpsa_score_max: int | None = None
    dh_population_covered: int | None = None
    dh_coverage_pct: float | None = None

    population_denominator_type: str | None = None
    population_denominator: int | None = None
    population_denominator_source: str | None = None

    coverage_population_aggregation_method: str | None = None
    coverage_overlap_caveat: str | None = None
    coverage_pct_definition: str | None = None
    pc_coverage_method: str | None = None
    mh_coverage_method: str | None = None
    dh_coverage_method: str | None = None

    raw_rows_in_county_pc: int | None = None
    raw_rows_in_county_mh: int | None = None
    raw_rows_in_county_dh: int | None = None

    as_of_date: date | None = None
    updated_at: datetime | None = None


class HPSADomainQuartiles(BaseModel):
    q25: float | None = None
    q50: float | None = None
    q75: float | None = None
    n_counties: int = 0
    as_of_date: date | None = None


class HPSAChoroplethCountyFeature(BaseModel):
    county_fips: str
    value: float | None = None
    designated: bool
    tier: int | None = None


class HPSAChoroplethCountiesResponse(BaseModel):
    domain: HPSADomain
    quartiles: HPSADomainQuartiles
    features: list[HPSAChoroplethCountyFeature]


class HPSACountyDomainDetailResponse(BaseModel):
    county_fips: str
    state_fips: str | None = None
    domain: HPSADomain
    designated: bool | None = None
    score_max: int | None = None
    tier: int | None = None
    population_covered: int | None = None
    coverage_pct: float | None = None
    hpsa_formal_ratio: str | None = None
    provider_ratio_goal: str | None = None
    fte: float | None = None
    methodology: MethodologyNote
