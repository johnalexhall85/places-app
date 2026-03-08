const DEFAULT_API_BASE = "http://localhost:8000";

async function parseJsonOrThrow(response, fallbackMessage) {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    const detail = body || fallbackMessage;
    throw new Error(detail);
  }
  return response.json();
}

function setIfPresent(url, key, value) {
  if (value === null || value === undefined) return;
  const token = String(value).trim();
  if (!token) return;
  url.searchParams.set(key, token);
}

export async function fetchCdcFundingFilters({
  apiBase = DEFAULT_API_BASE,
  basis = "all",
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/cdc/funding/filters`);
  url.searchParams.set("basis", String(basis));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding filters.");
}

export async function fetchCdcFundingMap({
  apiBase = DEFAULT_API_BASE,
  basis = "prime",
  geography = "county",
  funding_geography_mode = "recipient_location",
  appropriation_type = "all",
  metric = "fy_obligated",
  display_mode = "total",
  assistance_type,
  fiscal_year,
  awarding_office,
  funding_office,
  office,
  center,
  state,
  bbox,
  zoom,
  limit = 7000,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/cdc/funding/map`);
  url.searchParams.set("basis", String(basis));
  url.searchParams.set("geography", String(geography));
  url.searchParams.set("funding_geography_mode", String(funding_geography_mode));
  url.searchParams.set("appropriation_type", String(appropriation_type));
  url.searchParams.set("metric", String(metric));
  url.searchParams.set("display_mode", String(display_mode));
  setIfPresent(url, "assistance_type", assistance_type);
  if (Number.isFinite(Number(fiscal_year))) {
    url.searchParams.set("fiscal_year", String(Number(fiscal_year)));
  }
  setIfPresent(url, "awarding_office", awarding_office);
  setIfPresent(url, "funding_office", funding_office);
  setIfPresent(url, "office", office);
  setIfPresent(url, "center", center);
  setIfPresent(url, "state", state);
  setIfPresent(url, "bbox", bbox);
  if (Number.isFinite(Number(zoom))) {
    url.searchParams.set("zoom", String(Number(zoom)));
  }
  url.searchParams.set("limit", String(limit));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding map.");
}

export async function fetchCdcFundingLegend({
  apiBase = DEFAULT_API_BASE,
  basis = "prime",
  geography = "county",
  funding_geography_mode = "recipient_location",
  appropriation_type = "all",
  metric = "fy_obligated",
  display_mode = "total",
  assistance_type,
  fiscal_year,
  awarding_office,
  funding_office,
  office,
  center,
  state,
  bbox,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/cdc/funding/legend`);
  url.searchParams.set("basis", String(basis));
  url.searchParams.set("geography", String(geography));
  url.searchParams.set("funding_geography_mode", String(funding_geography_mode));
  url.searchParams.set("appropriation_type", String(appropriation_type));
  url.searchParams.set("metric", String(metric));
  url.searchParams.set("display_mode", String(display_mode));
  setIfPresent(url, "assistance_type", assistance_type);
  if (Number.isFinite(Number(fiscal_year))) {
    url.searchParams.set("fiscal_year", String(Number(fiscal_year)));
  }
  setIfPresent(url, "awarding_office", awarding_office);
  setIfPresent(url, "funding_office", funding_office);
  setIfPresent(url, "office", office);
  setIfPresent(url, "center", center);
  setIfPresent(url, "state", state);
  setIfPresent(url, "bbox", bbox);
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding legend.");
}

export async function fetchCdcFundingNational({
  apiBase = DEFAULT_API_BASE,
  basis = "prime",
  funding_geography_mode = "recipient_location",
  appropriation_type = "all",
  metric = "fy_obligated",
  display_mode = "total",
  assistance_type,
  fiscal_year,
  awarding_office,
  funding_office,
  office,
  center,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/cdc/funding/national`);
  url.searchParams.set("basis", String(basis));
  url.searchParams.set("funding_geography_mode", String(funding_geography_mode));
  url.searchParams.set("appropriation_type", String(appropriation_type));
  url.searchParams.set("metric", String(metric));
  url.searchParams.set("display_mode", String(display_mode));
  setIfPresent(url, "assistance_type", assistance_type);
  if (Number.isFinite(Number(fiscal_year))) {
    url.searchParams.set("fiscal_year", String(Number(fiscal_year)));
  }
  setIfPresent(url, "awarding_office", awarding_office);
  setIfPresent(url, "funding_office", funding_office);
  setIfPresent(url, "office", office);
  setIfPresent(url, "center", center);
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC national summary.");
}

