import { expect, it } from "vitest";
import { legacyStateFundingTarget } from "./stateFundingRedirect";
it("redirects the legacy state profile to the rebuilt state route", () => {
  expect(legacyStateFundingTarget("?state=AL&metric=old")).toBe("/cdc-funding/state/AL");
});
