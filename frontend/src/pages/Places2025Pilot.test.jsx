import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import Places2025Pilot, { pilotQuery, safeViewportBbox, PILOT_TRACT_ZOOM, areaGeography, ACS_COUNTY_ZOOM, ACS_TRACT_ZOOM } from "./Places2025Pilot";
import { resolveRoute } from "../utils/routeResolver";

const mapHarness = vi.hoisted(() => ({ zoom: 4, handlers: null }));

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }) => <div>{children}</div>,
  TileLayer: () => null,
  ZoomControl: () => null,
  GeoJSON: () => null,
  useMapEvents: (handlers) => {
    mapHarness.handlers = handlers;
    return { getZoom: () => mapHarness.zoom,
      getBounds: () => ({ getWest: () => -100, getSouth: () => 30, getEast: () => -90, getNorth: () => 40 }) };
  },
}));

describe("PLACES 2025 county pilot selection", () => {
  afterEach(() => { vi.unstubAllGlobals(); mapHarness.zoom = 4; mapHarness.handlers = null; });
  it("routes the pilot separately from the legacy map", () => {
    expect(resolveRoute("/area/places-2025")).toEqual({ type: "places-2025-pilot" });
    expect(resolveRoute("/")).toEqual({ type: "map" });
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
