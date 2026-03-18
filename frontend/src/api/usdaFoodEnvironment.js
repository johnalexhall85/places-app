import { API_BASE as DEFAULT_API_BASE } from "../config/apiBase";

async function parseJsonOrThrow(response, fallbackMessage) {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    const detail = body || fallbackMessage;
    throw new Error(detail);
  }
  return response.json();
}

export async function fetchUsdaFoodEnvironmentVariables({
  apiBase = DEFAULT_API_BASE,
  q,
  level = "county",
  include_archival = false,
  year,
  category,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/usda/food-environment/variables`);
  if (q) {
    url.searchParams.set("q", String(q));
  }
  if (level) {
    url.searchParams.set("level", String(level));
  }
  if (include_archival) {
    url.searchParams.set("include_archival", "true");
  }
  if (Number.isFinite(Number(year))) {
    url.searchParams.set("year", String(Number(year)));
  }
  if (category) {
    url.searchParams.set("category", String(category));
  }
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load USDA Food Environment variables.");
}

export async function fetchUsdaFoodEnvironmentLegend({
  apiBase = DEFAULT_API_BASE,
  variable,
  bbox,
  level = "auto",
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/usda/food-environment/legend`);
  url.searchParams.set("variable", String(variable));
  url.searchParams.set("level", String(level));
  if (bbox) {
    url.searchParams.set("bbox", String(bbox));
  }
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load USDA Food Environment legend.");
}

export async function fetchUsdaFoodEnvironmentMap({
  apiBase = DEFAULT_API_BASE,
  variable,
  bbox,
  zoom,
  level = "auto",
  limit = 5000,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/usda/food-environment/map`);
  url.searchParams.set("variable", String(variable));
  url.searchParams.set("bbox", String(bbox));
  url.searchParams.set("zoom", String(zoom));
  url.searchParams.set("level", String(level));
  url.searchParams.set("limit", String(limit));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load USDA Food Environment map.");
}
