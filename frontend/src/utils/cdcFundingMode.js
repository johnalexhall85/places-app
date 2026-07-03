export const CDC_FUNDING_MODES = {
  CHIP_ACCOUNT_CLASSIFICATION_V1: "chip_account_classification_v1",
  CHIP_LEGACY: "chip_legacy",
  CANONICAL_V1: "canonical_v1",
  RAW_TOTAL: "raw_total",
  CHIP_NORMALIZED: "chip_normalized",
  CHIP_NORMALIZED_V11: "chip_normalized_v1_1",
  BUDGET_GROUNDED_V1: "budget_grounded_v1",
};

export const CDC_GEOGRAPHY_LEVELS = {
  NATIONAL: "national",
  STATE: "state",
  COUNTY: "county",
};

export const CDC_DEFAULT_FUNDING_MODE = CDC_FUNDING_MODES.CHIP_ACCOUNT_CLASSIFICATION_V1;
export const CDC_DEFAULT_GEOGRAPHY_LEVEL = CDC_GEOGRAPHY_LEVELS.STATE;
export const CDC_DEFAULT_BUDGET_GROUNDED_REVIEW_MODE = "all_master_universe";
export const CDC_DEFAULT_CANONICAL_REVIEW_MODE = CDC_DEFAULT_BUDGET_GROUNDED_REVIEW_MODE;
export const CDC_STATE_LAYER_MAX_ZOOM = 5;

export const CDC_FUNDING_MODE_LABELS = {
  [CDC_FUNDING_MODES.CHIP_ACCOUNT_CLASSIFICATION_V1]: "CHIP Account Classification v1",
  [CDC_FUNDING_MODES.CHIP_LEGACY]: "CHIP Legacy",
  [CDC_FUNDING_MODES.CANONICAL_V1]: "Canonical CDC Funding",
  [CDC_FUNDING_MODES.RAW_TOTAL]: "Raw total funding",
  [CDC_FUNDING_MODES.CHIP_NORMALIZED]: "CHIP Normalized Funding (Legacy)",
  [CDC_FUNDING_MODES.CHIP_NORMALIZED_V11]: "CHIP Normalized Funding v1.1",
  [CDC_FUNDING_MODES.BUDGET_GROUNDED_V1]: "Budget-grounded funding",
};

export const CDC_VISIBLE_FUNDING_MODE_VALUES = [
  CDC_FUNDING_MODES.CHIP_ACCOUNT_CLASSIFICATION_V1,
  CDC_FUNDING_MODES.CHIP_LEGACY,
];

const CUSTOM_FUNDING_MODE_RE = /^[a-z][a-z0-9_]*$/;

export function isNormalizedCdcFundingMode(value) {
  const token = String(value ?? "").trim().toLowerCase();
  return (
    token === CDC_FUNDING_MODES.CHIP_NORMALIZED
    || token === CDC_FUNDING_MODES.CHIP_NORMALIZED_V11
  );
}

export function isCanonicalCdcFundingMode(value) {
  const token = String(value ?? "").trim().toLowerCase();
  return token === CDC_FUNDING_MODES.CANONICAL_V1;
}

export function isBudgetGroundedCdcFundingMode(value) {
  const token = String(value ?? "").trim().toLowerCase();
  return token === CDC_FUNDING_MODES.BUDGET_GROUNDED_V1;
}

export function isChipAccountClassificationCdcFundingMode(value) {
  const token = String(value ?? "").trim().toLowerCase();
  return token === CDC_FUNDING_MODES.CHIP_ACCOUNT_CLASSIFICATION_V1;
}

export function isVisibleCdcFundingMode(value) {
  const token = String(value ?? "").trim().toLowerCase();
  return CDC_VISIBLE_FUNDING_MODE_VALUES.includes(token);
}

export function normalizeCdcFundingMode(value) {
  const token = String(value ?? "").trim().toLowerCase();
  if (token === CDC_FUNDING_MODES.CHIP_ACCOUNT_CLASSIFICATION_V1) {
    return CDC_FUNDING_MODES.CHIP_ACCOUNT_CLASSIFICATION_V1;
  }
  if (token === CDC_FUNDING_MODES.CHIP_LEGACY) {
    return CDC_FUNDING_MODES.CHIP_LEGACY;
  }
  if (token === CDC_FUNDING_MODES.CANONICAL_V1) {
    return CDC_FUNDING_MODES.CANONICAL_V1;
  }
  if (token === CDC_FUNDING_MODES.RAW_TOTAL) {
    return CDC_FUNDING_MODES.RAW_TOTAL;
  }
  if (token === CDC_FUNDING_MODES.CHIP_NORMALIZED) {
    return CDC_FUNDING_MODES.CHIP_NORMALIZED;
  }
  if (token === CDC_FUNDING_MODES.CHIP_NORMALIZED_V11) {
    return CDC_FUNDING_MODES.CHIP_NORMALIZED_V11;
  }
  if (token === CDC_FUNDING_MODES.BUDGET_GROUNDED_V1) {
    return CDC_FUNDING_MODES.BUDGET_GROUNDED_V1;
  }
  if (CUSTOM_FUNDING_MODE_RE.test(token)) {
    return token;
  }
  return CDC_DEFAULT_FUNDING_MODE;
}

