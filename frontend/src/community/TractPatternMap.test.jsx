import { describe, expect, it } from "vitest";
import { tractColor } from "./TractPatternMap";

describe("tract map status display", () => {
  it("shows published values in a blue scale and keeps missing statuses separate", () => {
    const low = tractColor(10, "available", 10, 30);
    const high = tractColor(30, "available", 10, 30);
    expect(low).not.toBe(high);
    expect(tractColor(0, "true_zero", 0, 30)).not.toBe(tractColor(null, "missing", 0, 30));
    expect(tractColor(null, "suppressed", 0, 30)).not.toBe(tractColor(null, "missing", 0, 30));
  });
});
