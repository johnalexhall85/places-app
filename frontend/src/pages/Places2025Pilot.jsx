import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GeoJSON, MapContainer, TileLayer, ZoomControl, useMapEvents } from "react-leaflet";
import { API_BASE } from "../config/apiBase";
import Header from "../components/Header";
import Footer from "../components/Footer";
import "./Places2025Pilot.css";

const cache = new Map();
export const PILOT_TRACT_ZOOM = 10;
export const ACS_COUNTY_ZOOM = 6;
export const ACS_TRACT_ZOOM = 10;

export function areaGeography(zoom, isAcs, tractSupported, tractCapExceeded) {
  if (isAcs && zoom < ACS_COUNTY_ZOOM) return "state";
  return zoom >= (isAcs ? ACS_TRACT_ZOOM : PILOT_TRACT_ZOOM) && tractSupported && !tractCapExceeded ? "tract" : "county";
}

const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
function displayValue(item, isAcs, isAhrf = false) {
  if (isAhrf) return item.value == null ? item.status : new Intl.NumberFormat("en-US").format(item.value);
  if (!isAcs) return item.value == null ? item.status : `${item.value}%`;
  if (item.status === "open_ended" && item.estimate_annotation) {
    const bound = Number(item.estimate_annotation.replace(/[^0-9]/g, ""));
    return `${item.estimate_annotation.endsWith("+") ? "≥" : "≤"}${dollars.format(bound)}`;
  }
  return item.value == null ? item.status : dollars.format(item.value);
}
function displayUncertainty(item, isAcs, isAhrf = false) {
  if (isAhrf) return "Not supplied";
  if (!isAcs) return item.ci_low == null ? "—" : `${item.ci_low}–${item.ci_high}%`;
  if (item.moe != null) return `±${dollars.format(item.moe)} (90% MOE)`;
  return item.moe_annotation ? `${item.moe_annotation} (MOE unavailable)` : "—";
}
function areaName(level) { return level === "state" ? "state" : level === "tract" ? "tract" : "county"; }

export function safeViewportBbox(bounds) {
  const west = Math.max(-180, bounds.getWest());
  const east = Math.min(180, bounds.getEast());
  const south = Math.max(-90, bounds.getSouth());
  const north = Math.min(90, bounds.getNorth());
  return [west, south, east, north].join(",");
}

function initialMapZoom() {
  // Keep a wide desktop map within canonical longitude bounds at its minimum zoom.
  const width = typeof window === "undefined" ? 1440 : window.innerWidth;
  return Math.max(4, Math.ceil(4 * Math.log2(width / (256 * 150 / 360))) / 4);
}

export function pilotQuery(selection, bbox, extra = {}) {
  return new URLSearchParams({
    dataset_id: selection.datasetId,
    release_id: selection.releaseId,
    measure_id: selection.measure.measure_id,
    period: selection.measure.observation_period,
    population: selection.measure.population,
    value_type: selection.valueType,
    geography: selection.geography || "county",
    bbox,
    ...extra,
  });
}

function Viewport({ onChange }) {
  const report = () => onChange(safeViewportBbox(map.getBounds()), map.getZoom());
  const map = useMapEvents({ moveend: report, zoomend: report });
  useEffect(() => onChange(safeViewportBbox(map.getBounds()), map.getZoom()), [map, onChange]);
  return null;
}

const prevalenceColors = ["#deebf7", "#c6dbef", "#9ecae1", "#6baed6", "#2171b5"];

function color(value, status, breaks) {
  if (status === "open_ended") return "#6d3b9e";
  if (status === "suppressed") return "#8f6b74";
  if (status === "not_applicable") return "#c4b4d4";
  if (!["available", "true_zero", "open_ended"].includes(status)) return status === "not_published" ? "#a5a5a5" : "#d8dee3";
  if (!breaks) return prevalenceColors[2];
  const index = breaks.findIndex((upper) => value < upper);
  return prevalenceColors[index < 0 ? 4 : index];
}

async function getJSON(endpoint, query, signal) {
  const key = `${endpoint}?${query}`;
  if (cache.has(key)) return cache.get(key);
  const response = await fetch(`${API_BASE}/area/${key}`, { signal });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body.detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  const data = await response.json();
  cache.set(key, data);
  return data;
}

