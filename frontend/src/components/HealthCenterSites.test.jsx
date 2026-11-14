import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { clearSiteCache, groupColocated, siteQuery, useHealthCenterSites, HealthCenterSitePanel } from "./HealthCenterSites";
import Places2025Pilot from "../pages/Places2025Pilot";

const harness = vi.hoisted(() => ({ zoom: 9, bounds: [-87, 32, -85, 33], handlers: null }));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }) => <div data-testid="map">{children}</div>,
  TileLayer: () => null,
  ZoomControl: () => null,
  GeoJSON: () => null,
  Pane: ({ children }) => <div data-testid="sites-pane">{children}</div>,
  Marker: ({ title, eventHandlers }) => <button type="button" data-testid="site-marker" onClick={() => eventHandlers.click({})}>{title}</button>,
  CircleMarker: ({ eventHandlers }) => <button type="button" data-testid="site-point" onClick={() => eventHandlers.click({})}>point</button>,
  useMap: () => ({ getZoom: () => harness.zoom, setView: vi.fn(), fitBounds: vi.fn() }),
  useMapEvents: (handlers) => {
    harness.handlers = handlers;
    const [w, s, e, n] = harness.bounds;
    return { getZoom: () => harness.zoom, getBounds: () => ({ getWest: () => w, getSouth: () => s, getEast: () => e, getNorth: () => n }) };
  },
}));

const CATALOG = {
  dataset_id: "hrsa_health_center_sites", active_release_id: "site-release-1", snapshot_date: "2026-11-14",
  source_url: "https://data.hrsa.gov/data/download", usage_terms: "Usage limitations: None.",
  limitations: ["Clusters are display groupings, not service areas."],
  counts: { source_sites: 5, mapped_eligible_sites: 3, not_mapped_by_reason: { suppressed_source_policy: 1, no_published_coordinates: 1 } },
  filters: [
    { name: "program", label: "Program", values: [{ code: "fqhc", label: "Awardee", default: true, mapped_sites: 2 }, { code: "look_alike", label: "Look-alike", default: true, mapped_sites: 1 }] },
    { name: "site_type", label: "Site type", values: [{ code: "service_delivery", label: "Service delivery site", default: true, mapped_sites: 2 }, { code: "administrative", label: "Administrative only", default: false, mapped_sites: 1 }] },
    { name: "location_type", label: "Location type", values: [{ code: "permanent", label: "Permanent", default: true, mapped_sites: 3 }] },
    { name: "setting", label: "Setting", values: [{ code: "general", label: "General", default: true, mapped_sites: 3 }] },
  ],
};
const POINTS = [
  { site_id: "BPS-H80-000001", site_name: "Clinic A", organization_name: "Org", program: "fqhc", site_type_label: "Service delivery site", city: "Town", state: "AL", lat: 32.5, lon: -86.5, location_key: "-86.5,32.5" },
  { site_id: "BPS-H80-000002", site_name: "Clinic B", organization_name: "Org", program: "fqhc", site_type_label: "Service delivery site", city: "Town", state: "AL", lat: 32.5, lon: -86.5, location_key: "-86.5,32.5" },
  { site_id: "BPS-LAL-000003", site_name: "Clinic C", organization_name: "Org 2", program: "look_alike", site_type_label: "Service delivery site", city: "City", state: "AL", lat: 32.6, lon: -85.5, location_key: "-85.5,32.6" },
];

