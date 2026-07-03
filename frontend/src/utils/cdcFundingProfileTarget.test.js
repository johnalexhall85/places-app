import { describe, expect, it, vi } from "vitest";
import {
  getProfileButtonCopy,
  openProfileTargetInNewTab,
  resolveCdcFundingProfileTarget,
} from "./cdcFundingProfileTarget";
import { resolveSelectedAreaProfileTarget } from "./selectedAreaProfileTarget";

describe("cdcFundingProfileTarget", () => {
  it("builds a state funding profile link from a selected state context", () => {
    const target = resolveCdcFundingProfileTarget({
      selectedFeatureProps: {
        geo_level: "state",
        state_abbr: "GA",
        location_id: "GA",
      },
      fiscalYear: 2022,
      metric: "total_funding",
      fundingType: "total_cdc_funding",
      fundingMode: "canonical_v1",
      cdcCenter: "public_health_preparedness_and_response",
      timeAggregation: "multi_year_total",
      includeEmergency: false,
      includeSupplemental: false,
      includePphf: true,
      includeTransfers: true,
      includePendingReview: true,
      reviewMode: "all_master_universe",
      geographyLevel: "state",
    });

    expect(target.enabled).toBe(true);
    expect(target.id).toBe("GA");
    expect(target.href).toContain("/cdc-funding/state/GA?");
    expect(target.href).toContain("fy=2022");
    expect(target.href).toContain("metric=total_funding");
    expect(target.href).toContain("funding_type=total_cdc_funding");
    expect(target.href).toContain("mode=canonical_v1");
    expect(target.href).toContain("cdc_center=public_health_preparedness_and_response");
    expect(target.href).toContain("time_aggregation=multi_year_total");
    expect(target.href).toContain("include_emergency=false");
    expect(target.href).toContain("include_supplemental=false");
    expect(target.href).toContain("include_pphf=true");
    expect(target.href).toContain("include_transfers=true");
    expect(target.href).toContain("include_pending_review=true");
    expect(target.href).toContain("review_mode=all_master_universe");
  });

  it("keeps CHIP scope filters on state funding profile links", () => {
    const target = resolveCdcFundingProfileTarget({
      selectedFeatureProps: {
        geo_level: "state",
        state_abbr: "AL",
      },
      fiscalYear: 2023,
      fundingMode: "chip_account_classification_v1",
      fundingScopePreset: "regular_grants_coops",
      awardType: "grants_coops",
      emergencySupplementalScope: "exclude",
      reviewStatus: "reviewed_plus_needs_review",
      includePphf: true,
      transfersScope: "cdc_relevant_only",
      dataSourceScope: "combined",
      geographyLevel: "state",
    });

    expect(target.href).toContain("fy=2023");
    expect(target.href).toContain("funding_scope_preset=regular_grants_coops");
    expect(target.href).toContain("award_type=grants_coops");
    expect(target.href).toContain("emergency_supplemental_scope=exclude");
    expect(target.href).toContain("review_status=reviewed_plus_needs_review");
    expect(target.href).toContain("include_pphf=true");
    expect(target.href).toContain("transfers_scope=cdc_relevant_only");
    expect(target.href).toContain("data_source_scope=combined");
  });

  it("uses the selected county's state when county selection is the active CDC pattern", () => {
    const target = resolveCdcFundingProfileTarget({
      selectedFeatureProps: {
        geo_level: "county",
        county_name: "Autauga",
        state_abbr: "AL",
        location_id: "01001",
      },
      fiscalYear: 2025,
      fundingType: "emergency_response",
      fundingMode: "raw_total",
      geographyLevel: "county",
    });

    expect(target.enabled).toBe(true);
    expect(target.id).toBe("AL");
    expect(target.href).toContain("/cdc-funding/state/AL?");
    expect(target.href).toContain("fy=2025");
    expect(target.href).toContain("mode=raw_total");
  });

  it("opens the resolved CDC state profile in a new tab", () => {
    const openWindow = vi.fn();
    const target = resolveCdcFundingProfileTarget({
      selectedFeatureProps: {
        geo_level: "state",
        state_abbr: "AL",
      },
      fiscalYear: 2024,
      fundingMode: "raw_total",
      geographyLevel: "state",
    });

    expect(openProfileTargetInNewTab(target, openWindow)).toBe(true);
    expect(openWindow).toHaveBeenCalledWith(
      expect.stringContaining("/cdc-funding/state/AL?"),
      "_blank",
      "noopener,noreferrer"
    );
  });

  it("disables the CDC state profile button for national geography", () => {
    const target = resolveCdcFundingProfileTarget({
      selectedFeatureProps: {
        geo_level: "state",
        state_abbr: "AL",
      },
      geographyLevel: "national",
    });

    expect(target.enabled).toBe(false);
    expect(target.href).toBeNull();
    expect(target.reason).toBe("Select a state first");
  });

  it("disables the CDC state profile button until a state can be resolved from selection", () => {
    const target = resolveCdcFundingProfileTarget({
      selectedFeatureProps: null,
      geographyLevel: "state",
    });

    expect(target.enabled).toBe(false);
    expect(target.href).toBeNull();
    expect(target.reason).toBe("Select a state first");
  });

  it("keeps non-CDC button labels on other sources", () => {
    expect(getProfileButtonCopy("cdc_funding").label).toBe("Open State Funding Profile");
    expect(getProfileButtonCopy("places").label).toBe("Open County/Tract Profile");
  });

  it("preserves county and tract profile targets for non-CDC maps", () => {
    const countyTarget = resolveSelectedAreaProfileTarget({
      selectedFeatureProps: {
        geo_level: "county",
        county_fips: "01001",
      },
      tractsActive: false,
    });
    const tractTarget = resolveSelectedAreaProfileTarget({
      selectedFeatureProps: {
        geo_level: "tract",
        geoid: "01001020100",
      },
      tractsActive: true,
    });

    expect(countyTarget.href).toBe("/profile/county/01001");
    expect(tractTarget.href).toBe("/profile/tract/01001020100");
  });
});
