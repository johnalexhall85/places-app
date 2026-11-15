import { describe, expect, it } from "vitest";
import { formatIndicatorValue } from "./CommunityPages";

describe("community indicator display", () => {
  it("keeps missing, true zero, and published percentages distinct", () => {
    expect(formatIndicatorValue({ value: null, status_text: "Suppressed by the source" })).toBe("Suppressed by the source");
    expect(formatIndicatorValue({ value: 0, status: "true_zero", unit: "percent" })).toBe("0%");
    expect(formatIndicatorValue({ value: 12.3, unit: "percent" })).toBe("12.3%");
  });

  it("converts CMS stored proportions for display only", () => {
    const row = { value: 0.1863, storage_scale: "proportion_0_1", unit: "proportion" };
    expect(formatIndicatorValue(row)).toBe("18.63%");
    expect(row.value).toBe(0.1863);
  });
});
