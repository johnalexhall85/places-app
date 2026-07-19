import { describe, expect, it } from "vitest";
import {
  buildFundingLegendBins,
  buildStateFundingAwardBadges,
  buildStateFundingSummaryCards,
  formatFundingCount,
  formatFundingCurrency,
  getFundingFiscalYearLabel,
  getFundingMechanismLabel,
  getFundingViewModeLabel,
  getFundingViewModeMethodologyNote,
  joinStateFundingRowsToGeometry,
  normalizeStateCode,
  normalizeStateFips,
  STATE_FUNDING_COVID_ERA_IMMUNIZATION_BADGE_LABEL,
  STATE_FUNDING_COVID_ERA_IMMUNIZATION_SUMMARY_LABEL,
  STATE_FUNDING_VFC_IMMUNIZATION_BADGE_LABEL,
} from "./stateFundingMap";

describe("stateFundingMap utilities", () => {
  it("normalizes state FIPS and codes", () => {
    expect(normalizeStateFips("1")).toBe("01");
    expect(normalizeStateFips("06")).toBe("06");
    expect(normalizeStateFips("006")).toBe("");
    expect(normalizeStateCode(" al ")).toBe("AL");
    expect(normalizeStateCode("Alabama")).toBe("");
  });

  it("joins funding rows to geometry by state FIPS first", () => {
    const geojson = {
      type: "FeatureCollection",
      features: [
        { type: "Feature", properties: { statefp: "01", state_abbr: "ZZ", state_desc: "Alabama" }, geometry: null },
      ],
    };
    const rows = [
      {
        state_fips: "01",
        state_code: "AL",
        state_name: "Alabama",
        total_obligations: "1000.50",
        transaction_count: 3,
        award_count: 2,
        recipient_count: 1,
      },
    ];

    const joined = joinStateFundingRowsToGeometry(geojson, rows);

    expect(joined.features[0].properties.state_code).toBe("AL");
    expect(joined.features[0].properties.value).toBe(1000.5);
    expect(joined.features[0].properties.funding_row_present).toBe(true);
  });

  it("falls back to joining funding rows by state code", () => {
    const geojson = {
      type: "FeatureCollection",
      features: [
        { type: "Feature", properties: { state_abbr: "CA", state_desc: "California" }, geometry: null },
      ],
    };
    const rows = [
      {
        state_fips: "06",
        state_code: "CA",
        state_name: "California",
        total_obligations: 2500,
      },
    ];

    const joined = joinStateFundingRowsToGeometry(geojson, rows);

    expect(joined.features[0].properties.state_fips).toBe("06");
    expect(joined.features[0].properties.total_obligations).toBe(2500);
  });

  it("treats numeric state_abbr geometry values as state FIPS", () => {
    const geojson = {
      type: "FeatureCollection",
      features: [
        { type: "Feature", properties: { state_abbr: "72", state_desc: "72" }, geometry: null },
      ],
    };
    const rows = [
      {
        state_fips: "72",
        state_code: "PR",
        state_name: "Puerto Rico",
        total_obligations: 750,
      },
    ];

    const joined = joinStateFundingRowsToGeometry(geojson, rows);

    expect(joined.features[0].properties.state_fips).toBe("72");
    expect(joined.features[0].properties.state_code).toBe("PR");
    expect(joined.features[0].properties.state_name).toBe("Puerto Rico");
    expect(joined.features[0].properties.value).toBe(750);
  });

  it("keeps no-data states neutral", () => {
    const geojson = {
      type: "FeatureCollection",
      features: [
        { type: "Feature", properties: { state_abbr: "VT", state_desc: "Vermont" }, geometry: null },
      ],
    };

    const joined = joinStateFundingRowsToGeometry(geojson, []);

    expect(joined.features[0].properties.value).toBeNull();
    expect(joined.features[0].properties.funding_row_present).toBe(false);
  });

  it("builds quantile-style funding legend bins", () => {
    const bins = buildFundingLegendBins([
      { total_obligations: 10 },
      { total_obligations: 20 },
      { total_obligations: 30 },
      { total_obligations: 40 },
      { total_obligations: 50 },
    ], 2);

    expect(bins).toHaveLength(2);
    expect(bins[0].min).toBe(10);
    expect(bins[1].max).toBe(50);
    expect(bins[0].label).toContain("$");
  });

  it("formats currency, counts, mechanisms, and fiscal years", () => {
    expect(formatFundingCurrency(568432986.49)).toBe("$568,432,986");
    expect(formatFundingCurrency(568432986.49, { compact: true })).toBe("$568.4M");
    expect(formatFundingCount(693)).toBe("693");
    expect(getFundingMechanismLabel("contracts")).toBe("Contracts");
    expect(getFundingMechanismLabel("all")).toBe("All Funding Mechanisms");
    expect(getFundingFiscalYearLabel(2026)).toBe("FY2026");
    expect(getFundingViewModeLabel()).toBe("USAspending Obligations");
    expect(getFundingViewModeLabel("funding_profiles_comparable")).toBe("CDC Funding Profiles Comparable");
    expect(getFundingViewModeMethodologyNote("standard_usaspending")).toContain("flagged but not automatically excluded");
    expect(getFundingViewModeMethodologyNote("funding_profiles_comparable")).toContain("approximates CDC Funding Profiles");
    expect(getFundingViewModeMethodologyNote("funding_profiles_comparable")).toContain("includes VFC / Immunization Cooperative Agreement obligations");
    expect(getFundingViewModeMethodologyNote("funding_profiles_comparable")).toContain("FY2021 includes a large COVID-era immunization response block");
    expect(getFundingViewModeMethodologyNote("funding_profiles_comparable")).toContain("unmapped obligations are included in the national total");
    expect(STATE_FUNDING_VFC_IMMUNIZATION_BADGE_LABEL).toBe("VFC / Immunization Cooperative Agreement");
    expect(STATE_FUNDING_VFC_IMMUNIZATION_BADGE_LABEL).not.toContain("purchase");
  });

  it("adds the COVID-era immunization summary card only when nonzero", () => {
    const withoutCovidCard = buildStateFundingSummaryCards({
      total_obligations: 100,
      covid_era_immunization_response_excluded_obligations: 0,
    });
    const withCovidCard = buildStateFundingSummaryCards({
      total_obligations: 100,
      covid_era_immunization_response_excluded_obligations: 7980141719,
    });

    expect(withoutCovidCard.map(([label]) => label)).not.toContain(STATE_FUNDING_COVID_ERA_IMMUNIZATION_SUMMARY_LABEL);
    expect(withCovidCard).toContainEqual([
      STATE_FUNDING_COVID_ERA_IMMUNIZATION_SUMMARY_LABEL,
      7980141719,
      "currency",
    ]);
  });

  it("builds funding award badges including COVID-era immunization response", () => {
    const badges = buildStateFundingAwardBadges({
      has_overall_award_supplemental_history: true,
      is_likely_vfc: true,
      is_covid_era_immunization_response: true,
      funding_profiles_comparison_excluded: false,
    });

    expect(badges).toContain("Supplemental history");
    expect(badges).toContain(STATE_FUNDING_VFC_IMMUNIZATION_BADGE_LABEL);
    expect(badges).toContain(STATE_FUNDING_COVID_ERA_IMMUNIZATION_BADGE_LABEL);
    expect(STATE_FUNDING_COVID_ERA_IMMUNIZATION_BADGE_LABEL).toBe("COVID-era immunization response");
  });
});
