import { API_BASE as DEFAULT_API_BASE } from "../config/apiBase";

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

export async function fetchTaggsFilters({
  apiBase = DEFAULT_API_BASE,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/taggs/filters`);
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load TAGGS filters.");
}

export async function fetchTaggsStateMap({
  apiBase = DEFAULT_API_BASE,
  metric = "total_funding",
  fiscal_year,
  program_office,
  aln,
  can_code,
  funding_stream,
  bbox,
  zoom,
  limit = 100,
  normalize = false,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/taggs/states/map`);
  url.searchParams.set("metric", String(metric));
  if (Number.isFinite(Number(fiscal_year))) {
    url.searchParams.set("fiscal_year", String(Number(fiscal_year)));
  }
  setIfPresent(url, "program_office", program_office);
  setIfPresent(url, "aln", aln);
  setIfPresent(url, "can_code", can_code);
  setIfPresent(url, "funding_stream", funding_stream);
  setIfPresent(url, "bbox", bbox);
  if (Number.isFinite(Number(zoom))) {
    url.searchParams.set("zoom", String(Number(zoom)));
  }
  if (Number.isFinite(Number(limit))) {
    url.searchParams.set("limit", String(Number(limit)));
  }
  url.searchParams.set("normalize", normalize ? "true" : "false");
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load TAGGS state map.");
}

export async function fetchTaggsStateLegend({
  apiBase = DEFAULT_API_BASE,
  metric = "total_funding",
  fiscal_year,
  program_office,
  aln,
  can_code,
  funding_stream,
  normalize = false,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/taggs/states/legend`);
  url.searchParams.set("metric", String(metric));
  if (Number.isFinite(Number(fiscal_year))) {
    url.searchParams.set("fiscal_year", String(Number(fiscal_year)));
  }
  setIfPresent(url, "program_office", program_office);
  setIfPresent(url, "aln", aln);
  setIfPresent(url, "can_code", can_code);
  setIfPresent(url, "funding_stream", funding_stream);
  url.searchParams.set("normalize", normalize ? "true" : "false");
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load TAGGS legend.");
}

function profileUrl(apiBase, endpoint, params = {}) {
  const url = new URL(`${apiBase}/api/taggs/funding-profile/${endpoint}`);
  setIfPresent(url, "state", params.state);
  if (Number.isFinite(Number(params.fy))) {
    url.searchParams.set("fy", String(Number(params.fy)));
  }
  setIfPresent(url, "program_office", params.program_office);
  setIfPresent(url, "aln", params.aln);
  setIfPresent(url, "can_code", params.can_code);
  setIfPresent(url, "funding_stream", params.funding_stream);
  if (typeof params.domestic_only === "boolean") {
    url.searchParams.set("domestic_only", params.domestic_only ? "true" : "false");
  }
  return url;
}

export async function fetchTaggsFundingProfileSummary({
  apiBase = DEFAULT_API_BASE,
  state,
  fy,
  program_office,
  aln,
  can_code,
  funding_stream,
  domestic_only = true,
  signal,
} = {}) {
  const url = profileUrl(apiBase, "summary", {
    state,
    fy,
    program_office,
    aln,
    can_code,
    funding_stream,
    domestic_only,
  });
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load TAGGS funding profile summary.");
}

export async function fetchTaggsFundingProfileCategories({
  apiBase = DEFAULT_API_BASE,
  state,
  fy,
  program_office,
  aln,
  can_code,
  funding_stream,
  domestic_only = true,
  signal,
} = {}) {
  const url = profileUrl(apiBase, "categories", {
    state,
    fy,
    program_office,
    aln,
    can_code,
    funding_stream,
    domestic_only,
  });
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load TAGGS category totals.");
}

export async function fetchTaggsFundingProfileSubcategories({
  apiBase = DEFAULT_API_BASE,
  state,
  fy,
  program_office,
  aln,
  can_code,
  funding_stream,
  domestic_only = true,
  signal,
} = {}) {
  const url = profileUrl(apiBase, "subcategories", {
    state,
    fy,
    program_office,
    aln,
    can_code,
    funding_stream,
    domestic_only,
  });
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load TAGGS sub-category totals.");
}

export async function fetchTaggsFundingProfileCanBreakdown({
  apiBase = DEFAULT_API_BASE,
  state,
  fy,
  program_office,
  aln,
  can_code,
  funding_stream,
  domestic_only = true,
  signal,
} = {}) {
  const url = profileUrl(apiBase, "can-breakdown", {
    state,
    fy,
    program_office,
    aln,
    can_code,
    funding_stream,
    domestic_only,
  });
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load TAGGS CAN breakdown.");
}

export async function fetchTaggsFundingProfileRecipients({
  apiBase = DEFAULT_API_BASE,
  state,
  fy,
  program_office,
  aln,
  can_code,
  funding_stream,
  domestic_only = true,
  page = 1,
  page_size = 20,
  signal,
} = {}) {
  const url = profileUrl(apiBase, "recipients", {
    state,
    fy,
    program_office,
    aln,
    can_code,
    funding_stream,
    domestic_only,
  });
  url.searchParams.set("page", String(page));
  url.searchParams.set("page_size", String(page_size));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load TAGGS top recipients.");
}

export async function fetchTaggsFundingProfileCounties({
  apiBase = DEFAULT_API_BASE,
  state,
  fy,
  program_office,
  aln,
  can_code,
  funding_stream,
  domestic_only = true,
  limit = 200,
  signal,
} = {}) {
  const url = profileUrl(apiBase, "counties", {
    state,
    fy,
    program_office,
    aln,
    can_code,
    funding_stream,
    domestic_only,
  });
  url.searchParams.set("limit", String(limit));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load TAGGS county distribution.");
}

export async function fetchTaggsFundingProfileDetails({
  apiBase = DEFAULT_API_BASE,
  state,
  fy,
  program_office,
  aln,
  can_code,
  funding_stream,
  domestic_only = true,
  page = 1,
  page_size = 25,
  sort_by = "amount",
  sort_dir = "desc",
  signal,
} = {}) {
  const url = profileUrl(apiBase, "details", {
    state,
    fy,
    program_office,
    aln,
    can_code,
    funding_stream,
    domestic_only,
  });
  url.searchParams.set("page", String(page));
  url.searchParams.set("page_size", String(page_size));
  url.searchParams.set("sort_by", String(sort_by));
  url.searchParams.set("sort_dir", String(sort_dir));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load TAGGS detail rows.");
}

export function buildTaggsDetailsExportUrl({
  apiBase = DEFAULT_API_BASE,
  state,
  fy,
  program_office,
  aln,
  can_code,
  funding_stream,
  domestic_only = true,
  sort_by = "amount",
  sort_dir = "desc",
} = {}) {
  const url = profileUrl(apiBase, "details/export", {
    state,
    fy,
    program_office,
    aln,
    can_code,
    funding_stream,
    domestic_only,
  });
  url.searchParams.set("sort_by", String(sort_by));
  url.searchParams.set("sort_dir", String(sort_dir));
  return url.toString();
}
