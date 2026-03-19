import { describe, expect, it } from "vitest";
import {
  getProfileButtonCopy,
  resolveCdcFundingProfileTarget,
} from "./cdcFundingProfileTarget";
import { resolveSelectedAreaProfileTarget } from "./selectedAreaProfileTarget";

describe("cdcFundingProfileTarget", () => {
  it("builds a state funding profile link from a selected county context", () => {
    const target = resolveCdcFundingProfileTarget({
      selectedFeatureProps: {
        geo_level: "county",
        county_name: "Autauga",
        state_abbr: "AL",
        location_id: "01001",
      },
      fiscalYear: 2025,
      metric: "funding_per_capita",
      fundingType: "emergency_response",
      cdcCenter: "public_health_preparedness_and_response",
      mechanism: "cooperative_agreements",
      recipientType: "state_governments",
      timeAggregation: "single_fiscal_year",
      geographyLevel: "county",
    });

    expect(target.enabled).toBe(true);
    expect(target.id).toBe("AL");
    expect(target.href).toContain("/cdc-funding/state/AL?");
    expect(target.href).toContain("fiscal_year=2025");
    expect(target.href).toContain("metric=funding_per_capita");
    expect(target.href).toContain("funding_type=emergency_response");
    expect(target.href).toContain("cdc_center=public_health_preparedness_and_response");
  });

  it("falls back to the state filter when nothing is selected", () => {
    const target = resolveCdcFundingProfileTarget({
      selectedFeatureProps: null,
      stateFilter: "ga",
      fundingType: "total_cdc_funding",
    });

    expect(target.enabled).toBe(true);
    expect(target.id).toBe("GA");
    expect(target.href).toContain("/cdc-funding/state/GA?");
    expect(target.href).toContain("funding_type=total_cdc_funding");
    expect(target.href).not.toContain("normalized=");
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
