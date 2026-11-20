import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CdcFundingMap from "./CdcFundingMap";

vi.mock("../components/SiteHeader", () => ({ default: () => <header>Header</header> }));
vi.mock("../components/Footer", () => ({ default: () => <footer>Footer</footer> }));
vi.mock("../api/stateFunding", () => ({
  fiscalYears: vi.fn(), fundingMap: vi.fn(), fundingMapShapes: vi.fn(), stateSummary: vi.fn(),
}));
const api = await import("../api/stateFunding");
const polygon = (west, south, east, north) => ({
  type: "Polygon", coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
});
const shapes = {
  CA: { fips: "06", name: "California", geometry: polygon(-124, 32, -114, 42) },
  WY: { fips: "56", name: "Wyoming", geometry: polygon(-111, 41, -104, 45) },
  DC: { fips: "11", name: "District of Columbia", geometry: polygon(-77.1, 38.8, -76.9, 39) },
  PR: { fips: "72", name: "Puerto Rico", geometry: polygon(-67.3, 17.9, -65.2, 18.5) },
};
const rows = [
  { code: "CA", fips: "06", name: "California", total: 200, regular: 220, supplemental: -20,
    award_count: 2, recipient_count: 2, has_shape: true, indicators_geoid: "06" },
  { code: "WY", fips: "56", name: "Wyoming", total: -10, regular: 0, supplemental: -10,
    award_count: 1, recipient_count: 1, has_shape: true, indicators_geoid: "56" },
  { code: "DC", fips: "11", name: "District of Columbia", total: 0, regular: 0, supplemental: 0,
    award_count: 1, recipient_count: 1, has_shape: true, indicators_geoid: "11" },
  { code: "GU", fips: "66", name: "Guam", total: 5, regular: 5, supplemental: 0,
    award_count: 1, recipient_count: 1, has_shape: false, indicators_geoid: null },
];
const mapData = {
  fiscal_year: 2026, period: "FY2026 P12",
  filters: { funding_type: "all", category: null, award_type: "grant" },
  categories_available: [{ code: "HIV", name: "HIV prevention", basis: "cdc_operating_plan" }],
  states: rows, national: { total: 195, award_count: 4 }, unattributed: { total: 0, award_count: 0 },
  citation: "USAspending File C", notes: ["Recipients' address is used."],
};
const summary = {
  by_category: [{ code: "HIV", name: "HIV prevention", total: 180, regular: 200, supplemental: -20 }],
};

beforeEach(() => {
  window.history.replaceState({}, "", "/cdc-funding/map");
  vi.clearAllMocks();
  api.fiscalYears.mockResolvedValue({ fiscal_years: [2026, 2025], default: 2026 });
  api.fundingMapShapes.mockResolvedValue({ states: shapes });
  api.fundingMap.mockResolvedValue(mapData);
  api.stateSummary.mockResolvedValue(summary);
});

