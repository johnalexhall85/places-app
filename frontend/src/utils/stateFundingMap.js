const STATE_FIPS_TO_CODE = {
  "01": "AL",
  "02": "AK",
  "04": "AZ",
  "05": "AR",
  "06": "CA",
  "08": "CO",
  "09": "CT",
  "10": "DE",
  "11": "DC",
  "12": "FL",
  "13": "GA",
  "15": "HI",
  "16": "ID",
  "17": "IL",
  "18": "IN",
  "19": "IA",
  "20": "KS",
  "21": "KY",
  "22": "LA",
  "23": "ME",
  "24": "MD",
  "25": "MA",
  "26": "MI",
  "27": "MN",
  "28": "MS",
  "29": "MO",
  "30": "MT",
  "31": "NE",
  "32": "NV",
  "33": "NH",
  "34": "NJ",
  "35": "NM",
  "36": "NY",
  "37": "NC",
  "38": "ND",
  "39": "OH",
  "40": "OK",
  "41": "OR",
  "42": "PA",
  "44": "RI",
  "45": "SC",
  "46": "SD",
  "47": "TN",
  "48": "TX",
  "49": "UT",
  "50": "VT",
  "51": "VA",
  "53": "WA",
  "54": "WV",
  "55": "WI",
  "56": "WY",
  "60": "AS",
  "66": "GU",
  "69": "MP",
  "72": "PR",
  "78": "VI",
};

const STATE_CODE_TO_FIPS = Object.entries(STATE_FIPS_TO_CODE).reduce((acc, [fips, code]) => {
  acc[code] = fips;
  return acc;
}, {});

export const STATE_FUNDING_VIEW_MODE_OPTIONS = [
  { value: "standard_usaspending", label: "USAspending Obligations" },
  { value: "funding_profiles_comparable", label: "CDC Funding Profiles Comparable" },
];

export const STATE_FUNDING_SUPPLEMENTAL_HISTORY_FILTER_OPTIONS = [
  { value: "all", label: "All awards" },
  { value: "only_awards_with_supplemental_history", label: "Only awards with supplemental history" },
  { value: "exclude_awards_with_supplemental_history", label: "Exclude awards with supplemental history" },
];

export const STATE_FUNDING_VFC_IMMUNIZATION_BADGE_LABEL = "VFC / Immunization Cooperative Agreement";
export const STATE_FUNDING_COVID_ERA_IMMUNIZATION_BADGE_LABEL = "COVID-era immunization response";
export const STATE_FUNDING_COVID_ERA_IMMUNIZATION_SUMMARY_LABEL = "COVID-era immunization excluded";

export const STATE_FUNDING_METHODOLOGY_NOTES = {
  standard_usaspending: (
    "This mode shows positive prime award obligations from USAspending where the funding agency is HHS and the funding sub-agency is CDC. Awards with supplemental/emergency history and likely VFC are flagged but not automatically excluded."
  ),
  funding_profiles_comparable: (
    "This mode approximates CDC Funding Profiles using public USAspending transaction data. It excludes awards with overall-award COVID/IIJA supplemental amounts, but includes VFC / Immunization Cooperative Agreement obligations when they appear as assistance transactions. FY2021 includes a large COVID-era immunization response block under Assistance Listing 93.268 in USAspending. CHIP excludes that FY2021 COVID-era block from the Funding Profiles Comparable total and reports it separately. Ordinary VFC / Immunization Cooperative Agreement assistance transactions remain included in other years unless separately excluded. Separate VFC vaccine purchase amounts from CDC Funding Profiles are not included in this grants/cooperative-agreement map. State choropleth shading only includes obligations that can be mapped to a U.S. state or territory; unmapped obligations are included in the national total and shown separately."
  ),
};

export function getFundingViewModeLabel(value) {
  const token = String(value ?? "").trim();
  return (
    STATE_FUNDING_VIEW_MODE_OPTIONS.find((option) => option.value === token)?.label
    ?? STATE_FUNDING_VIEW_MODE_OPTIONS[0].label
  );
}

export function getFundingViewModeMethodologyNote(value) {
  const token = String(value ?? "").trim();
  return STATE_FUNDING_METHODOLOGY_NOTES[token] ?? STATE_FUNDING_METHODOLOGY_NOTES.standard_usaspending;
}

