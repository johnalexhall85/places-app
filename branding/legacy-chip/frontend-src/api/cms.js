import { API_BASE as DEFAULT_API_BASE } from "../config/apiBase";

async function parseJsonOrThrow(response, fallbackMessage) {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    const detail = body || fallbackMessage;
    throw new Error(detail);
  }
  return response.json();
}

export async function fetchCmsGvCountyGeo({
  year,
  age_level,
  measure_id,
  apiBase = DEFAULT_API_BASE,
  signal,
}) {
  const url = new URL(`${apiBase}/cms/gv/geo`);
  url.searchParams.set("level", "county");
  url.searchParams.set("year", String(year));
  url.searchParams.set("age_level", String(age_level));
  url.searchParams.set("measure_id", String(measure_id));
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CMS county data.");
}

export async function fetchCmsMeasures({ apiBase = DEFAULT_API_BASE, signal } = {}) {
  const url = new URL(`${apiBase}/cms/gv/measures`);
  url.searchParams.set("level", "county");
  const response = await fetch(url, { signal });
  return parseJsonOrThrow(response, "Failed to load CMS measures.");
}

export async function fetchCmsYears({ apiBase = DEFAULT_API_BASE, signal } = {}) {
  const url = new URL(`${apiBase}/cms/gv/years`);
  url.searchParams.set("level", "county");
  const response = await fetch(url, { signal });
  const payload = await parseJsonOrThrow(response, "Failed to load CMS years.");
  const years = Array.isArray(payload?.years) ? payload.years : [];
  return years.map((value) => Number(value)).filter((value) => Number.isFinite(value));
}
