import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CdcStateFundingProfile from "./CdcStateFundingProfile";

vi.mock("../components/SiteHeader", () => ({ default: () => <header>Header</header> }));
vi.mock("../components/Footer", () => ({ default: () => <footer>Footer</footer> }));
vi.mock("../api/stateFunding", () => ({
  fiscalYears: vi.fn(), stateSummary: vi.fn(), stateGrants: vi.fn(), grantsCsvUrl: vi.fn(() => "/download.csv"),
}));
const api = await import("../api/stateFunding");
const summary = { state: { code: "AL", name: "Alabama" }, fiscal_year: 2026, period: "FY2026 P12",
  totals: { total: 100, regular: 120, supplemental: -20, award_count: 1, recipient_count: 1 },
  by_category: [{ code: "HIV", name: "HIV prevention", basis: "cdc_operating_plan",
    regular: 120, supplemental: -20, total: 100,
    accounts: [{ symbol: "075-0950", name: "Account", regular: 120, supplemental: -20, total: 100 }] }],
  categories_available: [{ code: "HIV", name: "HIV prevention", basis: "cdc_operating_plan" }],
  citation: "Source: USAspending · FY2026 P12", notes: [] };
const grant = { award_unique_key: "ASST_1", award_id: "FAIN1", award_type: "grant", grant_name: "Public health grant",
  name_source: "grants_gov_nofo_title", project_title: "Project title", description: "Full award description",
  recipient_name: "Alabama Health", is_state_government: true, fon: "CDC-RFA-X", cfda_number: "93.1",
  cfda_title: "Listing", accounts: [{ symbol: "075-0950", name: "Account", regular: 120, supplemental: -20 }],
  categories: [{ code: "HIV", name: "HIV prevention", regular: 120, supplemental: -20 }],
  regular: 120, supplemental: -20, total: 100, usaspending_url: "https://usaspending.gov/award/1" };

beforeEach(() => {
  window.history.replaceState({}, "", "/cdc-funding/state/AL");
  api.fiscalYears.mockResolvedValue({ fiscal_years: [2026, 2025], default: 2026 });
  api.stateSummary.mockResolvedValue(summary);
  api.stateGrants.mockResolvedValue({ fiscal_year: 2026, filters: {}, page: 1, page_size: 25, total_rows: 1, rows: [grant], sum_total: 100, citation: summary.citation });
});

describe("CDC state funding profile", () => {
  it("renders funding, signed reductions, and award details", async () => {
    render(<CdcStateFundingProfile stateCode="AL" />);
    expect(await screen.findByText("CDC grants to recipients in Alabama")).toBeTruthy();
    expect(screen.getAllByText("−$20").length).toBeGreaterThan(0);
    expect(screen.getByText("Funding by budget category")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Funding totals" }))
      .getByText("Supplemental (emergency)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Public health grant" }));
    expect(screen.getByText("Full award description")).toBeTruthy();
    expect(screen.getByText("View on USAspending")).toBeTruthy();
  });
  it("shows only funded bar rows and expands only categories with multiple accounts", async () => {
    api.stateSummary.mockResolvedValue({ ...summary, by_category: [
      { ...summary.by_category[0], regular: 120, supplemental: 0 },
      { code: "OTHER", name: "Other programs", regular: 0, supplemental: -20,
        accounts: [
          { symbol: "075-0100", name: "First account", regular: 0, supplemental: -10 },
          { symbol: "075-0200", name: "Second account", regular: 0, supplemental: -10 },
        ] },
      { code: "ZERO", name: "Zero category", regular: 0, supplemental: 0, accounts: [] },
    ] });
    render(<CdcStateFundingProfile stateCode="AL" />);
    const single = (await screen.findByRole("heading", { name: "HIV prevention" })).closest(".sf-category");
    expect(within(single).getByText("Federal account 075-0950").getAttribute("title")).toBe("Account");
    expect(Array.from(single.querySelectorAll(".sf-bar-row"), (row) =>
      row.querySelector("span").textContent)).toEqual(["Regular"]);
    expect(within(single).queryByText("Federal accounts (1)")).toBeNull();
    const multiple = screen.getByRole("heading", { name: "Other programs" }).closest(".sf-category");
    expect(Array.from(multiple.querySelectorAll(".sf-bar-row"), (row) =>
      row.querySelector("span").textContent)).toEqual(["Supplemental"]);
    expect(within(multiple).getByText("Federal accounts (2)")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Zero category" })).toBeNull();
  });
  it("updates filters and the shareable URL", async () => {
    render(<CdcStateFundingProfile stateCode="AL" />);
    await screen.findByText("CDC grants to recipients in Alabama");
    fireEvent.change(screen.getByLabelText("Funding type"), { target: { value: "supplemental" } });
    await waitFor(() => expect(api.stateSummary).toHaveBeenCalledWith("AL", expect.objectContaining({ funding_type: "supplemental" }), expect.anything()));
    expect(window.location.search).toContain("funding_type=supplemental");
    fireEvent.change(screen.getByLabelText("Budget category"), { target: { value: "HIV" } });
    await waitFor(() => expect(api.stateSummary).toHaveBeenCalledWith("AL", expect.objectContaining({ category: "HIV" }), expect.anything()));
    expect(window.location.search).toContain("category=HIV");
  });
  it("searches and sorts grants", async () => {
    render(<CdcStateFundingProfile stateCode="AL" />);
    await screen.findByText("CDC grants to recipients in Alabama");
    fireEvent.change(screen.getByLabelText("Search grants"), { target: { value: "FAIN1 health" } });
    await waitFor(() => expect(api.stateGrants).toHaveBeenCalledWith("AL", expect.objectContaining({ q: "FAIN1 health" }), expect.anything()));
    fireEvent.click(screen.getByRole("button", { name: "Recipient ↕" }));
    await waitFor(() => expect(api.stateGrants).toHaveBeenCalledWith("AL", expect.objectContaining({ sort: "recipient" }), expect.anything()));
    fireEvent.click(screen.getByRole("button", { name: "Budget category ↕" }));
    await waitFor(() => expect(api.stateGrants).toHaveBeenCalledWith("AL", expect.objectContaining({ sort: "category" }), expect.anything()));
  });
  it("explains contracts when they are included", async () => {
    render(<CdcStateFundingProfile stateCode="AL" />);
    await screen.findByText("CDC grants to recipients in Alabama");
    fireEvent.change(screen.getByLabelText("Award type"), { target: { value: "all" } });
    expect(await screen.findByText(/Contracts are counted in the state/)).toBeTruthy();
  });
});