export function getCdcFundingModeLabel(value, options = []) {
  const normalized = normalizeCdcFundingMode(value);
  const staticLabel = CDC_FUNDING_MODE_LABELS[normalized];
  if (staticLabel) return staticLabel;
  const optionLabel = (Array.isArray(options) ? options : [])
    .find((option) => String(option?.value ?? "").trim().toLowerCase() === normalized)?.label;
  if (optionLabel) return String(optionLabel);
  return normalized
    .split("_")
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export function normalizeCdcFundingGeographyLevel(value) {
  const token = String(value ?? "").trim().toLowerCase();
  if (token === CDC_GEOGRAPHY_LEVELS.NATIONAL) {
    return CDC_GEOGRAPHY_LEVELS.NATIONAL;
  }
  if (token === CDC_GEOGRAPHY_LEVELS.COUNTY) {
    return CDC_GEOGRAPHY_LEVELS.COUNTY;
  }
  return CDC_DEFAULT_GEOGRAPHY_LEVEL;
}

export function normalizeCdcFiscalYearToken(value, { allowAll = false } = {}) {
  const token = String(value ?? "").trim().toLowerCase();
  if (!token) return "";
  if (allowAll && token === "all") return "all";
  const numeric = Number(token);
  if (!Number.isInteger(numeric) || numeric <= 0) {
    return "";
  }
  return String(numeric);
}

export function resolveCdcFiscalYearSelection({
  selectedValue,
  defaultValue,
  availableValues = [],
} = {}) {
  const normalizedAvailable = Array.from(
    new Set(
      (Array.isArray(availableValues) ? availableValues : [])
        .map((value) => normalizeCdcFiscalYearToken(value, { allowAll: true }))
        .filter(Boolean)
    )
  );
  const normalizedSelected = normalizeCdcFiscalYearToken(selectedValue, { allowAll: true });
  if (normalizedSelected && normalizedAvailable.includes(normalizedSelected)) {
    return normalizedSelected;
  }
  const actualYears = normalizedAvailable.filter((value) => value !== "all");
  const normalizedDefault = normalizeCdcFiscalYearToken(defaultValue);
  if (normalizedDefault && actualYears.includes(normalizedDefault)) {
    return normalizedDefault;
  }
  return actualYears[0] ?? (normalizedAvailable.includes("all") ? "all" : "");
}

export function resolveCdcRequestGeographyLevel(geographyLevel, mapZoom) {
  const normalizedLevel = normalizeCdcFundingGeographyLevel(geographyLevel);
  if (normalizedLevel !== CDC_GEOGRAPHY_LEVELS.COUNTY) {
    return normalizedLevel;
  }
  return Number(mapZoom) <= CDC_STATE_LAYER_MAX_ZOOM
    ? CDC_GEOGRAPHY_LEVELS.STATE
    : CDC_GEOGRAPHY_LEVELS.COUNTY;
}

export function readCdcFundingUrlState(search) {
  const params = new URLSearchParams(String(search ?? ""));
  const dataSource = String(params.get("data_source") ?? "").trim().toLowerCase();
  if (dataSource !== "cdc_funding") {
    return null;
  }
  return {
    fundingMode: normalizeCdcFundingMode(params.get("funding_mode")),
    geographyLevel: normalizeCdcFundingGeographyLevel(
      params.get("geography_level") ?? params.get("geography")
    ),
  };
}

export function buildCdcFundingUrlSearch(search, { activeDataSource, fundingMode } = {}) {
  const params = new URLSearchParams(String(search ?? ""));
  if (activeDataSource === "cdc_funding") {
    params.set("data_source", "cdc_funding");
    params.set("funding_mode", normalizeCdcFundingMode(fundingMode));
    return params.toString();
  }
  if (String(params.get("data_source") ?? "").trim().toLowerCase() === "cdc_funding") {
    params.delete("data_source");
    params.delete("funding_mode");
  }
  return params.toString();
}
