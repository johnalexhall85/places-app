import { describe, expect, it } from "vitest";
import {
  getProfileButtonCopy,
  resolveCdcFundingProfileTarget,
} from "./cdcFundingProfileTarget";
import { resolveSelectedAreaProfileTarget } from "./selectedAreaProfileTarget";

describe("cdcFundingProfileTarget", () => {
  it("enables the CDC state profile from a selected county context", () => {
    const target = resolveCdcFundingProfileTarget({
      selectedFeatureProps: {
        geo_level: "county",
        county_name: "Autauga",
        state_abbr: "AL",
        location_id: "01001",
      },
      basis: "prime",
      fundingGeographyMode: "recipient_location",
      appropriationType: "regular",
      normalized: true,
      fiscalYear: 2025,
      fundingOffice: "Office B",
    });

    expect(target.enabled).toBe(true);
    expect(target.id).toBe("AL");
    expect(target.href).toContain("/cdc-funding/state/AL?");
    expect(target.href).toContain("fy=2025");
    expect(target.href).toContain("normalized=true");
    expect(target.href).toContain("funding_office=Office+B");
  });

  it("falls back to the CDC state filter when nothing is selected", () => {
    const target = resolveCdcFundingProfileTarget({
      selectedFeatureProps: null,
      stateFilter: "ga",
      basis: "subaward",
      normalized: false,
    });

    expect(target.enabled).toBe(true);
    expect(target.id).toBe("GA");
    expect(target.href).toContain("/cdc-funding/state/GA?");
    expect(target.href).toContain("basis=subaward");
    expect(target.href).toContain("normalized=false");
  });

  it("disables the CDC state profile button when no state is inferable", () => {
    const target = resolveCdcFundingProfileTarget({
      selectedFeatureProps: {
        geo_level: "county",
        county_name: "Unknown County",
      },
      stateFilter: "",
    });

    expect(target.enabled).toBe(false);
    expect(target.href).toBeNull();
    expect(target.reason).toBe("Select a state first");
  });

  it("keeps non-CDC button labels on other sources", () => {
    expect(getProfileButtonCopy("cdc_funding").label).toBe("Open State Funding Profile");
    expect(getProfileButtonCopy("taggs").label).toBe("Open Funding Profile");
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
