import { API_BASE as DEFAULT_API_BASE } from "../config/apiBase";

export const CDC_FUNDING_SCOPE_ALL_ACCOUNTS = "all_accounts";
export const CDC_FUNDING_PROFILE_SCOPE = "cdc_funding_profiles";

async function parseJsonOrThrow(response, fallbackMessage) {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    let detail = body || fallbackMessage;
    try {
      const parsed = JSON.parse(body);
      detail = parsed?.detail?.message ?? parsed?.detail ?? detail;
    } catch {
      // Keep the raw response text when the server did not return JSON.
    }
    const message = typeof detail === "string" ? detail : fallbackMessage;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function buildCdcFundingOverviewUrl(apiBase, path, params = {}) {
  const base = String(apiBase ?? DEFAULT_API_BASE)
    .trim()
    .replace(/\/+$/, "");
  const normalizedPath = `/${String(path ?? "")
    .trim()
    .replace(/^\/+/, "")}`;
  const effectiveBase =
    /\/api$/i.test(base) && normalizedPath.startsWith("/api/")
      ? base.slice(0, -4)
      : base;
  const url = new URL(`${effectiveBase}${normalizedPath}`);
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined) return;
    const token = String(value).trim();
    if (token) {
      url.searchParams.set(key, token);
    }
  });
  return url;
}

export async function fetchCdcFundingFiscalYears({
  apiBase = DEFAULT_API_BASE,
  signal,
  scope,
} = {}) {
  const url = buildCdcFundingOverviewUrl(
    apiBase,
    "/api/cdc-funding/v1/fiscal-years",
    {
      scope,
    },
  );
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding fiscal years.");
}

export async function fetchCdcFundingOverview(
  fiscalYear,
  { apiBase = DEFAULT_API_BASE, signal, scope } = {},
) {
  const url = buildCdcFundingOverviewUrl(
    apiBase,
    "/api/cdc-funding/v1/overview",
    {
      fiscal_year: fiscalYear,
      scope,
    },
  );
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding overview.");
}

export async function fetchCdcFundingAccounts(
  fiscalYear,
  { apiBase = DEFAULT_API_BASE, signal, scope } = {},
) {
  const url = buildCdcFundingOverviewUrl(
    apiBase,
    "/api/cdc-funding/v1/accounts",
    {
      fiscal_year: fiscalYear,
      scope,
    },
  );
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding accounts.");
}

export async function fetchCdcFundingCategories(
  fiscalYear,
  { apiBase = DEFAULT_API_BASE, signal, scope } = {},
) {
  const url = buildCdcFundingOverviewUrl(
    apiBase,
    "/api/cdc-funding/v1/categories",
    {
      fiscal_year: fiscalYear,
      scope,
    },
  );
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CDC funding categories.");
}

export async function fetchCdcFundingQuarterlyTrends({
  apiBase = DEFAULT_API_BASE,
  signal,
  scope,
  measure,
  view,
  federalAccountSymbol,
  emergencyStatus,
  awardType,
} = {}) {
  const url = buildCdcFundingOverviewUrl(
    apiBase,
    "/api/cdc-funding/v1/quarterly-trends",
    {
      scope,
      measure,
      view,
      federal_account_symbol: federalAccountSymbol,
      emergency_status: emergencyStatus,
      award_type: awardType,
    },
  );
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(
    response,
    "Failed to load CDC funding quarterly trends.",
  );
}

export async function fetchCdcFundingObligationTrends({
  apiBase = DEFAULT_API_BASE,
  signal,
  scope,
  period,
  view,
  federalAccountSymbol,
  emergencyStatus,
  awardType,
  excludeDeobligations,
} = {}) {
  const url = buildCdcFundingOverviewUrl(
    apiBase,
    "/api/cdc-funding/v1/obligation-trends",
    {
      scope,
      period,
      view,
      federal_account_symbol: federalAccountSymbol,
      emergency_status: emergencyStatus,
      award_type: awardType,
      exclude_deobligations: excludeDeobligations ? "true" : undefined,
    },
  );
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(
    response,
    "Failed to load CDC funding obligation trends.",
  );
}

export async function fetchCdcFundingTrendAccounts({
  apiBase = DEFAULT_API_BASE,
  signal,
  scope,
} = {}) {
  const url = buildCdcFundingOverviewUrl(
    apiBase,
    "/api/cdc-funding/v1/quarterly-trends/accounts",
    {
      scope,
    },
  );
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(
    response,
    "Failed to load CDC funding trend account options.",
  );
}
