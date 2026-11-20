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
    expect(screen.getAllByRole("link", { name: "State funding page" })[0].getAttribute("href"))
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

  it("puts labeled details in a full-width row", async () => {
    api.grantAward.mockResolvedValue({ ...fixture.awards[0], address: { line1: "123 MAIN STREET" },
      categories: [], period_of_performance: {}, cfda: {}, abstract: "An abstract",
      business_types: ["STATE GOVERNMENT"], congressional_district: "CA-01",
      congressional_district_source: "usaspending_current", abstract_source: "taggs",
      subawards: null });
    render(<CdcGrantHistory nofo="ps212102" />);
    await screen.findByRole("heading", { name: "Prevention grant" });
    fireEvent.click(within(document.getElementById("state-CA"))
      .getByRole("button", { name: "Health One" }));
    expect(await screen.findByText("HHS TAGGS recipient class")).toBeTruthy();
    expect(screen.getByText("USAspending, current district")).toBeTruthy();
    expect(screen.getByText("Abstract source: HHS TAGGS")).toBeTruthy();
    expect(screen.getByText("123 Main Street")).toBeTruthy();
    expect(screen.getAllByText("State Government", { exact: true }).length).toBeGreaterThan(0);
    const detailCell = document.querySelector(".gh-detail-row > td");
    expect(detailCell?.getAttribute("colspan")).toBe("4");
    expect(detailCell?.closest("tr")?.previousElementSibling?.cells.length).toBe(4);
    expect(detailCell?.closest(".gh-awards-scroll")).toBeTruthy();
    expect(detailCell?.closest("tr")?.previousElementSibling?.cells[0].dataset.label).toBe("Recipient");
  });

  it.each([
    ["usaspending_business_types", "usaspending_original", "usaspending",
      "USAspending business types", "USAspending, district at award", "Abstract source: USAspending"],
    ["none", "taggs", null, null, "HHS TAGGS", null],
  ])("shows readable source labels for %s and %s", async (
    recipientSource, districtSource, abstractSource, recipientLabel, districtLabel, abstractLabel,
  ) => {
    api.grantAward.mockResolvedValue({ ...fixture.awards[0], address: {}, categories: [],
      period_of_performance: {}, cfda: {}, abstract: "An abstract", business_types: [],
      recipient_type_source: recipientSource, congressional_district_source: districtSource,
      abstract_source: abstractSource, subawards: null });
    render(<CdcGrantHistory nofo="ps212102" />);
    await screen.findByRole("heading", { name: "Prevention grant" });
    fireEvent.click(within(document.getElementById("state-CA"))
      .getByRole("button", { name: "Health One" }));
    await screen.findByText("An abstract");
    if (recipientLabel) expect(screen.getByText(recipientLabel)).toBeTruthy();
    else expect(screen.queryByText(/recipient class|business types/i, { selector: "small" })).toBeNull();
    expect(screen.getByText(districtLabel)).toBeTruthy();
    if (abstractLabel) expect(screen.getByText(abstractLabel)).toBeTruthy();
    else expect(screen.queryByText(/Abstract source:/)).toBeNull();
  });

  it("deduplicates the FON, anchors positive bars left, and limits states to ten", async () => {
    const states = Array.from({ length: 12 }, (_, index) => ({
      state: `S${index}`, name: `State ${index}`, latest_fy_total: 100 - index,
      current_count: 1, past_count: 0,
    }));
    api.grantHistory.mockResolvedValue({ ...fixture,
      nofo: { ...fixture.nofo, fon_variants: [fixture.nofo.fon_display, "PS21-2102"] },
      by_state: states,
      by_fiscal_year: [{ fiscal_year: 2026, regular: 100, supplemental: 0, total: 100 }],
    });
    render(<CdcGrantHistory nofo="ps212102" />);
    await screen.findByRole("heading", { name: "Prevention grant" });
    expect(screen.getByText(/Also recorded as PS21-2102/)).toBeTruthy();
    expect(screen.queryByText(/Also recorded as CDC-RFA-PS21-2102/)).toBeNull();
    expect(document.querySelector(".gh-positive-only .gh-zero")).toBeTruthy();
    expect(document.querySelectorAll(".gh-states > div")).toHaveLength(10);
    fireEvent.click(screen.getByRole("button", { name: "Show all 12 states" }));
    expect(document.querySelectorAll(".gh-states > div")).toHaveLength(12);
  });

  it("keeps past-only states and State not recorded last for every sort and direction", async () => {
    const byState = [
      { state: "TX", name: "Texas", latest_fy_total: 2_000_000, current_count: 1, past_count: 0 },
      { state: "CA", name: "California", latest_fy_total: 500_000, current_count: 1, past_count: 0 },
      { state: "WY", name: "Wyoming", latest_fy_total: -5_000, current_count: 1, past_count: 0 },
      { state: "PR", name: "Puerto Rico", latest_fy_total: null, current_count: 0, past_count: 1 },
      { state: "__", name: "State not recorded", latest_fy_total: 1_268_643,
        current_count: 1, past_count: 0 },
    ];
    api.grantHistory.mockResolvedValue({ ...fixture,
      nofo: { ...fixture.nofo, nofo_key: "TU240137", fon_display: "CDC-RFA-TU-24-0137" },
      by_state: byState,
      awards: [award("tx", "TX", 2_000_000), award("ca", "CA", 500_000),
        award("wy", "WY", -5_000), award("pr", "PR", 100, false),
        award("unknown", "__", 1_268_643)],
    });
    render(<CdcGrantHistory nofo="CDC-RFA-TU-24-0137" />);
    await screen.findByRole("heading", { name: "Prevention grant" });
    const order = () => [...document.querySelectorAll(".gh-group")].map((group) => group.id);
    for (const sort of ["state_total", "state_name", "recipient", "recipient_type", "amount"]) {
      fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: sort } });
      for (const dir of ["asc", "desc"]) {
        fireEvent.change(screen.getByLabelText("Direction"), { target: { value: dir } });
        expect(order().slice(-2)).toEqual(["state-PR", "state-__"]);
        expect(order().slice(0, 3).sort()).toEqual(["state-CA", "state-TX", "state-WY"]);
      }
    }
    fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "state_total" } });
    fireEvent.change(screen.getByLabelText("Direction"), { target: { value: "asc" } });
    expect(order()).toEqual(["state-WY", "state-CA", "state-TX", "state-PR", "state-__"]);
  });
});
