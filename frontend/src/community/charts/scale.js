export const COLORS = { area: "#0277BD", state: "#F0B97D", national: "#009688" };

export function extent(values, row = {}) {
  const found = values.filter(Number.isFinite);
  if (!found.length) return [0, 1];
  const low = Math.min(...found);
  const high = Math.max(...found);
  const ceiling = row.storage_scale === "proportion_0_1" ? 1 : row.unit === "percent" || row.unit === "%" ? 100 : Infinity;
  const start = low >= 0 || ceiling !== Infinity ? 0 : low;
  const capped = Math.min(ceiling, Math.max(high, 0));
  const span = Math.max(capped - start, Number.EPSILON);
  const power = 10 ** Math.floor(Math.log10(span / 4));
  const steps = [1, 2, 2.5, 5, 10].map((factor) => factor * power);
  const step = steps.find((candidate) => Math.ceil(span / candidate) <= 4) || steps.at(-1);
  const min = start === 0 ? 0 : Math.floor(start / step) * step;
  const max = Math.min(ceiling, Math.max(step, Math.ceil(capped / step) * step));
  return [Number(min.toPrecision(12)), Number(max.toPrecision(12))];
}

export function focusedExtent(values, row = {}) {
  const found = values.filter(Number.isFinite);
  if (!found.length) return extent(values, row);
  const low = Math.min(...found);
  const high = Math.max(...found);
  const pad = Math.max((high - low) * 0.08, Math.abs(high) * 0.01, 0.1);
  const power = 10 ** Math.floor(Math.log10(Math.max((high - low + 2 * pad) / 6, 0.01)));
  const step = [1, 2, 2.5, 5, 10].map((factor) => factor * power)
    .find((candidate) => Math.ceil((high - low + 2 * pad) / candidate) <= 6) || 10 * power;
  const ceiling = row.storage_scale === "proportion_0_1" ? 1 : row.unit === "percent" || row.unit === "%" ? 100 : Infinity;
  const min = Math.max(0, Math.floor((low - pad) / step) * step);
  const max = Math.min(ceiling, Math.ceil((high + pad) / step) * step);
  return [Number(min.toPrecision(12)), Number(Math.max(max, min + step).toPrecision(12))];
}

export function ticks(domain, count = 5) {
  const [low, high] = domain;
  const span = high - low;
  const power = 10 ** Math.floor(Math.log10(span / (count - 1)));
  const step = [1, 2, 2.5, 5, 10].map((factor) => factor * power)
    .find((candidate) => Math.floor(span / candidate) + 1 <= count) || 10 * power;
  const result = [];
  for (let value = low; value <= high + step / 1000; value += step) result.push(Number(value.toPrecision(10)));
  if (result.at(-1) !== high && result.length < count) result.push(high);
  return result;
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
  const text = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(display);
  if (row.kind === "currency" || /\bUSD\b|US dollars/i.test(row.unit || "")) return `$${text}`;
  return row.storage_scale === "proportion_0_1" || row.unit === "percent" || row.unit === "%" ? `${text}%` : text;
}

export function formatTick(value, row = {}) {
  if (row.kind === "currency" || /\bUSD\b|US dollars/i.test(row.unit || "")) {
    const short = Math.abs(value) >= 1000000 ? `${Number((value / 1000000).toFixed(1))}m` : Math.abs(value) >= 1000 ? `${Number((value / 1000).toFixed(1))}k` : `${Number(value.toFixed(1))}`;
    return `$${short}`;
  }
  return formatValue(value, row);
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
  return { selected: [...ordered.filter((item) => core.has(item.geoid)), ...ordered.filter((item) => fringe.has(item.geoid))],
    remaining: ordered.filter((item) => !chosen.has(item.geoid)), fringe };
}
