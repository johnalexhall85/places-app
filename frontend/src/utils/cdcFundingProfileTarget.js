function normalizeStateCode(value) {
  const letters = String(value ?? "").replace(/[^A-Za-z]/g, "").toUpperCase();
  return letters.length === 2 ? letters : "";
}

function firstDefined(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined) {
      return value;
    }
  }
  return null;
}

export function resolveCdcFundingProfileStateCode({ selectedFeatureProps, stateFilter } = {}) {
  const selected = selectedFeatureProps && typeof selectedFeatureProps === "object"
    ? selectedFeatureProps
    : null;
  const selectedGeoLevel = String(
    firstDefined(selected?.geo_level, selected?.level, "")
  ).trim().toLowerCase();
  const fromSelection = normalizeStateCode(
    selectedGeoLevel === "state"
      ? firstDefined(
        selected?.state_abbr,
        selected?.state_code,
        selected?.id,
        selected?.location_id,
        selected?.locationid,
        ""
      )
      : firstDefined(
        selected?.state_abbr,
        selected?.state_code,
        ""
      )
  );
  if (fromSelection) {
    return fromSelection;
  }
  return normalizeStateCode(stateFilter);
}

export function buildCdcFundingProfileHref({
  stateCode,
  basis = "prime",
  fundingGeographyMode = "recipient_location",
  appropriationType = "all",
  normalized = false,
  assistanceType,
  fiscalYear,
  awardingOffice,
  fundingOffice,
  center,
  metric,
  displayMode,
} = {}) {
  const normalizedStateCode = normalizeStateCode(stateCode);
  if (!normalizedStateCode) return null;
  const params = new URLSearchParams();
  params.set("basis", String(basis || "prime"));
  params.set("funding_geography_mode", String(fundingGeographyMode || "recipient_location"));
  params.set("appropriation_type", String(appropriationType || "all"));
  params.set("normalized", normalized ? "true" : "false");
  if (Number.isFinite(Number(fiscalYear))) {
    params.set("fy", String(Number(fiscalYear)));
  }
  if (String(assistanceType ?? "").trim()) {
    params.set("assistance_type", String(assistanceType).trim());
  }
  if (String(awardingOffice ?? "").trim()) {
    params.set("awarding_office", String(awardingOffice).trim());
  }
  if (String(fundingOffice ?? "").trim()) {
    params.set("funding_office", String(fundingOffice).trim());
  }
  if (String(center ?? "").trim()) {
    params.set("center", String(center).trim());
  }
  if (String(metric ?? "").trim()) {
    params.set("metric", String(metric).trim());
  }
  if (String(displayMode ?? "").trim()) {
    params.set("display_mode", String(displayMode).trim());
  }
  return `/cdc-funding/state/${encodeURIComponent(normalizedStateCode)}?${params.toString()}`;
}

export function resolveCdcFundingProfileTarget({
  selectedFeatureProps,
  stateFilter,
  basis = "prime",
  fundingGeographyMode = "recipient_location",
  appropriationType = "all",
  normalized = false,
  assistanceType,
  fiscalYear,
  awardingOffice,
  fundingOffice,
  center,
  metric,
  displayMode,
} = {}) {
  const stateCode = resolveCdcFundingProfileStateCode({ selectedFeatureProps, stateFilter });
  const href = buildCdcFundingProfileHref({
    stateCode,
    basis,
    fundingGeographyMode,
    appropriationType,
    normalized,
    assistanceType,
    fiscalYear,
    awardingOffice,
    fundingOffice,
    center,
    metric,
    displayMode,
  });
  return {
    enabled: Boolean(href),
    reason: href ? "" : "Select a state first",
    geography: href ? "state" : null,
    id: stateCode || null,
    href,
  };
}

export function getProfileButtonCopy(dataSource) {
  if (dataSource === "cdc_funding") {
    return {
      label: "Open State Funding Profile",
      tooltipEnabled: "Open state CDC funding profile",
      tooltipDisabled: "Select a state first",
    };
  }
  if (dataSource === "taggs") {
    return {
      label: "Open Funding Profile",
      tooltipEnabled: "Open state TAGGS funding profile",
      tooltipDisabled: "Select a state first",
    };
  }
  return {
    label: "Open County/Tract Profile",
    tooltipEnabled: "Open County/Tract Profile",
    tooltipDisabled: "Select a county or tract first",
  };
}
