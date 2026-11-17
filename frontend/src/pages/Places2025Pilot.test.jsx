import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import Places2025Pilot, { pilotQuery, safeViewportBbox, initialMapView, PILOT_TRACT_ZOOM, areaGeography, ACS_COUNTY_ZOOM, ACS_TRACT_ZOOM, aqiBinLabels, aqiColor, aqiValueText, aqiReportingText, gvGeography, gvNumber, gvValueText, gvBinLabels, gvColor, FEA_DATASET_ID, FEA_STATUS_TEXT, feaNumber, feaValueText, feaColor, feaBinLabels, brfssColor, brfssValueText, areaFeatureDetails, areaTooltip, parseFocus, profileHrefFor, focusZoomRange, quintileColor } from "./Places2025Pilot";
import { resolveRoute } from "../utils/routeResolver";

const mapHarness = vi.hoisted(() => ({ zoom: 4, handlers: null, geojson: null, outline: null,
  map: { setView: vi.fn(), zoomIn: vi.fn(), zoomOut: vi.fn(), getBoundsZoom: () => 8 } }));

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }) => <div>{children}</div>,
  TileLayer: () => null,
  ZoomControl: () => null,
  GeoJSON: (props) => { if (props.onEachFeature) mapHarness.geojson = props; else mapHarness.outline = props; return null; },
  Pane: ({ children }) => <div>{children}</div>,
  useMap: () => mapHarness.map,
  useMapEvents: (handlers) => {
    mapHarness.handlers = handlers;
    return { getZoom: () => mapHarness.zoom,
      getCenter: () => ({ lat: 35, lng: -95 }),
      getBounds: () => ({ getWest: () => -100, getSouth: () => 30, getEast: () => -90, getNorth: () => 40 }) };
  },
}));

afterEach(() => window.history.replaceState(null, "", "/"));