export async function searchCdcFunding({
  apiBase = DEFAULT_API_BASE,
  q,
  basis = "prime",
  funding_geography_mode = "recipient_location",
  appropriation_type = "all",
  assistance_type,
  fiscal_year,
  awarding_office,
  funding_office,
  funding_cio,
  center,
  state,
  selected_state_code,
  selected_state_name,
  selected_county_fips,
  selected_county_name,
  page = 1,
  page_size = 25,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/cdc/funding/search`);
  setIfPresent(url, "q", q);
  url.searchParams.set("basis", String(basis));
  url.searchParams.set("funding_geography_mode", String(funding_geography_mode));
  url.searchParams.set("appropriation_type", String(appropriation_type));
  setIfPresent(url, "assistance_type", assistance_type);
  if (Number.isFinite(Number(fiscal_year))) {
    url.searchParams.set("fiscal_year", String(Number(fiscal_year)));
  }
  setIfPresent(url, "awarding_office", awarding_office);
  setIfPresent(url, "funding_office", funding_office);
  setIfPresent(url, "funding_cio", funding_cio);
  setIfPresent(url, "center", center);
  setIfPresent(url, "state", state);
  setIfPresent(url, "selected_state_code", selected_state_code);
  setIfPresent(url, "selected_state_name", selected_state_name);
  setIfPresent(url, "selected_county_fips", selected_county_fips);
  setIfPresent(url, "selected_county_name", selected_county_name);
  url.searchParams.set("page", String(page));
  url.searchParams.set("page_size", String(page_size));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to search CDC funding.");
}

export async function fetchCdcFundingDetail({
  apiBase = DEFAULT_API_BASE,
  prime_unique_key,
  subaward_id,
  fiscal_year,
  funding_geography_mode = "recipient_location",
  appropriation_type = "all",
  selected_county_fips,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/cdc/funding/detail`);
  setIfPresent(url, "prime_unique_key", prime_unique_key);
  if (Number.isFinite(Number(subaward_id))) {
    url.searchParams.set("subaward_id", String(Number(subaward_id)));
  }
  if (Number.isFinite(Number(fiscal_year))) {
    url.searchParams.set("fiscal_year", String(Number(fiscal_year)));
  }
  url.searchParams.set("funding_geography_mode", String(funding_geography_mode));
  url.searchParams.set("appropriation_type", String(appropriation_type));
  setIfPresent(url, "selected_county_fips", selected_county_fips);
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding detail.");
}

export async function fetchCdcFundingTop({
  apiBase = DEFAULT_API_BASE,
  basis = "prime",
  geography = "county",
  funding_geography_mode = "recipient_location",
  appropriation_type = "all",
  geography_id,
  metric = "fy_obligated",
  assistance_type,
  fiscal_year,
  awarding_office,
  funding_office,
  office,
  center,
  limit = 5,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/cdc/funding/top`);
  url.searchParams.set("basis", String(basis));
  url.searchParams.set("geography", String(geography));
  url.searchParams.set("funding_geography_mode", String(funding_geography_mode));
  url.searchParams.set("appropriation_type", String(appropriation_type));
  setIfPresent(url, "geography_id", geography_id);
  url.searchParams.set("metric", String(metric));
  setIfPresent(url, "assistance_type", assistance_type);
  if (Number.isFinite(Number(fiscal_year))) {
    url.searchParams.set("fiscal_year", String(Number(fiscal_year)));
  }
  setIfPresent(url, "awarding_office", awarding_office);
  setIfPresent(url, "funding_office", funding_office);
  setIfPresent(url, "office", office);
  setIfPresent(url, "center", center);
  url.searchParams.set("limit", String(limit));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC top awards.");
}

export async function fetchCdcFundingTrend({
  apiBase = DEFAULT_API_BASE,
  basis = "prime",
  geography_type = "county",
  geography_id,
  funding_geography_mode = "recipient_location",
  appropriation_type = "all",
  metric = "fy_obligated",
  assistance_type,
  awarding_office,
  funding_office,
  funding_cio,
  office,
  center,
  state,
  start_fy,
  end_fy,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/cdc/funding/trend`);
  url.searchParams.set("basis", String(basis));
  url.searchParams.set("geography_type", String(geography_type));
  setIfPresent(url, "geography_id", geography_id);
  url.searchParams.set("funding_geography_mode", String(funding_geography_mode));
  url.searchParams.set("appropriation_type", String(appropriation_type));
  url.searchParams.set("metric", String(metric));
  setIfPresent(url, "assistance_type", assistance_type);
  setIfPresent(url, "awarding_office", awarding_office);
  setIfPresent(url, "funding_office", funding_office);
  setIfPresent(url, "funding_cio", funding_cio);
  setIfPresent(url, "office", office);
  setIfPresent(url, "center", center);
  setIfPresent(url, "state", state);
  if (Number.isFinite(Number(start_fy))) {
    url.searchParams.set("start_fy", String(Number(start_fy)));
  }
  if (Number.isFinite(Number(end_fy))) {
    url.searchParams.set("end_fy", String(Number(end_fy)));
  }
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding trend.");
}
