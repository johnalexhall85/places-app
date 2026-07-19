from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateInfo:
    state_fips: str
    state_code: str
    state_name: str


STATE_ROWS: tuple[StateInfo, ...] = (
    StateInfo("01", "AL", "Alabama"),
    StateInfo("02", "AK", "Alaska"),
    StateInfo("04", "AZ", "Arizona"),
    StateInfo("05", "AR", "Arkansas"),
    StateInfo("06", "CA", "California"),
    StateInfo("08", "CO", "Colorado"),
    StateInfo("09", "CT", "Connecticut"),
    StateInfo("10", "DE", "Delaware"),
    StateInfo("11", "DC", "District of Columbia"),
    StateInfo("12", "FL", "Florida"),
    StateInfo("13", "GA", "Georgia"),
    StateInfo("15", "HI", "Hawaii"),
    StateInfo("16", "ID", "Idaho"),
    StateInfo("17", "IL", "Illinois"),
    StateInfo("18", "IN", "Indiana"),
    StateInfo("19", "IA", "Iowa"),
    StateInfo("20", "KS", "Kansas"),
    StateInfo("21", "KY", "Kentucky"),
    StateInfo("22", "LA", "Louisiana"),
    StateInfo("23", "ME", "Maine"),
    StateInfo("24", "MD", "Maryland"),
    StateInfo("25", "MA", "Massachusetts"),
    StateInfo("26", "MI", "Michigan"),
    StateInfo("27", "MN", "Minnesota"),
    StateInfo("28", "MS", "Mississippi"),
    StateInfo("29", "MO", "Missouri"),
    StateInfo("30", "MT", "Montana"),
    StateInfo("31", "NE", "Nebraska"),
    StateInfo("32", "NV", "Nevada"),
    StateInfo("33", "NH", "New Hampshire"),
    StateInfo("34", "NJ", "New Jersey"),
    StateInfo("35", "NM", "New Mexico"),
    StateInfo("36", "NY", "New York"),
    StateInfo("37", "NC", "North Carolina"),
    StateInfo("38", "ND", "North Dakota"),
    StateInfo("39", "OH", "Ohio"),
    StateInfo("40", "OK", "Oklahoma"),
    StateInfo("41", "OR", "Oregon"),
    StateInfo("42", "PA", "Pennsylvania"),
    StateInfo("44", "RI", "Rhode Island"),
    StateInfo("45", "SC", "South Carolina"),
    StateInfo("46", "SD", "South Dakota"),
    StateInfo("47", "TN", "Tennessee"),
    StateInfo("48", "TX", "Texas"),
    StateInfo("49", "UT", "Utah"),
    StateInfo("50", "VT", "Vermont"),
    StateInfo("51", "VA", "Virginia"),
    StateInfo("53", "WA", "Washington"),
    StateInfo("54", "WV", "West Virginia"),
    StateInfo("55", "WI", "Wisconsin"),
    StateInfo("56", "WY", "Wyoming"),
    StateInfo("60", "AS", "American Samoa"),
    StateInfo("66", "GU", "Guam"),
    StateInfo("69", "MP", "Northern Mariana Islands"),
    StateInfo("72", "PR", "Puerto Rico"),
    StateInfo("78", "VI", "U.S. Virgin Islands"),
)

BY_FIPS = {row.state_fips: row for row in STATE_ROWS}
BY_CODE = {row.state_code: row for row in STATE_ROWS}


def normalize_state(value: str | None) -> StateInfo | None:
    if value is None:
        return None
    token = str(value).strip().upper()
    if not token:
        return None
    if token.isdigit():
        return BY_FIPS.get(token.zfill(2))
    return BY_CODE.get(token)


def state_values_sql(alias: str = "state_lookup") -> str:
    def _quoted(value: str) -> str:
        return value.replace("'", "''")

    values = ",\n            ".join(
        f"('{row.state_fips}', '{row.state_code}', '{_quoted(row.state_name)}')"
        for row in STATE_ROWS
    )
    return f"""
        {alias}(state_fips, state_code, state_name) AS (
            VALUES
            {values}
        )
    """