describe("PLACES 2025 county pilot selection", () => {
  afterEach(() => { vi.unstubAllGlobals(); mapHarness.zoom = 4; mapHarness.handlers = null; });
  it("restores a valid shared map view and rejects invalid coordinates", () => {
    expect(initialMapView("?lat=36.4&lon=-79&zoom=10")).toEqual({ center: [36.4, -79], zoom: 10 });
    expect(initialMapView("?lat=999&lon=-79&zoom=10").center).toEqual([38, -104]);
  });
  it("routes each area map, and /explore/map now opens the published-release map", () => {
    expect(resolveRoute("/area/places-2025")).toEqual({ type: "places-2025-pilot" });
    expect(resolveRoute("/")).toEqual({ type: "community-landing" });
    expect(resolveRoute("/explore/map")).toEqual({ type: "map" });
    expect(resolveRoute("/area/brfss")).toEqual({ type: "brfss-state-area" });
  });
  it("lists only published-release maps in the Data source menu", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ active_release_id: null, measures: [] }) }));
    render(<Places2025Pilot />);
    const menu = await screen.findByLabelText("Data source");
    const options = [...menu.querySelectorAll("option")].map((option) => option.textContent);
    expect(options).toHaveLength(9);
    expect(options.some((label) => /legacy|main/i.test(label))).toBe(false);
    expect(screen.queryByRole("link", { name: /legacy map/i })).not.toBeInTheDocument();
  });
  it("keeps BRFSS state survey values, uncertainty, and not-published status distinct", () => {
    expect(brfssColor(null, "not_published", [9, 11, 12, 14])).toBe("#a5a5a5");
    expect(brfssColor(12.4, "available", [9, 11, 12, 14])).toBe("#0277bd");
    expect(brfssValueText({ value: null, status_text: "Not published by CDC" })).toBe("Not published by CDC");
    expect(areaFeatureDetails("brfss", { name: "North Carolina", geography_id: "37", value: 12.4, ci_low: 11,
      ci_high: 13.8, sample_size: 577 }, { label: "Diagnosed diabetes", observation_period: "2023", population: "adults" }, { geography: "state" }).lines)
      .toContain("95% confidence interval: 11–13.8%");
  });
  it("pins every selection and viewport in each request key", () => {
    const selection = { datasetId: "cdc_places_county_2025_pilot", releaseId: "release-a", valueType: "crude_prevalence", measure: {
      measure_id: "dental_crudeprev", observation_period: "2022", population: "adults",
    } };
    const params = pilotQuery(selection, "-100,30,-90,40", { simplify: "0.04" });
    expect(params.get("release_id")).toBe("release-a");
    expect(params.get("dataset_id")).toBe("cdc_places_county_2025_pilot");
    expect(params.get("measure_id")).toBe("dental_crudeprev");
    expect(params.get("period")).toBe("2022");
    expect(params.get("population")).toBe("adults");
    expect(params.get("value_type")).toBe("crude_prevalence");
    expect(params.get("geography")).toBe("county");
    expect(params.get("bbox")).toBe("-100,30,-90,40");
    expect(params.get("simplify")).toBe("0.04");
  });
  it("keeps a wide viewport inside API longitude and latitude bounds", () => {
    expect(safeViewportBbox({ getWest: () => -207, getSouth: () => -93, getEast: () => 16, getNorth: () => 94 }))
      .toBe("-180,-90,16,90");
  });
  it("shows a review state when no release is published", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      active_release_id: null, measures: [],
    }) }));
    render(<Places2025Pilot />);
    expect(await screen.findByText(/awaiting supervised review and publication/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("County pilot map")).not.toBeInTheDocument();
  });
  it("shows unavailable counties in the table with the selected release", async () => {
    const fetchMock = vi.fn(async (url) => {
      const path = String(url);
      const payload = path.endsWith("/catalog") ? {
        dataset_id: "cdc_places_county_2025_pilot", active_release_id: "release-a", value_type: "crude_prevalence", unit: "percent",
        measures: [{ measure_id: "access2_crudeprev", label: "Insurance", observation_period: "2023", population: "adults aged 18-64" }],
      } : path.includes("/map?") ? { release_id: "release-a", features: [] }
        : path.includes("/legend?") ? { release_id: "release-a", statuses: [{ status: "not_published", n: 1 }] }
        : { release_id: "release-a", total: 1, rows: [{ county_fips: "21001", name: "Adair", value: null, ci_low: null, ci_high: null, status: "not_published" }] };
      return { ok: true, json: async () => ({ ...payload, geography: "county" }) };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Places2025Pilot />);
    expect(await screen.findByText("21001")).toBeInTheDocument();
    expect(screen.getAllByText("not_published").length).toBeGreaterThan(0);
    const urls = fetchMock.mock.calls.map(([url]) => String(url)).filter((url) => url.includes("/area/") && !url.endsWith("/catalog"));
    expect(urls).toHaveLength(3);
    expect(urls.every((url) => url.includes("release_id=release-a") && url.includes("period=2023") && url.includes("population=adults+aged+18-64"))).toBe(true);
  });
  it("keeps the selected table page when the map component rerenders", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      const path = String(url);
      const payload = path.endsWith("/catalog") ? {
        dataset_id: "cdc_places_county_2025_pilot", active_release_id: "release-a", value_type: "crude_prevalence", unit: "percent",
        measures: [{ measure_id: "dental_crudeprev", label: "Dental", observation_period: "2022", population: "adults" }],
      } : path.includes("/map?") ? { release_id: "release-a", features: [] }
        : path.includes("/legend?") ? { release_id: "release-a", statuses: [{ status: "available", n: 101 }] }
        : { release_id: "release-a", total: 101, rows: [{ county_fips: path.includes("offset=100") ? "01003" : "01001", name: "County", value: 10, ci_low: 9, ci_high: 11, status: "available" }] };
      return { ok: true, json: async () => ({ ...payload, geography: "county" }) };
    }));
    render(<Places2025Pilot />);
    expect(await screen.findByText("01001")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("01003")).toBeInTheDocument();
    expect(screen.getByText(/Page 2 of 2/)).toBeInTheDocument();
  });
  it("hides old values while a different measure is loading", async () => {
    const pending = [];
    vi.stubGlobal("fetch", vi.fn((url) => {
      const path = String(url);
      const payload = path.endsWith("/catalog") ? {
        dataset_id: "cdc_places_county_2025_pilot", active_release_id: "release-a", value_type: "crude_prevalence", unit: "percent",
        measures: [
          { measure_id: "dental_crudeprev", label: "Dental", observation_period: "2022", population: "adults" },
          { measure_id: "access2_crudeprev", label: "Insurance", observation_period: "2023", population: "adults aged 18-64" },
        ],
      } : path.includes("/map?") ? { release_id: "release-a", features: [] }
        : path.includes("/legend?") ? { release_id: "release-a", statuses: [] }
        : { release_id: "release-a", total: 1, rows: [{ county_fips: path.includes("access2_crudeprev") ? "21001" : "01001", name: "County", value: 10, ci_low: 9, ci_high: 11, status: "available" }] };
      const response = { ok: true, json: async () => ({ ...payload, geography: "county" }) };
      if (path.includes("access2_crudeprev")) return new Promise((resolve) => pending.push(() => resolve(response)));
      return Promise.resolve(response);
    }));
    render(<Places2025Pilot />);
    expect(await screen.findByText("01001")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Measure"), { target: { value: "access2_crudeprev" } });
    expect(screen.queryByText("01001")).not.toBeInTheDocument();
    expect(screen.getByText(/Loading selected county estimates/)).toBeInTheDocument();
    await act(async () => { pending.forEach((resolve) => resolve()); });
    expect(await screen.findByText("21001")).toBeInTheDocument();
  });
  it("shows the logo overlay only on the first load and the small loading pill on later loads", async () => {
    const pending = [];
    vi.stubGlobal("fetch", vi.fn((url) => {
      const path = String(url);
      const payload = path.endsWith("/catalog") ? {
        dataset_id: "cdc_places_county_2025_pilot", active_release_id: "release-a", value_type: "crude_prevalence", unit: "percent",
        measures: [
          { measure_id: "dental_crudeprev", label: "Dental", observation_period: "2022", population: "adults" },
          { measure_id: "access2_crudeprev", label: "Insurance", observation_period: "2023", population: "adults aged 18-64" },
        ],
      } : path.includes("/map?") ? { release_id: "release-a", features: [] }
        : path.includes("/legend?") ? { release_id: "release-a", statuses: [] }
        : { release_id: "release-a", total: 1, rows: [{ county_fips: "01001", name: "County", value: 10, ci_low: 9, ci_high: 11, status: "available" }] };
      const response = { ok: true, json: async () => ({ ...payload, geography: "county" }) };
      if (path.includes("access2_crudeprev")) return new Promise((resolve) => pending.push(() => resolve(response)));
      return Promise.resolve(response);
    }));
    render(<Places2025Pilot />);
    expect(screen.getByTestId("map-loading-overlay")).toHaveTextContent(/Loading map/);
    expect(await screen.findByText("01001")).toBeInTheDocument();
    expect(screen.getByTestId("map-loading-overlay")).toHaveClass("is-leaving");
    expect(screen.queryByTestId("map-loading-strip")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Measure"), { target: { value: "access2_crudeprev" } });
    expect(screen.getByTestId("map-loading-strip")).toHaveTextContent("Loading county shapes…");
    expect(screen.getByText("Loading legend…")).toBeInTheDocument();
    await act(async () => { pending.forEach((resolve) => resolve()); });
    expect(await screen.findByText(/Page 1 of 1/)).toBeInTheDocument();
    expect(screen.queryByTestId("map-loading-strip")).not.toBeInTheDocument();
    expect(screen.queryByText(/Loading map/)).not.toBeInTheDocument();
  });
  it("switches an exact release and measure to tracts at the app threshold", async () => {
    const requests = [];
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      const path = String(url);
      const tract = path.includes("geography=tract");
      if (path.includes("/area/") && !path.endsWith("/catalog")) requests.push(path);
      const payload = path.endsWith("/catalog") ? {
        dataset_id: "cdc_places_county_2025_pilot", active_release_id: "release-b", value_type: "crude_prevalence", unit: "percent",
        geographies: ["county", "tract"], measures: [{ measure_id: "dental_crudeprev", label: "Dental", observation_period: "2022", population: "adults" }],
      } : path.includes("/map?") ? { release_id: "release-b", features: [] }
        : path.includes("/legend?") ? { release_id: "release-b", statuses: [{ status: "available", n: 1, low: 50, high: 50 }] }
        : { release_id: "release-b", total: 1, rows: [{ geography_id: tract ? "01001020100" : "01001", name: "Area", value: 50, ci_low: 45, ci_high: 55, status: "available" }] };
      return { ok: true, json: async () => ({ ...payload, geography: tract ? "tract" : "county" }) };
    }));
    render(<Places2025Pilot />);
    expect(await screen.findByText("01001")).toBeInTheDocument();
    mapHarness.zoom = PILOT_TRACT_ZOOM;
    act(() => mapHarness.handlers.zoomend());
    expect(await screen.findByText("01001020100")).toBeInTheDocument();
    expect(screen.queryByText("01001")).not.toBeInTheDocument();
    const tractRequests = requests.filter((url) => url.includes("geography=tract"));
    expect(tractRequests).toHaveLength(3);
    expect(tractRequests.every((url) => url.includes("release_id=release-b") && url.includes("period=2022") && url.includes("population=adults"))).toBe(true);
  });
  it("visibly returns to counties when a tract viewport exceeds its cap", async () => {
    const requests = [];
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      const path = String(url);
      if (path.endsWith("/catalog")) return { ok: true, json: async () => ({
        dataset_id: "cdc_places_county_2025_pilot", active_release_id: "release-cap", value_type: "crude_prevalence", unit: "percent",
        geographies: ["county", "tract"], measures: [{ measure_id: "dental_crudeprev", label: "Dental", observation_period: "2022", population: "adults" }],
      }) };
      requests.push(path);
      if (path.includes("geography=tract") && path.includes("/map?")) return {
        ok: false, status: 413, json: async () => ({ detail: "Viewport contains more than 5000 tracts" }),
      };
      const payload = path.includes("/map?") ? { features: [] }
        : path.includes("/legend?") ? { statuses: [{ status: "available", n: 1, low: 50, high: 50 }] }
        : { total: 1, rows: [{ geography_id: "01001", name: "County", value: 50, ci_low: 45, ci_high: 55, status: "available" }] };
      return { ok: true, json: async () => ({ ...payload, geography: path.includes("geography=tract") ? "tract" : "county", release_id: "release-cap" }) };
    }));
    render(<Places2025Pilot />);
    expect(await screen.findByText("01001")).toBeInTheDocument();
    mapHarness.zoom = PILOT_TRACT_ZOOM;
    act(() => mapHarness.handlers.zoomend());
    expect(await screen.findByText(/This viewport contains more than 5,000 tracts/)).toBeInTheDocument();
    expect(await screen.findByText("01001")).toBeInTheDocument();
    expect(requests.some((path) => path.includes("geography=tract") && path.includes("/map?"))).toBe(true);
  });
});

describe("AHRF county selection", () => {
  afterEach(() => { vi.unstubAllGlobals(); mapHarness.zoom = 4; mapHarness.handlers = null; });
  it("shows a 2023 source count and missing planning-region value in the same county table", async () => {
    expect(resolveRoute("/area/ahrf")).toEqual({ type: "ahrf-area" });
    const urls = [];
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      const path = String(url); urls.push(path);
      const payload = path.includes("/catalog") ? {
        dataset_id: "hrsa_ahrf_county_2024_2025", active_release_id: "release-ahrf", value_type: "administrative_count", unit: "count", geographies: ["county"],
        measures: [{ measure_id: "phys_nf_prim_care_pc_exc_rsdt_23", label: "Primary care physicians in patient care", observation_period: "2023", population: "nonfederal primary care physicians in patient care, excluding hospital residents and age 75+", unit: "physicians" }],
      } : path.includes("/map?") ? { release_id: "release-ahrf", features: [] }
        : path.includes("/legend?") ? { release_id: "release-ahrf", statuses: [{ status: "missing", n: 1 }] }
        : { release_id: "release-ahrf", total: 1, rows: [{ geography_id: "09110", name: "Capitol Planning Region", value: null, status: "missing" }] };
      return { ok: true, json: async () => ({ ...payload, geography: "county" }) };
    }));
    render(<Places2025Pilot dataset="ahrf" />);
    expect(await screen.findByText("09110")).toBeInTheDocument();
    expect(screen.getByText(/Observation year 2023/)).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Value (physicians)" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Uncertainty" })).toBeInTheDocument();
    expect(urls.filter((url) => url.includes("/area/") && !url.includes("/catalog")).every((url) =>
      url.includes("dataset_id=hrsa_ahrf_county_2024_2025") && url.includes("geography=county") && url.includes("release_id=release-ahrf"))).toBe(true);
    act(() => { mapHarness.zoom = 12; mapHarness.handlers.zoomend(); });
    expect(urls.some((url) => url.includes("geography=tract"))).toBe(false);
  });
});

