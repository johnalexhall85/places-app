import { API_BASE as DEFAULT_API_BASE } from "../config/apiBase";
import {
  CDC_DEFAULT_FUNDING_MODE,
  CDC_DEFAULT_GEOGRAPHY_LEVEL,
} from "../utils/cdcFundingMode";

const CDC_DEFAULT_FISCAL_YEAR = 2023;
const CDC_DEFAULT_CHIP_V1_SCOPE_PARAMS = {
  funding_scope_preset: "regular_grants_coops",
  award_type: "grants_coops",
  emergency_supplemental_scope: "exclude",
  review_status: "reviewed_plus_needs_review",
  include_pphf: true,
  transfers_scope: "cdc_relevant_only",
  data_source_scope: "combined",
};

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

function setBoolIfPresent(url, key, value) {
  if (value === null || value === undefined) return;
  url.searchParams.set(key, value ? "true" : "false");
}

function setCdcScopeParams(url, {
  funding_scope_preset,
  award_type,
  emergency_supplemental_scope,
  review_status,
  include_pphf,
  transfers_scope,
  data_source_scope,
} = {}) {
  setIfPresent(url, "funding_scope_preset", funding_scope_preset);
  setIfPresent(url, "award_type", award_type);
  setIfPresent(url, "emergency_supplemental_scope", emergency_supplemental_scope);
  setIfPresent(url, "review_status", review_status);
  setBoolIfPresent(url, "include_pphf", include_pphf);
  setIfPresent(url, "transfers_scope", transfers_scope);
  setIfPresent(url, "data_source_scope", data_source_scope);
}

function resolveChipV1ScopeParams({
  funding_mode,
  fiscal_year,
  funding_scope_preset,
  award_type,
  emergency_supplemental_scope,
  review_status,
  include_pphf,
  transfers_scope,
  data_source_scope,
} = {}) {
  const normalizedMode = String(funding_mode ?? CDC_DEFAULT_FUNDING_MODE).trim().toLowerCase();
  if (normalizedMode !== CDC_DEFAULT_FUNDING_MODE) {
    return {
      fiscal_year,
      funding_scope_preset,
      award_type,
      emergency_supplemental_scope,
      review_status,
      include_pphf,
      transfers_scope,
      data_source_scope,
    };
  }
  return {
    fiscal_year: fiscal_year ?? CDC_DEFAULT_FISCAL_YEAR,
    funding_scope_preset: funding_scope_preset ?? CDC_DEFAULT_CHIP_V1_SCOPE_PARAMS.funding_scope_preset,
    award_type: award_type ?? CDC_DEFAULT_CHIP_V1_SCOPE_PARAMS.award_type,
    emergency_supplemental_scope: (
      emergency_supplemental_scope ?? CDC_DEFAULT_CHIP_V1_SCOPE_PARAMS.emergency_supplemental_scope
    ),
    review_status: review_status ?? CDC_DEFAULT_CHIP_V1_SCOPE_PARAMS.review_status,
    include_pphf: include_pphf ?? CDC_DEFAULT_CHIP_V1_SCOPE_PARAMS.include_pphf,
    transfers_scope: transfers_scope ?? CDC_DEFAULT_CHIP_V1_SCOPE_PARAMS.transfers_scope,
    data_source_scope: data_source_scope ?? CDC_DEFAULT_CHIP_V1_SCOPE_PARAMS.data_source_scope,
  };
}

function resolveIncludePendingReview(fundingMode, includePendingReview) {
  if (includePendingReview !== null && includePendingReview !== undefined) {
    return includePendingReview;
  }
  const normalizedMode = String(fundingMode ?? CDC_DEFAULT_FUNDING_MODE).trim().toLowerCase();
  return normalizedMode === CDC_DEFAULT_FUNDING_MODE ? true : null;
}

function setFiscalYearIfPresent(url, fiscalYear) {
  if (fiscalYear === null || fiscalYear === undefined) return;
  const token = String(fiscalYear).trim();
  if (!token) return;
  const numeric = Number(token);
  if (!Number.isInteger(numeric) || numeric <= 0) return;
  url.searchParams.set("fiscal_year", String(numeric));
}

