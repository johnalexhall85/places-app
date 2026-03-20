import {
  CDC_DEFAULT_FUNDING_MODE,
  normalizeCdcFundingMode,
} from "./cdcFundingMode";

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
  const selectedFundingProfile = selected?.funding_profile && typeof selected.funding_profile === "object"
    ? selected.funding_profile
    : null;
  const selectedGeoLevel = String(
    firstDefined(selected?.geo_level, selected?.level, selectedFundingProfile?.geography_type, "")
  ).trim().toLowerCase();
  const fromSelection = normalizeStateCode(
    selectedGeoLevel === "state"
      ? firstDefined(
        selected?.state_abbr,
        selected?.state_code,
        selectedFundingProfile?.state_code,
        selected?.id,
        selected?.location_id,
        selected?.locationid,
        selectedFundingProfile?.geography_id,
        ""
      )
      : firstDefined(
        selected?.state_abbr,
        selected?.state_code,
        selectedFundingProfile?.state_code,
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
  fiscalYear,
  metric = "total_funding",
  fundingType = "total_cdc_funding",
  fundingMode = CDC_DEFAULT_FUNDING_MODE,
  cdcCenter,
  programArea,
  mechanism,
  recipientType,
  timeAggregation,
  geographyLevel,
} = {}) {
  const normalizedStateCode = normalizeStateCode(stateCode);
  if (!normalizedStateCode) return null;
  if (String(geographyLevel ?? "").trim().toLowerCase() === "national") {
    return null;
  }
  const params = new URLSearchParams();
  params.set("metric", String(metric || "total_funding"));
  params.set("funding_type", String(fundingType || "total_cdc_funding"));
  params.set("mode", normalizeCdcFundingMode(fundingMode));
  if (Number.isFinite(Number(fiscalYear))) {
    params.set("fy", String(Number(fiscalYear)));
  }
  if (String(cdcCenter ?? "").trim()) {
    params.set("cdc_center", String(cdcCenter).trim());
  }
  if (String(programArea ?? "").trim()) {
    params.set("program_area", String(programArea).trim());
  }
  if (String(mechanism ?? "").trim()) {
    params.set("mechanism", String(mechanism).trim());
  }
  if (String(recipientType ?? "").trim()) {
    params.set("recipient_type", String(recipientType).trim());
  }
  if (String(timeAggregation ?? "").trim()) {
    params.set("time_aggregation", String(timeAggregation).trim());
  }
  return `/cdc-funding/state/${encodeURIComponent(normalizedStateCode)}?${params.toString()}`;
}

export function resolveCdcFundingProfileTarget({
  selectedFeatureProps,
  stateFilter,
  fiscalYear,
  metric = "total_funding",
  fundingType = "total_cdc_funding",
  fundingMode = CDC_DEFAULT_FUNDING_MODE,
  cdcCenter,
  programArea,
  mechanism,
  recipientType,
  timeAggregation,
  geographyLevel,
} = {}) {
  const stateCode = resolveCdcFundingProfileStateCode({ selectedFeatureProps, stateFilter });
  const href = buildCdcFundingProfileHref({
    stateCode,
    fiscalYear,
    metric,
    fundingType,
    fundingMode,
    cdcCenter,
    programArea,
    mechanism,
    recipientType,
    timeAggregation,
    geographyLevel,
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
  return {
    label: "Open County/Tract Profile",
    tooltipEnabled: "Open County/Tract Profile",
    tooltipDisabled: "Select a county or tract first",
  };
}

export function openProfileTargetInNewTab(
  profileTarget,
  openWindow = typeof window !== "undefined" ? window.open : null
) {
  if (!profileTarget?.enabled || !profileTarget?.href || typeof openWindow !== "function") {
    return false;
  }
  openWindow(profileTarget.href, "_blank", "noopener,noreferrer");
  return true;
}