function params(url) { return new URL(String(url), "http://x").searchParams; }
function filtersFrom(query) {
  return Object.fromEntries(["program", "site_type", "location_type", "setting"].map((n) => [n, (query.get(n) || "").split(",").filter(Boolean)]));
}
function siteResponse(url, { release = "site-release-1" } = {}) {
  const query = params(url);
  const base = { release_id: release, bbox: query.get("bbox"), filters: filtersFrom(query), snapshot_date: "2026-11-14" };
  const points = query.get("site_type")?.includes("administrative") ? [] : POINTS;
  if (String(url).includes("/area/sites/map?")) return { ...base, mode: "points", total: points.length, points, clusters: [] };
  if (String(url).includes("/area/sites/table?")) return { ...base, total: points.length, rows: points };
  if (String(url).includes("/area/sites/detail?")) return { release_id: release, site_id: query.get("site_id"), snapshot_date: "2026-11-14",
    program_label: "Awardee", site_type_label: "Service delivery site", location_type_label: "Permanent", setting_label: "General",
    attributes: { site_name: `Detail ${query.get("site_id")}`, organization_name: "Org", health_center_number: "H80CS00001", site_city: "Town", site_state: "AL" },
    location: { published_x: "-86.5", published_y: "32.5", crs: "EPSG:4326", sites_at_location: 2, boundary_check: "within_published_county" },
    services_note: "HRSA does not list services offered." };
  return CATALOG;
}
const ok = (body) => ({ ok: true, json: async () => body });

function Harness({ bbox, zoom = 9 }) {
  const sites = useHealthCenterSites({ bbox, zoom });
  return <HealthCenterSitePanel sites={sites} />;
}

