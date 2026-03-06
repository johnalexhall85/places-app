const DEFAULT_API_BASE = "http://localhost:8000";

async function parseJsonOrThrow(response, fallbackMessage) {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    const detail = body || fallbackMessage;
    throw new Error(detail);
  }
  return response.json();
}

export async function fetchUsdaVariables({
  apiBase = DEFAULT_API_BASE,
  q,
  includeRawOnly = false,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/usda/food-access/variables`);
  if (q) {
    url.searchParams.set("q", String(q));
  }
  url.searchParams.set("include_raw_only", includeRawOnly ? "true" : "false");
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load USDA variables.");
}

export async function fetchUsdaLegend({
  apiBase = DEFAULT_API_BASE,
  variable,
  bbox,
  bins = 5,
  mode = "auto",
  signal,
}) {
  const url = new URL(`${apiBase}/api/usda/food-access/legend`);
  url.searchParams.set("variable", String(variable));
  url.searchParams.set("bins", String(bins));
  url.searchParams.set("mode", String(mode));
  if (bbox) {
    url.searchParams.set("bbox", String(bbox));
  }
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load USDA legend.");
}

export async function fetchUsdaHeat({
  apiBase = DEFAULT_API_BASE,
  variable,
  bbox,
  zoom,
  limit = 2000,
  agg = "auto",
  mode = "auto",
  signal,
}) {
  const url = new URL(`${apiBase}/api/usda/food-access/heat`);
  url.searchParams.set("variable", String(variable));
  url.searchParams.set("bbox", String(bbox));
  url.searchParams.set("zoom", String(zoom));
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("agg", String(agg));
  url.searchParams.set("mode", String(mode));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load USDA heat map.");
}
