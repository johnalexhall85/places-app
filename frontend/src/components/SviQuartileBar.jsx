export const SVI_NO_DATA_COLOR = "#d8dee3";
export const SVI_UNAVAILABLE_MESSAGE = "Data unavailable from the Census to calculate this variable.";
export const SVI_RANGE_TEXT = "Possible ranks range from 0 (lowest vulnerability) to 1 (highest vulnerability).";

export const SVI_LEVELS = [
  { key: "low", label: "Low", range: "0–0.25", phrase: "low", max: 0.25 },
  { key: "low_medium", label: "Low-Medium", range: "0.2501–0.50", phrase: "low to medium", max: 0.5 },
  { key: "medium_high", label: "Medium-High", range: "0.5001–0.75", phrase: "medium to high", max: 0.75 },
  { key: "high", label: "High", range: "0.7501–1.0", phrase: "high", max: 1.0 },
];

export const SVI_THEMES = [
  {
    baseId: "rpl_themes",
    stateId: "rpl_themes_state",
    title: "Overall SVI",
    isOverall: true,
    palette: ["#FFFEDD", "#C0E5CC", "#80CDD5", "#6596C0"],
  },
  {
    baseId: "rpl_theme1",
    stateId: "rpl_theme1_state",
    title: "Socioeconomic Status",
    isOverall: false,
    palette: ["#F3FAF0", "#D1ECCC", "#A2D6A2", "#6EAE80"],
  },
  {
    baseId: "rpl_theme2",
    stateId: "rpl_theme2_state",
    title: "Household Characteristics",
    isOverall: false,
    palette: ["#FFFFE2", "#FEE3B3", "#FCB571", "#D97B54"],
  },
  {
    baseId: "rpl_theme3",
    stateId: "rpl_theme3_state",
    title: "Racial & Ethnic Minority Status",
    isOverall: false,
    palette: ["#F6F5F9", "#DAD9EA", "#BAB9D7", "#9586BD"],
  },
  {
    baseId: "rpl_theme4",
    stateId: "rpl_theme4_state",
    title: "Housing Type & Transportation",
    isOverall: false,
    palette: ["#F4F7FF", "#D1E3EE", "#99C7E1", "#649DC9"],
  },
];

// 50 U.S. states and the District of Columbia (matches CDC SVI 2022 state files).
export const SVI_STATES = [
  { fips: "01", abbr: "AL", name: "Alabama" },
  { fips: "02", abbr: "AK", name: "Alaska" },
  { fips: "04", abbr: "AZ", name: "Arizona" },
  { fips: "05", abbr: "AR", name: "Arkansas" },
  { fips: "06", abbr: "CA", name: "California" },
  { fips: "08", abbr: "CO", name: "Colorado" },
  { fips: "09", abbr: "CT", name: "Connecticut" },
  { fips: "10", abbr: "DE", name: "Delaware" },
  { fips: "11", abbr: "DC", name: "District of Columbia" },
  { fips: "12", abbr: "FL", name: "Florida" },
  { fips: "13", abbr: "GA", name: "Georgia" },
  { fips: "15", abbr: "HI", name: "Hawaii" },
  { fips: "16", abbr: "ID", name: "Idaho" },
  { fips: "17", abbr: "IL", name: "Illinois" },
  { fips: "18", abbr: "IN", name: "Indiana" },
  { fips: "19", abbr: "IA", name: "Iowa" },
  { fips: "20", abbr: "KS", name: "Kansas" },
  { fips: "21", abbr: "KY", name: "Kentucky" },
  { fips: "22", abbr: "LA", name: "Louisiana" },
  { fips: "23", abbr: "ME", name: "Maine" },
  { fips: "24", abbr: "MD", name: "Maryland" },
  { fips: "25", abbr: "MA", name: "Massachusetts" },
  { fips: "26", abbr: "MI", name: "Michigan" },
  { fips: "27", abbr: "MN", name: "Minnesota" },
  { fips: "28", abbr: "MS", name: "Mississippi" },
  { fips: "29", abbr: "MO", name: "Missouri" },
  { fips: "30", abbr: "MT", name: "Montana" },
  { fips: "31", abbr: "NE", name: "Nebraska" },
  { fips: "32", abbr: "NV", name: "Nevada" },
  { fips: "33", abbr: "NH", name: "New Hampshire" },
  { fips: "34", abbr: "NJ", name: "New Jersey" },
  { fips: "35", abbr: "NM", name: "New Mexico" },
  { fips: "36", abbr: "NY", name: "New York" },
  { fips: "37", abbr: "NC", name: "North Carolina" },
  { fips: "38", abbr: "ND", name: "North Dakota" },
  { fips: "39", abbr: "OH", name: "Ohio" },
  { fips: "40", abbr: "OK", name: "Oklahoma" },
  { fips: "41", abbr: "OR", name: "Oregon" },
  { fips: "42", abbr: "PA", name: "Pennsylvania" },
  { fips: "44", abbr: "RI", name: "Rhode Island" },
  { fips: "45", abbr: "SC", name: "South Carolina" },
  { fips: "46", abbr: "SD", name: "South Dakota" },
  { fips: "47", abbr: "TN", name: "Tennessee" },
  { fips: "48", abbr: "TX", name: "Texas" },
  { fips: "49", abbr: "UT", name: "Utah" },
  { fips: "50", abbr: "VT", name: "Vermont" },
  { fips: "51", abbr: "VA", name: "Virginia" },
  { fips: "53", abbr: "WA", name: "Washington" },
  { fips: "54", abbr: "WV", name: "West Virginia" },
  { fips: "55", abbr: "WI", name: "Wisconsin" },
  { fips: "56", abbr: "WY", name: "Wyoming" },
];