describe("ACS 2020–2024 area selection", () => {
  afterEach(() => { vi.unstubAllGlobals(); mapHarness.zoom = 4; mapHarness.handlers = null; });
  it("routes ACS and selects state, county, then tract with one exact selection", () => {
    expect(resolveRoute("/area/acs-2024")).toEqual({ type: "acs-2024-area" });
    expect(areaGeography(4, true, true, false)).toBe("state");
    expect(areaGeography(ACS_COUNTY_ZOOM, true, true, false)).toBe("county");
    expect(areaGeography(ACS_TRACT_ZOOM, true, true, false)).toBe("tract");
    expect(areaGeography(ACS_TRACT_ZOOM, true, true, true)).toBe("county");
  });
  it("keeps ACS release, period, universe and MOE through zoom transitions", async () => {
    const requests = [];
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      const path = String(url);
      if (path.includes("/catalog?")) return { ok: true, json: async () => ({
        dataset_id: "census_acs5_2024_b19013", active_release_id: "acs-release", value_type: "median_household_income",
        unit: "2024 inflation-adjusted USD", geographies: ["state", "county", "tract"],
        measures: [{ measure_id: "B19013_001E", label: "Median household income", observation_period: "2020–2024", population: "households" }],
      }) };
      requests.push(path);
      const geography = path.includes("geography=tract") ? "tract" : path.includes("geography=county") ? "county" : "state";
      const geoid = geography === "tract" ? "09110000100" : geography === "county" ? "09110" : "09";
      const payload = path.includes("/map?") ? { features: [] }
        : path.includes("/legend?") ? { statuses: [{ status: "available", n: 1, low: 50000, high: 50000 }] }
        : { total: 1, rows: [{ geography_id: geoid, name: "Area", value: 50000, moe: 5000, status: "available" }] };
      return { ok: true, json: async () => ({ ...payload, release_id: "acs-release", geography }) };
    }));
    render(<Places2025Pilot dataset="acs" />);
    expect(await screen.findByText("09")).toBeInTheDocument();
    mapHarness.zoom = ACS_COUNTY_ZOOM;
    act(() => mapHarness.handlers.zoomend());
    expect(await screen.findByText("09110")).toBeInTheDocument();
    mapHarness.zoom = ACS_TRACT_ZOOM;
    act(() => mapHarness.handlers.zoomend());
    expect(await screen.findByText("09110000100")).toBeInTheDocument();
    expect(screen.getByText(/±\$5,000 \(90% MOE\)/)).toBeInTheDocument();
    expect(requests.filter((path) => path.includes("/map?")).map((path) => new URLSearchParams(path.split("?")[1]).get("geography")))
      .toEqual(["state", "county", "tract"]);
    expect(requests.every((path) => path.includes("release_id=acs-release") && path.includes("period=2020%E2%80%932024") && path.includes("population=households") && path.includes("dataset_id=census_acs5_2024_b19013"))).toBe(true);
  });
  it("shows an open-ended median as an annotated bound", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      const path = String(url);
      const payload = path.includes("/catalog?") ? {
        dataset_id: "census_acs5_2024_b19013", active_release_id: "acs-open", value_type: "median_household_income",
        unit: "2024 inflation-adjusted USD", geographies: ["state", "county", "tract"],
        measures: [{ measure_id: "B19013_001E", label: "Income", observation_period: "2020–2024", population: "households" }],
      } : path.includes("/map?") ? { release_id: "acs-open", geography: "state", features: [] }
        : path.includes("/legend?") ? { release_id: "acs-open", geography: "state", statuses: [
            { status: "available", n: 1, low: 50000, high: 50000 }, { status: "open_ended", n: 1, low: 250001, high: 250001 },
          ] }
        : { release_id: "acs-open", geography: "state", total: 1, rows: [
            { geography_id: "09", name: "Area", value: 250001, estimate_annotation: "250,000+", moe: null, moe_annotation: "***", status: "open_ended" },
          ] };
      return { ok: true, json: async () => payload };
    }));
    render(<Places2025Pilot dataset="acs" />);
    expect(await screen.findByText("≥$250,000")).toBeInTheDocument();
    expect(screen.getByText("*** (MOE unavailable)")).toBeInTheDocument();
    expect(screen.getByText("Open-ended median")).toBeInTheDocument();
    expect(screen.queryByText("$250,001")).not.toBeInTheDocument();
  });
});

describe("CLH measure geography", () => {
  afterEach(() => { vi.unstubAllGlobals(); mapHarness.zoom = 4; mapHarness.handlers = null; });
  it("keeps the county grocery rate at high zoom with its exact period and unit", async () => {
    expect(resolveRoute("/area/clh")).toEqual({ type: "clh-area" });
    const requests = [];
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      const path = String(url);
      if (path.includes("/catalog")) return { ok: true, json: async () => ({
        dataset_id: "ahrq_clh_2023_curated", active_release_id: "release-clh", value_type: "published_rate_or_percentage",
        geographies: ["county", "tract"], source_url: "https://www.ahrq.gov/data/innovations/clh-data.html",
        measures: [{ measure_id: "CCBP_SOGS_RATE", label: "Supermarkets and grocery stores per 1,000 residents",
          observation_period: "2023", population: "paid-employee establishments, NAICS 445110",
          denominator: "county resident population", unit: "establishments per 1,000 people", source: "U.S. Census Bureau",
          geographies: ["county"] }],
      }) };
      requests.push(path);
      const payload = path.includes("/map?") ? { features: [] } : path.includes("/legend?")
        ? { statuses: [{ status: "available", n: 1, low: 0.13, high: 0.13 }] }
        : { total: 1, rows: [{ geography_id: "01001", name: "Autauga County", value: 0.13, status: "available" }] };
      return { ok: true, json: async () => ({ ...payload, geography: "county", release_id: "release-clh" }) };
    }));
    render(<Places2025Pilot dataset="clh" />);
    expect(await screen.findByText("01001")).toBeInTheDocument();
    act(() => { mapHarness.zoom = PILOT_TRACT_ZOOM; mapHarness.handlers.zoomend(); });
    expect(await screen.findByText(/no tract estimate is published/i)).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Value (establishments per 1,000 people)" })).toBeInTheDocument();
    expect(requests.every((url) => url.includes("geography=county") && url.includes("period=2023")
      && url.includes("release_id=release-clh"))).toBe(true);
  });
});

