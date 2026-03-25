import { describe, expect, it } from "vitest";
import {
  buildCdcFundingUrlSearch,
  CDC_DEFAULT_GEOGRAPHY_LEVEL,
  CDC_DEFAULT_FUNDING_MODE,
  getCdcFundingModeLabel,
  normalizeCdcFundingMode,
  readCdcFundingUrlState,
} from "./cdcFundingMode";

describe("cdcFundingMode", () => {
  it("normalizes invalid values to the default mode", () => {
    expect(normalizeCdcFundingMode("raw_total")).toBe("raw_total");
    expect(normalizeCdcFundingMode("chip_normalized")).toBe("chip_normalized");
    expect(normalizeCdcFundingMode("chip_normalized_v1_1")).toBe("chip_normalized_v1_1");
    expect(normalizeCdcFundingMode("chip_v1_1_emergency")).toBe("chip_v1_1_emergency");
    expect(normalizeCdcFundingMode("bad-value")).toBe(CDC_DEFAULT_FUNDING_MODE);
  });

  it("resolves custom funding mode labels from options", () => {
    expect(
      getCdcFundingModeLabel("chip_v1_1_emergency", [
        { value: "chip_v1_1_emergency", label: "CHIP v1.1 Emergency Classification" },
      ])
    ).toBe("CHIP v1.1 Emergency Classification");
  });

  it("reads CDC funding mode from shareable url state", () => {
    expect(readCdcFundingUrlState("?data_source=cdc_funding&funding_mode=raw_total")).toEqual({
      fundingMode: "raw_total",
      geographyLevel: CDC_DEFAULT_GEOGRAPHY_LEVEL,
    });
    expect(readCdcFundingUrlState("?data_source=cdc_funding&geography_level=county")).toEqual({
      fundingMode: CDC_DEFAULT_FUNDING_MODE,
      geographyLevel: "county",
    });
    expect(readCdcFundingUrlState("?data_source=places")).toBeNull();
  });

  it("writes and clears CDC funding mode url state without affecting non-CDC urls", () => {
    expect(
      buildCdcFundingUrlSearch("", {
        activeDataSource: "cdc_funding",
        fundingMode: "raw_total",
      })
    ).toBe("data_source=cdc_funding&funding_mode=raw_total");

    expect(
      buildCdcFundingUrlSearch("data_source=cdc_funding&funding_mode=chip_normalized_v1_1", {
        activeDataSource: "places",
        fundingMode: "chip_normalized_v1_1",
      })
    ).toBe("");

    expect(
      buildCdcFundingUrlSearch("year=2024", {
        activeDataSource: "places",
        fundingMode: "chip_normalized_v1_1",
      })
    ).toBe("year=2024");
  });
});
