const SVI_FIXED_BINS = [
  {
    key: "low",
    label: "Low",
    level: "low",
    min: 0.0,
    max: 0.25,
    rangeLabel: "0.0 — 0.25",
    colorIndex: 0,
  },
  {
    key: "low-medium",
    label: "Low-Medium",
    level: "low-medium",
    min: 0.25,
    max: 0.5,
    rangeLabel: "0.2501 — 0.50",
    colorIndex: 1,
  },
  {
    key: "medium-high",
    label: "Medium-High",
    level: "medium-high",
    min: 0.5,
    max: 0.75,
    rangeLabel: "0.5001 — 0.75",
    colorIndex: 2,
  },
  {
    key: "high",
    label: "High",
    level: "high",
    min: 0.75,
    max: 1.0,
    rangeLabel: "0.7501 — 1.0",
    colorIndex: 3,
  },
];

export const sviMeasureGroups = [
  {
    id: "overall",
    label: "SVI Themes and Indicators",
    options: [
      { label: "Overall SVI", measure_id: "RPL_THEMES" },
    ],
  },
  {
    id: "theme1",
    label: "Socioeconomic Status",
    options: [
      { label: "Socioeconomic Status", measure_id: "RPL_THEME1" },
      { label: "Below Poverty", measure_id: "EPL_POV150" },
      { label: "Unemployed", measure_id: "EPL_UNEMP" },
      { label: "Housing Cost Burden", measure_id: "EPL_HBURD" },
      { label: "No High School Diploma", measure_id: "EPL_NOHSDP" },
      { label: "No Health Insurance", measure_id: "EPL_UNINSUR" },
    ],
  },
  {
    id: "theme2",
    label: "Household Characteristics",
    options: [
      { label: "Household Characteristics", measure_id: "RPL_THEME2" },
      { label: "Aged 65 & Older", measure_id: "EPL_AGE65" },
      { label: "Aged 17 & Younger", measure_id: "EPL_AGE17" },
      { label: "Civilian with a Disability", measure_id: "EPL_DISABL" },
      { label: "Single-Parent Households", measure_id: "EPL_SNGPNT" },
      { label: "Limited English", measure_id: "EPL_LIMENG" },
    ],
  },
  {
    id: "theme3",
    label: "Racial & Ethnic Minority Status",
    options: [
      { label: "Racial & Ethnic Minority Status", measure_id: "RPL_THEME3" },
      { label: "Minority", measure_id: "EPL_MINRTY" },
    ],
  },
  {
    id: "theme4",
    label: "Housing Type & Transportation",
    options: [
      { label: "Housing Type & Transportation", measure_id: "RPL_THEME4" },
      { label: "Multi-Unit Structures", measure_id: "EPL_MUNIT" },
      { label: "Mobile Homes", measure_id: "EPL_MOBILE" },
      { label: "Crowding", measure_id: "EPL_CROWD" },
      { label: "No Vehicle", measure_id: "EPL_NOVEH" },
      { label: "Group Quarters", measure_id: "EPL_GROUPQ" },
    ],
  },
];

const SVI_LABEL_BY_ID = sviMeasureGroups.reduce((acc, group) => {
  group.options.forEach((option) => {
    acc[option.measure_id] = option.label;
  });
  return acc;
}, {});

export function getSviLabel(measureId) {
  const normalized = String(measureId ?? "").trim().toUpperCase();
  return SVI_LABEL_BY_ID[normalized] ?? normalized;
}

export function getSviLevel(value) {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return null;
  if (numeric <= 0.25) return "low";
  if (numeric <= 0.5) return "low-medium";
  if (numeric <= 0.75) return "medium-high";
  return "high";
}

export function getSviBins() {
  return SVI_FIXED_BINS.map((bin) => ({ ...bin }));
}
