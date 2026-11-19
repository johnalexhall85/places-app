export const COLORS = {
  area: "#0277BD",
  state: "#C77700",
  national: "#2BA48A",
};

export const DASH_ARRAYS = {
  area: undefined,
  state: "5 3",
  national: "1.5 3",
};

export const DOT_RADIUS = {
  area: 4,
  state: 3.5,
  national: 3.5,
};

export function isPercentRow(row = {}) {
  return (
    row.storage_scale === "proportion_0_1" ||
    row.kind === "percent" ||
    row.unit === "percent" ||
    row.unit === "%"
  );
}

export function isCurrencyRow(row = {}) {
  return row.kind === "currency" || /\bUSD\b|US dollars/i.test(row.unit || "");
}

export function toDisplayValue(value, row = {}) {
  if (value == null || !Number.isFinite(value)) return null;
  return row.storage_scale === "proportion_0_1" ? value * 100 : value;
}

export function shortPeriod(period) {
  return String(period).split(/[-–]/).at(-1).trim();
}

export function formatCardValue(value, row = {}, statusText) {
  if (value == null || !Number.isFinite(value)) {
    return statusText || row.status_text || "No published value";
  }
  const display = toDisplayValue(value, row);
  if (isCurrencyRow(row)) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(display);
  }
  const formatted = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: Number.isInteger(display) ? 0 : 2,
  }).format(display);
  if (isPercentRow(row)) return `${formatted}%`;
  return formatted;
}

function cleanTickNumber(value) {
  const safe = Math.abs(value) < 1e-9 ? 0 : value;
  const digits = safe > 0 && safe < 0.1 ? 2 : 1;
  return String(Number(safe.toFixed(digits)));
}

export function formatShortTick(displayValue, row = {}) {
  const safe = Math.max(0, Number.isFinite(displayValue) ? displayValue : 0);
  if (isCurrencyRow(row)) {
    if (safe >= 1_000_000) return `$${cleanTickNumber(safe / 1_000_000)}M`;
    if (safe >= 1_000) return `$${cleanTickNumber(safe / 1_000)}k`;
    return `$${cleanTickNumber(safe)}`;
  }
  if (isPercentRow(row)) {
    return `${cleanTickNumber(safe)}%`;
  }
  if (safe >= 1_000_000) return `${cleanTickNumber(safe / 1_000_000)}M`;
  if (safe >= 1_000) return `${cleanTickNumber(safe / 1_000)}k`;
  return cleanTickNumber(safe);
}

function buildTicks(min, step, intervals) {
  const list = [];
  for (let index = 0; index <= intervals; index += 1) {
    list.push(Number((min + index * step).toPrecision(10)));
  }
  return list;
}

export function computeYAxis(displayValues, row = {}) {
  const found = displayValues
    .filter((value) => value != null && Number.isFinite(value))
    .map((value) => Math.max(0, value));
  const percent = isPercentRow(row);
  if (!found.length) {
    const step = percent ? 10 : 1;
    return { domain: [0, step * 2], ticks: [0, step, step * 2] };
  }

  const low = Math.min(...found);
  const high = Math.max(...found);
  const ceiling = percent && high <= 100 ? 100 : Infinity;

  if (percent && low > 40) {
    const candidateSteps = [1, 2, 2.5, 5, 10, 20, 25, 50];
    for (const step of candidateSteps) {
      let min = Math.max(0, Math.floor((low - 1e-9) / step) * step);
      let max = Math.ceil(high / step) * step;
      if (max > ceiling) continue;
      let intervals = Math.round((max - min) / step);
      while (intervals < 2 && max + step <= ceiling) {
        max += step;
        intervals += 1;
      }
      while (intervals < 2 && min - step >= 0) {
        min -= step;
        intervals += 1;
      }
      if (intervals >= 2 && intervals <= 3 && min >= 0 && max <= ceiling) {
        const minClean = Number(min.toPrecision(10));
        const maxClean = Number(max.toPrecision(10));
        return { domain: [minClean, maxClean], ticks: buildTicks(minClean, step, intervals) };
      }
    }
    return { domain: [0, 100], ticks: [0, 50, 100] };
  }

  if (high <= 0) {
    const step = percent ? 10 : 1;
    return { domain: [0, step * 2], ticks: [0, step, step * 2] };
  }

  const startPower = Math.floor(Math.log10(high / 3)) - 1;
  const factors = [1, 2, 2.5, 5];
  for (let power = startPower; power <= startPower + 4; power += 1) {
    const scale = 10 ** power;
    for (const factor of factors) {
      const step = Number((factor * scale).toPrecision(10));
      const intervals = Math.max(2, Math.ceil(high / step));
      const max = Number((intervals * step).toPrecision(10));
      if (intervals <= 3 && max <= ceiling) {
        return { domain: [0, max], ticks: buildTicks(0, step, intervals) };
      }
    }
  }

  const fallbackMax = ceiling !== Infinity ? ceiling : high;
  return { domain: [0, fallbackMax], ticks: [0, fallbackMax / 2, fallbackMax] };
}

export function position(value, domain, start, end) {
  const span = domain[1] - domain[0];
  if (!span) return (start + end) / 2;
  return start + ((value - domain[0]) / span) * (end - start);
}

export function visibleXIndices(count, plotWidth) {
  if (count <= 0) return [];
  if (count === 1) return [0];
  if (count === 2) return [0, 1];
  const minGap = 38;
  const stepPx = plotWidth / (count - 1);
  if (stepPx >= minGap) return Array.from({ length: count }, (_, index) => index);
  const stride = Math.ceil(minGap / stepPx);
  const indices = [0];
  for (let index = stride; index < count - 1; index += stride) {
    if ((count - 1 - index) * stepPx >= minGap) indices.push(index);
  }
  indices.push(count - 1);
  return indices;
}

export function chartRowMap(charts) {
  const map = new Map();
  for (const section of charts?.sections || []) {
    for (const group of section.groups || []) {
      for (const row of group.rows || []) {
        map.set(`${row.product}:${row.measure_id}`, row);
      }
    }
  }
  return map;
}

export function hasTrendChart(row) {
  if (!row?.trend) return false;
  const published = (row.trend.series || []).filter((point) => point.value != null);
  return published.length >= 2;
}

export function hasBarChart(row) {
  if (!row || hasTrendChart(row)) return false;
  return (
    row.comparisons?.state?.value != null ||
    row.comparisons?.national?.value != null
  );
}

export function sectionChartInfo(rows = []) {
  let hasCharts = false;
  let hasTrend = false;
  let hasBars = false;
  let hasArea = false;
  let hasState = false;
  let hasNational = false;

  for (const row of rows) {
    if (hasTrendChart(row)) {
      hasCharts = true;
      hasTrend = true;
      hasArea = true;
      const isPlaces = row.product === "places" || row.trend.style === "dots_ci";
      if (!isPlaces) {
        if ((row.trend.state_series || []).some((point) => point.value != null)) {
          hasState = true;
        }
        if ((row.trend.national_series || []).some((point) => point.value != null)) {
          hasNational = true;
        }
      }
    } else if (hasBarChart(row)) {
      hasCharts = true;
      hasBars = true;
      if (row.value != null) hasArea = true;
      if (row.comparisons?.state?.value != null) hasState = true;
      if (row.comparisons?.national?.value != null) hasNational = true;
    }
  }

  return {
    hasCharts,
    hasArea,
    hasState,
    hasNational,
    barsOnly: hasBars && !hasTrend,
  };
}