function buildCdcApiUrl(apiBase, path) {
  const base = String(apiBase ?? DEFAULT_API_BASE).trim().replace(/\/+$/, "");
  const normalizedPath = `/${String(path ?? "").trim().replace(/^\/+/, "")}`;
  const effectiveBase = /\/api$/i.test(base) && normalizedPath.startsWith("/api/")
    ? base.slice(0, -4)
    : base;
  return new URL(`${effectiveBase}${normalizedPath}`);
}

function buildCdcFundingProfileUrl({
  apiBase = DEFAULT_API_BASE,
  endpoint,
  state,
  fiscal_year,
  metric = "total_funding",
  funding_type = "total_cdc_funding",
  funding_mode = CDC_DEFAULT_FUNDING_MODE,
  cdc_center,
  program_area,
  mechanism,
  recipient_type,
  time_aggregation,
  include_mandatory,
  include_emergency,
  include_supplemental,
  include_pphf,
  include_transfers,
  include_pending_review,
  review_mode,
  funding_scope_preset,
  award_type,
  emergency_supplemental_scope,
  review_status,
  transfers_scope,
  data_source_scope,
}) {
  const url = buildCdcApiUrl(apiBase, `/api/cdc/funding/profile/${endpoint}`);
  const scopeParams = resolveChipV1ScopeParams({
    funding_mode,
    fiscal_year,
    funding_scope_preset,
    award_type,
    emergency_supplemental_scope,
    review_status,
    include_pphf,
    transfers_scope,
    data_source_scope,
  });
  url.searchParams.set("state", String(state ?? "").trim().toUpperCase());
  url.searchParams.set("metric", String(metric));
  url.searchParams.set("funding_type", String(funding_type));
  url.searchParams.set("funding_mode", String(funding_mode));
  setFiscalYearIfPresent(url, scopeParams.fiscal_year);
  setIfPresent(url, "cdc_center", cdc_center);
  setIfPresent(url, "program_area", program_area);
  setIfPresent(url, "mechanism", mechanism);
  setIfPresent(url, "recipient_type", recipient_type);
  setIfPresent(url, "time_aggregation", time_aggregation);
  setBoolIfPresent(url, "include_mandatory", include_mandatory);
  setBoolIfPresent(url, "include_emergency", include_emergency);
  setBoolIfPresent(url, "include_supplemental", include_supplemental);
  setBoolIfPresent(url, "include_pphf", scopeParams.include_pphf);
  setBoolIfPresent(url, "include_transfers", include_transfers);
  setBoolIfPresent(
    url,
    "include_pending_review",
    resolveIncludePendingReview(funding_mode, include_pending_review)
  );
  setIfPresent(url, "review_mode", review_mode);
  setCdcScopeParams(url, scopeParams);
  return url;
}

export async function fetchCdcFundingFilters({
  apiBase = DEFAULT_API_BASE,
  signal,
} = {}) {
  const url = buildCdcApiUrl(apiBase, "/api/cdc/funding/filters");
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding filters.");
}

export async function fetchCdcFundingMethodologySummary({
  apiBase = DEFAULT_API_BASE,
  signal,
} = {}) {
  const url = buildCdcApiUrl(apiBase, "/api/cdc/funding/methodology/summary");
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding methodology summary.");
}

