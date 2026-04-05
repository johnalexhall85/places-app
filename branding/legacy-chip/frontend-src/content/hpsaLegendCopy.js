const DEFAULT_CUTPOINT_FALLBACK = "N/A";

function toFiniteNumber(value) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed.replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function formatCutpoint(value) {
  const numeric = toFiniteNumber(value);
  if (numeric == null) return DEFAULT_CUTPOINT_FALLBACK;
  if (Number.isInteger(numeric)) return `${numeric}`;
  return numeric.toFixed(1);
}

export function formatNumberWithCommas(value) {
  const numeric = toFiniteNumber(value);
  if (numeric == null) return "Not available";
  return Math.round(numeric).toLocaleString();
}

export function formatPercent(value, digits = 1) {
  const numeric = toFiniteNumber(value);
  if (numeric == null) return "Not available";
  return `${numeric.toFixed(digits)}%`;
}

export function formatRatio(value) {
  if (value == null) return "Not available";
  const text = String(value).trim();
  if (!text) return "Not available";

  const leftSide = text.includes(":")
    ? text.split(":")[0]
    : text.includes("/")
      ? text.split("/")[0]
      : text;

  const numeric = Number(leftSide.replace(/[^0-9.]/g, ""));
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return text;
  }
  return `${Math.round(numeric).toLocaleString()} residents per provider`;
}

export function getSeverityLabel(tier) {
  const normalized = Number(tier);
  if (normalized === 1) return "Lower";
  if (normalized === 2) return "Moderate";
  if (normalized === 3) return "High";
  if (normalized === 4) return "Very high";
  return "Not designated";
}

export function formatTierRanges(quartiles) {
  const q25 = formatCutpoint(quartiles?.q25);
  const q50 = formatCutpoint(quartiles?.q50);
  const q75 = formatCutpoint(quartiles?.q75);

  return [
    {
      tier: 1,
      severityLabel: "Lower shortage severity (Q1)",
      tierMeta: "Q1 (Tier 1)",
      rangeLabel: `≤ ${q25}`,
    },
    {
      tier: 2,
      severityLabel: "Moderate (Q2)",
      tierMeta: "Q2 (Tier 2)",
      rangeLabel: `> ${q25} to ≤ ${q50}`,
    },
    {
      tier: 3,
      severityLabel: "High (Q3)",
      tierMeta: "Q3 (Tier 3)",
      rangeLabel: `> ${q50} to ≤ ${q75}`,
    },
    {
      tier: 4,
      severityLabel: "Very high (Q4)",
      tierMeta: "Q4 (Tier 4)",
      rangeLabel: `> ${q75}`,
    },
  ];
}

export function buildInterpretationLines({ designated, domainLabel }) {
  if (!designated) {
    return [
      `This county is not currently designated as an HPSA for ${domainLabel} care.`,
    ];
  }
  return [
    `This county is federally designated as a Health Professional Shortage Area (HPSA) for ${domainLabel} care.`,
    "HPSA scores reflect shortage severity; higher scores indicate greater shortage.",
    "Severity tiers here are relative (quartiles) among designated counties.",
  ];
}
