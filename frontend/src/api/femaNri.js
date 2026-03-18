import { API_BASE as DEFAULT_API_BASE } from "../config/apiBase";

async function parseJsonOrThrow(response, fallbackMessage) {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    const detail = body || fallbackMessage;
    throw new Error(detail);
  }
  return response.json();
}

export async function fetchFemaNriMeasures({
  apiBase = DEFAULT_API_BASE,
  level = "all",
  include_hidden = false,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/fema/nri/measures`);
  if (level) {
    url.searchParams.set("level", String(level));
  }
  if (include_hidden) {
    url.searchParams.set("include_hidden", "true");
  }
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load FEMA NRI measures.");
}

export async function fetchFemaNriMap({
  apiBase = DEFAULT_API_BASE,
  measure,
  bbox,
  zoom,
  level = "auto",
  limit = 5000,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/fema/nri/map`);
  url.searchParams.set("measure", String(measure));
  url.searchParams.set("bbox", String(bbox));
  url.searchParams.set("zoom", String(zoom));
  url.searchParams.set("level", String(level));
  url.searchParams.set("limit", String(limit));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load FEMA NRI map.");
}

export async function fetchFemaNriLegend({
  apiBase = DEFAULT_API_BASE,
  measure,
  bbox,
  level = "auto",
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/fema/nri/legend`);
  url.searchParams.set("measure", String(measure));
  url.searchParams.set("level", String(level));
  if (bbox) {
    url.searchParams.set("bbox", String(bbox));
  }
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load FEMA NRI legend.");
}

export async function fetchFemaNriDetail({
  apiBase = DEFAULT_API_BASE,
  level,
  geoid,
  signal,
} = {}) {
  const url = new URL(`${apiBase}/api/fema/nri/detail`);
  url.searchParams.set("level", String(level));
  url.searchParams.set("geoid", String(geoid));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load FEMA NRI detail.");
}
