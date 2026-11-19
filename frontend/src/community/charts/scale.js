export const COLORS = { area: "#0277BD", state: "#F0B97D", national: "#009688" };

export function extent(values) {
  const found = values.filter(Number.isFinite);
  if (!found.length) return [0, 1];
  const low = Math.min(...found);
  const high = Math.max(...found);
  const pad = (high - low || Math.max(Math.abs(high), 1)) * 0.08;
  return [Math.min(0, low - pad), high + pad];
}

export const position = (value, domain, left, right) =>
  left + ((value - domain[0]) / (domain[1] - domain[0] || 1)) * (right - left);

export function interval(row) {
  if (!row || row.value == null) return [null, null];
  const uncertainty = row.uncertainty || {};
  if (uncertainty.low != null && uncertainty.high != null) return [uncertainty.low, uncertainty.high];
  if (uncertainty.moe != null) return [row.value - uncertainty.moe, row.value + uncertainty.moe];
  return [row.value, row.value];
}

export function formatValue(value, row = {}) {
  if (value == null) return row.status_text || "No published value";
  const display = row.storage_scale === "proportion_0_1" ? value * 100 : value;
  const text = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(display);
  if (row.kind === "currency" || /\bUSD\b|US dollars/i.test(row.unit || "")) return `$${text}`;
  return row.storage_scale === "proportion_0_1" || row.unit === "percent" || row.unit === "%" ? `${text}%` : text;
}

export function peerSubset(values, areaGeoid) {
  const published = values.filter((item) => item.value != null);
  const area = published.find((item) => item.geoid === areaGeoid);
  const ordered = [...published].sort((a, b) => b.value - a.value || a.geoid.localeCompare(b.geoid));
  if (!area) return { selected: ordered.slice(0, 17), remaining: ordered.slice(17) };
  const nearest = [...published].filter((item) => item.geoid !== areaGeoid)
    .sort((a, b) => Math.abs(a.value - area.value) - Math.abs(b.value - area.value) || a.geoid.localeCompare(b.geoid))
    .slice(0, 15);
  const core = new Set([area.geoid, ...nearest.map((item) => item.geoid)]);
  const fringe = new Set([ordered[0]?.geoid, ordered.at(-1)?.geoid].filter((geoid) => !core.has(geoid)));
  const chosen = new Set([...core, ...fringe]);
  return { selected: ordered.filter((item) => chosen.has(item.geoid)),
    remaining: ordered.filter((item) => !chosen.has(item.geoid)), fringe };
}
