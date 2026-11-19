import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { IndicatorChart, SectionChartLegend } from "./IndicatorChart";
import { COLORS, computeYAxis, formatShortTick, shortPeriod } from "./scale";
import { CommunityCounty, Indicator } from "../CommunityPages";
import { CommunityState } from "../CommunityState";
import { CommunityDistrict } from "../CommunityDistrict";

const acsRow = {
  product: "acs_profile",
  measure_id: "poverty_pct",
  label: "People below poverty",
  unit: "percent",
  kind: "percent",
  period: "2020–2024",
  population: "All residents for whom poverty status is determined",
  value: 19.2,
  status: "available",
  status_text: "Published value",
  uncertainty: { kind: "moe90", moe: 1.4 },
  comparisons: {
    state: { geoid: "01", name: "Alabama", value: 15.6, period: "2020–2024" },
    national: { geoid: "US", name: "United States", value: 12.5, period: "2020–2024" },
    side_note: null,
  },
  peers: null,
  trend: {
    style: "line_band",
    note: "5-year windows overlap, so neighbouring periods share survey years.",
    series: [
      { period: "2016–2020", value: 21.0, low: 19.5, high: 22.5, status_text: "Published" },
      { period: "2018-2022", value: 20.1, low: 18.7, high: 21.5, status_text: "Published" },
      { period: "2020–2024", value: 19.2, low: 17.8, high: 20.6, status_text: "Published" },
    ],
    state_series: [
      { period: "2016–2020", value: 16.4, status_text: "Published" },
      { period: "2018-2022", value: 16.0, status_text: "Published" },
      { period: "2020–2024", value: 15.6, status_text: "Published" },
    ],
    national_series: [
      { period: "2016–2020", value: 12.8, status_text: "Published" },
      { period: "2018-2022", value: 12.6, status_text: "Published" },
      { period: "2020–2024", value: 12.5, status_text: "Published" },
    ],
    unavailable_periods: [],
  },
  source: { publisher: "Census Bureau", product_name: "ACS 5-Year", credit: null },
  citation: "Census data",
};

const placesRow = {
  product: "places",
  measure_id: "diabetes_crudeprev",
  label: "Diagnosed diabetes",
  unit: "percent",
  kind: null,
  period: "2023",
  population: "Adults",
  value: 27.1,
  status: "available",
  status_text: "Published value",
  uncertainty: { kind: "ci95", low: 23.9, high: 30.3 },
  comparisons: { state: null, national: null, side_note: null },
  peers: null,
  trend: {
    style: "dots_ci",
    note: "Each year is a separate PLACES model run from a different release; CDC advises comparing across releases with caution.",
    series: [
      { period: "2021", value: 25.4, low: 22.3, high: 28.5, status_text: "Published" },
      { period: "2022", value: 26.0, low: 23.0, high: 29.0, status_text: "Published" },
      { period: "2023", value: 27.1, low: 23.9, high: 30.3, status_text: "Published" },
    ],
    state_series: null,
    national_series: null,
    unavailable_periods: [],
  },
  source: { publisher: "CDC", product_name: "PLACES", credit: null },
  citation: "CDC data",
};

