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
  metric = "total_funding",
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
  url.searchParams.set("metric", String(metric));
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
  metric = "total_funding",
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
  url.searchParams.set("metric", String(metric));
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

export async function searchCdcFunding({
  apiBase = DEFAULT_API_BASE,
  q,
  basis = "all",
  assistance_type,
  fiscal_year,
  state,
  page = 1,
  page_size = 25,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/cdc/funding/search`);
  setIfPresent(url, "q", q);
  url.searchParams.set("basis", String(basis));
  setIfPresent(url, "assistance_type", assistance_type);
  if (Number.isFinite(Number(fiscal_year))) {
    url.searchParams.set("fiscal_year", String(Number(fiscal_year)));
  }
  setIfPresent(url, "state", state);
  url.searchParams.set("page", String(page));
  url.searchParams.set("page_size", String(page_size));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to search CDC funding.");
}

export async function fetchCdcFundingDetail({
  apiBase = DEFAULT_API_BASE,
  prime_unique_key,
  subaward_id,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/cdc/funding/detail`);
  setIfPresent(url, "prime_unique_key", prime_unique_key);
  if (Number.isFinite(Number(subaward_id))) {
    url.searchParams.set("subaward_id", String(Number(subaward_id)));
  }
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding detail.");
}

export async function fetchCdcFundingTop({
  apiBase = DEFAULT_API_BASE,
  basis = "prime",
  geography = "county",
  geography_id,
  metric = "total_funding",
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
