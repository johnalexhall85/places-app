from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MapContextSelectedArea(BaseModel):
    countyFips: str | None = None
    tractGeoid: str | None = None
    name: str | None = None
    stateAbbr: str | None = None

    model_config = ConfigDict(extra="ignore")


class MapContextSelection(BaseModel):
    hpsaDomain: Literal["pc", "mh", "dh"] | None = None

    placesMeasureId: str | None = None
    placesYear: int | None = None
    placesValueTypeId: str | None = None

    acsVariable: str | None = None
    acsYearWindow: str | None = None
    acsDataValueTypeId: str | None = None

    femaMeasureId: str | None = None

    sviTheme: str | None = None
    sviMeasureId: str | None = None
    sviYear: int | None = None

    model_config = ConfigDict(extra="ignore")


class MapContextMapState(BaseModel):
    zoom: float | None = None
    bbox: list[float] | None = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("bbox")
    @classmethod
    def _validate_bbox(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        if len(value) != 4:
            raise ValueError("bbox must contain exactly 4 values")
        return [float(item) for item in value]


class MapContext(BaseModel):
    dataSource: str
    geoLevel: Literal["county", "tract", "place", "zcta"] | str = "county"
    selectedArea: MapContextSelectedArea = Field(default_factory=MapContextSelectedArea)
    selection: MapContextSelection = Field(default_factory=MapContextSelection)
    mapState: MapContextMapState = Field(default_factory=MapContextMapState)
    asOfDate: str | None = None

    model_config = ConfigDict(extra="ignore")