const districtRow = {
  product: "acs_profile",
  measure_id: "poverty_pct",
  label: "People below poverty",
  unit: "percent",
  kind: "percent",
  period: "2020–2024",
  population: "All residents",
  value: 17.4,
  status: "available",
  status_text: "Published value",
  uncertainty: { kind: "moe90", moe: 0.9 },
  comparisons: {
    state: { geoid: "54", name: "West Virginia", value: 16.7, period: "2020–2024" },
    national: { geoid: "US", name: "United States", value: 12.5, period: "2020–2024" },
    side_note: null,
  },
  peers: null,
  trend: null,
  source: { publisher: "Census Bureau", product_name: "ACS 5-Year", credit: null },
  citation: "Census data",
};

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    }
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("IndicatorChart", () => {
  it("draws 3 paths with different dash arrays and palette colours for an ACS row", () => {
    const { container } = render(
      <IndicatorChart row={acsRow} areaLabel="Etowah County" stateLabel="Alabama" />
    );
    const paths = [...container.querySelectorAll("svg path")];
    expect(paths).toHaveLength(3);

    const dashes = paths.map((path) => path.getAttribute("stroke-dasharray") || "solid");
    expect(new Set(dashes).size).toBe(3);
    expect(dashes).toContain("solid");
    expect(dashes).toContain("5 3");
    expect(dashes).toContain("1.5 3");

    const strokes = paths.map((path) => path.getAttribute("stroke"));
    expect(strokes).toContain(COLORS.area);
    expect(strokes).toContain(COLORS.state);
    expect(strokes).toContain(COLORS.national);

    const svg = container.querySelector("svg");
    expect(svg.getAttribute("role")).toBe("img");
    expect(svg.getAttribute("height")).toBe("120");
    expect(svg.getAttribute("aria-label")).toContain("Etowah County");
    expect(svg.getAttribute("aria-label")).toContain("Alabama");
    expect(svg.getAttribute("aria-label")).toContain("United States");

    // X-axis splits ACS periods on hyphen and en-dash to show end years
    expect(shortPeriod("2016–2020")).toBe("2020");
    expect(shortPeriod("2018-2022")).toBe("2022");
    const axisTexts = [...container.querySelectorAll(".indicator-chart-axis-label")].map(
      (node) => node.textContent
    );
    expect(axisTexts).toContain("2020");
    expect(axisTexts).toContain("2024");
  });

  it("draws no stroked path and draws CI whiskers for a PLACES row", () => {
    const { container } = render(<IndicatorChart row={placesRow} areaLabel="Greene County" />);
    const strokedPaths = [...container.querySelectorAll("svg path")].filter((path) =>
      path.getAttribute("stroke")
    );
    expect(strokedPaths).toHaveLength(0);

    const whiskers = container.querySelectorAll("line.indicator-chart-whisker");
    expect(whiskers).toHaveLength(3);
    const dots = container.querySelectorAll("circle.indicator-chart-dot");
    expect(dots).toHaveLength(3);
    expect(container.querySelector(".indicator-chart-caption").textContent).toContain(
      "separate PLACES model run"
    );
  });

  it("draws 3 horizontal bars for a district row with no trend", () => {
    const { container } = render(
      <IndicatorChart row={districtRow} areaLabel="This district" stateLabel="West Virginia" />
    );
    const bars = [...container.querySelectorAll("rect.indicator-chart-bar")];
    expect(bars).toHaveLength(3);
    expect(bars.every((bar) => bar.getAttribute("height") === "10")).toBe(true);
    expect(bars.map((bar) => bar.getAttribute("fill"))).toEqual([
      COLORS.area,
      COLORS.state,
      COLORS.national,
    ]);
    expect(container.textContent).toContain("This district");
    expect(container.textContent).toContain("West Virginia");
    expect(container.textContent).toContain("United States");
    expect(container.textContent).toContain("17.4%");
    expect(container.textContent).toContain("16.7%");
    expect(container.textContent).toContain("12.5%");
    expect(container.querySelector("table.sr-only")).toBeTruthy();
  });

  it("renders nothing when a row has no trend and no comparisons", () => {
    const bareRow = {
      ...districtRow,
      measure_id: "total_population",
      unit: "people",
      kind: "count",
      value: 880000,
      comparisons: { state: null, national: null, side_note: null },
      trend: null,
    };
    const { container } = render(<IndicatorChart row={bareRow} />);
    expect(container.firstChild).toBeNull();
  });

  it("breaks the line at a missing period or unavailable period", () => {
    const gappedRow = {
      ...acsRow,
      trend: {
        ...acsRow.trend,
        style: "line",
        state_series: null,
        national_series: null,
        series: [
          { period: "2019", value: 10, status_text: "Published" },
          { period: "2020", value: 12, status_text: "Published" },
          { period: "2021", value: null, status_text: "Unavailable" },
          { period: "2022", value: 14, status_text: "Published" },
          { period: "2023", value: 15, status_text: "Published" },
        ],
        unavailable_periods: [],
      },
    };
    const { container } = render(<IndicatorChart row={gappedRow} />);
    const d = container.querySelector('path[data-series="area"]').getAttribute("d");
    expect(d.match(/M/g) || []).toHaveLength(2);
    expect(d.match(/L/g) || []).toHaveLength(2);

    const unavailableRow = {
      ...gappedRow,
      trend: {
        ...gappedRow.trend,
        series: [
          { period: "2019", value: 10, status_text: "Published" },
          { period: "2020", value: 12, status_text: "Published" },
          { period: "2022", value: 14, status_text: "Published" },
          { period: "2023", value: 15, status_text: "Published" },
        ],
        unavailable_periods: [{ period: "2021", reason: "Not collected in 2021" }],
      },
    };
    const { container: c2 } = render(<IndicatorChart row={unavailableRow} />);
    const d2 = c2.querySelector('path[data-series="area"]').getAttribute("d");
    expect(d2.match(/M/g) || []).toHaveLength(2);
    expect(d2.match(/L/g) || []).toHaveLength(2);
  });

  it("keeps Indicator markup identical when no chart prop is passed", () => {
    const indicatorRow = {
      product: "places",
      measure_id: "diabetes_crudeprev",
      level: "county",
      geoid: "01063",
      label: "Diagnosed diabetes",
      unit: "percent",
      period: "2023",
      population: "Adults",
      value: 27.1,
      status: "available",
      uncertainty: { kind: "ci95", low: 23.9, high: 30.3 },
      source: { publisher: "CDC", product_name: "PLACES", credit: null },
      source_release_id: "places-2025",
    };
    const { container } = render(<Indicator row={indicatorRow} />);
    expect(container.querySelector(".indicator-chart")).toBeNull();
    expect(container.innerHTML).toBe(
      '<article class="community-indicator ">' +
        "<h3>Diagnosed diabetes</h3>" +
        '<p class="community-value">27.1%</p>' +
        '<p class="community-indicator-note">95% confidence interval: 23.9–30.3%</p>' +
        '<p class="community-source">Source: CDC · PLACES · 2023 · places-2025<br>Population: Adults</p>' +
        '<a class="community-map-link" href="/area/places-2025?measure_id=diabetes_crudeprev&amp;focus=county:01063">Open source map →</a>' +
        "</article>"
    );
  });

  it("starts percent y-ticks at 0 unless every value is above 40, and scales proportion_0_1", () => {
    const lowPercent = computeYAxis([12.5, 19.2, 21.0], { unit: "percent" });
    expect(lowPercent.ticks[0]).toBe(0);
    expect(lowPercent.ticks.length).toBeGreaterThanOrEqual(3);
    expect(lowPercent.ticks.length).toBeLessThanOrEqual(4);

    const highPercent = computeYAxis([76, 82, 88], { unit: "percent" });
    expect(highPercent.ticks[0]).toBeGreaterThan(0);
    expect(highPercent.ticks[0]).toBeLessThan(76);
    expect(highPercent.ticks.at(-1)).toBeLessThanOrEqual(100);
    expect(highPercent.ticks.length).toBeGreaterThanOrEqual(3);
    expect(highPercent.ticks.length).toBeLessThanOrEqual(4);

    const cmsProportion = {
      ...acsRow,
      product: "cms_gv",
      measure_id: "readmission_rate",
      unit: "proportion",
      kind: null,
      storage_scale: "proportion_0_1",
      trend: {
        style: "line",
        note: "2020 reflects the COVID-19 pandemic.",
        series: [
          { period: "2022", value: 0.162, status_text: "Published" },
          { period: "2023", value: 0.1863, status_text: "Published" },
        ],
        state_series: null,
        national_series: null,
        unavailable_periods: [],
      },
    };
    const { container } = render(<IndicatorChart row={cmsProportion} />);
    const axisLabels = [...container.querySelectorAll(".indicator-chart-axis-label")].map(
      (node) => node.textContent
    );
    expect(axisLabels[0]).toBe("0%");
    expect(axisLabels.some((label) => label.endsWith("%") && label !== "0%")).toBe(true);
    expect(formatShortTick(12000, { kind: "currency", unit: "USD" })).toBe("$12k");
  });

  it("shows a tooltip on click/hover and truncates long captions with full text in title and table", () => {
    const longNote = "A".repeat(165);
    const longNoteRow = {
      ...acsRow,
      trend: { ...acsRow.trend, note: longNote },
    };
    const { container } = render(
      <IndicatorChart row={longNoteRow} areaLabel="Etowah County" stateLabel="Alabama" />
    );
    const caption = container.querySelector(".indicator-chart-caption");
    expect(caption.textContent.length).toBeLessThanOrEqual(141);
    expect(caption.textContent.endsWith("…")).toBe(true);
    expect(caption.getAttribute("title")).toBe(longNote);
    expect(container.querySelector("table.sr-only caption").textContent).toContain(longNote);

    const svg = container.querySelector("svg");
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      width: 280,
      height: 120,
      right: 280,
      bottom: 120,
    });
    fireEvent.click(svg, { clientX: 265 });
    const tooltip = container.querySelector(".indicator-chart-tooltip");
    expect(tooltip).toBeTruthy();
    expect(tooltip.textContent).toContain("2020–2024");
    expect(tooltip.textContent).toContain("Etowah County: 19.2%");
    expect(tooltip.textContent).toContain("Alabama: 15.6%");
    expect(tooltip.textContent).toContain("United States: 12.5%");
  });

  it("renders SectionChartLegend only for series present in the section", () => {
    const { container: empty } = render(
      <SectionChartLegend rows={[{ ...districtRow, comparisons: { state: null, national: null } }]} areaLabel="Greene County" stateLabel="Alabama" />
    );
    expect(empty.firstChild).toBeNull();

    const { container: placesOnly } = render(
      <SectionChartLegend rows={[placesRow]} areaLabel="Greene County" stateLabel="Alabama" />
    );
    expect(placesOnly.textContent).toContain("Greene County");
    expect(placesOnly.textContent).not.toContain("Alabama");
    expect(placesOnly.textContent).not.toContain("United States");

    const { container: full } = render(
      <SectionChartLegend rows={[acsRow]} areaLabel="Etowah County" stateLabel="Alabama" />
    );
    expect(full.textContent).toContain("Etowah County");
    expect(full.textContent).toContain("Alabama");
    expect(full.textContent).toContain("United States");
  });

  it("keeps CommunityCounty usable without chart bands when charts succeed or fail", async () => {
    const profile = {
      area: {
        name: "Greene",
        state_name: "Alabama",
        state_geoid: "01",
        geoid: "01063",
        boundary_vintage: "2024",
      },
      values: [
        {
          ...placesRow,
          level: "county",
          geoid: "01063",
          source_release_id: "places-2025",
        },
      ],
      state_values: [],
      survey_companions: {},
      facilities: { health_centers: null, nursing_homes: null, tri_facilities: null },
      limitations: [],
      releases: {},
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((url) => {
        if (url.includes("/charts")) return Promise.reject(new Error("unavailable"));
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(url.includes("/catalog") ? { measures: [] } : profile),
        });
      })
    );
    const { container } = render(<CommunityCounty geoid="01063" />);
    await waitFor(() => expect(screen.getByText("Diagnosed diabetes")).toBeTruthy());
    expect(container.querySelector(".chart-band")).toBeNull();
  });

  it("renders inline card charts and section legends on CommunityCounty when charts load", async () => {
    const profile = {
      area: {
        name: "Etowah",
        state_name: "Alabama",
        state_geoid: "01",
        geoid: "01055",
        boundary_vintage: "2024",
      },
      values: [
        {
          ...acsRow,
          level: "county",
          geoid: "01055",
          source_release_id: "acs-2024",
        },
      ],
      state_values: [],
      survey_companions: {},
      facilities: { health_centers: null, nursing_homes: null, tri_facilities: null },
      limitations: [],
      releases: {},
    };
    const chartsPayload = {
      level: "county",
      geoid: "01055",
      name: "Etowah County, Alabama",
      state: { geoid: "01", name: "Alabama" },
      sections: [
        {
          key: "people",
          groups: [{ key: "community", title: "Community", rows: [acsRow] }],
        },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((url) =>
        Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve(
              url.includes("/charts")
                ? chartsPayload
                : url.includes("/catalog")
                ? { measures: [] }
                : profile
            ),
        })
      )
    );
    const { container } = render(<CommunityCounty geoid="01055" />);
    await waitFor(() => expect(container.querySelector(".indicator-chart")).toBeTruthy());
    expect(container.querySelector(".chart-band")).toBeNull();
    const legend = container.querySelector(".section-chart-legend");
    expect(legend).toBeTruthy();
    expect(legend.textContent).toContain("Etowah County");
    expect(legend.textContent).toContain("Alabama");
    expect(legend.textContent).toContain("United States");
  });

  it("renders state and district profile legends and inline charts without chart bands", async () => {
    const stateAcsRow = {
      ...acsRow,
      comparisons: { state: null, national: acsRow.comparisons.national, side_note: null },
      trend: { ...acsRow.trend, state_series: null },
    };
    const stateProfile = {
      area: { name: "Alabama", geoid: "01", boundary_vintage: "2024" },
      values: [{ ...stateAcsRow, level: "state", geoid: "01", source_release_id: "acs-2024" }],
      counties: [],
      districts: [],
      facilities: { health_centers: null, nursing_homes: null, tri_facilities: null },
      limitations: [],
    };
    const stateCharts = {
      level: "state",
      geoid: "01",
      name: "Alabama",
      state: { geoid: "01", name: "Alabama" },
      sections: [{ key: "people", groups: [{ key: "community", rows: [stateAcsRow] }] }],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((url) =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve(url.includes("/charts") ? stateCharts : stateProfile),
        })
      )
    );
    const { container: stateContainer } = render(<CommunityState geoid="01" />);
    await waitFor(() => expect(stateContainer.querySelector(".indicator-chart")).toBeTruthy());
    expect(stateContainer.querySelector(".chart-band")).toBeNull();
    const stateLegend = stateContainer.querySelector(".section-chart-legend");
    expect(stateLegend.textContent).toContain("Alabama");
    expect(stateLegend.textContent).toContain("United States");

    const districtProfile = {
      area: { name: "Congressional District 1", state_name: "West Virginia", geoid: "5401", boundary_vintage: "2024" },
      values: [{ ...districtRow, level: "cd", geoid: "5401", source_release_id: "acs-2024" }],
      counties: { note: "Overlap note", counties: [] },
      facilities: { health_centers: null, nursing_homes: null, tri_facilities: null },
      limitations: [],
    };
    const districtCharts = {
      level: "district",
      geoid: "5401",
      name: "Congressional District 1",
      state: { geoid: "54", name: "West Virginia" },
      sections: [{ key: "people", groups: [{ key: "community", rows: [districtRow] }] }],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((url) =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve(url.includes("/charts") ? districtCharts : districtProfile),
        })
      )
    );
    const { container: districtContainer } = render(<CommunityDistrict geoid="5401" />);
    await waitFor(() => expect(districtContainer.querySelector(".indicator-chart")).toBeTruthy());
    expect(districtContainer.querySelector(".chart-band")).toBeNull();
    expect(districtContainer.querySelectorAll("rect.indicator-chart-bar")).toHaveLength(3);
    const districtLegend = districtContainer.querySelector(".section-chart-legend");
    expect(districtLegend.textContent).toContain("This district");
    expect(districtLegend.textContent).toContain("West Virginia");
    expect(districtLegend.textContent).toContain("United States");
  });
});
