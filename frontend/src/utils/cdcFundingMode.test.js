import { describe, expect, it } from "vitest";
import {
  CDC_DEFAULT_BUDGET_GROUNDED_REVIEW_MODE,
  buildCdcFundingUrlSearch,
  CDC_DEFAULT_GEOGRAPHY_LEVEL,
  CDC_DEFAULT_FUNDING_MODE,
  CDC_STATE_LAYER_MAX_ZOOM,
  getCdcFundingModeLabel,
  isChipAccountClassificationCdcFundingMode,
  isCanonicalCdcFundingMode,
  isBudgetGroundedCdcFundingMode,
  isVisibleCdcFundingMode,
  normalizeCdcFiscalYearToken,
  normalizeCdcFundingMode,
  readCdcFundingUrlState,
  resolveCdcFiscalYearSelection,
  resolveCdcRequestGeographyLevel,
} from "./cdcFundingMode";

describe("cdcFundingMode", () => {
  it("normalizes invalid values to the default mode", () => {
    expect(normalizeCdcFundingMode("chip_account_classification_v1")).toBe("chip_account_classification_v1");
    expect(normalizeCdcFundingMode("chip_legacy")).toBe("chip_legacy");
    expect(normalizeCdcFundingMode("raw_total")).toBe("raw_total");
    expect(normalizeCdcFundingMode("chip_normalized")).toBe("chip_normalized");
    expect(normalizeCdcFundingMode("chip_normalized_v1_1")).toBe("chip_normalized_v1_1");
    expect(normalizeCdcFundingMode("canonical_v1")).toBe("canonical_v1");
    expect(normalizeCdcFundingMode("budget_grounded_v1")).toBe("budget_grounded_v1");
    expect(normalizeCdcFundingMode("chip_v1_1_emergency")).toBe("chip_v1_1_emergency");
    expect(normalizeCdcFundingMode("bad-value")).toBe(CDC_DEFAULT_FUNDING_MODE);
  });

  it("recognizes the default, visible, canonical, and budget-grounded funding modes explicitly", () => {
    expect(CDC_DEFAULT_FUNDING_MODE).toBe("chip_account_classification_v1");
    expect(CDC_DEFAULT_BUDGET_GROUNDED_REVIEW_MODE).toBe("all_master_universe");
    expect(isChipAccountClassificationCdcFundingMode("chip_account_classification_v1")).toBe(true);
    expect(isVisibleCdcFundingMode("chip_account_classification_v1")).toBe(true);
    expect(isVisibleCdcFundingMode("chip_legacy")).toBe(true);
    expect(isVisibleCdcFundingMode("canonical_v1")).toBe(false);
    expect(isCanonicalCdcFundingMode("canonical_v1")).toBe(true);
    expect(isCanonicalCdcFundingMode("chip_normalized_v1_1")).toBe(false);
    expect(isBudgetGroundedCdcFundingMode("budget_grounded_v1")).toBe(true);
    expect(isBudgetGroundedCdcFundingMode("chip_normalized_v1_1")).toBe(false);
  });

  it("resolves custom funding mode labels from options", () => {
    expect(
      getCdcFundingModeLabel("chip_v1_1_emergency", [
        { value: "chip_v1_1_emergency", label: "CHIP v1.1 Emergency Classification" },
      ])
    ).toBe("CHIP v1.1 Emergency Classification");
  });

  it("reads CDC funding mode from shareable url state", () => {
    expect(readCdcFundingUrlState("?data_source=cdc_funding_state")).toEqual({
      dataSource: "cdc_funding_state",
      fundingMode: CDC_DEFAULT_FUNDING_MODE,
      geographyLevel: CDC_DEFAULT_GEOGRAPHY_LEVEL,
      isStateFundingRebuild: true,
    });
    expect(readCdcFundingUrlState("?data_source=cdc_funding&funding_mode=raw_total")).toEqual({
      dataSource: "cdc_funding",
      fundingMode: "raw_total",
      geographyLevel: CDC_DEFAULT_GEOGRAPHY_LEVEL,
      isStateFundingRebuild: false,
    });
    expect(readCdcFundingUrlState("?data_source=cdc_funding&geography_level=county")).toEqual({
      dataSource: "cdc_funding",
      fundingMode: CDC_DEFAULT_FUNDING_MODE,
      geographyLevel: "county",
      isStateFundingRebuild: false,
    });
    expect(readCdcFundingUrlState("?data_source=places")).toBeNull();
  });

  it("writes and clears CDC funding mode url state without affecting non-CDC urls", () => {
    expect(
      buildCdcFundingUrlSearch("funding_mode=chip_account_classification_v1", {
        activeDataSource: "cdc_funding_state",
        fundingMode: "chip_account_classification_v1",
      })
    ).toBe("data_source=cdc_funding_state");

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
      buildCdcFundingUrlSearch("data_source=cdc_funding_state", {
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

  it("falls back to state requests for county mode at low zoom", () => {
    expect(resolveCdcRequestGeographyLevel("county", CDC_STATE_LAYER_MAX_ZOOM)).toBe("state");
    expect(resolveCdcRequestGeographyLevel("county", CDC_STATE_LAYER_MAX_ZOOM + 1)).toBe("county");
    expect(resolveCdcRequestGeographyLevel("state", 3)).toBe("state");
    expect(resolveCdcRequestGeographyLevel("national", 3)).toBe("national");
  });

  it("normalizes fiscal year tokens and ignores invalid defaults", () => {
    expect(normalizeCdcFiscalYearToken(null)).toBe("");
    expect(normalizeCdcFiscalYearToken("")).toBe("");
    expect(normalizeCdcFiscalYearToken("0")).toBe("");
    expect(normalizeCdcFiscalYearToken("2025")).toBe("2025");
    expect(normalizeCdcFiscalYearToken("all", { allowAll: true })).toBe("all");

    expect(
      resolveCdcFiscalYearSelection({
        selectedValue: "",
        defaultValue: 0,
        availableValues: ["all", 2025, 2024],
      })
    ).toBe("2025");

    expect(
      resolveCdcFiscalYearSelection({
        selectedValue: "all",
        defaultValue: 2025,
        availableValues: ["all", 2025, 2024],
      })
    ).toBe("all");
  });
});