export async function fetchCdcFundingMap({
  apiBase = DEFAULT_API_BASE,
  fiscal_year,
  metric = "total_funding",
  funding_type = "total_cdc_funding",
  funding_mode = CDC_DEFAULT_FUNDING_MODE,
  cdc_center,
  program_area,
  mechanism,
  recipient_type,
  geography_level = CDC_DEFAULT_GEOGRAPHY_LEVEL,
  time_aggregation,
  include_mandatory,
  include_emergency,
  include_supplemental,
  include_pphf,
  include_transfers,
  include_pending_review,
  review_mode,
  funding_scope_preset,
  award_type,
  emergency_supplemental_scope,
  review_status,
  transfers_scope,
  data_source_scope,
  geography,
  center,
  bbox,
  limit = 7000,
  signal,
} = {}) {
  const url = buildCdcApiUrl(apiBase, "/api/cdc/funding/map");
  const scopeParams = resolveChipV1ScopeParams({
    funding_mode,
    fiscal_year,
    funding_scope_preset,
    award_type,
    emergency_supplemental_scope,
    review_status,
    include_pphf,
    transfers_scope,
    data_source_scope,
  });
  url.searchParams.set(
    "geography_level",
    String(geography_level || geography || CDC_DEFAULT_GEOGRAPHY_LEVEL)
  );
  url.searchParams.set("metric", String(metric));
  url.searchParams.set("funding_type", String(funding_type));
  url.searchParams.set("funding_mode", String(funding_mode));
  setFiscalYearIfPresent(url, scopeParams.fiscal_year);
  setIfPresent(url, "cdc_center", cdc_center || center);
  setIfPresent(url, "program_area", program_area);
  setIfPresent(url, "mechanism", mechanism);
  setIfPresent(url, "recipient_type", recipient_type);
  setIfPresent(url, "time_aggregation", time_aggregation);
  setBoolIfPresent(url, "include_mandatory", include_mandatory);
  setBoolIfPresent(url, "include_emergency", include_emergency);
  setBoolIfPresent(url, "include_supplemental", include_supplemental);
  setBoolIfPresent(url, "include_pphf", scopeParams.include_pphf);
  setBoolIfPresent(url, "include_transfers", include_transfers);
  setBoolIfPresent(
    url,
    "include_pending_review",
    resolveIncludePendingReview(funding_mode, include_pending_review)
  );
  setIfPresent(url, "review_mode", review_mode);
  setCdcScopeParams(url, scopeParams);
  setIfPresent(url, "bbox", bbox);
  url.searchParams.set("limit", String(limit));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding map.");
}

export async function fetchCdcFundingLegend({
  apiBase = DEFAULT_API_BASE,
  fiscal_year,
  metric = "total_funding",
  funding_type = "total_cdc_funding",
  funding_mode = CDC_DEFAULT_FUNDING_MODE,
  cdc_center,
  program_area,
  mechanism,
  recipient_type,
  geography_level = CDC_DEFAULT_GEOGRAPHY_LEVEL,
  time_aggregation,
  include_mandatory,
  include_emergency,
  include_supplemental,
  include_pphf,
  include_transfers,
  include_pending_review,
  review_mode,
  funding_scope_preset,
  award_type,
  emergency_supplemental_scope,
  review_status,
  transfers_scope,
  data_source_scope,
  geography,
  center,
  bbox,
  signal,
} = {}) {
  const url = buildCdcApiUrl(apiBase, "/api/cdc/funding/legend");
  const scopeParams = resolveChipV1ScopeParams({
    funding_mode,
    fiscal_year,
    funding_scope_preset,
    award_type,
    emergency_supplemental_scope,
    review_status,
    include_pphf,
    transfers_scope,
    data_source_scope,
  });
  url.searchParams.set(
    "geography_level",
    String(geography_level || geography || CDC_DEFAULT_GEOGRAPHY_LEVEL)
  );
  url.searchParams.set("metric", String(metric));
  url.searchParams.set("funding_type", String(funding_type));
  url.searchParams.set("funding_mode", String(funding_mode));
  setFiscalYearIfPresent(url, scopeParams.fiscal_year);
  setIfPresent(url, "cdc_center", cdc_center || center);
  setIfPresent(url, "program_area", program_area);
  setIfPresent(url, "mechanism", mechanism);
  setIfPresent(url, "recipient_type", recipient_type);
  setIfPresent(url, "time_aggregation", time_aggregation);
  setBoolIfPresent(url, "include_mandatory", include_mandatory);
  setBoolIfPresent(url, "include_emergency", include_emergency);
  setBoolIfPresent(url, "include_supplemental", include_supplemental);
  setBoolIfPresent(url, "include_pphf", scopeParams.include_pphf);
  setBoolIfPresent(url, "include_transfers", include_transfers);
  setBoolIfPresent(
    url,
    "include_pending_review",
    resolveIncludePendingReview(funding_mode, include_pending_review)
  );
  setIfPresent(url, "review_mode", review_mode);
  setCdcScopeParams(url, scopeParams);
  setIfPresent(url, "bbox", bbox);
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding legend.");
}