describe("EPA annual county AQI", () => {
  afterEach(() => { vi.unstubAllGlobals(); mapHarness.zoom = 4; mapHarness.handlers = null; });
  const measures = [
    { measure_id: "median_aqi", label: "Median AQI", kind: "aqi_index", unit: "AQI index value", observation_period: "2025",
      population: "days with a reported daily AQI from county monitoring sites", legend_breaks: [25, 50, 100, 150],
      official_definition: "Half of daily AQI values during the year were less than or equal to the median value, and half equaled or exceeded it.",
      statistic_note: "Median of the county's daily AQI values; a distribution statistic, not an uncertainty interval." },
    { measure_id: "p90_aqi", label: "90th percentile AQI", kind: "aqi_index", unit: "AQI index value", observation_period: "2025",
      population: "days with a reported daily AQI from county monitoring sites", legend_breaks: [25, 50, 100, 150],
      official_definition: "90 percent of daily AQI values during the year were less than or equal to the 90th percentile value.",
      statistic_note: "90th percentile of the county's daily AQI values; a distribution statistic, not a confidence interval or margin of error." },
    { measure_id: "good_days", label: "Good days", kind: "day_count", unit: "days", observation_period: "2025",
      population: "days with a reported daily AQI from county monitoring sites", legend_breaks: [73, 146, 219, 292],
      official_definition: "Number of days in the year having an AQI value 0 through 50.", statistic_note: "Interpret with Days with AQI." },
  ];
  const limitations = ["Annual historical AQI summary for one calendar year; not current or forecast conditions.",
    "No reported value means no county summary was published, not that the air was clean."];

  it("formats values, reporting days, beyond-index maxima, and absent counties without inventing zeros", () => {
    expect(aqiValueText({ value: 0, status: "true_zero" }, measures[2])).toBe("0 days");
    expect(aqiValueText({ value: null, status: "no_reported_value" }, measures[0])).toBe("No reported value");
    expect(aqiValueText({ value: 2122, status: "available", value_note: "above_500_beyond_aqi_scale" }, measures[0]))
      .toBe("2,122 (above 500: beyond the AQI scale)");
    expect(aqiReportingText({ days_with_aqi: 355 }, "2025")).toBe("355 of 365 days with AQI");
    expect(aqiReportingText({ days_with_aqi: 366 }, "2024")).toBe("366 of 366 days with AQI");
    expect(aqiReportingText({ days_with_aqi: null }, "2025")).toMatch(/No EPA county summary/);
    expect(aqiBinLabels([25, 50, 100, 150], "AQI index value")).toEqual(["0–25", "26–50", "51–100", "101–150", "151 or more"]);
    expect(aqiColor(null, "no_reported_value", [25])).toBe("#ffffff");
    expect(aqiColor(0, "true_zero", [25, 50])).not.toBe(aqiColor(null, "no_reported_value", [25, 50]));
    // No daily health-category palette (green/yellow/orange/red/purple/maroon).
    expect(["#00e400", "#ffff00", "#ff7e00", "#ff0000", "#8f3f97", "#7e0023"]).not.toContain(aqiColor(40, "available", [25, 50, 100, 150]));
    const popup = areaTooltip("aqi", { name: "Baldwin<script>", geography_id: "01003", value: 42, status: "available", days_with_aqi: 355,
      source_name: "Baldwin, Alabama" }, measures[0], { geography: "county" })
      + areaFeatureDetails("aqi", { name: "Baldwin", geography_id: "01003", value: 42, status: "available", days_with_aqi: 355 }, measures[0], { geography: "county" }).lines.join(" | ");
    expect(popup).toContain("355 of 365 days with AQI");
    expect(popup).toContain("historical, not current");
    expect(popup).not.toContain("<script>");
  });

  it("keeps one release-pinned county selection with reporting days in table and limitations visible", async () => {
    expect(resolveRoute("/area/epa-aqi")).toEqual({ type: "epa-aqi-area" });
    const urls = [];
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      const path = String(url); urls.push(path);
      const payload = path.includes("/catalog") ? {
        dataset_id: "epa_airdata_aqi_county_2025", active_release_id: "release-aqi", value_type: "annual_aqi_summary",
        geographies: ["county"], source_url: "https://aqs.epa.gov/aqsweb/airdata/download_files.html", measures, limitations,
      } : path.includes("/map?") ? { release_id: "release-aqi", features: [] }
        : path.includes("/legend?") ? { release_id: "release-aqi", statuses: [
          { status: "available", n: 1, low: 42, high: 42, days_low: 355, days_high: 355 },
          { status: "no_reported_value", n: 1, low: null, high: null, days_low: null, days_high: null }] }
        : { release_id: "release-aqi", total: 2, rows: [
          { geography_id: "01001", name: "Autauga", value: null, status: "no_reported_value", days_with_aqi: null, source_name: null },
          { geography_id: "01003", name: "Baldwin", value: 42, status: "available", days_with_aqi: 355, source_name: "Baldwin, Alabama" }] };
      return { ok: true, json: async () => ({ ...payload, geography: "county" }) };
    }));
    render(<Places2025Pilot dataset="aqi" />);
    expect(await screen.findByText("01003")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Days with AQI" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "EPA source name" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /95% CI|MOE|Uncertainty/ })).not.toBeInTheDocument();
    expect(screen.getByText("355")).toBeInTheDocument();
    expect(screen.getAllByText("No reported value").length).toBeGreaterThan(0);
    expect(screen.getByText(/not that the air was clean/)).toBeInTheDocument();
    expect(screen.getByText(/not current or forecast conditions/)).toBeInTheDocument();
    expect(screen.getByText(/category colors are not used/)).toBeInTheDocument();
    expect(screen.getByText(/does not mean clean air/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Measure/), { target: { value: "p90_aqi" } });
    expect(await screen.findByText(/not a confidence interval or margin of error/)).toBeInTheDocument();
    act(() => { mapHarness.zoom = 12; mapHarness.handlers.zoomend(); });
    const data = urls.filter((url) => url.includes("/area/") && !url.includes("/catalog"));
    expect(data.every((url) => url.includes("dataset_id=epa_airdata_aqi_county_2025") && url.includes("geography=county")
      && url.includes("release_id=release-aqi") && url.includes("period=2025"))).toBe(true);
    expect(data.some((url) => url.includes("measure_id=p90_aqi"))).toBe(true);
  });
});

