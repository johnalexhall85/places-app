import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ChartBand, DotIntervalRow, PeerList, TrendChart } from "./ChartBand";
import { extent, focusedExtent, formatTick, peerSubset, ticks } from "./scale";
import { CommunityCounty } from "../CommunityPages";

const row = {
  product: "places", measure_id: "diabetes_crudeprev", label: "Diagnosed diabetes",
  unit: "percent", period: "2023", population: "Adults", value: 27.1,
  status: "available", status_text: "Published value", uncertainty: { kind: "ci95", low: 23.9, high: 30.3 },
  comparisons: { state: null, national: null, side_note: null }, peers: null,
  trend: { style: "dots_ci", note: "Separate model runs", series: [
    { period: "2022", value: 26, low: 23, high: 29, status_text: "Published", boundary_vintage: "2020", release_label: "PLACES 2024 release" },
    { period: "2023", value: 27.1, low: 23.9, high: 30.3, status_text: "Published", boundary_vintage: "2024", release_label: "PLACES 2025 release" },
  ], state_series: null, national_series: null, unavailable_periods: [] },
  source: { publisher: "CDC", product_name: "PLACES", credit: null }, citation: "CDC data",
};

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("profile charts", () => {
  it("draws PLACES periods without a connecting path", () => {
    const { container } = render(<TrendChart row={row} />);
    expect(container.querySelector(".chart-trend-line")).toBeNull();
    expect(container.querySelectorAll('[data-marker="area"]')).toHaveLength(2);
    expect(screen.getByText(/Separate model runs/)).toBeTruthy();
  });

  it("omits a state marker when the comparison is null", () => {
    const { container } = render(<DotIntervalRow row={row} />);
    expect(container.querySelector('[data-marker="state"]')).toBeNull();
  });

  it("selects the area, 15 nearest, and the extremes without ranks", () => {
    const values = Array.from({ length: 25 }, (_, index) => ({ geoid: String(index), value: index }));
    const { selected, remaining } = peerSubset(values, "12");
    expect(selected).toHaveLength(18);
    expect(selected.map((item) => item.geoid)).toContain("12");
    expect(selected.map((item) => item.geoid)).toContain("0");
    expect(selected.map((item) => item.geoid)).toContain("24");
    expect(remaining).toHaveLength(7);
  });

  it("opens the table and retains missing status text", () => {
    const missing = { ...row, value: null, status_text: "Suppressed by source", trend: null };
    render(<ChartBand section={{ groups: [{ key: "one", title: "Conditions", shared_axis: true, rows: [missing] }] }} areaGeoid="01063" areaName="Greene County, Alabama" stateName="Alabama" />);
    expect(screen.getAllByText("Suppressed by source").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Show as table" }));
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Hide table" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("uses rounded bounded ticks and short currency labels", () => {
    const percent = extent([-3.87, 23.4, 50.77], { unit: "percent" });
    expect(percent[0]).toBe(0);
    expect(percent[1]).toBeLessThanOrEqual(100);
    expect(ticks(percent).length).toBeGreaterThanOrEqual(3);
    expect(ticks(percent).length).toBeLessThanOrEqual(5);
    expect(extent([0.6, 1.2], { storage_scale: "proportion_0_1" })).toEqual([0, 1]);
    const currency = { kind: "currency", unit: "USD" };
    expect(formatTick(40000, currency)).toBe("$40k");
    expect(formatTick(80000, currency)).toBe("$80k");
    expect(focusedExtent([10.7, 29.8], { unit: "percent" })).toEqual([5, 35]);
  });

  it("places peer ticks and the area dot on the same scale", () => {
    const withPeers = { ...row, peers: { values: [10, 20, 27.1, 40], count: 4,
      level: "county", parent_geoid: "01", min: { name: "Low", value: 10 }, max: { name: "High", value: 40 } } };
    const { container } = render(<DotIntervalRow row={withPeers} />);
    const dots = container.querySelectorAll('[data-marker="area"]');
    expect(dots).toHaveLength(2);
    expect(dots[0].getAttribute("cx")).toBe(dots[1].getAttribute("cx"));
    expect(container.querySelector('[data-testid="peer-strip"]')).toBeTruthy();
  });

  it("shows a peer interval chart with at most 18 default rows and fringe labels", async () => {
    const values = Array.from({ length: 25 }, (_, index) => ({ geoid: String(index), name: `County ${index}`, value: index,
      uncertainty: { low: index - 0.5, high: index + 0.5 } }));
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ values }) })));
    const withPeers = { ...row, peers: { peers_url: "/community/county/12/peers", level: "county" } };
    const { container } = render(<PeerList row={withPeers} areaGeoid="12" areaName="County 12" />);
    fireEvent.click(screen.getByRole("button", { name: "Compare counties" }));
    await waitFor(() => expect(container.querySelectorAll("[data-peer-row]")).toHaveLength(18));
    expect(container.querySelector('[aria-label*="(lowest)"]')).toBeTruthy();
    expect(container.querySelector('[aria-label*="(highest)"]')).toBeTruthy();
    expect(container.querySelectorAll(".chart-peer-chart circle")).toHaveLength(18);
    fireEvent.click(screen.getByRole("button", { name: "Show all 25" }));
    expect(container.querySelectorAll("[data-peer-row]")).toHaveLength(25);
  });

  it("connects a vintage-label change but breaks at a missing period", () => {
    const lineRow = { ...row, trend: { ...row.trend, style: "line", series: [
      { period: "2020", value: 10, boundary_vintage: "2010" },
      { period: "2021", value: 12, boundary_vintage: "2020" },
      { period: "2022", value: null, boundary_vintage: "2020", status_text: "Unavailable" },
      { period: "2023", value: 13, boundary_vintage: "2020" },
    ] } };
    const { container } = render(<TrendChart row={lineRow} />);
    const path = container.querySelector(".chart-trend-line").getAttribute("d");
    expect((path.match(/L/g) || [])).toHaveLength(1);
    expect((path.match(/M/g) || [])).toHaveLength(2);
    expect(screen.queryByText(/Boundary changed; line breaks here/)).toBeNull();
    expect(screen.getByText("About these years")).toBeTruthy();
  });

  it("keeps a county profile usable when charts fail", async () => {
    const profile = { area: { name: "Greene", state_name: "Alabama", state_geoid: "01", geoid: "01063", boundary_vintage: "2024" },
      values: [row], state_values: [], survey_companions: {}, facilities: { health_centers: null, nursing_homes: null, tri_facilities: null }, limitations: [], releases: {} };
    vi.stubGlobal("fetch", vi.fn((url) => {
      if (url.includes("/charts")) return Promise.reject(new Error("unavailable"));
      return Promise.resolve({ ok: true, json: () => Promise.resolve(url.includes("/catalog") ? { measures: [] } : profile) });
    }));
    render(<CommunityCounty geoid="01063" />);
    await waitFor(() => expect(screen.getByText("Diagnosed diabetes")).toBeTruthy());
    expect(screen.queryByText("At a glance")).toBeNull();
  });
});