export async function fetchCdcFundingNational({
  apiBase = DEFAULT_API_BASE,
  fiscal_year,
  metric = "total_funding",
  funding_type = "total_cdc_funding",
  funding_mode = CDC_DEFAULT_FUNDING_MODE,
  cdc_center,
  program_area,
  mechanism,
  recipient_type,
  time_aggregation,
  include_mandatory,
  include_emergency,
  include_supplemental,
  include_pphf,
  include_transfers,
  include_pending_review,
  review_mode,
  funding_scope_preset,
  award_type,
  emergency_supplemental_scope,
  review_status,
  transfers_scope,
  data_source_scope,
  center,
  signal,
} = {}) {
  const url = buildCdcApiUrl(apiBase, "/api/cdc/funding/national");
  const scopeParams = resolveChipV1ScopeParams({
    funding_mode,
    fiscal_year,
    funding_scope_preset,
    award_type,
    emergency_supplemental_scope,
    review_status,
    include_pphf,
    transfers_scope,
    data_source_scope,
  });
  url.searchParams.set("metric", String(metric));
  url.searchParams.set("funding_type", String(funding_type));
  url.searchParams.set("funding_mode", String(funding_mode));
  setFiscalYearIfPresent(url, scopeParams.fiscal_year);
  setIfPresent(url, "cdc_center", cdc_center || center);
  setIfPresent(url, "program_area", program_area);
  setIfPresent(url, "mechanism", mechanism);
  setIfPresent(url, "recipient_type", recipient_type);
  setIfPresent(url, "time_aggregation", time_aggregation);
  setBoolIfPresent(url, "include_mandatory", include_mandatory);
  setBoolIfPresent(url, "include_emergency", include_emergency);
  setBoolIfPresent(url, "include_supplemental", include_supplemental);
  setBoolIfPresent(url, "include_pphf", scopeParams.include_pphf);
  setBoolIfPresent(url, "include_transfers", include_transfers);
  setBoolIfPresent(
    url,
    "include_pending_review",
    resolveIncludePendingReview(funding_mode, include_pending_review)
  );
  setIfPresent(url, "review_mode", review_mode);
  setCdcScopeParams(url, scopeParams);
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
  const url = buildCdcApiUrl(apiBase, "/api/cdc/funding/search");
  setIfPresent(url, "q", q);
  url.searchParams.set("basis", String(basis));
  url.searchParams.set("funding_geography_mode", String(funding_geography_mode));
  url.searchParams.set("appropriation_type", String(appropriation_type));
  setIfPresent(url, "assistance_type", assistance_type);
  setFiscalYearIfPresent(url, fiscal_year);
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
  funding_mode = CDC_DEFAULT_FUNDING_MODE,
  funding_geography_mode = "recipient_location",
  appropriation_type = "all",
  selected_county_fips,
  signal,
} = {}) {
  const url = buildCdcApiUrl(apiBase, "/api/cdc/funding/detail");
  setIfPresent(url, "prime_unique_key", prime_unique_key);
  if (Number.isFinite(Number(subaward_id))) {
    url.searchParams.set("subaward_id", String(Number(subaward_id)));
  }
  setFiscalYearIfPresent(url, fiscal_year);
  url.searchParams.set("funding_mode", String(funding_mode));
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
  const url = buildCdcApiUrl(apiBase, "/api/cdc/funding/top");
  url.searchParams.set("basis", String(basis));
  url.searchParams.set("geography", String(geography));
  url.searchParams.set("funding_geography_mode", String(funding_geography_mode));
  url.searchParams.set("appropriation_type", String(appropriation_type));
  setIfPresent(url, "geography_id", geography_id);
  url.searchParams.set("metric", String(metric));
  setIfPresent(url, "assistance_type", assistance_type);
  setFiscalYearIfPresent(url, fiscal_year);
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
  const url = buildCdcApiUrl(apiBase, "/api/cdc/funding/trend");
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

export async function fetchCdcFundingProfileSummary({
  apiBase = DEFAULT_API_BASE,
  state,
  fiscal_year,
  metric = "total_funding",
  funding_type = "total_cdc_funding",
  funding_mode = CDC_DEFAULT_FUNDING_MODE,
  cdc_center,
  program_area,
  mechanism,
  recipient_type,
  time_aggregation,
  include_mandatory,
  include_emergency,
  include_supplemental,
  include_pphf,
  include_transfers,
  include_pending_review,
  review_mode,
  funding_scope_preset,
  award_type,
  emergency_supplemental_scope,
  review_status,
  transfers_scope,
  data_source_scope,
  signal,
} = {}) {
  const url = buildCdcFundingProfileUrl({
    apiBase,
    endpoint: "summary",
    state,
    fiscal_year,
    metric,
    funding_type,
    funding_mode,
    cdc_center,
    program_area,
    mechanism,
    recipient_type,
    time_aggregation,
    include_mandatory,
    include_emergency,
    include_supplemental,
    include_pphf,
    include_transfers,
    include_pending_review,
    review_mode,
    funding_scope_preset,
    award_type,
    emergency_supplemental_scope,
    review_status,
    transfers_scope,
    data_source_scope,
  });
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding profile summary.");
}

export async function fetchCdcFundingProfileOverview({
  apiBase = DEFAULT_API_BASE,
  state,
  fiscal_year,
  metric = "total_funding",
  funding_type = "total_cdc_funding",
  funding_mode = CDC_DEFAULT_FUNDING_MODE,
  cdc_center,
  program_area,
  mechanism,
  recipient_type,
  time_aggregation,
  include_mandatory,
  include_emergency,
  include_supplemental,
  include_pphf,
  include_transfers,
  include_pending_review,
  review_mode,
  funding_scope_preset,
  award_type,
  emergency_supplemental_scope,
  review_status,
  transfers_scope,
  data_source_scope,
  signal,
} = {}) {
  const url = buildCdcFundingProfileUrl({
    apiBase,
    endpoint: "overview",
    state,
    fiscal_year,
    metric,
    funding_type,
    funding_mode,
    cdc_center,
    program_area,
    mechanism,
    recipient_type,
    time_aggregation,
    include_mandatory,
    include_emergency,
    include_supplemental,
    include_pphf,
    include_transfers,
    include_pending_review,
    review_mode,
    funding_scope_preset,
    award_type,
    emergency_supplemental_scope,
    review_status,
    transfers_scope,
    data_source_scope,
  });
  const response = await fetch(url, { signal });
  if (response.status === 404) {
    const [summary, categories, subcategories] = await Promise.all([
      fetchCdcFundingProfileSummary({
        apiBase,
        state,
        fiscal_year,
        metric,
        funding_type,
        funding_mode,
        cdc_center,
        program_area,
        mechanism,
        recipient_type,
        time_aggregation,
        include_mandatory,
        include_emergency,
        include_supplemental,
        include_pphf,
        include_transfers,
        include_pending_review,
        review_mode,
        funding_scope_preset,
        award_type,
        emergency_supplemental_scope,
        review_status,
        transfers_scope,
        data_source_scope,
        signal,
      }),
      fetchCdcFundingProfileCategories({
        apiBase,
        state,
        fiscal_year,
        funding_type,
        funding_mode,
        cdc_center,
        program_area,
        mechanism,
        recipient_type,
        time_aggregation,
        include_mandatory,
        include_emergency,
        include_supplemental,
        include_pphf,
        include_transfers,
        include_pending_review,
        review_mode,
        funding_scope_preset,
        award_type,
        emergency_supplemental_scope,
        review_status,
        transfers_scope,
        data_source_scope,
        signal,
      }),
      fetchCdcFundingProfileSubcategories({
        apiBase,
        state,
        fiscal_year,
        funding_type,
        funding_mode,
        cdc_center,
        program_area,
        mechanism,
        recipient_type,
        time_aggregation,
        include_mandatory,
        include_emergency,
        include_supplemental,
        include_pphf,
        include_transfers,
        include_pending_review,
        review_mode,
        funding_scope_preset,
        award_type,
        emergency_supplemental_scope,
        review_status,
        transfers_scope,
        data_source_scope,
        signal,
      }),
    ]);
    return {
      summary,
      categories,
      subcategories,
    };
  }
  return parseJsonOrThrow(response, "Failed to load CDC funding profile overview.");
}

export async function fetchCdcFundingProfileCategories({
  apiBase = DEFAULT_API_BASE,
  state,
  fiscal_year,
  funding_type = "total_cdc_funding",
  funding_mode = CDC_DEFAULT_FUNDING_MODE,
  cdc_center,
  program_area,
  mechanism,
  recipient_type,
  time_aggregation,
  include_mandatory,
  include_emergency,
  include_supplemental,
  include_pphf,
  include_transfers,
  include_pending_review,
  review_mode,
  funding_scope_preset,
  award_type,
  emergency_supplemental_scope,
  review_status,
  transfers_scope,
  data_source_scope,
  signal,
} = {}) {
  const url = buildCdcFundingProfileUrl({
    apiBase,
    endpoint: "categories",
    state,
    fiscal_year,
    funding_type,
    funding_mode,
    cdc_center,
    program_area,
    mechanism,
    recipient_type,
    time_aggregation,
    include_mandatory,
    include_emergency,
    include_supplemental,
    include_pphf,
    include_transfers,
    include_pending_review,
    review_mode,
    funding_scope_preset,
    award_type,
    emergency_supplemental_scope,
    review_status,
    transfers_scope,
    data_source_scope,
  });
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding profile categories.");
}

export async function fetchCdcFundingProfileSubcategories({
  apiBase = DEFAULT_API_BASE,
  state,
  fiscal_year,
  funding_type = "total_cdc_funding",
  funding_mode = CDC_DEFAULT_FUNDING_MODE,
  cdc_center,
  program_area,
  mechanism,
  recipient_type,
  time_aggregation,
  include_mandatory,
  include_emergency,
  include_supplemental,
  include_pphf,
  include_transfers,
  include_pending_review,
  review_mode,
  funding_scope_preset,
  award_type,
  emergency_supplemental_scope,
  review_status,
  transfers_scope,
  data_source_scope,
  signal,
} = {}) {
  const url = buildCdcFundingProfileUrl({
    apiBase,
    endpoint: "subcategories",
    state,
    fiscal_year,
    funding_type,
    funding_mode,
    cdc_center,
    program_area,
    mechanism,
    recipient_type,
    time_aggregation,
    include_mandatory,
    include_emergency,
    include_supplemental,
    include_pphf,
    include_transfers,
    include_pending_review,
    review_mode,
    funding_scope_preset,
    award_type,
    emergency_supplemental_scope,
    review_status,
    transfers_scope,
    data_source_scope,
  });
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding profile sub-categories.");
}

export async function fetchCdcFundingProfileDetails({
  apiBase = DEFAULT_API_BASE,
  state,
  fiscal_year,
  funding_type,
  funding_mode = CDC_DEFAULT_FUNDING_MODE,
  basis = "prime",
  funding_geography_mode = "recipient_location",
  appropriation_type = "all",
  include_mandatory,
  include_emergency,
  include_supplemental,
  include_pphf,
  include_transfers,
  include_pending_review,
  review_mode,
  funding_scope_preset,
  award_type,
  emergency_supplemental_scope,
  review_status,
  transfers_scope,
  data_source_scope,
  assistance_type,
  center,
  q,
  page = 1,
  page_size = 25,
  sort_by = "amount",
  sort_dir = "desc",
  signal,
} = {}) {
  const url = buildCdcApiUrl(apiBase, "/api/cdc/funding/profile/details");
  const scopeParams = resolveChipV1ScopeParams({
    funding_mode,
    fiscal_year,
    funding_scope_preset,
    award_type,
    emergency_supplemental_scope,
    review_status,
    include_pphf,
    transfers_scope,
    data_source_scope,
  });
  url.searchParams.set("state", String(state ?? "").trim().toUpperCase());
  setIfPresent(url, "funding_type", funding_type);
  url.searchParams.set("funding_mode", String(funding_mode));
  url.searchParams.set("basis", String(basis));
  url.searchParams.set("funding_geography_mode", String(funding_geography_mode));
  url.searchParams.set("appropriation_type", String(appropriation_type));
  setBoolIfPresent(url, "include_mandatory", include_mandatory);
  setBoolIfPresent(url, "include_emergency", include_emergency);
  setBoolIfPresent(url, "include_supplemental", include_supplemental);
  setBoolIfPresent(url, "include_pphf", scopeParams.include_pphf);
  setBoolIfPresent(url, "include_transfers", include_transfers);
  setBoolIfPresent(
    url,
    "include_pending_review",
    resolveIncludePendingReview(funding_mode, include_pending_review)
  );
  setIfPresent(url, "review_mode", review_mode);
  setCdcScopeParams(url, scopeParams);
  setFiscalYearIfPresent(url, scopeParams.fiscal_year);
  setIfPresent(url, "assistance_type", assistance_type);
  setIfPresent(url, "center", center);
  setIfPresent(url, "q", q);
  url.searchParams.set("page", String(page));
  url.searchParams.set("page_size", String(page_size));
  url.searchParams.set("sort_by", String(sort_by));
  url.searchParams.set("sort_dir", String(sort_dir));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding profile details.");
}