describe("CMS Original Medicare Geographic Variation", () => {
  afterEach(() => { vi.unstubAllGlobals(); mapHarness.zoom = 4; mapHarness.handlers = null; });
  const population = "Original Medicare beneficiaries, all ages";
  const measures = [
    { measure_id: "om_beneficiaries", label: "Original Medicare beneficiaries", source_field: "BENES_OM_CNT", kind: "count",
      unit: "beneficiaries", observation_period: "2024", population, denominator: "None (count).",
      official_definition: "Count of Medicare beneficiaries who were enrolled in Part A and Part B.", interpretation: "Not a resident population." },
    { measure_id: "std_payment_per_capita", label: "Standardized Medicare payment per beneficiary", source_field: "TOT_MDCR_STDZD_PYMT_PC",
      kind: "currency", unit: "US dollars per Original Medicare beneficiary (2024, nominal)", observation_period: "2024", population,
      denominator: "Original Medicare beneficiaries in the area (per capita).",
      official_definition: "Actual per capita Original Medicare payment for beneficiaries, adjusted for geographic differences in payment rates.",
      interpretation: "It is not adjusted for inflation. CMS's catalog states it does not adjust for beneficiaries' health status, so CHIP does not present it as risk-adjusted." },
    { measure_id: "readmission_rate", label: "All-cause 30-day hospital readmission rate", source_field: "ACUTE_HOSP_READMSN_PCT",
      kind: "proportion", unit: "percent of acute hospital stays (CMS stores 0-1)", observation_period: "2024", population,
      denominator: "Acute hospital admissions where the beneficiary was discharged alive (not beneficiaries).",
      official_definition: "Percentage of inpatient readmissions within 30 days of an acute hospital stay.", interpretation: "Not risk-adjusted." },
  ];
  const catalog = {
    dataset_id: "cms_om_geographic_variation", active_release_id: "gv-release", value_type: "cms_om_gv_published",
    geographies: ["state", "county"], state_to_county_zoom: 6, observation_year: 2024,
    source_release_id: "OM GV PUF May 2026 update (2014-2024 CSV)",
    population_label: "Original Medicare beneficiaries (Part A and Part B, no Medicare Advantage), all ages",
    source_url: "https://data.cms.gov/summary-statistics-on-use-and-payments/medicare-geographic-comparisons/medicare-geographic-variation-by-national-state-county",
    measures, limitations: ["Original Medicare (fee-for-service) beneficiaries with Part A and Part B only. Medicare Advantage enrollees are excluded.",
      "State and county values are published separately by CMS. CHIP does not add counties into states."],
  };

  it("formats each unit and keeps suppressed, missing, not-published, and zero distinct", () => {
    expect(gvGeography(4)).toBe("state");
    expect(gvGeography(6)).toBe("county");
    expect(gvGeography(12)).toBe("county");
    expect(gvNumber(27732177, "count")).toBe("27,732,177");
    expect(gvNumber(12553.26, "currency")).toBe("$12,553");
    expect(gvNumber(224.8391, "per_1000")).toBe("224.8 per 1,000");
    expect(gvNumber(0.1807, "proportion")).toBe("18.07%");
    expect(gvValueText({ value: 0, status: "true_zero" }, measures[2])).toBe("0.00%");
    const texts = ["suppressed", "missing", "not_published"].map((status) => gvValueText({ value: null, status }, measures[0]));
    expect(new Set(texts).size).toBe(3);
    expect(texts[0]).toMatch(/fewer than 11/);
    expect(gvColor(null, "suppressed", [1])).not.toBe(gvColor(null, "not_published", [1]));
    expect(gvColor(0, "true_zero", [0.15, 0.165])).not.toBe(gvColor(null, "missing", [0.15, 0.165]));
    expect(gvBinLabels([0.15, 0.165, 0.18, 0.195], "proportion")).toEqual(
      ["Under 15.00%", "15.00% to under 16.50%", "16.50% to under 18.00%", "18.00% to under 19.50%", "19.50% or more"]);
    const gvItem = { name: "Baldwin<b>", geography_id: "01003", value: 0.2, status: "available", source_name: "AL-Baldwin" };
    const popup = areaTooltip("cmsgv", gvItem, measures[2], { geography: "county", catalog })
      + areaFeatureDetails("cmsgv", gvItem, measures[2], { geography: "county", catalog }).lines.join(" | ");
    expect(popup).toContain("Baldwin&lt;b&gt; · County 01003");
    expect(popup).toContain("20.00%");
    expect(popup).toContain("Medicare Advantage");
  });

  it("starts with states, switches to counties, keeps counties at tract zoom, and pins one exact selection", async () => {
    expect(resolveRoute("/area/cms-gv")).toEqual({ type: "cms-gv-area" });
    const urls = [];
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      const path = String(url); urls.push(path);
      if (path.includes("/catalog")) return { ok: true, json: async () => catalog };
      const geography = path.includes("geography=county") ? "county" : "state";
      const breaks = [10500, 11500, 12500, 13500];
      const payload = path.includes("/map?") ? { features: [], legend_breaks: breaks }
        : path.includes("/legend?") ? { legend_breaks: breaks, national_reference: { value: 12553.26, status: "available" },
          statuses: [{ status: "available", n: 1, low: 11000, high: 11000 }, { status: "not_published", n: 1, low: null, high: null },
            { status: "suppressed", n: 1, low: null, high: null }] }
        : geography === "state" ? { total: 1, rows: [{ geography_id: "01", name: "Alabama", value: 11000.5, source_value: "11000.5", status: "available" }] }
        : { total: 3, rows: [
          { geography_id: "01001", name: "Autauga", value: 12527.77, source_value: "12527.77", status: "available" },
          { geography_id: "02000", name: "Unknown", value: null, source_value: "*", status: "suppressed" },
          { geography_id: "11001", name: "District of Columbia", value: null, source_value: null, status: "not_published" }] };
      return { ok: true, json: async () => ({ ...payload, release_id: "gv-release", geography }) };
    }));
    render(<Places2025Pilot dataset="cmsgv" />);
    expect(await screen.findByText("01")).toBeInTheDocument();
    expect(screen.getByText("$11,001")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "CMS source value" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /95% CI|MOE|Uncertainty/ })).not.toBeInTheDocument();
    expect(screen.getByText(/United States \(CMS-published national value, reference only\): \$12,553/)).toBeInTheDocument();
    expect(screen.getByText(/does not present it as risk-adjusted/)).toBeInTheDocument();
    expect(screen.queryByText(/legacy import/)).not.toBeInTheDocument();
    expect(screen.getByText(/CHIP does not add counties into states/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Measure/), { target: { value: "readmission_rate" } });
    expect(await screen.findByText(/discharged alive \(not beneficiaries\)/)).toBeInTheDocument();
    mapHarness.zoom = 6;
    act(() => mapHarness.handlers.zoomend());
    expect(await screen.findByText("01001")).toBeInTheDocument();
    expect(screen.getAllByText("Suppressed by CMS (fewer than 11)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Not published by CMS at this level").length).toBeGreaterThan(0);
    act(() => { mapHarness.zoom = 12; mapHarness.handlers.zoomend(); });
    expect(await screen.findByText(/CMS publishes no tract estimates/)).toBeInTheDocument();
    const data = urls.filter((url) => url.includes("/area/") && !url.includes("/catalog"));
    expect(data.every((url) => url.includes("dataset_id=cms_om_geographic_variation") && url.includes("release_id=gv-release")
      && url.includes("period=2024") && url.includes(`population=${encodeURIComponent(population).replace(/%20/g, "+")}`)
      && !url.includes("geography=tract"))).toBe(true);
    const mapGeographies = data.filter((url) => url.includes("/map?")).map((url) => [
      new URLSearchParams(url.split("?")[1]).get("geography"), new URLSearchParams(url.split("?")[1]).get("measure_id")]);
    expect(mapGeographies[0]).toEqual(["state", "std_payment_per_capita"]);
    expect(mapGeographies).toContainEqual(["state", "readmission_rate"]);
    expect(mapGeographies).toContainEqual(["county", "readmission_rate"]);
    expect(mapGeographies.filter(([geo, id]) => geo === "county" && id !== "readmission_rate")).toEqual([]);
  });

  it("ignores a slower response for a measure the user already left", async () => {
    const pending = [];
    vi.stubGlobal("fetch", vi.fn((url) => {
      const path = String(url);
      // Distinct release: the page's response cache is module-level and shared across tests.
      if (path.includes("/catalog")) return Promise.resolve({ ok: true, json: async () => ({ ...catalog, active_release_id: "gv-stale" }) });
      const measure = new URLSearchParams(path.split("?")[1]).get("measure_id");
      const value = measure === "om_beneficiaries" ? 999999 : 12000;
      const payload = path.includes("/map?") ? { features: [], legend_breaks: [1] }
        : path.includes("/legend?") ? { legend_breaks: [1], statuses: [] }
        : { total: 1, rows: [{ geography_id: "01", name: "Alabama", value, source_value: String(value), status: "available" }] };
      return new Promise((resolve) => pending.push({ measure, resolve: () => resolve({ ok: true,
        json: async () => ({ ...payload, release_id: "gv-stale", geography: "state" }) }) }));
    }));
    render(<Places2025Pilot dataset="cmsgv" />);
    await screen.findByLabelText(/Measure/);
    await act(async () => { await Promise.resolve(); });
    fireEvent.change(screen.getByLabelText(/Measure/), { target: { value: "om_beneficiaries" } });
    fireEvent.change(screen.getByLabelText(/Measure/), { target: { value: "std_payment_per_capita" } });
    await act(async () => { pending.filter((item) => item.measure === "std_payment_per_capita").forEach((item) => item.resolve()); });
    await act(async () => { pending.filter((item) => item.measure === "om_beneficiaries").forEach((item) => item.resolve()); });
    expect(await screen.findByText("$12,000")).toBeInTheDocument();
    expect(screen.queryByText("999,999")).not.toBeInTheDocument();
  });
});

