// PDO brand guide map scale: Blues, light for lower values to Deep Navy for the highest.
// Lightness falls in even steps so neighbouring classes stay distinct, also in greyscale.
export const BLUES = ["#e3eef9", "#a9cce9", "#5fa3d6", "#0277bd", "#003f61"];

// Selected-area outline: Deep Navy over a white casing, visible on every class.
export const SELECTION_LINE = "#003f61";
export const SELECTION_CASING = "#ffffff";
export const HOVER_LINE = "#003f61";

// Colours for n classes (1 to 5), spread across the ramp so the ends are always used.
export function rampColors(count) {
  if (count >= 5) return BLUES;
  if (count === 4) return [BLUES[0], BLUES[1], BLUES[3], BLUES[4]];
  if (count === 3) return [BLUES[0], BLUES[2], BLUES[4]];
  if (count === 2) return [BLUES[1], BLUES[4]];
  return [BLUES[2]];
}

// Quintile cut points can repeat when many areas share a value (for example a count of 0).
// Repeated cuts are merged, so no class is empty by construction.
export function quantileCuts(breaks) {
  if (!Array.isArray(breaks)) return [];
  return [...new Set(breaks.filter((value) => Number.isFinite(value)))].sort((a, b) => a - b);
}

// Class index with inclusive upper bounds: value <= cut[i] falls in class i.
export function quantileClass(value, cuts) {
  const index = cuts.findIndex((upper) => value <= upper);
  return index < 0 ? cuts.length : index;
}

export function quantileColor(value, cuts) {
  return rampColors(cuts.length + 1)[quantileClass(value, cuts)];
}

export function quantileLabels(cuts, format) {
  if (!cuts.length) return [];
  return [
    `${format(cuts[0])} or less`,
    ...cuts.slice(1).map((upper, i) => `Above ${format(cuts[i])} to ${format(upper)}`),
    `Above ${format(cuts[cuts.length - 1])}`,
  ];
}