export default function Places2025Pilot({ dataset = "places" }) {
  const isAcs = dataset === "acs";
  const isAhrf = dataset === "ahrf";
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState("");
  const [measureId, setMeasureId] = useState(isAcs ? "B19013_001E" : isAhrf ? "phys_nf_prim_care_pc_exc_rsdt_23" : "dental_crudeprev");
  const [bbox, setBBox] = useState(null);
  const [mapZoom, setMapZoom] = useState(initialMapZoom);
  const [tractCapKey, setTractCapKey] = useState(null);
  const [page, setPage] = useState(0);
  const [mapData, setMapData] = useState(null);
  const [legend, setLegend] = useState(null);
  const [table, setTable] = useState(null);
  const [error, setError] = useState("");
  const [loadedKey, setLoadedKey] = useState(null);
  const [tableOpen, setTableOpen] = useState(true);
  const requestId = useRef(0);
  const viewportRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/area/catalog${isAcs ? "?dataset_id=census_acs5_2024_b19013" : isAhrf ? "?dataset_id=hrsa_ahrf_county_2024_2025" : ""}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(`Catalog unavailable (${response.status})`); return response.json(); })
      .then(setCatalog).catch((err) => { if (err.name !== "AbortError") setCatalogError(err.message); });
    return () => controller.abort();
  }, [isAcs, isAhrf]);

  useEffect(() => {
    if (catalog?.measures?.length && !catalog.measures.some((item) => item.measure_id === measureId)) {
      setMeasureId(catalog.measures[0].measure_id);
    }
  }, [catalog, measureId]);

  const measure = useMemo(() => catalog?.measures.find((item) => item.measure_id === measureId), [catalog, measureId]);
  const releaseId = catalog?.active_release_id;
  const wantsTracts = mapZoom >= (isAcs ? ACS_TRACT_ZOOM : PILOT_TRACT_ZOOM);
  const tractSupported = catalog?.geographies?.includes("tract");
  const capSelectionKey = `${releaseId}|${measureId}|${bbox}`;
  const tractCapExceeded = tractCapKey === capSelectionKey;
  const geography = isAhrf ? "county" : areaGeography(mapZoom, isAcs, tractSupported, tractCapExceeded);
  const simplify = geography === "tract" ? 0.002 : geography === "state" ? 0.06 : 0.04;
  const selection = useMemo(() => releaseId && measure ? {
    datasetId: catalog.dataset_id, releaseId, measure, valueType: catalog.value_type, geography,
  } : null, [releaseId, measure, catalog, geography]);
  const requestKey = useMemo(() => selection && bbox
    ? String(pilotQuery(selection, bbox, { simplify: String(simplify), limit: "100", offset: String(page * 100) }))
    : null, [selection, bbox, page]);
  const onViewport = useCallback((next, zoomLevel) => {
    const key = `${next}|${zoomLevel}`;
    if (viewportRef.current === key) return;
    viewportRef.current = key;
    setBBox(next);
    setMapZoom(zoomLevel);
    setPage(0);
  }, []);

  useEffect(() => {
    if (!selection || !bbox) return;
    const controller = new AbortController();
    const id = ++requestId.current;
    const base = pilotQuery(selection, bbox);
    const withMap = pilotQuery(selection, bbox, { simplify: String(simplify) });
    const withTable = pilotQuery(selection, bbox, { limit: "100", offset: String(page * 100) });
    setError("");
    setLoadedKey(null);
    setMapData(null);
    setLegend(null);
    setTable(null);
    Promise.all([
      getJSON("map", withMap, controller.signal),
      getJSON("legend", base, controller.signal),
      getJSON("table", withTable, controller.signal),
    ]).then(([nextMap, nextLegend, nextTable]) => {
      if (id !== requestId.current) return;
      if ([nextMap, nextLegend, nextTable].some((item) => item.release_id !== releaseId || item.geography !== geography)) {
        throw new Error("Release or geography mismatch");
      }
      setMapData(nextMap); setLegend(nextLegend); setTable(nextTable);
      setLoadedKey(requestKey);
    }).catch((err) => {
      if (err.name !== "AbortError" && id === requestId.current) {
        if (geography === "tract" && err.status === 413) setTractCapKey(capSelectionKey);
        else { setError(err.message); setLoadedKey(null); setMapData(null); setLegend(null); setTable(null); }
      }
    });
    return () => controller.abort();
  }, [selection, bbox, page, releaseId, requestKey, geography, capSelectionKey]);

  const ready = Boolean(requestKey && loadedKey === requestKey);
  const features = ready ? mapData?.features || [] : [];
  const numericStatuses = ready ? legend?.statuses.filter((item) => ["available", "true_zero"].includes(item.status) && item.low != null) : [];
  const availableRange = numericStatuses?.length ? {
    low: Math.min(...numericStatuses.map((item) => item.low)), high: Math.max(...numericStatuses.map((item) => item.high)),
  } : null;
  const breaks = availableRange && availableRange.low != null && availableRange.high != null
    ? Array.from({ length: 4 }, (_, i) => availableRange.low + (availableRange.high - availableRange.low) * (i + 1) / 5)
    : null;
  const zoom = initialMapZoom();
  return <div className="app pilot-app">
    <Header />
    <main className="app-content pilot-content">
      <div className="chip-brand-line"><strong>CHIP by Public Data Observatory</strong><span>{isAcs ? "ACS 2020–2024 5-year income" : isAhrf ? "AHRF 2023 county resources" : "PLACES 2025 county and tract pilot"}</span></div>
      <div className="map-wrapper pilot-map" aria-label={catalog && releaseId ? `${areaName(geography)} ${isAcs ? "ACS" : "pilot"} map` : undefined}>
        {catalog && releaseId && <MapContainer center={[38, -104]} zoom={zoom} minZoom={zoom} zoomSnap={0.25} zoomControl={false}
          maxBounds={[[-85, -180], [85, 180]]} maxBoundsViscosity={1} style={{ height: "100%", width: "100%" }}>
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap contributors" />
          <ZoomControl position="bottomright" />
          <Viewport onChange={onViewport} />
          {features.length > 0 && <GeoJSON key={`${releaseId}:${measureId}:${geography}:${bbox}`} data={mapData} style={(feature) => ({
            color: "#516677", weight: 0.5, fillOpacity: 0.78,
            fillColor: color(feature.properties.value, feature.properties.status, breaks),
          })} onEachFeature={(feature, layer) => {
            const item = feature.properties;
            const value = displayValue(item, isAcs, isAhrf);
            const uncertainty = displayUncertainty(item, isAcs, isAhrf);
            layer.bindPopup(`${areaName(geography)} ${item.name} (${item.geography_id || item.county_fips})<br>${value} ${isAhrf && item.value != null ? measure?.unit : ""}<br>${uncertainty}<br>${measure?.observation_period}${isAcs ? " · ACS 5-year · 2024 dollars" : ""}`);
          }} />}
        </MapContainer>}
      </div>
      <section className="pilot-panel pilot-controls" aria-label="Analytical controls">
        <h1>{isAcs ? "ACS 2020–2024 5-year income" : isAhrf ? "AHRF 2023 county resources" : "PLACES 2025 pilot"}</h1>
        <p className="pilot-scope">{isAcs ? "Published median household income for states, counties, and census tracts. Values are 2024 inflation-adjusted dollars; margins of error use 90% confidence." : isAhrf ? "HRSA AHRF 2024–2025 release, with 2023 observations. County counts only; no state or tract values are inferred. Connecticut planning-region values are unavailable for four measures. Uncertainty was not supplied." : "Official county and census tract estimates. No state estimates are provided by this pilot."}</p>
        <label>Data source <select value={isAcs ? "acs" : isAhrf ? "ahrf" : "pilot"} onChange={(event) => { const paths = { main: "/", acs: "/area/acs-2024", ahrf: "/area/ahrf", pilot: "/area/places-2025" }; window.location.assign(paths[event.target.value]); }}>
          <option value="pilot">PLACES 2025 county and tract pilot</option><option value="acs">ACS 2020–2024 5-year income</option><option value="ahrf">AHRF 2023 workforce and hospitals</option><option value="main">Main CHIP map</option>
        </select></label>
        {catalogError && <p role="alert">{catalogError}</p>}
        {!catalog && !catalogError && <p role="status">Loading catalog…</p>}
        {catalog && !releaseId && <p role="status">The first {isAcs ? "ACS" : "county"} candidate is awaiting supervised review and publication. No {isAcs ? "ACS" : "pilot"} map is published yet.</p>}
        {catalog && releaseId && <>
          <label>Measure <select value={measureId} onChange={(event) => { setMeasureId(event.target.value); setPage(0); }}>
            {catalog.measures.map((item) => <option key={item.measure_id} value={item.measure_id}>{item.label} ({item.observation_period})</option>)}
          </select></label>
          <p className="pilot-metadata">{areaName(geography)} estimates · Observation year {measure?.observation_period} · {measure?.population} · {isAhrf ? measure?.unit : catalog.unit}{isAcs ? " · ACS 5-year Detailed Tables" : ""}</p>
          {isAhrf && <p className="pilot-metadata">Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">HRSA Area Health Resources Files</a>, compiled from {measure?.source}. Counts have no published uncertainty estimate.</p>}
          {wantsTracts && !tractSupported && <p role="status">County estimates remain displayed; no tract estimate is published for this release.</p>}
          {wantsTracts && tractCapExceeded && <p role="status">This viewport contains more than 5,000 tracts. County estimates remain displayed; zoom in for tracts.</p>}
          <p className="pilot-release">Release {releaseId}</p>
        </>}
        <a href="/">← Main map</a>
      </section>
      {catalog && releaseId && <>
        <section className="pilot-panel pilot-legend" aria-label="Legend">
          <h2>{isAcs ? "Median household income" : isAhrf ? measure?.label : "Crude prevalence"} — {areaName(geography)} level</h2>
          {ready && legend ? <>
            <ul className="pilot-swatches">
              {prevalenceColors.map((shade, i) => <li key={shade}><i style={{ background: shade }} />{breaks ?
                isAcs ? `${dollars.format(i === 0 ? availableRange.low : breaks[i - 1])}–${dollars.format(i === 4 ? availableRange.high : breaks[i])}` : isAhrf ? `${Math.round(i === 0 ? availableRange.low : breaks[i - 1])}–${Math.round(i === 4 ? availableRange.high : breaks[i])} ${measure?.unit}` : `${(i === 0 ? availableRange.low : breaks[i - 1]).toFixed(1)}–${(i === 4 ? availableRange.high : breaks[i]).toFixed(1)}%` : "Available"}</li>)}
              {isAcs ? <>
                <li><i style={{ background: "#6d3b9e" }} />Open-ended median</li>
                <li><i style={{ background: "#d8dee3" }} />Missing estimate</li>
                <li><i style={{ background: "#8f6b74" }} />Suppressed estimate</li>
                <li><i style={{ background: "#c4b4d4" }} />Not applicable</li>
              </> : isAhrf ? <><li><i style={{ background: "#d8dee3" }} />Missing source value</li><li><i style={{ background: "#8f6b74" }} />Suppressed</li></> : <><li><i style={{ background: "#a5a5a5" }} />Not published</li><li><i style={{ background: "#d8dee3" }} />Missing or suppressed</li></>}
            </ul>
            <p>{legend.statuses.map((item) => `${item.status}: ${item.n}`).join(" · ")}</p>
            <p>Click a {areaName(geography)} for its value and {isAcs ? "90% margin of error" : isAhrf ? "source status" : "95% confidence interval"}. {isAcs ? "Open-ended medians use the published annotation." : isAhrf ? "Uncertainty was not supplied." : ""}</p>
          </> : <p>{error ? "Data unavailable" : "Loading legend…"}</p>}
        </section>
        <section className={`pilot-panel pilot-table ${tableOpen ? "is-open" : ""}`} aria-label={`${areaName(geography)} table`}>
          <button className="pilot-table-toggle" type="button" aria-expanded={tableOpen} onClick={() => setTableOpen((open) => !open)}>
            <span>Displayed {areaName(geography)} values{ready && table ? ` (${table.total})` : ""}</span><span aria-hidden="true">{tableOpen ? "−" : "+"}</span>
          </button>
          {tableOpen && <div className="pilot-table-body">
            {error && <p role="alert">{error}</p>}
            {!ready && !error && <p role="status">Loading selected {areaName(geography)} estimates…</p>}
            {ready && table && <>
              <p>{areaName(geography)} areas intersecting the map viewport. Map and table use the same geometry rule.</p>
              <div className="pilot-table-scroll"><table><caption>{measure?.label}, {measure?.observation_period}; release {releaseId}</caption>
                <thead><tr><th scope="col">{geography === "tract" ? "Tract GEOID" : geography === "state" ? "State FIPS" : "County FIPS"}</th><th scope="col">{areaName(geography)}</th><th scope="col">{isAcs ? "Value (2024 USD)" : isAhrf ? `Value (${measure?.unit})` : "Value (%)"}</th><th scope="col">{isAcs ? "90% MOE" : isAhrf ? "Uncertainty" : "95% CI"}</th><th scope="col">Status</th></tr></thead>
                <tbody>{table.rows.map((row) => {
                  const key = row.geography_id || row.tract_fips || row.county_fips;
                  return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{displayValue(row, isAcs, isAhrf)}</td><td>{displayUncertainty(row, isAcs, isAhrf)}</td><td>{row.status}</td></tr>;
                })}</tbody>
              </table></div>
              <nav aria-label={`${areaName(geography)} table pages`}><button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button> Page {page + 1} of {Math.max(1, Math.ceil(table.total / 100))} <button disabled={(page + 1) * 100 >= table.total} onClick={() => setPage(page + 1)}>Next</button></nav>
            </>}
          </div>}
        </section>
      </>}
    </main>
    <Footer />
  </div>;
}