describe("USDA Food Environment Atlas county measures", () => {
  afterEach(() => { vi.unstubAllGlobals(); mapHarness.zoom = 4; mapHarness.handlers = null; mapHarness.geojson = null; });
  const measures = [
    { measure_id: "low_income_low_access_pct", variable_code: "PCT_LACCESS_LOWI19", label: "Low-income residents with low supermarket access (share of all residents)",
      observation_period: "2019", kind: "percent", unit: "percent of total county population", population: "total county population",
      denominator: "Total county population (2010 Census block population). The numerator is low-income residents only.",
      official_definition: "Percentage of people in a county with low income and living more than 1 mile from a foodstore.",
      contributing_sources: "ERS low-access tracts.", interpretation: "Not a food-desert designation.", source_boundary_basis: "2020 Census counties",
      legend_breaks: [3, 6, 9, 13], geographies: ["county"] },
    { measure_id: "snap_stores_per_1000", variable_code: "SNAPSPTH23", label: "SNAP-authorized stores per 1,000 residents",
      observation_period: "2023", kind: "per_1000", unit: "stores per 1,000 residents", population: "county residents",
      denominator: "County residents.", official_definition: "The average monthly number of stores in the county authorized to accept SNAP per 1,000 county residents.",
      contributing_sources: "USDA FNS.", interpretation: "Not a current store directory.", source_boundary_basis: "2020 Census counties",
      legend_breaks: [0.7, 0.9, 1.1, 1.3], geographies: ["county"] },
    { measure_id: "farmers_markets_per_1000", variable_code: "FMRKTPTH18", label: "Farmers' markets per 1,000 residents",
      observation_period: "2018", kind: "per_1000", unit: "markets per 1,000 residents", population: "county residents",
      denominator: "County residents.", official_definition: "The number of farmers' markets in the county per 1,000 county residents.",
      contributing_sources: "USDA AMS.", interpretation: "Voluntary listings.", source_boundary_basis: "Pre-2019 counties",
      legend_breaks: [0.02, 0.04, 0.08, 0.15], geographies: ["county"] },
  ];
  const catalog = { dataset_id: FEA_DATASET_ID, release_label: "July 2025", value_type: "published_county_value",
    geographies: ["county"], measures, active_release_id: "fea-release", boundary_vintage: "TIGER/Line 2024 county equivalents",
    source_url: "https://www.ers.usda.gov/data-products/food-environment-atlas", documentation_url: "https://www.ers.usda.gov/doc",
    limitations: ["Each measure has its own observation year (2018–2023); they are not one snapshot and not current conditions."] };

  it("keeps sentinels, zero, and boundary exceptions distinct in text, color, and bins", () => {
    expect(resolveRoute("/area/usda-fea")).toEqual({ type: "usda-fea-area" });
    expect(feaNumber(13.020998, "percent")).toBe("13%");
    expect(feaNumber(0.096, "per_1000")).toBe("0.096 per 1,000");
    const statuses = ["not_available", "did_not_exist", "boundary_not_comparable", "not_covered"];
    const texts = statuses.map((status) => feaValueText({ value: null, status }, measures[0]));
    expect(new Set(texts).size).toBe(4);
    expect(texts[0]).toMatch(/-9999/); expect(texts[1]).toMatch(/-8888/);
    expect(feaValueText({ value: 0, status: "true_zero" }, measures[2])).toBe("0 (published zero)");
    expect(feaColor(0, "true_zero", [0.02])).not.toBe(feaColor(null, "not_available", [0.02]));
    expect(feaColor(0, "true_zero", [0.02])).not.toBe(feaColor(0.01, "available", [0.02]));
    expect(feaColor(null, "did_not_exist", [1])).not.toBe(feaColor(null, "not_available", [1]));
    expect(feaBinLabels([3, 6, 9, 13], "percent")).toEqual(
      ["Above 0 to under 3%", "3% to under 6%", "6% to under 9%", "9% to under 13%", "13% or more"]);
    const feaItem = { name: "Autauga<i>", geography_id: "01001", value: 13.02, source_value: "13.02099800", status: "available", source_name: "Autauga, AL" };
    const popup = areaTooltip("usdafea", feaItem, measures[0], { geography: "county" })
      + areaFeatureDetails("usdafea", feaItem, measures[0], { geography: "county" }).lines.join(" | ");
    expect(popup).toContain("Autauga&lt;i&gt; · County 01001");
    expect(popup).toContain("Observation year 2019");
    expect(popup).toContain("USDA value: 13.02099800 (PCT_LACCESS_LOWI19)");
  });

  it("shows counties at national view, keeps the exact selection across zooms, and matches map and table", async () => {
    const urls = [];
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      const path = String(url); urls.push(path);
      if (path.includes("/catalog")) return { ok: true, json: async () => catalog };
      const query = new URLSearchParams(path.split("?")[1]);
      const rows = [
        { geography_id: "01001", name: "Autauga", value: 0, source_value: "0", status: "true_zero" },
        { geography_id: "01003", name: "Baldwin", value: null, source_value: "-9999", status: "not_available" },
        { geography_id: "02063", name: "Chugach", value: null, source_value: "-8888", status: "did_not_exist" },
        { geography_id: "09110", name: "Capitol", value: null, source_value: null, status: "boundary_not_comparable" },
        { geography_id: "72001", name: "Adjuntas", value: null, source_value: null, status: "not_covered" },
      ];
      const payload = path.includes("/map?")
        ? { type: "FeatureCollection", legend_breaks: [0.02, 0.04, 0.08, 0.15],
          features: rows.map((row) => ({ type: "Feature", geometry: null, properties: row })) }
        : path.includes("/legend?") ? { legend_breaks: [0.02, 0.04, 0.08, 0.15], statuses: rows.map((row) => ({ status: row.status, n: 1, low: row.value, high: row.value })) }
        : { total: rows.length, rows };
      return { ok: true, json: async () => ({ ...payload, release_id: "fea-release", geography: query.get("geography") }) };
    }));
    render(<Places2025Pilot dataset="usdafea" />);
    expect(await screen.findByText("01001")).toBeInTheDocument();
    expect(screen.getByText(/Observation year 2019/)).toBeInTheDocument();
    expect(screen.getByText(/State values are not published for this measure; counties are shown at the national view/)).toBeInTheDocument();
    expect(screen.getByText(/numerator is low-income residents only/)).toBeInTheDocument();
    expect(screen.queryByText(/legacy import/)).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "USDA source value" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Measure/), { target: { value: "farmers_markets_per_1000" } });
    expect(await screen.findByText(/Observation year 2018/)).toBeInTheDocument();
    expect(await screen.findByText("-8888")).toBeInTheDocument();
    expect(screen.getAllByText(FEA_STATUS_TEXT.did_not_exist).length).toBeGreaterThan(0);
    expect(screen.getAllByText(FEA_STATUS_TEXT.not_available).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Published zero").length).toBeGreaterThan(0);
    // Map/table parity: same counties in the same order, and every status has a distinct non-numeric color.
    const tableIds = screen.getAllByRole("rowheader").map((cell) => cell.textContent);
    expect(mapHarness.geojson.data.features.map((f) => f.properties.geography_id)).toEqual(tableIds);
    const fills = mapHarness.geojson.data.features.map((f) => mapHarness.geojson.style(f).fillColor);
    expect(new Set(fills.slice(0, 3)).size).toBe(3);
    act(() => { mapHarness.zoom = 7; mapHarness.handlers.zoomend(); });
    act(() => { mapHarness.zoom = 12; mapHarness.handlers.zoomend(); });
    expect(await screen.findByText(/USDA publishes no tract values for these measures/)).toBeInTheDocument();
    const data = urls.filter((url) => url.includes("/area/") && !url.includes("/catalog"));
    expect(data.every((url) => url.includes(`dataset_id=${FEA_DATASET_ID}`) && url.includes("release_id=fea-release")
      && url.includes("geography=county"))).toBe(true);
    const fm = data.filter((url) => url.includes("measure_id=farmers_markets_per_1000"));
    expect(fm.length).toBeGreaterThan(0);
    expect(fm.every((url) => url.includes("period=2018") && url.includes("population=county+residents"))).toBe(true);
    expect(data.filter((url) => url.includes("measure_id=low_income_low_access_pct")).every((url) => url.includes("period=2019"))).toBe(true);
  });

  it("describes the selected USDA year and its Connecticut county boundary", async () => {
    const current = { period: "2019", current: true, available: true, release_id: "fea-copy-current" };
    const earlier = { period: "2015", current: false, available: true, release_id: "fea-copy-history",
      levels: ["county"], boundary_vintage: { county: "TIGER/Line 2020 (Connecticut former counties)" }, note: "Earlier USDA measure." };
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      const path = String(url);
      if (path.includes("/catalog")) return { ok: true, json: async () => ({ ...catalog,
        active_release_id: current.release_id,
        measures: [{ ...measures[0], periods: [current, earlier] }],
        limitations: [...catalog.limitations,
          "Connecticut values exist only for its eight former counties and cannot be shown on the 2024 planning-region boundaries. Puerto Rico is outside the Atlas."],
      }) };
      const old = new URLSearchParams(path.split("?")[1]).get("period") === "2015";
      const payload = path.includes("/map?") ? { features: [] }
        : path.includes("/legend?") ? { legend_breaks: [3, 6, 9, 13], statuses: [] }
        : { total: 0, rows: [] };
      return { ok: true, json: async () => ({ ...payload, release_id: old ? earlier.release_id : current.release_id, geography: "county" }) };
    }));
    render(<Places2025Pilot dataset="usdafea" />);
    await screen.findByLabelText("Year");
    expect(screen.getByText(/cannot be shown on the 2024 planning-region boundaries/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Year"), { target: { value: "2015" } });
    expect(await screen.findByText(/this map shows 2015/)).toBeInTheDocument();
    expect(screen.getByText(/Connecticut's eight former counties are drawn on the TIGER\/Line 2020/)).toBeInTheDocument();
    expect(screen.queryByText(/cannot be shown on the 2024 planning-region boundaries/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Not published on this boundary \(Connecticut planning region\) or/)).not.toBeInTheDocument();
    expect(screen.queryByText(/PCT_LACCESS_LOWI19/)).not.toBeInTheDocument();
    expect(screen.queryByText(/County boundary basis in the source:/)).not.toBeInTheDocument();
    expect(screen.getAllByText("Outside Atlas coverage (Puerto Rico)").length).toBeGreaterThan(0);
    expect(areaFeatureDetails("usdafea", { source_value: "4.5", value: 4.5, status: "available" },
      measures[0], { period: "2015" }).lines).toContain("USDA value: 4.5");
  });
});

