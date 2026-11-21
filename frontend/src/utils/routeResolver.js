export function resolveRoute(pathname) {
  const normalizedPath = String(pathname ?? "").trim();
  if (/^\/?$/.test(normalizedPath)) {
    return { type: "community-landing" };
  }
  if (/^\/explore\/map\/?$/i.test(normalizedPath)) {
    return { type: "map" };
  }
  if (/^\/compare\/?$/i.test(normalizedPath)) {
    return { type: "community-compare" };
  }
  if (/^\/districts\/?$/i.test(normalizedPath)) {
    return { type: "community-districts" };
  }
  const districtMatch = normalizedPath.match(/^\/district\/cd\/(\d{4})\/?$/i);
  if (districtMatch) {
    return { type: "community-district", id: districtMatch[1] };
  }
  if (/^\/topics\/?$/i.test(normalizedPath)) {
    return { type: "community-topics" };
  }
  if (/^\/about\/?$/i.test(normalizedPath)) {
    return { type: "community-about" };
  }
  if (/^\/ai\/?$/i.test(normalizedPath)) {
    return { type: "community-ai" };
  }
  if (/^\/methodology\/?$/i.test(normalizedPath)) {
    return { type: "community-methodology" };
  }
  const topicMatch = normalizedPath.match(/^\/topics\/([a-z0-9-]+)\/?$/i);
  if (topicMatch) {
    return { type: "community-topic", slug: topicMatch[1] };
  }
  const communityCountyMatch = normalizedPath.match(/^\/community\/county\/(\d{5})\/?$/i);
  if (communityCountyMatch) {
    return { type: "community-county", id: communityCountyMatch[1] };
  }
  const communityStateMatch = normalizedPath.match(/^\/community\/state\/(\d{2})\/?$/i);
  if (communityStateMatch) {
    return { type: "community-state", id: communityStateMatch[1] };
  }
  if (/^\/area\/places-2025\/?$/i.test(normalizedPath)) {
    return { type: "places-2025-pilot" };
  }
  if (/^\/area\/brfss\/?$/i.test(normalizedPath)) {
    return { type: "brfss-state-area" };
  }
  if (/^\/area\/acs-2024\/?$/i.test(normalizedPath)) {
    return { type: "acs-2024-area" };
  }
  if (/^\/area\/acs-community\/?$/i.test(normalizedPath)) {
    return { type: "acs-community-area" };
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
  if (/^\/area\/heart-stroke-mortality\/?$/i.test(normalizedPath)) {
    return { type: "hds-mortality-area" };
  }
  if (/^\/area\/svi\/?$/i.test(normalizedPath)) {
    return { type: "svi-area" };
  }
  if (/^\/area\/fema-nri\/?$/i.test(normalizedPath)) {
    return { type: "fema-nri-area" };
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
  if (/^\/cdc-funding\/map\/?$/i.test(normalizedPath)) {
    return { type: "cdc-funding-map" };
  }
  const cdcFundingProfileMatch = normalizedPath.match(/^\/cdc-funding\/state\/([^/]+)\/?$/i);
  if (cdcFundingProfileMatch) {
    return { type: "cdc-state-funding-profile", id: cdcFundingProfileMatch[1] };
  }
  const cdcGrantMatch = normalizedPath.match(/^\/cdc-funding\/grant\/([^/]+)\/?$/i);
  if (cdcGrantMatch) {
    return { type: "cdc-grant-history", id: decodeURIComponent(cdcGrantMatch[1]) };
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
