export function legacyStateFundingTarget(search) {
  const state = new URLSearchParams(search).get("state") || "";
  return `/cdc-funding/state/${encodeURIComponent(state)}`;
}