describe("area map selection, focus, and class breaks", () => {
  afterEach(() => { vi.unstubAllGlobals(); mapHarness.zoom = 4; mapHarness.handlers = null; mapHarness.outline = null; mapHarness.map.setView.mockClear(); });

  const placesStub = (extra = {}) => vi.fn(async (url) => {
    const path = String(url);
    if (path.includes("/community/area/")) {
      return { ok: true, json: async () => ({ level: "county", geoid: "37145", name: "Person", bbox: [-79.2, 36.2, -78.8, 36.5],
        geometry: { type: "Polygon", coordinates: [] } }) };
    }
    const payload = path.endsWith("/catalog") ? {
      dataset_id: "cdc_places_county_2025_pilot", active_release_id: "release-a", value_type: "crude_prevalence", unit: "percent",
      measures: [{ measure_id: "diabetes_crudeprev", label: "Diagnosed diabetes", observation_period: "2023", population: "adults" }],
    } : path.includes("/map?") ? { release_id: "release-a", features: [{ type: "Feature", geometry: { type: "Polygon", coordinates: [] },
        properties: { county_fips: "37145", geography_id: "37145", name: "Person", value: 13.4, ci_low: 11.9, ci_high: 15, status: "available" } }] }
      : path.includes("/legend?") ? { release_id: "release-a", quantile_breaks: [11.4, 12.7, 13.9, 15.7], statuses: [{ status: "available", n: 1, low: 13.4, high: 13.4 }], ...extra }
      : { release_id: "release-a", total: 1, rows: [{ county_fips: "37145", name: "Person", value: 13.4, ci_low: 11.9, ci_high: 15, status: "available" }] };
    return { ok: true, json: async () => ({ ...payload, geography: "county" }) };
  });

  it("classes values by release quintiles so an outlier cannot wash out the map", () => {
    const cuts = [11.4, 12.7, 13.9, 15.7];
    const shades = [9, 12, 13.4, 15, 27.1].map((value) => quintileColor(value, "available", cuts));
    expect(new Set(shades).size).toBe(5);
    expect(shades[4]).toBe("#003f61");
    expect(quintileColor(null, "suppressed", cuts)).not.toBe(quintileColor(null, "missing", cuts));
    expect(shades).not.toContain(quintileColor(null, "not_published", cuts));
  });

  it("reads focus links and maps each level to its profile and zoom limits", () => {
    expect(parseFocus("?focus=county:37145")).toEqual({ level: "county", geoid: "37145" });
    expect(parseFocus("?focus=cd:5401")).toEqual({ level: "cd", geoid: "5401" });
    expect(parseFocus("?focus=county:37")).toBeNull();
    expect(parseFocus("?focus=zip:27573")).toBeNull();
    expect(profileHrefFor({ level: "state", geoid: "37" })).toBe("/community/state/37");
    expect(profileHrefFor({ level: "cd", geoid: "5401" })).toBe("/district/cd/5401");
    expect(profileHrefFor({ level: "tract", geoid: "37145920100" })).toBeNull();
    expect(focusZoomRange("state", { stateBelow: 6 }).max).toBeLessThan(6);
    expect(focusZoomRange("county", { countyFrom: 6, tractFrom: 10 })).toEqual({ min: 6, max: 9.75 });
  });

  it("opens zoomed to a focused county, outlines it, and shows its value in the legend", async () => {
    window.history.replaceState(null, "", "/area/places-2025?measure_id=diabetes_crudeprev&focus=county:37145");
    const fetchMock = placesStub();
    vi.stubGlobal("fetch", fetchMock);
    render(<Places2025Pilot />);
    const block = await screen.findByTestId("selected-area");
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/community/area/county/37145"))).toBe(true);
    expect(mapHarness.map.setView).toHaveBeenCalledWith([36.35, -79], 8);
    expect(block).toHaveTextContent("Person · County 37145");
    expect(await screen.findByText("13.4%", { selector: "strong" })).toBeInTheDocument();
    expect(block).toHaveTextContent("95% confidence interval: 11.9–15%");
    expect(mapHarness.outline.data).toEqual({ type: "Polygon", coordinates: [] });
    expect(screen.getByRole("link", { name: "Open county profile →" })).toHaveAttribute("href", "/community/county/37145");
    fireEvent.click(screen.getByRole("button", { name: /Map Tools/ }));
    expect(screen.getByRole("link", { name: "Open profile" })).toHaveAttribute("href", "/community/county/37145");
    expect(screen.getByRole("button", { name: "Zoom to selected county" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Analyze/ })).not.toBeInTheDocument();
    expect(window.location.search).toContain("focus=county%3A37145");
    expect(screen.getByText(/quintiles of all published county values/i)).toBeInTheDocument();
    expect(screen.getByText("11.4% or less")).toBeInTheDocument();
  });

  it("selects a clicked area, keeps it across a viewport change, and clears on Escape", async () => {
    vi.stubGlobal("fetch", placesStub());
    render(<Places2025Pilot />);
    await screen.findByText("37145");
    const handlers = {};
    const layer = { on: (name, handler) => { handlers[name] = handler; }, setStyle: vi.fn(), bindTooltip: vi.fn(),
      getBounds: () => ({ isValid: () => true, getWest: () => -79.2, getSouth: () => 36.2, getEast: () => -78.8, getNorth: () => 36.5 }) };
    const feature = mapHarness.geojson.data.features[0];
    mapHarness.geojson.onEachFeature(feature, layer);
    expect(layer.bindTooltip.mock.calls[0][0]).toContain("Person · County 37145<br/>Diagnosed diabetes<br/>13.4% • 2023");
    expect(layer.bindTooltip.mock.calls[0][1].className).toBe("pdo-map-tooltip");
    expect(screen.queryByTestId("selected-area")).not.toBeInTheDocument();
    act(() => handlers.click());
    expect(screen.getByTestId("selected-area")).toHaveTextContent("Person · County 37145");
    mapHarness.zoom = 7;
    await act(async () => { mapHarness.handlers.moveend(); });
    expect(screen.getByTestId("selected-area")).toHaveTextContent("Person · County 37145");
    expect(await screen.findByText("13.4%", { selector: "strong" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("selected-area")).not.toBeInTheDocument();
  });

  it("says so, and computes nothing, when the selected state has no value at the level drawn", async () => {
    window.history.replaceState(null, "", "/area/places-2025?focus=state:37");
    vi.stubGlobal("fetch", placesStub());
    render(<Places2025Pilot />);
    const block = await screen.findByTestId("selected-area");
    expect(block).toHaveTextContent(/showing county values/i);
    expect(block).toHaveTextContent(/none is calculated/i);
  });
});

describe("historical area map years", () => {
  afterEach(() => { vi.unstubAllGlobals(); mapHarness.zoom = 4; mapHarness.geojson = null; });

  function historyStub({ district = false, missingShape = false, publishedWithoutBoundary = 2, releaseTag = "h4" } = {}) {
    const measures = [{ measure_id: "diabetes_crudeprev", label: "Diagnosed diabetes", observation_period: "2023", population: "adults",
      periods: [
        { period: "2023", current: true, available: true, release_id: `${releaseTag}-current` },
        { period: "2022", current: false, available: true, release_id: `${releaseTag}-history`, levels: district ? ["state", "county", "tract"] : ["county", "tract"],
          note: "A separate model run.", boundary_vintage: { county: "TIGER/Line 2020", tract: "TIGER/Line 2019" } },
        { period: "2021", current: false, available: false, release_id: null, levels: ["county"], note: "Unavailable" },
        { period: "2020", current: false, available: true, release_id: `${releaseTag}-history`, levels: ["county"],
          note: "An older model run.", boundary_vintage: { county: "TIGER/Line 2020" } },
      ] }, { measure_id: "access2_crudeprev", label: "Insurance", observation_period: "2023", population: "adults",
        periods: [{ period: "2023", current: true, available: true, release_id: `${releaseTag}-current` },
          { period: "2022", current: false, available: true, release_id: `${releaseTag}-history`, levels: ["county"], note: "An older estimate." }] },
      { measure_id: "dental_crudeprev", label: "Dental visits", observation_period: "2023", population: "adults",
        periods: [{ period: "2023", current: true, available: true, release_id: `${releaseTag}-current` }] }];
    return vi.fn(async (url) => {
      const path = String(url);
      if (path.includes("/community/area/")) return { ok: true, json: async () => ({ geoid: "37145", name: "Person", bbox: [-95.2, 36.2, -94.8, 36.5], geometry: { type: "Polygon", coordinates: [] } }) };
      if (path.endsWith("/catalog") || path.includes("/catalog?")) return { ok: true, json: async () => ({
        dataset_id: district ? "census_acs5_2024_community_profile" : "cdc_places_county_2025_pilot",
        active_release_id: `${releaseTag}-current`, value_type: "crude_prevalence", unit: "percent",
        geographies: district ? ["state", "county", "tract", "cd"] : ["county", "tract"], measures,
      }) };
      const query = new URLSearchParams(path.split("?")[1]);
      const selectedPeriod = query.get("period");
      const older = selectedPeriod !== "2023";
      const feature = { type: "Feature", geometry: { type: "Polygon", coordinates: [] },
        properties: { geography_id: "37145", county_fips: "37145", name: "Person", value: selectedPeriod === "2020" ? 11 : older ? 12 : 13, status: "available", ci_low: 10, ci_high: 14 } };
      const common = { release_id: older ? `${releaseTag}-history` : `${releaseTag}-current`, period: selectedPeriod,
        geography: query.get("geography") };
      const payload = path.includes("/map?") ? { features: missingShape && older ? [] : [feature], quantile_breaks: [10, 11, 12, 13] }
        : path.includes("/legend?") ? { quantile_breaks: [10, 11, 12, 13], statuses: [{ status: "available", n: 1 }],
          published_without_boundary: older ? publishedWithoutBoundary : 0 }
        : { rows: [{ geography_id: "37145", name: "Person", value: selectedPeriod === "2020" ? 11 : older ? 12 : 13, status: "available" }], total: 1 };
      return { ok: true, json: async () => ({ ...payload, ...common }) };
    });
  }

  it("lists years, requests the chosen release for map, legend, and table, and keeps the selected GEOID", async () => {
    const fetchMock = historyStub();
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState(null, "", "/area/places-2025?measure_id=diabetes_crudeprev");
    render(<Places2025Pilot />);
    const year = await screen.findByLabelText("Year");
    expect([...year.options].map((option) => option.textContent.trim())).toEqual(["2023 (latest)", "2022", "2021 (not published)", "2020"]);
    expect(year.options[2]).toBeDisabled();
    await screen.findByText("37145");
    const handlers = {};
    mapHarness.geojson.onEachFeature(mapHarness.geojson.data.features[0], { on: (name, handler) => { handlers[name] = handler; }, bindTooltip: vi.fn() });
    act(() => handlers.click());
    expect(screen.getByTestId("selected-area")).toHaveTextContent("13%");
    expect(screen.queryByText("A separate model run.")).not.toBeInTheDocument();
    fireEvent.change(year, { target: { value: "2022" } });
    await screen.findByText("A separate model run.");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("PLACES county and tract estimates, 2022");
    await waitFor(() => expect(screen.getByTestId("selected-area")).toHaveTextContent("12%"));
    expect(screen.getByTestId("selected-area")).toHaveTextContent("Person · County 37145");
    const historicalTooltip = vi.fn();
    mapHarness.geojson.onEachFeature(mapHarness.geojson.data.features[0], { on: vi.fn(), bindTooltip: historicalTooltip });
    expect(historicalTooltip.mock.calls[0][0]).toContain("12% • 2022");
    expect(screen.getByText("Boundary: TIGER/Line 2020.")).toBeInTheDocument();
    expect(screen.getByText("Colour classes are for this year only; compare values, not colours.")).toBeInTheDocument();
    expect(screen.getByText("2 areas published for this year have no matching boundary and are not drawn.")).toBeInTheDocument();
    expect(screen.getByText("Diagnosed diabetes, 2022; release h4-history")).toBeInTheDocument();
    const historyRequests = fetchMock.mock.calls.map(([url]) => String(url)).filter((url) => url.includes("/area/") && url.includes("period=2022"));
    expect(historyRequests).toHaveLength(3);
    expect(historyRequests.every((url) => url.includes("release_id=h4-history"))).toBe(true);
    expect(historyRequests.map((url) => /\/area\/(map|legend|table)\?/.exec(url)?.[1]).sort()).toEqual(["legend", "map", "table"]);
    expect(window.location.search).toContain("period=2022");
    fireEvent.change(screen.getByLabelText("Measure"), { target: { value: "access2_crudeprev" } });
    expect(screen.getByLabelText("Year")).toHaveValue("2022");
    fireEvent.change(screen.getByLabelText("Measure"), { target: { value: "diabetes_crudeprev" } });
    fireEvent.change(year, { target: { value: "2020" } });
    await waitFor(() => expect(screen.getByTestId("selected-area")).toHaveTextContent("11%"));
    const sameReleaseRequests = fetchMock.mock.calls.map(([url]) => String(url)).filter((url) => url.includes("/area/") && url.includes("period=2020"));
    expect(sameReleaseRequests).toHaveLength(3);
    expect(sameReleaseRequests.every((url) => url.includes("release_id=h4-history"))).toBe(true);
    fireEvent.change(year, { target: { value: "2023" } });
    await waitFor(() => expect(screen.queryByText("A separate model run.")).not.toBeInTheDocument());
    expect(screen.queryByText(/Colour classes are for this year only/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Measure"), { target: { value: "dental_crudeprev" } });
    expect(screen.getByLabelText("Year")).toHaveValue("2023");
  });

  it("reads a valid URL year and ignores an unavailable or unknown one", async () => {
    vi.stubGlobal("fetch", historyStub());
    window.history.replaceState(null, "", "/area/places-2025?measure_id=diabetes_crudeprev&period=2022");
    const view = render(<Places2025Pilot />);
    expect(await screen.findByLabelText("Year")).toHaveValue("2022");
    expect(await screen.findByText("Diagnosed diabetes, 2022; release h4-history")).toBeInTheDocument();
    view.unmount();
    window.history.replaceState(null, "", "/area/places-2025?measure_id=diabetes_crudeprev&period=2099");
    render(<Places2025Pilot />);
    expect(await screen.findByLabelText("Year")).toHaveValue("2023");
    await waitFor(() => expect(window.location.search).toContain("period=2023"));
  });

  it("uses singular copy when one published area has no boundary", async () => {
    vi.stubGlobal("fetch", historyStub({ publishedWithoutBoundary: 1, releaseTag: "h4-singular" }));
    window.history.replaceState(null, "", "/area/places-2025?measure_id=diabetes_crudeprev&period=2022");
    render(<Places2025Pilot />);
    expect(await screen.findByText("1 area published for this year has no matching boundary and is not drawn.")).toBeInTheDocument();
  });

  it("falls back from older districts and explains when a selected area has no older shape", async () => {
    vi.stubGlobal("fetch", historyStub({ district: true, missingShape: true }));
    window.history.replaceState(null, "", "/area/acs-community?measure_id=diabetes_crudeprev&geography=cd&period=2022&focus=county:37145");
    render(<Places2025Pilot dataset="acs_profile" />);
    expect(await screen.findByText("Districts have no earlier years in CHIP: older Congresses had different districts.")).toBeInTheDocument();
    expect(screen.getByTestId("selected-area")).toHaveTextContent("Person · County 37145");
    expect(await screen.findByText("This area has no shape on this year's boundary, so no value is shown or inferred.")).toBeInTheDocument();
    expect(screen.getByLabelText("Geography")).toHaveValue("cd");
  });
});
