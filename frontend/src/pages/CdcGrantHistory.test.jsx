import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CdcGrantHistory from "./CdcGrantHistory";

vi.mock("../components/SiteHeader", () => ({ default: () => <header>Header</header> }));
vi.mock("../components/Footer", () => ({ default: () => <footer>Footer</footer> }));
vi.mock("../api/stateFunding", () => ({
  grantHistory: vi.fn(), grantAward: vi.fn(), grantHistoryCsvUrl: vi.fn(() => "/grant.csv"),
}));
const api = await import("../api/stateFunding");
const award = (key, state, amount, current = true) => ({
  award_unique_key: key, award_id: key, state, split_state: key === "split", is_current: current,
  recipient_name: key === "split" ? "Health One" : "Past Agency", recipient_uei: key,
  city: "City", recipient_type: "State Government", recipient_type_source: "taggs_recipient_class",
  project_title: "Prevention project", latest_fy_amount: current ? { total: amount } : null,
  history: [{ fiscal_year: 2025, regular: amount, supplemental: 0, total: amount }],
  all_years_total: amount, last_fy: current ? 2026 : 2025, subawards: null,
});
const fixture = {
  nofo: { nofo_key: "PS212102", fon_display: "CDC-RFA-PS21-2102", fon_variants: [],
    grant_name: "Prevention grant", name_source: "grants_gov_nofo_title", cfda: [],
    awarding_offices: [], period_of_performance: {}, categories: [] },
  latest_fy: 2026, latest_fy_note: null, fiscal_years: [2026, 2025],
  totals: { latest_fy: { total: -10, regular: -10, supplemental: 0, recipient_count: 1,
    state_count: 2 }, all_years: { total: 20 } },
  by_fiscal_year: [{ fiscal_year: 2025, regular: 30, supplemental: 0, total: 30 },
    { fiscal_year: 2026, regular: -10, supplemental: 0, total: -10 }],
  by_state: [{ state: "CA", name: "California", latest_fy_total: -6, current_count: 1, past_count: 1 },
    { state: "TX", name: "Texas", latest_fy_total: -4, current_count: 1, past_count: 0 }],
  awards: [award("split", "CA", -6), award("split", "TX", -4), award("past", "CA", 30, false)],
  citation: "Source: USAspending · FY2026 P12", notes: ["A source note."],
};

beforeEach(() => {
  window.history.replaceState({}, "", "/cdc-funding/grant/ps212102");
  api.grantHistory.mockReset().mockResolvedValue(fixture);
  api.grantAward.mockReset().mockResolvedValue({ ...fixture.awards[0], address: {}, categories: [],
    period_of_performance: {}, cfda: {}, abstract: "An abstract", business_types: [],
    subawards: { subawardee_count: 0, action_count: 0, reported_amount: 0 } });
});

describe("CDC grant history", () => {
  it("groups split awards, signs negatives, and canonicalizes the URL", async () => {
    render(<CdcGrantHistory nofo="ps212102" />);
    expect(await screen.findByRole("heading", { name: "Prevention grant" })).toBeTruthy();
    expect(window.location.pathname).toBe("/cdc-funding/grant/CDC-RFA-PS21-2102");
    expect(screen.getAllByText("−$6").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Split across states").length).toBe(2);
    expect(screen.getAllByRole("link", { name: "State profile" })[0].getAttribute("href"))
      .toContain("q=CDC-RFA-PS21-2102");
  });

  it("searches, sorts, hides past recipients, and lazily expands", async () => {
    render(<CdcGrantHistory nofo="ps212102" />);
    await screen.findByRole("heading", { name: "Prevention grant" });
    expect(screen.getByText("Past Agency")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Show past recipients"));
    expect(screen.queryByText("Past Agency")).toBeNull();
    fireEvent.change(screen.getByLabelText("Search recipients"), { target: { value: "health prevention" } });
    expect(window.location.search).toContain("q=health+prevention");
    fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "state_name" } });
    expect(window.location.search).toContain("sort=state_name");
    expect(api.grantAward).not.toHaveBeenCalled();
    const ca = document.getElementById("state-CA");
    fireEvent.click(within(ca).getByRole("button", { name: "Health One" }));
    await waitFor(() => expect(api.grantAward).toHaveBeenCalledWith(
      "CDC-RFA-PS21-2102", "split", expect.anything()));
    expect(await screen.findByText("An abstract")).toBeTruthy();
    expect(document.querySelector('[data-subawards-for="split"]')).toBeTruthy();
  });
});