const STATE_BY_FIPS = new Map(SVI_STATES.map((item) => [item.fips, item]));
const STATE_BY_ABBR = new Map(SVI_STATES.map((item) => [item.abbr, item]));
const EXTRA_STATE_ABBR = { "72": "PR", "60": "AS", "66": "GU", "69": "MP", "78": "VI" };

export function sviStateByFips(fips) {
  return STATE_BY_FIPS.get(String(fips || "").trim().padStart(2, "0")) || null;
}

export function normalizeSviStateParam(raw) {
  const token = String(raw || "").trim();
  if (!token) return "";
  if (/^\d{1,2}$/.test(token)) {
    const padded = token.padStart(2, "0");
    return STATE_BY_FIPS.has(padded) ? padded : "";
  }
  const byAbbr = STATE_BY_ABBR.get(token.toUpperCase());
  return byAbbr ? byAbbr.fips : "";
}

export function sviStateAbbrForGeoid(geoid) {
  const prefix = String(geoid || "").slice(0, 2);
  return STATE_BY_FIPS.get(prefix)?.abbr || EXTRA_STATE_ABBR[prefix] || "";
}

export function sviCountyHeading(name, geoid) {
  const clean = String(name || "").trim();
  const abbr = sviStateAbbrForGeoid(geoid);
  if (!clean) return abbr || "";
  const formattedCounty = String(geoid || "").startsWith("11")
    || /District of Columbia|County|Parish|Borough|Planning Region|Municipality|Census Area|City|Area$/i.test(clean)
    ? clean
    : `${clean} County`;
  return abbr ? `${formattedCounty}, ${abbr}` : formattedCounty;
}

export function sviBaseMeasureId(measureId) {
  return String(measureId || "rpl_themes").replace(/_state$/, "");
}

export function sviThemeForMeasure(measureId) {
  const base = sviBaseMeasureId(measureId);
  return SVI_THEMES.find((item) => item.baseId === base) || SVI_THEMES[0];
}

export function sviPanelRankTitle(measureId, scope = "us") {
  const theme = sviThemeForMeasure(measureId);
  const scopeLabel = scope === "state" ? "Statewide" : "National";
  return theme.isOverall
    ? `2022 ${scopeLabel} Overall SVI Rank`
    : `2022 ${scopeLabel} ${theme.title} Theme Rank`;
}

export function sviIsMissing(value, status) {
  if (status === "not_available" || status === "not_in_release") return true;
  if (value == null || value === "") return true;
  const num = Number(value);
  return !Number.isFinite(num) || num < 0 || num > 1;
}

// A value on a boundary belongs to the lower class: 0.25 -> Low, 0.50 -> Low-Medium, 0.75 -> Medium-High.
export function sviLevelIndex(value, status) {
  if (sviIsMissing(value, status)) return -1;
  const num = Number(value);
  if (num <= 0.25) return 0;
  if (num <= 0.5) return 1;
  if (num <= 0.75) return 2;
  return 3;
}

export function sviLevel(value, status) {
  const index = sviLevelIndex(value, status);
  return index >= 0 ? SVI_LEVELS[index] : null;
}

const sviValueFormatter = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

export function sviFormatValue(value) {
  if (value == null || value === "") return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  return sviValueFormatter.format(num);
}

export function sviPaletteColor(value, status, measureId = "rpl_themes") {
  const index = sviLevelIndex(value, status);
  if (index < 0) return SVI_NO_DATA_COLOR;
  return sviThemeForMeasure(measureId).palette[index];
}

const TICKS = [
  { label: "0", x: 10 },
  { label: "0.25", x: 65 },
  { label: "0.50", x: 120 },
  { label: "0.75", x: 175 },
  { label: "1", x: 230 },
];

export default function SviQuartileBar({ value, status, measureId = "rpl_themes", className = "" }) {
  if (sviIsMissing(value, status)) return null;
  const num = Math.max(0, Math.min(1, Number(value)));
  const theme = sviThemeForMeasure(measureId);
  const level = sviLevel(num, status);
  const formatted = sviFormatValue(num);
  const barX = 10;
  const barY = 6;
  const barW = 220;
  const barH = 14;
  const bandW = barW / 4;
  const dotX = barX + num * barW;
  const dotY = barY + barH / 2;
  const ariaLabel = `Rank ${formatted} of 1, ${level.phrase} vulnerability`;

  return (
    <svg
      className={`svi-quartile-bar ${className}`.trim()}
      viewBox="0 0 240 42"
      role="img"
      aria-label={ariaLabel}
      style={{ width: "100%", height: "auto", display: "block", overflow: "visible" }}
    >
      {theme.palette.map((fill, index) => (
        <rect
          key={SVI_LEVELS[index].key}
          x={barX + index * bandW}
          y={barY}
          width={bandW}
          height={barH}
          fill={fill}
          stroke="#555555"
          strokeWidth="0.75"
        />
      ))}
      <rect
        x={barX}
        y={barY}
        width={barW}
        height={barH}
        fill="none"
        stroke="#555555"
        strokeWidth="1"
      />
      {TICKS.map((tick) => (
        <g key={tick.label}>
          <line x1={tick.x} y1={barY + barH} x2={tick.x} y2={barY + barH + 3} stroke="#555555" strokeWidth="1" />
          <text
            x={tick.x}
            y={35}
            textAnchor="middle"
            fontSize="10"
            fill="#334e5e"
            fontFamily="Arial, sans-serif"
          >
            {tick.label}
          </text>
        </g>
      ))}
      <circle
        cx={dotX}
        cy={dotY}
        r={5}
        fill="#000000"
        stroke="#ffffff"
        strokeWidth="1.25"
        data-testid="svi-quartile-dot"
        data-pct={(num * 100).toFixed(2)}
      />
    </svg>
  );
}
