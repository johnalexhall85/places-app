export const CDC_FUNDING_MODES = {
  RAW_TOTAL: "raw_total",
  CHIP_NORMALIZED: "chip_normalized",
  CHIP_NORMALIZED_V11: "chip_normalized_v1_1",
};

export const CDC_GEOGRAPHY_LEVELS = {
  NATIONAL: "national",
  STATE: "state",
  COUNTY: "county",
};

export const CDC_DEFAULT_FUNDING_MODE = CDC_FUNDING_MODES.CHIP_NORMALIZED_V11;
export const CDC_DEFAULT_GEOGRAPHY_LEVEL = CDC_GEOGRAPHY_LEVELS.STATE;

export const CDC_FUNDING_MODE_LABELS = {
  [CDC_FUNDING_MODES.RAW_TOTAL]: "Raw total funding",
  [CDC_FUNDING_MODES.CHIP_NORMALIZED]: "CHIP Normalized Funding (Legacy)",
  [CDC_FUNDING_MODES.CHIP_NORMALIZED_V11]: "CHIP Normalized Funding v1.1",
};

export function isNormalizedCdcFundingMode(value) {
  const token = String(value ?? "").trim().toLowerCase();
  return (
    token === CDC_FUNDING_MODES.CHIP_NORMALIZED
    || token === CDC_FUNDING_MODES.CHIP_NORMALIZED_V11
  );
}

export function normalizeCdcFundingMode(value) {
  const token = String(value ?? "").trim().toLowerCase();
  if (token === CDC_FUNDING_MODES.RAW_TOTAL) {
    return CDC_FUNDING_MODES.RAW_TOTAL;
  }
  if (token === CDC_FUNDING_MODES.CHIP_NORMALIZED) {
    return CDC_FUNDING_MODES.CHIP_NORMALIZED;
  }
  if (token === CDC_FUNDING_MODES.CHIP_NORMALIZED_V11) {
    return CDC_FUNDING_MODES.CHIP_NORMALIZED_V11;
  }
  return CDC_DEFAULT_FUNDING_MODE;
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