function toFiniteNumber(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed.replace(/[$,]/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function quantile(sortedValues, percentile) {
  if (!sortedValues.length) return null;
  const position = (sortedValues.length - 1) * percentile;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sortedValues[lower];
  const weight = position - lower;
  return sortedValues[lower] * (1 - weight) + sortedValues[upper] * weight;
}

export function normalizeStateFips(value) {
  if (value == null) return "";
  const digits = String(value).replace(/[^0-9]/g, "");
  if (!digits) return "";
  if (digits.length === 1) return `0${digits}`;
  if (digits.length === 2) return digits;
  return "";
}

export function normalizeStateCode(value) {
  if (value == null) return "";
  const letters = String(value).replace(/[^A-Za-z]/g, "").toUpperCase();
  return letters.length === 2 ? letters : "";
}

export function getStateCodeForFips(value) {
  const fips = normalizeStateFips(value);
  return fips ? (STATE_FIPS_TO_CODE[fips] ?? "") : "";
}

export function getStateFipsForCode(value) {
  const code = normalizeStateCode(value);
  return code ? (STATE_CODE_TO_FIPS[code] ?? "") : "";
}

export function formatFundingCurrency(value, { compact = false, noDataLabel = "No data" } = {}) {
  const numeric = toFiniteNumber(value);
  if (numeric == null) return noDataLabel;
  if (compact) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      notation: "compact",
      maximumFractionDigits: Math.abs(numeric) >= 1_000_000 ? 1 : 0,
    }).format(numeric);
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(numeric);
}

export function formatFundingCount(value, { noDataLabel = "No data" } = {}) {
  const numeric = toFiniteNumber(value);
  if (numeric == null) return noDataLabel;
  return Math.round(numeric).toLocaleString("en-US");
}

export function buildStateFundingSummaryCards(summary = {}) {
  const covidEraImmunizationExcluded = toFiniteNumber(
    summary?.covid_era_immunization_response_excluded_obligations
  );
  const cards = [
    ["Total including unmapped", summary?.total_obligations_including_unmapped ?? summary?.total_obligations, "currency"],
    ["State-mapped obligations", summary?.state_mapped_obligations ?? summary?.total_obligations, "currency"],
    ["Not mapped to state", summary?.state_unmapped_obligations, "currency"],
    [
      "VFC / Immunization Cooperative Agreements",
      summary?.vfc_immunization_cooperative_agreement_obligations ?? summary?.likely_vfc_obligations,
      "currency",
    ],
    ["Emergency/supplemental excluded", summary?.funding_profiles_excluded_obligations, "currency"],
  ];
  if (covidEraImmunizationExcluded != null && covidEraImmunizationExcluded !== 0) {
    cards.push([
      STATE_FUNDING_COVID_ERA_IMMUNIZATION_SUMMARY_LABEL,
      covidEraImmunizationExcluded,
      "currency",
    ]);
  }
  cards.push(
    ["States", summary?.state_count, "count"],
    ["Awards", summary?.award_count, "count"],
    ["Recipients", summary?.recipient_count, "count"],
    ["Transactions", summary?.transaction_count, "count"],
  );
  return cards;
}

export function buildStateFundingAwardBadges(award = {}) {
  return [
    award?.has_overall_award_supplemental_history ? "Supplemental history" : null,
    award?.is_likely_vfc ? STATE_FUNDING_VFC_IMMUNIZATION_BADGE_LABEL : null,
    award?.is_covid_era_immunization_response ? STATE_FUNDING_COVID_ERA_IMMUNIZATION_BADGE_LABEL : null,
    award?.funding_profiles_comparison_excluded ? "Excluded from Funding Profiles comparable view" : null,
  ].filter(Boolean);
}

function getGeometryStateFips(properties = {}) {
  return normalizeStateFips(
    properties.state_fips
    ?? properties.statefp
    ?? properties.STATEFP
    ?? properties.STATE_FIPS
    ?? properties.fips
    ?? properties.state_code
    ?? properties.state_abbr
  );
}