describe("CDC state funding map", () => {
  it("updates all filters in the URL and refetches", async () => {
    render(<CdcFundingMap />);
    await screen.findByText("FY2026 P12");
    fireEvent.change(screen.getByLabelText("Fiscal year"), { target: { value: "2025" } });
    await waitFor(() => expect(api.fundingMap).toHaveBeenCalledWith(
      expect.objectContaining({ fy: "2025" }), expect.anything(),
    ));
    fireEvent.change(screen.getByLabelText("Budget category"), { target: { value: "HIV" } });
    fireEvent.change(screen.getByLabelText("Funding type"), { target: { value: "supplemental" } });
    await waitFor(() => expect(api.fundingMap).toHaveBeenCalledWith(
      expect.objectContaining({ category: "HIV", funding_type: "supplemental" }), expect.anything(),
    ));
    expect(window.location.search).toContain("fy=2025");
    expect(window.location.search).toContain("category=HIV");
    expect(window.location.search).toContain("funding_type=supplemental");
  });

  it("shows tooltip, negative and zero classes, applicable tiles, and sorted table", async () => {
    render(<CdcFundingMap />);
    await screen.findByText("FY2026 P12");
    const ca = screen.getByRole("button", { name: "California: $200" });
    fireEvent.pointerEnter(ca, { pointerType: "mouse" });
    expect(within(screen.getByRole("tooltip")).getByText("2 grants")).toBeTruthy();
    expect(screen.getByText("Net reduction")).toBeTruthy();
    expect(ca.getAttribute("fill")).not.toBe(
      screen.getByRole("button", { name: "Wyoming: −$10" }).getAttribute("fill"),
    );
    expect(screen.getByRole("button", { name: "District of Columbia: $0" }).getAttribute("fill"))
      .toBe("#e3e7e9");
    for (const code of ["DC", "PR", "GU"]) {
      expect(screen.getByRole("button", { name: new RegExp(`^${code}`) })).toBeTruthy();
    }
    for (const code of ["VI", "AS", "MP", "FM", "MH", "PW"]) {
      expect(screen.queryByRole("button", { name: new RegExp(`^${code}`) })).toBeNull();
    }
    fireEvent.click(screen.getByText("Table of states"));
    const table = screen.getByRole("table");
    fireEvent.click(within(table).getByRole("button", { name: "Amount ↕" }));
    expect(within(table).getAllByRole("row")[1].textContent).toContain("California");
  });

  it("shows Freely Associated State tiles only when that fiscal year has grant rows", async () => {
    window.history.replaceState({}, "", "/cdc-funding/map?fy=2023");
    const associated = [
      ["FM", "Federated States of Micronesia"],
      ["MH", "Marshall Islands"],
      ["PW", "Palau"],
    ].map(([code, name]) => ({
      code, fips: null, name, total: 100, regular: 100, supplemental: 0,
      award_count: 1, recipient_count: 1, has_shape: false, indicators_geoid: null,
    }));
    api.fiscalYears.mockResolvedValue({ fiscal_years: [2026, 2023], default: 2026 });
    api.fundingMap.mockImplementation(async ({ fy }) => ({
      ...mapData, fiscal_year: Number(fy), period: `FY${fy} P12`,
      states: fy === "2023" ? [...rows, ...associated] : rows,
    }));
    render(<CdcFundingMap />);
    await screen.findByText("FY2023 P12");
    const tiles = screen.getByLabelText("District and territory tiles");
    expect(within(tiles).getAllByRole("button").map((tile) => tile.querySelector("strong").textContent))
      .toEqual(["DC", "PR", "GU", "FM", "MH", "PW"]);
    expect(within(tiles).getByRole("button", { name: /^PR/ }).textContent).toContain("No grants");
    fireEvent.click(within(tiles).getByRole("button", { name: /^FM/ }));
    expect(within(screen.getByRole("complementary", { name: "Selected state" }))
      .queryByRole("link", { name: "State indicators" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Fiscal year"), { target: { value: "2026" } });
    await screen.findByText("FY2026 P12");
    await waitFor(() => expect(within(screen.getByLabelText("District and territory tiles")).getAllByRole("button")
      .map((tile) => tile.querySelector("strong").textContent)).toEqual(["DC", "PR", "GU"]));
  });

  it("merges quantile classes with equal rounded bounds and labels single values once", async () => {
    const grantRow = (code, total) => ({
      code, fips: null, name: code, total, regular: total, supplemental: 0,
      award_count: 1, recipient_count: 1, has_shape: false, indicators_geoid: null,
    });
    api.fundingMap.mockResolvedValue({
      ...mapData,
      states: [
        grantRow("CA", 74998), grantRow("WY", 75000), grantRow("DC", 75002),
        grantRow("GU", 75004), grantRow("PR", 120000),
        grantRow("VI", -74998), grantRow("AS", -75000), grantRow("MP", -75002),
      ],
    });
    render(<CdcFundingMap />);
    await screen.findByText("FY2026 P12");
    const legend = screen.getByLabelText("Map legend");
    expect(within(legend).getByText("−$75.0 thousand")).toBeTruthy();
    expect(within(legend).getByText("$75.0 thousand")).toBeTruthy();
    expect(within(legend).getByText("$120.0 thousand")).toBeTruthy();
    expect(legend.querySelectorAll("span")).toHaveLength(5);
    expect(legend.textContent).not.toMatch(/\$75\.0 thousand to .*\$75\.0 thousand/);
  });

  it("opens a panel with filtered links and omits unavailable indicators", async () => {
    render(<CdcFundingMap />);
    await screen.findByText("FY2026 P12");
    fireEvent.click(screen.getByRole("button", { name: "California: $200" }));
    const panel = screen.getByRole("complementary", { name: "Selected state" });
    expect(await within(panel).findByText("HIV prevention")).toBeTruthy();
    expect(within(panel).getByRole("link", { name: "State indicators" }).getAttribute("href"))
      .toBe("/community/state/06");
    expect(within(panel).getByRole("link", { name: "State funding profile" }).getAttribute("href"))
      .toContain("award_type=grant");
    fireEvent.click(screen.getByRole("button", { name: /^GU/ }));
    expect(within(screen.getByRole("complementary", { name: "Selected state" }))
      .queryByRole("link", { name: "State indicators" })).toBeNull();
    expect(window.location.search).toContain("state=GU");
  });

  it("excludes deobligations across the map, subtitle, and panel without changing the profile link", async () => {
    api.fundingMap.mockImplementation(async (filters) => filters.deobligations === "exclude"
      ? {
        ...mapData,
        filters: { ...mapData.filters, deobligations: "exclude" },
        states: rows.map((row) => ({
          ...row, total: Math.max(0, row.regular), supplemental: 0,
        })),
        notes: [
          "Deobligations (net reductions for an award in this year) are left out, "
            + "so totals show new and added obligations only.",
        ],
      }
      : mapData);
    render(<CdcFundingMap />);
    await screen.findByText("FY2026 P12");
    const checkbox = screen.getByRole("checkbox", { name: "Exclude deobligations" });
    expect(checkbox.checked).toBe(false);
    fireEvent.click(checkbox);
    expect(window.location.search).toContain("deobligations=exclude");
    await waitFor(() => expect(api.fundingMap).toHaveBeenCalledWith(
      expect.objectContaining({ deobligations: "exclude" }), expect.anything(),
    ));
    expect(await screen.findByText("FY2026 P12 · Deobligations excluded")).toBeTruthy();
    expect(screen.queryByText("Net reduction")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "California: $220" }));
    const panel = screen.getByRole("complementary", { name: "Selected state" });
    await waitFor(() => expect(api.stateSummary).toHaveBeenCalledWith(
      "CA", expect.objectContaining({ deobligations: "exclude" }), expect.anything(),
    ));
    expect(within(panel).getByText(
      "The state funding profile shows net amounts, including deobligations.",
    )).toBeTruthy();
    expect(within(panel).getByRole("link", { name: "State indicators" }).getAttribute("href"))
      .toBe("/community/state/06");
    expect(within(panel).getByRole("link", { name: "State funding profile" }).getAttribute("href"))
      .not.toContain("deobligations");
    fireEvent.click(checkbox);
    expect(window.location.search).not.toContain("deobligations");
  });
});
