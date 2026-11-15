// Hover tooltip shared by the legacy map and the /area maps.
export const MAP_HOVER_TOOLTIP_OPTIONS = {
  sticky: true,
  direction: "top",
  opacity: 0.95,
  interactive: false,
  className: "pdo-map-tooltip",
};

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}

export function formatTooltipMetaLine(valueText, periodText) {
  const safeValue = String(valueText ?? "").trim() || "No data";
  const safePeriod = String(periodText ?? "").trim();
  if (!safePeriod) return safeValue;
  return `${safeValue} • ${safePeriod}`;
}

export function formatTooltipExplanationLine(value) {
  const text = String(value ?? "").trim();
  return text ? `<br/><span style="color:#546E7A;">${text}</span>` : "";
}

// Hover tooltips are skipped on touch pointers, where they would stick after a tap.
export function isCoarsePointer() {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(pointer: coarse)").matches;
}

// Area name, measure, "value • period", then one muted explanation line. Inputs are escaped here.
export function areaTooltipHtml({ area, measure, value, period, explanation }) {
  return `${escapeHtml(area)}<br/>${escapeHtml(measure)}<br/>${escapeHtml(formatTooltipMetaLine(value, period))}`
    + formatTooltipExplanationLine(escapeHtml(explanation));
}
