export function resolveRoute(pathname) {
  const normalizedPath = String(pathname ?? "").trim();
  if (/^\/area\/places-2025\/?$/i.test(normalizedPath)) {
    return { type: "places-2025-pilot" };
  }
  if (/^\/area\/acs-2024\/?$/i.test(normalizedPath)) {
    return { type: "acs-2024-area" };
  }
  if (/^\/area\/ahrf\/?$/i.test(normalizedPath)) {
    return { type: "ahrf-area" };
  }
  if (/^\/area\/clh\/?$/i.test(normalizedPath)) {
    return { type: "clh-area" };
  }
  if (/^\/area\/epa-aqi\/?$/i.test(normalizedPath)) {
    return { type: "epa-aqi-area" };
  }
  if (/^\/area\/cms-gv\/?$/i.test(normalizedPath)) {
    return { type: "cms-gv-area" };
  }
  if (/^\/area\/usda-fea\/?$/i.test(normalizedPath)) {
    return { type: "usda-fea-area" };
  }
  if (/^\/funding-model-builder\/?$/i.test(normalizedPath)) {
    return { type: "funding-model-builder" };
  }
  if (/^\/cdc-funding\/?$/i.test(normalizedPath)) {
    return { type: "cdc-funding-overview" };
  }
  const cdcFundingProfileMatch = normalizedPath.match(/^\/cdc-funding\/state\/([^/]+)\/?$/i);
  if (cdcFundingProfileMatch) {
    return { type: "cdc-state-funding-profile", id: cdcFundingProfileMatch[1] };
  }
  const countyMatch = normalizedPath.match(/^\/profile\/county\/([^/]+)\/?$/i);
  if (countyMatch) {
    return { type: "profile-county", id: countyMatch[1] };
  }
  const tractMatch = normalizedPath.match(/^\/profile\/tract\/([^/]+)\/?$/i);
  if (tractMatch) {
    return { type: "profile-tract", id: tractMatch[1] };
  }
  return { type: "map" };
}