function getGeometryStateCode(properties = {}) {
  return normalizeStateCode(
    properties.state_code
    ?? properties.state_abbr
    ?? properties.STUSPS
    ?? properties.postal
    ?? properties.abbr
  );
}

function getGeometryStateName(properties = {}) {
  return String(
    properties.state_name
    ?? properties.state_desc
    ?? properties.NAME
    ?? properties.name
    ?? ""
  ).trim();
}

export function joinStateFundingRowsToGeometry(geojson, rows) {
  const rowByFips = new Map();
  const rowByCode = new Map();
  for (const row of Array.isArray(rows) ? rows : []) {
    const stateFips = normalizeStateFips(row?.state_fips);
    const stateCode = normalizeStateCode(row?.state_code) || getStateCodeForFips(stateFips);
    if (stateFips) rowByFips.set(stateFips, row);
    if (stateCode) rowByCode.set(stateCode, row);
  }

  const features = Array.isArray(geojson?.features) ? geojson.features : [];
  return {
    type: "FeatureCollection",
    features: features.map((feature) => {
      const properties = feature?.properties ?? {};
      const geometryFips = getGeometryStateFips(properties);
      const geometryCode = getGeometryStateCode(properties) || getStateCodeForFips(geometryFips);
      const row = (geometryFips && rowByFips.get(geometryFips))
        || (geometryCode && rowByCode.get(geometryCode))
        || null;
      const stateFips = normalizeStateFips(row?.state_fips) || geometryFips || getStateFipsForCode(geometryCode);
      const stateCode = normalizeStateCode(row?.state_code) || geometryCode || getStateCodeForFips(stateFips);
      const stateName = String(row?.state_name ?? "").trim() || getGeometryStateName(properties) || stateCode;
      const totalObligations = toFiniteNumber(row?.total_obligations);
      return {
        ...feature,
        properties: {
          ...properties,
          source: "funding_state",
          geo_level: "state",
          level: "state",
          state_fips: stateFips || null,
          state_code: stateCode || null,
          state_abbr: stateCode || null,
          state_name: stateName,
          name: stateName,
          value: totalObligations,
          metric_value: totalObligations,
          data_value: totalObligations,
          metric: "total_obligations",
          metric_label: "Total obligations",
          total_obligations: totalObligations,
          transaction_count: toFiniteNumber(row?.transaction_count),
          award_count: toFiniteNumber(row?.award_count),
          recipient_count: toFiniteNumber(row?.recipient_count),
          obligations_from_awards_with_supplemental_history: toFiniteNumber(
            row?.obligations_from_awards_with_supplemental_history
          ),
          likely_vfc_obligations: toFiniteNumber(row?.likely_vfc_obligations),
          funding_profiles_excluded_obligations: toFiniteNumber(row?.funding_profiles_excluded_obligations),
          funding_row_present: Boolean(row),
        },
      };
    }),
  };
}

export function buildFundingLegendBins(rows, binCount = 5) {
  const values = (Array.isArray(rows) ? rows : [])
    .map((row) => toFiniteNumber(row?.total_obligations ?? row?.value))
    .filter((value) => value != null)
    .sort((left, right) => left - right);
  if (values.length === 0) return [];
  const breaks = [];
  for (let index = 0; index <= binCount; index += 1) {
    breaks.push(quantile(values, index / binCount));
  }
  const deduped = [breaks[0]];
  for (let index = 1; index < breaks.length; index += 1) {
    if (breaks[index] > deduped[deduped.length - 1]) {
      deduped.push(breaks[index]);
    }
  }
  if (deduped.length < 2) deduped.push(deduped[0]);
  return deduped.slice(0, -1).map((min, index) => {
    const max = deduped[index + 1];
    return {
      min,
      max,
      colorIndex: index,
      label: `${formatFundingCurrency(min, { compact: true })} - ${formatFundingCurrency(max, { compact: true })}`,
    };
  });
}

export function getFundingMechanismLabel(value) {
  const token = String(value ?? "").trim();
  if (token === "contracts") return "Contracts";
  if (token === "all") return "All Funding Mechanisms";
  return "Grants & Cooperative Agreements";
}

export function getFundingFiscalYearLabel(value) {
  const token = String(value ?? "").trim();
  return token ? `FY${token}` : "Latest fiscal year";
}
