import { API_BASE } from "../config/apiBase";

const root = `${API_BASE}/state-funding/v1`;

async function get(path, params = {}, signal) {
  const url = new URL(`${root}${path}`);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, value);
  });
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(response.status === 404 ? "State funding not found." : "State funding is unavailable right now.");
  return response.json();
}

export const fiscalYears = (signal) => get("/fiscal-years", {}, signal);
export const stateSummary = (code, params, signal) => get(`/states/${encodeURIComponent(code)}/summary`, params, signal);
export const stateGrants = (code, params, signal) => get(`/states/${encodeURIComponent(code)}/grants`, params, signal);
export function grantsCsvUrl(code, params) {
  const url = new URL(`${root}/states/${encodeURIComponent(code)}/grants.csv`);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, value);
  });
  return url.toString();
}
