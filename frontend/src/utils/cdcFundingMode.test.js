import { describe, expect, it } from "vitest";
import {
  buildCdcFundingUrlSearch,
  CDC_DEFAULT_GEOGRAPHY_LEVEL,
  CDC_DEFAULT_FUNDING_MODE,
  normalizeCdcFundingMode,
  readCdcFundingUrlState,
} from "./cdcFundingMode";

describe("cdcFundingMode", () => {
  it("normalizes invalid values to the default mode", () => {
    expect(normalizeCdcFundingMode("raw_total")).toBe("raw_total");
    expect(normalizeCdcFundingMode("chip_normalized")).toBe("chip_normalized");
    expect(normalizeCdcFundingMode("bad-value")).toBe(CDC_DEFAULT_FUNDING_MODE);
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
      buildCdcFundingUrlSearch("data_source=cdc_funding&funding_mode=chip_normalized", {
        activeDataSource: "places",
        fundingMode: "chip_normalized",
      })
    ).toBe("");

    expect(
      buildCdcFundingUrlSearch("year=2024", {
        activeDataSource: "places",
        fundingMode: "chip_normalized",
      })
    ).toBe("year=2024");
  });
});
