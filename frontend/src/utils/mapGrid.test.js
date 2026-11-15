import { describe, expect, it } from "vitest";
import { gridForZoom } from "./mapGrid";

describe("shape tolerance by zoom", () => {
  it("is about one pixel, halves with each zoom level, and stays within the API limits", () => {
    expect(gridForZoom(4)).toBeCloseTo(0.0879, 4);
    expect(gridForZoom(5)).toBeCloseTo(gridForZoom(4) / 2, 3);
    expect(gridForZoom(9.75)).toBe(gridForZoom(9));
    expect(gridForZoom(9)).toBeLessThan(0.003);
    expect(gridForZoom(2)).toBeLessThanOrEqual(0.1);
    expect(gridForZoom(18)).toBeGreaterThan(0);
    expect(gridForZoom(undefined)).toBe(gridForZoom(4));
  });
});
