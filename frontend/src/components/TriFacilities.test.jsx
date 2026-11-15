import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { clearTriCache, triQuery, useTriFacilities, TriFacilityPanel } from "./TriFacilities";
import { clearSiteCache } from "./HealthCenterSites";
import Places2025Pilot from "../pages/Places2025Pilot";

const harness = vi.hoisted(() => ({ zoom: 9, bounds: [-87, 32, -85, 33] }));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }) => <div data-testid="map">{children}</div>,
  TileLayer: () => null,
  ZoomControl: () => null,
  GeoJSON: () => null,
  Pane: ({ name, children }) => <div data-testid={`pane-${name}`}>{children}</div>,
  Marker: ({ title, eventHandlers }) => <button type="button" data-testid="marker" onClick={() => eventHandlers.click({})}>{title}</button>,
  CircleMarker: ({ eventHandlers }) => <button type="button" data-testid="point" onClick={() => eventHandlers.click({})}>point</button>,
  useMap: () => ({ getZoom: () => harness.zoom, setView: vi.fn(), fitBounds: vi.fn() }),
  useMapEvents: () => {
    const [w, s, e, n] = harness.bounds;
    return { getZoom: () => harness.zoom, getCenter: () => ({ lat: (s + n) / 2, lng: (w + e) / 2 }),
      getBounds: () => ({ getWest: () => w, getSouth: () => s, getEast: () => e, getNorth: () => n }) };
  },
}));

const SECTORS = [{ code: "325", label: "Chemicals", mapped_facilities: 2 }, { code: "562", label: "Hazardous Waste", mapped_facilities: 1 }];
const CATALOG = {
  dataset_id: "epa_tri_facilities", active_release_id: "tri-release-1", reporting_year: 2024, processed_as_of: "2025-11-05",
  source_url: "https://www.epa.gov/tri-basic", usage_terms: "Public data.",
  interpretation: ["Presence does not establish a regulatory violation.", "Absence does not establish the absence of pollution."],
  limitations: ["Release quantities are not shown."],
  counts: { facilities: 4, mapped_facilities: 3, source_reports: 7, not_mapped_by_reason: { no_published_coordinates: 1 } },
  sectors: SECTORS,
};
// Two facilities share a published coordinate; facility A filed two forms for the same chemical.
const FACILITIES = [
  { facility_id: "00001TSTFC0001A", facility_name: "Plant A", city: "Town", state: "AL", sectors: [{ code: "325", label: "Chemicals" }], chemical_count: 2, form_count: 3, lat: 32.5, lon: -86.5, location_key: "-86.512345,32.512345", chemicals: ["0000050000", "N420"] },
  { facility_id: "00002TSTFC0002A", facility_name: "Plant B", city: "Town", state: "AL", sectors: [{ code: "325", label: "Chemicals" }], chemical_count: 1, form_count: 1, lat: 32.5, lon: -86.5, location_key: "-86.512345,32.512345", chemicals: ["0000050000"] },
  { facility_id: "00003TSTFC0003A", facility_name: "Plant C", city: "City", state: "AL", sectors: [{ code: "562", label: "Hazardous Waste" }], chemical_count: 1, form_count: 1, lat: 32.6, lon: -85.5, location_key: "-85.512345,32.612345", chemicals: ["N420"] },
];
const CHEMICALS = [
  { chemical_id: "0000050000", names: ["Formaldehyde"], cas_number: "50-00-0", facilities: 2, mapped_facilities: 2 },
  { chemical_id: "N420", names: ["Lead  And Lead Compounds", "Lead compounds"], cas_number: "N420", facilities: 2, mapped_facilities: 2 },
];

