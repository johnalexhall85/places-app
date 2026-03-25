export function resolveRoute(pathname) {
  const normalizedPath = String(pathname ?? "").trim();
  if (/^\/funding-model-builder\/?$/i.test(normalizedPath)) {
    return { type: "funding-model-builder" };
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