describe("HRSA health center site overlay", () => {
  beforeEach(() => { clearSiteCache(); window.sessionStorage.clear(); });
  afterEach(() => { vi.unstubAllGlobals(); harness.zoom = 9; });

  it("pins release, viewport, zoom, and sorted filters in every request", () => {
    const query = siteQuery({ releaseId: "r1", bbox: "-87,32,-85,33", zoom: 9, filters: { program: ["look_alike", "fqhc"] }, limit: 50, offset: 100 });
    expect(query.get("release_id")).toBe("r1");
    expect(query.get("bbox")).toBe("-87,32,-85,33");
    expect(query.get("zoom")).toBe("9");
    expect(query.get("program")).toBe("fqhc,look_alike");
    expect(query.get("offset")).toBe("100");
  });

  it("keeps distinct sites that share published coordinates", () => {
    const groups = groupColocated(POINTS);
    expect(groups).toHaveLength(2);
    expect(groups[0].map((p) => p.site_id)).toEqual(["BPS-H80-000001", "BPS-H80-000002"]);
  });

  it("is off by default and loads the pinned release only when enabled", async () => {
    const fetchMock = vi.fn(async (url) => ok(siteResponse(url)));
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness bbox="-87,32,-85,33" />);
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText(/show hrsa health center sites/i));
    expect(await screen.findByText(/3 sites in view under these filters/i)).toBeInTheDocument();
    const siteCalls = fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => /sites\/(map|table)\?/.test(u));
    expect(siteCalls.every((u) => params(u).get("release_id") === "site-release-1")).toBe(true);
    expect(params(siteCalls.find((u) => u.includes("/map?"))).get("site_type")).toBe("service_delivery");
    expect(screen.getByText(/snapshot 2026-11-14 \(current directory, not an annual period\)/i)).toBeInTheDocument();
    expect(screen.getByText(/2 are listed without a mappable exact location/i)).toBeInTheDocument();
  });

  it("gives keyboard-reachable detail from the table and moves focus to it", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url) => ok(siteResponse(url))));
    render(<Harness bbox="-87,32,-85,33" />);
    fireEvent.click(screen.getByLabelText(/show hrsa health center sites/i));
    const button = await screen.findByRole("button", { name: "Details for Clinic A" });
    button.focus();
    fireEvent.click(button);
    const heading = await screen.findByRole("heading", { name: "Detail BPS-H80-000001" });
    await waitFor(() => expect(heading).toHaveFocus());
    const region = screen.getByRole("region", { name: "Detail BPS-H80-000001" });
    expect(within(region).getByText(/2 sites share this location/)).toBeInTheDocument();
    expect(within(region).getByText(/does not list services/)).toBeInTheDocument();
  });

  it("refetches with new filters and keeps at least one value per group", async () => {
    const fetchMock = vi.fn(async (url) => ok(siteResponse(url)));
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness bbox="-87,32,-85,33" />);
    fireEvent.click(screen.getByLabelText(/show hrsa health center sites/i));
    await screen.findByText(/3 sites in view/i);
    fireEvent.click(screen.getByLabelText(/Administrative only/));
    await screen.findByText(/0 sites in view/i);
    const last = fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/map?")).at(-1);
    expect(params(last).get("site_type")).toBe("administrative,service_delivery");
    fireEvent.click(screen.getByLabelText(/Permanent/));
    expect(screen.getByLabelText(/Permanent/)).toBeChecked();
  });

  it("ignores stale responses after a rapid viewport change and rejects release mismatches", async () => {
    let releaseFirst;
    const fetchMock = vi.fn((url) => {
      const text = String(url);
      if (text.includes("/map?") && params(text).get("bbox") === "-90,30,-80,40") {
        return new Promise((resolve) => { releaseFirst = () => resolve(ok({ ...siteResponse(url), total: 999 })); });
      }
      return Promise.resolve(ok(siteResponse(url)));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = render(<Harness bbox="-90,30,-80,40" />);
    fireEvent.click(screen.getByLabelText(/show hrsa health center sites/i));
    await waitFor(() => expect(releaseFirst).toBeTypeOf("function"));
    rerender(<Harness bbox="-87,32,-85,33" />);
    expect(await screen.findByText(/3 sites in view/i)).toBeInTheDocument();
    await act(async () => { releaseFirst(); });
    expect(screen.queryByText(/999 sites/)).not.toBeInTheDocument();

    clearSiteCache();
    vi.stubGlobal("fetch", vi.fn(async (url) => ok(String(url).includes("/catalog") ? CATALOG : siteResponse(url, { release: "other-release" }))));
    rerender(<Harness bbox="-88,32,-85,33" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/did not match the requested release/i);
  });

  it("stays independent of area measure switching on the area page", async () => {
    harness.bounds = [-87, 32, -85, 33];
    const fetchMock = vi.fn(async (url) => {
      const text = String(url);
      if (text.includes("/area/sites/")) return ok(siteResponse(url));
      if (text.includes("/area/catalog")) return ok({ dataset_id: "cdc_places_county_2025_pilot", active_release_id: "area-release", value_type: "crude_prevalence", unit: "percent",
        measures: [{ measure_id: "dental_crudeprev", label: "Dental", observation_period: "2022", population: "adults" },
          { measure_id: "access2_crudeprev", label: "Insurance", observation_period: "2023", population: "adults aged 18-64" }] });
      const q = params(text);
      if (text.includes("/area/map?")) return ok({ release_id: "area-release", geography: q.get("geography"), features: [] });
      if (text.includes("/area/legend?")) return ok({ release_id: "area-release", geography: q.get("geography"), statuses: [] });
      return ok({ release_id: "area-release", geography: q.get("geography"), total: 0, rows: [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Places2025Pilot />);
    fireEvent.click(await screen.findByLabelText(/show hrsa health center sites/i));
    await screen.findByText(/3 sites in view/i);
    // A colocated marker opens a list of distinct sites; it does not select an area polygon.
    fireEvent.click(screen.getAllByTestId("site-marker")[0]);
    expect(await screen.findByRole("heading", { name: "2 sites at one published location" })).toBeInTheDocument();
    const siteMapCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).includes("/area/sites/map?")).length;
    const areaMapCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).includes("/area/map?")).length;
    const before = [siteMapCalls(), areaMapCalls()];
    fireEvent.change(screen.getByLabelText("Measure"), { target: { value: "access2_crudeprev" } });
    await waitFor(() => expect(areaMapCalls()).toBeGreaterThan(before[1]));
    expect(siteMapCalls()).toBe(before[0]);
    expect(screen.getByText(/3 sites in view/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "2 sites at one published location" })).toBeInTheDocument();
  });
});