function params(url) { return new URL(String(url), "http://x").searchParams; }
function triResponse(url, { release = "tri-release-1" } = {}) {
  const text = String(url);
  const q = params(text);
  if (text.includes("/area/tri/catalog")) return CATALOG;
  const sector = (q.get("sector") || "").split(",").filter(Boolean);
  const chemical = q.get("chemical");
  const base = { release_id: release, bbox: q.get("bbox"), reporting_year: 2024, filters: { sector, chemical } };
  const rows = FACILITIES.filter((f) => f.sectors.some((s) => sector.includes(s.code)) && (!chemical || f.chemicals.includes(chemical)));
  if (text.includes("/area/tri/map?")) return { ...base, mode: "points", total: rows.length, points: rows, clusters: [] };
  if (text.includes("/area/tri/table?")) return { ...base, total: rows.length, rows };
  if (text.includes("/area/tri/chemicals?")) {
    const term = (q.get("q") || "").toLowerCase();
    const list = CHEMICALS.filter((c) => !term || c.names.join(" ").toLowerCase().includes(term));
    return { release_id: release, q: q.get("q") || "", total: list.length, rows: list };
  }
  if (text.includes("/area/tri/detail?")) return {
    release_id: release, facility_id: q.get("facility_id"), facility_name: `Detail ${q.get("facility_id")}`, reporting_year: 2024,
    processed_as_of: "2025-11-05", address: { street_address: "1 TEST RD", city: "Town", state: "AL", zip: "00000", county: "TEST" },
    sectors: [{ code: "325", label: "Chemicals" }], naics_codes: ["325199"], forms: { total: 3, form_r: 2, form_a: 1 },
    chemical_total: 2, chemicals: [{ chemical_id: "0000050000", names: ["Formaldehyde"], cas_number: "50-00-0", form_types: ["R"], forms: 2 },
      { chemical_id: "N420", names: ["Lead compounds"], cas_number: "N420", form_types: ["A"], forms: 1 }],
    location: { published_latitude: "32.512345", published_longitude: "-86.512345", crs: "EPSG:4326", facilities_at_location: 2,
      boundary_check: "within_published_state", derived_county_geoid: "01001", derived_county_name: "West County" },
    epa_link: { label: "EPA Facility Registry Service record for this TRI facility ID", url: "https://frs-public.epa.gov/x" },
    quantities_note: "Release and waste quantities are not shown in this phase.", reporting_note: "Filed TRI forms for reporting year 2024." };
  return {};
}
const ok = (body) => ({ ok: true, json: async () => body });

function Harness({ bbox, zoom = 9 }) {
  const tri = useTriFacilities({ bbox, zoom });
  return <TriFacilityPanel tri={tri} />;
}

