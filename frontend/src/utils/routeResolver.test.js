import { describe, expect, it } from "vitest";
import { resolveRoute } from "./routeResolver";

describe("routeResolver", () => {
  it("sends home to the community landing page and keeps the map reachable", () => {
    expect(resolveRoute("/")).toEqual({ type: "community-landing" });
    expect(resolveRoute("/explore/map")).toEqual({ type: "map" });
    expect(resolveRoute("/community/county/37145")).toEqual({ type: "community-county", id: "37145" });
    expect(resolveRoute("/community/state/37")).toEqual({ type: "community-state", id: "37" });
    expect(resolveRoute("/compare")).toEqual({ type: "community-compare" });
    expect(resolveRoute("/districts")).toEqual({ type: "community-districts" });
    expect(resolveRoute("/district/cd/5401")).toEqual({ type: "community-district", id: "5401" });
    expect(resolveRoute("/area/acs-community")).toEqual({ type: "acs-community-area" });
    expect(resolveRoute("/area/brfss")).toEqual({ type: "brfss-state-area" });
    expect(resolveRoute("/topics")).toEqual({ type: "community-topics" });
    expect(resolveRoute("/topics/food-environment")).toEqual({ type: "community-topic", slug: "food-environment" });
    expect(resolveRoute("/about")).toEqual({ type: "community-about" });
    expect(resolveRoute("/methodology")).toEqual({ type: "community-methodology" });
  });
  it("matches the funding model builder route", () => {
    expect(resolveRoute("/funding-model-builder")).toEqual({ type: "funding-model-builder" });
  });

  it("matches the CDC funding overview route without shadowing state profiles", () => {
    expect(resolveRoute("/cdc-funding")).toEqual({ type: "cdc-funding-overview" });
    expect(resolveRoute("/cdc-funding/")).toEqual({ type: "cdc-funding-overview" });
  });

  it("matches the CDC state funding profile route", () => {
    expect(resolveRoute("/cdc-funding/state/AL")).toEqual({
      type: "cdc-state-funding-profile",
      id: "AL",
    });
  });

  it("keeps existing county and tract profile routes intact", () => {
    expect(resolveRoute("/taggs/funding-profile")).toEqual({ type: "map" });
    expect(resolveRoute("/profile/county/01001")).toEqual({ type: "profile-county", id: "01001" });
    expect(resolveRoute("/profile/tract/01001020100")).toEqual({
      type: "profile-tract",
      id: "01001020100",
    });
  });
});