describe("EPA TRI reporting facility overlay", () => {
  beforeEach(() => { clearTriCache(); clearSiteCache(); window.sessionStorage.clear(); });
  afterEach(() => { vi.unstubAllGlobals(); harness.zoom = 9; });

  it("pins release, viewport, zoom, sorted sectors, and chemical in every request", () => {
    const query = triQuery({ releaseId: "r1", bbox: "-87,32,-85,33", zoom: 9, filters: { sector: ["562", "325"], chemical: { id: "N420" } }, limit: 50, offset: 50 });
    expect(query.get("release_id")).toBe("r1");
    expect(query.get("sector")).toBe("325,562");
    expect(query.get("chemical")).toBe("N420");
    expect(query.get("zoom")).toBe("9");
    expect(query.get("offset")).toBe("50");
    expect(triQuery({ releaseId: "r1", bbox: "b", filters: { sector: ["325"], chemical: null } }).has("chemical")).toBe(false);
  });

  it("is off by default, labelled as TRI reporting facilities, and explains limits", async () => {
    const fetchMock = vi.fn(async (url) => ok(triResponse(url)));
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness bbox="-87,32,-85,33" />);
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("Show TRI reporting facilities"));
    expect(await screen.findByText(/3 TRI facilities in view under these filters/i)).toBeInTheDocument();
    expect(screen.queryByText(/all pollution sources/i)).not.toBeInTheDocument();
    expect(screen.getByText(/does not establish a regulatory violation/)).toBeInTheDocument();
    expect(screen.getByText(/reporting year 2024 · basic data file processed as of 2025-11-05/)).toBeInTheDocument();
    expect(screen.getByText(/1 have no usable published location/)).toBeInTheDocument();
    const calls = fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => /tri\/(map|table)\?/.test(u));
    expect(calls.every((u) => params(u).get("release_id") === "tri-release-1" && params(u).get("sector") === "325,562")).toBe(true);
  });

  it("filters by chemical with unique facilities and paginated chemical search", async () => {
    const fetchMock = vi.fn(async (url) => ok(triResponse(url)));
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness bbox="-87,32,-85,33" />);
    fireEvent.click(screen.getByLabelText("Show TRI reporting facilities"));
    await screen.findByText(/3 TRI facilities in view/i);
    // jsdom does not dispatch <details> toggle events; open it the way a browser would report it.
    const details = screen.getByText("Choose a chemical").closest("details");
    details.open = true;
    fireEvent(details, new Event("toggle"));
    fireEvent.change(screen.getByLabelText(/Search by name, CAS number/), { target: { value: "lead" } });
    const option = await screen.findByRole("button", { name: /Lead And Lead Compounds \/ Lead compounds/ });
    expect(within(screen.getByRole("navigation", { name: "Chemical list pages" })).getByText(/Page 1 of 1/)).toBeInTheDocument();
    fireEvent.click(option);
    expect(await screen.findByText(/2 TRI facilities in view/i)).toBeInTheDocument();
    const rows = screen.getAllByRole("button", { name: /^Details for/ }).map((b) => b.getAttribute("aria-label"));
    expect(rows).toEqual(["Details for Plant A", "Details for Plant C"]);
    const last = fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/tri/map?")).at(-1);
    expect(params(last).get("chemical")).toBe("N420");
    fireEvent.click(screen.getByRole("button", { name: "Clear chemical" }));
    expect(await screen.findByText(/3 TRI facilities in view/i)).toBeInTheDocument();
  });

  it("filters by industry sector and keeps at least one sector selected", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url) => ok(triResponse(url))));
    render(<Harness bbox="-87,32,-85,33" />);
    fireEvent.click(screen.getByLabelText("Show TRI reporting facilities"));
    await screen.findByText(/3 TRI facilities in view/i);
    fireEvent.click(screen.getByLabelText(/^Chemicals/));
    expect(await screen.findByText(/1 TRI facilities in view/i)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/^Hazardous Waste/));
    expect(screen.getByLabelText(/^Hazardous Waste/)).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Select all sectors" }));
    expect(await screen.findByText(/3 TRI facilities in view/i)).toBeInTheDocument();
  });

  it("gives keyboard-reachable facility detail with chemicals and the EPA link", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url) => ok(triResponse(url))));
    render(<Harness bbox="-87,32,-85,33" />);
    fireEvent.click(screen.getByLabelText("Show TRI reporting facilities"));
    const button = await screen.findByRole("button", { name: "Details for Plant A" });
    button.focus();
    fireEvent.click(button);
    const heading = await screen.findByRole("heading", { name: "Detail 00001TSTFC0001A" });
    await waitFor(() => expect(heading).toHaveFocus());
    const region = screen.getByRole("region", { name: "Detail 00001TSTFC0001A" });
    expect(within(region).getByText(/Reported does not mean released/)).toBeInTheDocument();
    expect(within(region).getByText(/Formaldehyde · CAS 50-00-0 · Form R \(2 forms\)/)).toBeInTheDocument();
    expect(within(region).getByText(/2 facilities share this location/)).toBeInTheDocument();
    expect(within(region).getByText(/datum not published/)).toBeInTheDocument();
    expect(within(region).getByRole("link", { name: /EPA Facility Registry Service record/ })).toHaveAttribute("href", "https://frs-public.epa.gov/x");
  });

  it("ignores stale responses after rapid filter switching and rejects mismatched releases", async () => {
    let releaseSlow;
    const fetchMock = vi.fn((url) => {
      const text = String(url);
      if (text.includes("/tri/map?") && params(text).get("sector") === "325") {
        return new Promise((resolve) => { releaseSlow = () => resolve(ok({ ...triResponse(url), total: 999 })); });
      }
      return Promise.resolve(ok(triResponse(url)));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness bbox="-87,32,-85,33" />);
    fireEvent.click(screen.getByLabelText("Show TRI reporting facilities"));
    await screen.findByText(/3 TRI facilities in view/i);
    fireEvent.click(screen.getByLabelText(/^Hazardous Waste/)); // -> sector 325 only (slow)
    await waitFor(() => expect(releaseSlow).toBeTypeOf("function"));
    fireEvent.click(screen.getByRole("button", { name: "Select all sectors" }));
    expect(await screen.findByText(/3 TRI facilities in view/i)).toBeInTheDocument();
    await act(async () => { releaseSlow(); });
    expect(screen.queryByText(/999 TRI/)).not.toBeInTheDocument();

    clearTriCache();
    vi.stubGlobal("fetch", vi.fn(async (url) => ok(triResponse(url, { release: String(url).includes("/catalog") ? "tri-release-1" : "other" }))));
    fireEvent.click(screen.getByLabelText(/^Chemicals/));
    expect(await screen.findByRole("alert")).toHaveTextContent(/did not match the requested release/i);
  });

  it("runs alongside the HRSA overlay without changing the area or site selection", async () => {
    const siteCatalog = { dataset_id: "hrsa_health_center_sites", active_release_id: "site-release-1", snapshot_date: "2026-11-14",
      source_url: "x", usage_terms: "", limitations: [], counts: { source_sites: 1, mapped_eligible_sites: 1 },
      filters: [{ name: "program", label: "Program", values: [{ code: "fqhc", label: "Awardee", default: true, mapped_sites: 1 }] },
        { name: "site_type", label: "Site type", values: [{ code: "service_delivery", label: "Service delivery", default: true, mapped_sites: 1 }] },
        { name: "location_type", label: "Location", values: [{ code: "permanent", label: "Permanent", default: true, mapped_sites: 1 }] },
        { name: "setting", label: "Setting", values: [{ code: "general", label: "General", default: true, mapped_sites: 1 }] }] };
    const fetchMock = vi.fn(async (url) => {
      const text = String(url);
      const q = params(text);
      if (text.includes("/area/tri/")) return ok(triResponse(url));
      if (text.includes("/area/sites/catalog")) return ok(siteCatalog);
      if (text.includes("/area/sites/")) {
        const filters = Object.fromEntries(["program", "site_type", "location_type", "setting"].map((n) => [n, (q.get(n) || "").split(",")]));
        const point = { site_id: "BPS-H80-000001", site_name: "Clinic", organization_name: "Org", program: "fqhc", site_type_label: "Service delivery", lat: 32.7, lon: -86.7, location_key: "a" };
        return ok({ release_id: "site-release-1", bbox: q.get("bbox"), filters, mode: "points", total: 1, points: [point], rows: [point], clusters: [] });
      }
      if (text.includes("/area/catalog")) return ok({ dataset_id: "cdc_places_county_2025_pilot", active_release_id: "area-release", value_type: "crude_prevalence", unit: "percent",
        measures: [{ measure_id: "dental_crudeprev", label: "Dental", observation_period: "2022", population: "adults" },
          { measure_id: "access2_crudeprev", label: "Insurance", observation_period: "2023", population: "adults aged 18-64" }] });
      if (text.includes("/area/map?")) return ok({ release_id: "area-release", geography: q.get("geography"), features: [] });
      if (text.includes("/area/legend?")) return ok({ release_id: "area-release", geography: q.get("geography"), statuses: [] });
      return ok({ release_id: "area-release", geography: q.get("geography"), total: 0, rows: [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Places2025Pilot />);
    fireEvent.click(await screen.findByLabelText(/show hrsa health center sites/i));
    fireEvent.click(screen.getByLabelText("Show TRI reporting facilities"));
    expect(await screen.findByText(/1 sites in view/i)).toBeInTheDocument();
    expect(await screen.findByText(/3 TRI facilities in view/i)).toBeInTheDocument();
    expect(screen.getByTestId("pane-chip-health-center-sites")).toBeInTheDocument();
    expect(screen.getByTestId("pane-chip-tri-facilities")).toBeInTheDocument();
    // The TRI colocated marker lists two distinct facilities.
    fireEvent.click(screen.getByText("2 distinct TRI facilities share this published location"));
    expect(await screen.findByRole("heading", { name: "2 TRI facilities at one published location" })).toBeInTheDocument();
    const count = (part) => fetchMock.mock.calls.filter(([u]) => String(u).includes(part)).length;
    const before = [count("/area/sites/map?"), count("/area/tri/map?"), count("/area/map?")];
    fireEvent.change(screen.getByLabelText("Measure"), { target: { value: "access2_crudeprev" } });
    await waitFor(() => expect(count("/area/map?")).toBeGreaterThan(before[2]));
    expect([count("/area/sites/map?"), count("/area/tri/map?")]).toEqual(before.slice(0, 2));
    // Changing a TRI filter does not refetch HRSA sites.
    fireEvent.click(screen.getByLabelText(/^Hazardous Waste/));
    await screen.findByText(/2 TRI facilities in view/i);
    expect(count("/area/sites/map?")).toBe(before[0]);
    expect(screen.getByText(/1 sites in view/i)).toBeInTheDocument();
  });
});
