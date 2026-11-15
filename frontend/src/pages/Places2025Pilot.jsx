import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GeoJSON, MapContainer, TileLayer, ZoomControl, useMapEvents } from "react-leaflet";
import { API_BASE } from "../config/apiBase";
import Header from "../components/Header";
import Footer from "../components/Footer";
import { HealthCenterSiteLayer, HealthCenterSitePanel, useHealthCenterSites } from "../components/HealthCenterSites";
import { TriFacilityLayer, TriFacilityPanel, useTriFacilities } from "../components/TriFacilities";
import { NursingHomeLayer, NursingHomePanel, useNursingHomes } from "../components/NursingHomes";
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
function displayValue(item, isAcs, isAhrf = false, isClh = false, unit = "%") {
  if (isAhrf) return item.value == null ? item.status : new Intl.NumberFormat("en-US").format(item.value);
  if (isClh) return item.value == null ? item.status : `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(item.value)} ${unit}`;
  if (!isAcs) return item.value == null ? item.status : `${item.value}%`;
  if (item.status === "open_ended" && item.estimate_annotation) {
    const bound = Number(item.estimate_annotation.replace(/[^0-9]/g, ""));
    return `${item.estimate_annotation.endsWith("+") ? "≥" : "≤"}${dollars.format(bound)}`;
  }
  return item.value == null ? item.status : dollars.format(item.value);
}
function displayUncertainty(item, isAcs, isAhrf = false, isClh = false) {
  if (isAhrf || isClh) return "Not supplied";
  if (!isAcs) return item.ci_low == null ? "—" : `${item.ci_low}–${item.ci_high}%`;
  if (item.moe != null) return `±${dollars.format(item.moe)} (90% MOE)`;
  return item.moe_annotation ? `${item.moe_annotation} (MOE unavailable)` : "—";
}
function areaName(level) { return level === "state" ? "state" : level === "tract" ? "tract" : "county"; }

export const AQI_DATASET_ID = "epa_airdata_aqi_county_2025";
export const AQI_NO_VALUE = "no_reported_value";
const integer = new Intl.NumberFormat("en-US");
// Neutral sequential shading. Deliberately not the daily AQI health-category colors:
// these are annual summary statistics, not a day's health category.
const aqiColors = ["#f1eef6", "#d0d1e6", "#a6bddb", "#3690c0", "#034e7b"];
const AQI_NO_VALUE_COLOR = "#ffffff";

export function aqiBinLabels(breaks, unit) {
  const suffix = unit === "days" ? " days" : "";
  return [
    `0–${breaks[0]}${suffix}`,
    ...breaks.slice(1).map((upper, i) => `${breaks[i] + 1}–${upper}${suffix}`),
    `${breaks[breaks.length - 1] + 1} or more${suffix}`,
  ];
}
export function aqiColor(value, status, breaks) {
  if (status === AQI_NO_VALUE || value == null) return AQI_NO_VALUE_COLOR;
  const index = breaks.findIndex((upper) => value <= upper);
  return aqiColors[index < 0 ? aqiColors.length - 1 : index];
}
export function aqiValueText(item, measure) {
  if (item.status === AQI_NO_VALUE || item.value == null) return "No reported value";
  const unit = measure?.unit === "days" ? (item.value === 1 ? " day" : " days") : "";
  const beyond = item.value_note === "above_500_beyond_aqi_scale" ? " (above 500: beyond the AQI scale)" : "";
  return `${integer.format(item.value)}${unit}${beyond}`;
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}
export function aqiPopup(item, measure) {
  const source = item.source_name ? `<br>EPA source name: ${escapeHtml(item.source_name)}` : "";
  return `County ${escapeHtml(item.name)} (${escapeHtml(item.geography_id)})<br>${escapeHtml(measure?.label)}: ${escapeHtml(aqiValueText(item, measure))}`
    + `<br>${escapeHtml(aqiReportingText(item, measure?.observation_period))}${source}`
    + `<br>${escapeHtml(measure?.observation_period)} annual summary · historical, not current conditions`;
}
export function aqiReportingText(item, year) {
  if (item.days_with_aqi == null) return "No EPA county summary for this year";
  const total = Number(year) % 4 === 0 && (Number(year) % 100 !== 0 || Number(year) % 400 === 0) ? 366 : 365;
  return `${integer.format(item.days_with_aqi)} of ${total} days with AQI`;
}

export const GV_DATASET_ID = "cms_om_geographic_variation";
// Fixed display classes from the registry, shared by map, legend, and table. Not statistics.
const gvColors = ["#edf8fb", "#b3cde3", "#8c96c6", "#8856a7", "#810f7c"];
const GV_STATUS_COLORS = { suppressed: "#8f6b74", missing: "#d8dee3", not_published: "#ffffff" };
const GV_STATUS_TEXT = {
  suppressed: "Suppressed by CMS (fewer than 11)",
  missing: "Missing in CMS file",
  not_published: "Not published by CMS at this level",
};
const gvMoney = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const gvDecimal = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

export function gvGeography(zoom, countyZoom = ACS_COUNTY_ZOOM) {
  return zoom < countyZoom ? "state" : "county";
}
export function gvNumber(value, kind) {
  if (value == null) return "—";
  if (kind === "count") return integer.format(value);
  if (kind === "currency") return gvMoney.format(value);
  if (kind === "per_1000") return `${gvDecimal.format(value)} per 1,000`;
  // CMS stores proportions as 0–1; multiply by 100 for display only.
  if (kind === "proportion") return `${(value * 100).toFixed(2)}%`;
  return String(value);
}
export function gvValueText(item, measure) {
  if (GV_STATUS_TEXT[item.status] || item.value == null) return GV_STATUS_TEXT[item.status] || "Missing in CMS file";
  return gvNumber(item.value, measure?.kind);
}
export function gvColor(value, status, breaks) {
  if (GV_STATUS_COLORS[status]) return GV_STATUS_COLORS[status];
  if (value == null) return GV_STATUS_COLORS.missing;
  const index = breaks.findIndex((upper) => value < upper);
  return gvColors[index < 0 ? gvColors.length - 1 : index];
}
export function gvBinLabels(breaks, kind) {
  return [
    `Under ${gvNumber(breaks[0], kind)}`,
    ...breaks.slice(1).map((upper, i) => `${gvNumber(breaks[i], kind)} to under ${gvNumber(upper, kind)}`),
    `${gvNumber(breaks[breaks.length - 1], kind)} or more`,
  ];
}
export function gvPopup(item, measure, geography, catalog) {
  const level = geography === "state" ? "State" : "County";
  return `${level} ${escapeHtml(item.name)} (${escapeHtml(item.geography_id)})<br>${escapeHtml(measure?.label)}: ${escapeHtml(gvValueText(item, measure))}`
    + `<br>${escapeHtml(measure?.observation_period)} · ${escapeHtml(catalog?.population_label)}`
    + (item.source_name ? `<br>CMS name: ${escapeHtml(item.source_name)}` : "");
}

export const FEA_DATASET_ID = "usda_ers_food_environment_atlas";
// Fixed registry display classes shared by map, legend, and table; not statistical groupings.
const feaColors = ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"];
const FEA_ZERO_COLOR = "#fdd49e";
export const FEA_STATUS_COLORS = {
  not_available: "#d8dee3", did_not_exist: "#a08c6a", boundary_not_comparable: "#ffffff", not_covered: "#ffffff",
};
export const FEA_STATUS_TEXT = {
  not_available: "Not available (USDA -9999 or N/A)",
  did_not_exist: "County did not exist in that year (USDA -8888)",
  boundary_not_comparable: "Not published on this boundary (Connecticut planning region)",
  not_covered: "Outside Atlas coverage (Puerto Rico)",
  not_in_source: "No USDA row",
};
const feaDecimal = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });
export function feaNumber(value, kind) {
  if (value == null) return "—";
  if (kind === "percent") return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)}%`;
  return `${feaDecimal.format(value)} per 1,000`;
}
export function feaValueText(item, measure) {
  if (FEA_STATUS_TEXT[item.status] || item.value == null) return FEA_STATUS_TEXT[item.status] || "Not available";
  if (item.status === "true_zero") return `0 (published zero)`;
  return feaNumber(item.value, measure?.kind);
}
export function feaColor(value, status, breaks) {
  if (FEA_STATUS_COLORS[status]) return FEA_STATUS_COLORS[status];
  if (value == null) return FEA_STATUS_COLORS.not_available;
  if (status === "true_zero") return FEA_ZERO_COLOR;
  const index = breaks.findIndex((upper) => value < upper);
  return feaColors[index < 0 ? feaColors.length - 1 : index];
}
export function feaBinLabels(breaks, kind) {
  return [
    `Above 0 to under ${feaNumber(breaks[0], kind)}`,
    ...breaks.slice(1).map((upper, i) => `${feaNumber(breaks[i], kind)} to under ${feaNumber(upper, kind)}`),
    `${feaNumber(breaks[breaks.length - 1], kind)} or more`,
  ];
}
export function feaPopup(item, measure) {
  return `County ${escapeHtml(item.name)} (${escapeHtml(item.geography_id)})<br>${escapeHtml(measure?.label)}: ${escapeHtml(feaValueText(item, measure))}`
    + `<br>Observation year ${escapeHtml(measure?.observation_period)} · ${escapeHtml(measure?.unit)}`
    + (item.source_value != null ? `<br>USDA value: ${escapeHtml(item.source_value)} (${escapeHtml(measure?.variable_code)})` : "")
    + (item.source_name ? `<br>USDA name: ${escapeHtml(item.source_name)}` : "");
}

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
  const isClh = dataset === "clh";
  const isAqi = dataset === "aqi";
  const isGv = dataset === "cmsgv";
  const isFea = dataset === "usdafea";
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState("");
  const [measureId, setMeasureId] = useState(() => new URLSearchParams(window.location.search).get("measure_id") ||
    (isAcs ? "B19013_001E" : isAhrf ? "phys_nf_prim_care_pc_exc_rsdt_23" : isClh ? "ACS_PCT_HH_BROADBAND_ANY" : isAqi ? "median_aqi" : isGv ? "std_payment_per_capita" : isFea ? "low_income_low_access_pct" : "dental_crudeprev"));
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
  // Optional point overlay: its own release, filters, and requests; it never changes the area selection.
  const sites = useHealthCenterSites({ bbox, zoom: mapZoom });
  // Second, independent point overlay (EPA TRI). Both overlays may be shown together.
  const tri = useTriFacilities({ bbox, zoom: mapZoom });
  const homes = useNursingHomes({ bbox, zoom: mapZoom });

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/area/catalog${isAcs ? "?dataset_id=census_acs5_2024_b19013" : isAhrf ? "?dataset_id=hrsa_ahrf_county_2024_2025" : isClh ? "?dataset_id=ahrq_clh_2023_curated" : isAqi ? `?dataset_id=${AQI_DATASET_ID}` : isGv ? `?dataset_id=${GV_DATASET_ID}` : isFea ? `?dataset_id=${FEA_DATASET_ID}` : ""}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(`Catalog unavailable (${response.status})`); return response.json(); })
      .then(setCatalog).catch((err) => { if (err.name !== "AbortError") setCatalogError(err.message); });
    return () => controller.abort();
  }, [isAcs, isAhrf, isClh, isAqi, isGv, isFea]);

  useEffect(() => {
    if (catalog?.measures?.length && !catalog.measures.some((item) => item.measure_id === measureId)) {
      setMeasureId(catalog.measures[0].measure_id);
    }
  }, [catalog, measureId]);

  const measure = useMemo(() => catalog?.measures.find((item) => item.measure_id === measureId), [catalog, measureId]);
  const releaseId = catalog?.active_release_id;
  const wantsTracts = mapZoom >= (isAcs ? ACS_TRACT_ZOOM : PILOT_TRACT_ZOOM);
  const tractSupported = measure?.geographies ? measure.geographies.includes("tract") : catalog?.geographies?.includes("tract");
  const capSelectionKey = `${releaseId}|${measureId}|${bbox}`;
  const tractCapExceeded = tractCapKey === capSelectionKey;
  // USDA FEA publishes no state value for its selected measures, so counties are shown at every zoom.
  const geography = isAhrf || isAqi || isFea ? "county" : isGv ? gvGeography(mapZoom, catalog?.state_to_county_zoom) : areaGeography(mapZoom, isAcs, tractSupported, tractCapExceeded);
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
      <div className="chip-brand-line"><strong>CHIP by Public Data Observatory</strong><span>{isAcs ? "ACS 2020–2024 5-year income" : isAhrf ? "AHRF 2023 county resources" : isClh ? "AHRQ CLH community conditions" : isAqi ? "EPA AirData 2025 annual county AQI" : isGv ? "CMS Original Medicare 2024, states and counties" : isFea ? "USDA Food Environment Atlas, county measures" : "PLACES 2025 county and tract pilot"}</span></div>
      <div className="map-wrapper pilot-map" aria-label={catalog && releaseId ? `${areaName(geography)} ${isAcs ? "ACS" : isClh ? "CLH" : isGv ? "CMS Original Medicare" : isFea ? "USDA Food Environment Atlas" : "pilot"} map` : undefined}>
        {catalog && releaseId && <MapContainer center={[38, -104]} zoom={zoom} minZoom={zoom} zoomSnap={0.25} zoomControl={false}
          maxBounds={[[-85, -180], [85, 180]]} maxBoundsViscosity={1} style={{ height: "100%", width: "100%" }}>
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap contributors" />
          <ZoomControl position="bottomright" />
          <Viewport onChange={onViewport} />
          {features.length > 0 && <GeoJSON key={`${releaseId}:${measureId}:${geography}:${bbox}`} data={mapData} style={(feature) => isFea ? {
            color: "#516677", weight: 0.5,
            fillOpacity: ["boundary_not_comparable", "not_covered"].includes(feature.properties.status) ? 0.35 : 0.85,
            dashArray: ["boundary_not_comparable", "not_covered"].includes(feature.properties.status) ? "2 3" : null,
            fillColor: feaColor(feature.properties.value, feature.properties.status, mapData?.legend_breaks || []),
          } : isGv ? {
            color: "#516677", weight: 0.5,
            fillOpacity: feature.properties.status === "not_published" ? 0.35 : 0.85,
            dashArray: feature.properties.status === "not_published" ? "2 3" : null,
            fillColor: gvColor(feature.properties.value, feature.properties.status, mapData?.legend_breaks || []),
          } : isAqi ? {
            color: "#516677", weight: 0.5,
            fillOpacity: feature.properties.status === AQI_NO_VALUE ? 0.35 : 0.85,
            dashArray: feature.properties.status === AQI_NO_VALUE ? "2 3" : null,
            fillColor: aqiColor(feature.properties.value, feature.properties.status, measure?.legend_breaks || []),
          } : ({
            color: "#516677", weight: 0.5, fillOpacity: 0.78,
            fillColor: color(feature.properties.value, feature.properties.status, breaks),
          })} onEachFeature={(feature, layer) => {
            const item = feature.properties;
            if (isAqi) { layer.bindPopup(aqiPopup(item, measure)); return; }
            if (isGv) { layer.bindPopup(gvPopup(item, measure, geography, catalog)); return; }
            if (isFea) { layer.bindPopup(feaPopup(item, measure)); return; }
            const value = displayValue(item, isAcs, isAhrf, isClh, measure?.unit);
            const uncertainty = displayUncertainty(item, isAcs, isAhrf, isClh);
            layer.bindPopup(`${areaName(geography)} ${item.name} (${item.geography_id || item.county_fips})<br>${value} ${isAhrf && item.value != null ? measure?.unit : ""}<br>${uncertainty}<br>${measure?.observation_period}${isAcs ? " · ACS 5-year · 2024 dollars" : ""}`);
          }} />}
          {sites.enabled && <HealthCenterSiteLayer sites={sites} />}
          {tri.enabled && <TriFacilityLayer tri={tri} />}
          {homes.enabled && <NursingHomeLayer homes={homes} />}
        </MapContainer>}
      </div>
      <section className="pilot-panel pilot-controls" aria-label="Analytical controls">
        <h1>{isAcs ? "ACS 2020–2024 5-year income" : isAhrf ? "AHRF 2023 county resources" : isClh ? "AHRQ CLH community conditions" : isAqi ? "EPA annual AQI by county, 2025" : isGv ? "CMS Original Medicare Geographic Variation, 2024" : isFea ? "USDA Food Environment Atlas: county food access and retailers" : "PLACES 2025 pilot"}</h1>
        {isFea ? <div className="pilot-scope">
          <p>Five published county measures from USDA ERS's Food Environment Atlas, {catalog?.release_label ?? "July 2025"} release. <strong>Each measure has its own observation year (2018–2023)</strong>; none describes 2025 or current conditions. USDA publishes no state value for these measures, so counties are shown at every zoom and none is averaged or summed. No tract values exist.</p>
          <p className="pilot-metadata">This is a separate, release-pinned product. The main map's “USDA Food Environment (legacy import)” option reads the older tables and is unchanged.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">
            {(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div> : isGv ? <div className="pilot-scope">
          <p>Published CMS values for the Original Medicare (fee-for-service) population with Part A and Part B, all ages. Medicare Advantage enrollees are excluded. Observation year {catalog?.observation_year ?? "2024"}; source release “{catalog?.source_release_id ?? "OM GV PUF May 2026 update"}”. States are shown at broad zoom and counties from zoom {catalog?.state_to_county_zoom ?? ACS_COUNTY_ZOOM}. No tract values exist.</p>
          <p className="pilot-metadata">This is a separate, release-pinned product. The main map's “CMS Medicare Fee-for-Service (legacy import)” option reads older tables and is unchanged.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">
            {(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div> : isAqi ? <div className="pilot-scope">
          <p>EPA AirData annual summary of daily Air Quality Index values for calendar year 2025, from the file EPA generated on 2026-06-25. County values only; no state or tract values are derived.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">
            {(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div> : <p className="pilot-scope">{isAcs ? "Published median household income for states, counties, and census tracts. Values are 2024 inflation-adjusted dollars; margins of error use 90% confidence." : isAhrf ? "HRSA AHRF 2024–2025 release, with 2023 observations. County counts only; no state or tract values are inferred. Connecticut planning-region values are unavailable for four measures. Uncertainty was not supplied." : isClh ? "AHRQ CLH September 2025 release. ACS measures cover 2019–2023 at county and tract levels; business densities describe 2023 counties only. No state estimates or uncertainty fields are supplied." : "Official county and census tract estimates. No state estimates are provided by this pilot."}</p>}
        <label>Data source <select value={isAcs ? "acs" : isAhrf ? "ahrf" : isClh ? "clh" : isAqi ? "aqi" : isGv ? "cmsgv" : isFea ? "usdafea" : "pilot"} onChange={(event) => { const paths = { main: "/", acs: "/area/acs-2024", ahrf: "/area/ahrf", clh: "/area/clh", aqi: "/area/epa-aqi", cmsgv: "/area/cms-gv", usdafea: "/area/usda-fea", pilot: "/area/places-2025" }; window.location.assign(paths[event.target.value]); }}>
          <option value="pilot">PLACES 2025 county and tract pilot</option><option value="acs">ACS 2020–2024 5-year income</option><option value="ahrf">AHRF 2023 workforce and hospitals</option><option value="clh">AHRQ CLH community conditions</option><option value="aqi">EPA annual AQI by county (2025)</option><option value="cmsgv">CMS Original Medicare 2024 (states and counties)</option><option value="usdafea">USDA Food Environment Atlas (county measures)</option><option value="main">Main CHIP map</option>
        </select></label>
        {catalogError && <p role="alert">{catalogError}</p>}
        {!catalog && !catalogError && <p role="status">Loading catalog…</p>}
        {catalog && !releaseId && <p role="status">The first {isAcs ? "ACS" : "county"} candidate is awaiting supervised review and publication. No {isAcs ? "ACS" : "pilot"} map is published yet.</p>}
        {catalog && releaseId && <>
          <label>Measure <select value={measureId} onChange={(event) => { setMeasureId(event.target.value); setPage(0); }}>
            {catalog.measures.map((item) => <option key={item.measure_id} value={item.measure_id}>{item.label} ({item.observation_period})</option>)}
          </select></label>
          {isFea && <div className="pilot-fea-measure">
            <p className="pilot-period"><strong>Observation year {measure?.observation_period}</strong> · {measure?.unit} · county values only</p>
            <p className="pilot-metadata">USDA definition ({measure?.variable_code}): {measure?.official_definition}</p>
            <p className="pilot-metadata">Denominator: {measure?.denominator} {measure?.interpretation}</p>
            <p className="pilot-metadata">Contributing sources: {measure?.contributing_sources} County boundary basis in the source: {measure?.source_boundary_basis}; joined by exact FIPS to {catalog.boundary_vintage}. Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">USDA ERS Food Environment Atlas</a> (<a href={catalog.documentation_url} target="_blank" rel="noreferrer">documentation</a>).</p>
            {mapZoom < ACS_COUNTY_ZOOM && <p role="status">State values are not published for this measure; counties are shown at the national view.</p>}
          </div>}
          {!isFea && <p className="pilot-metadata">{areaName(geography)} estimates · {isClh ? "Observation period" : "Observation year"} {measure?.observation_period} · {measure?.population} · {isAhrf || isClh || isAqi || isGv ? measure?.unit : catalog.unit}{isAcs ? " · ACS 5-year Detailed Tables" : ""}</p>}
          {isAhrf && <p className="pilot-metadata">Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">HRSA Area Health Resources Files</a>, compiled from {measure?.source}. Counts have no published uncertainty estimate.</p>}
          {isGv && <p className="pilot-metadata">CMS definition ({measure?.source_field}): {measure?.official_definition} Denominator: {measure?.denominator} {measure?.interpretation} Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">CMS Medicare Geographic Variation</a>.</p>}
          {isAqi && <p className="pilot-metadata">EPA definition: {measure?.official_definition} {measure?.statistic_note} Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">EPA AirData pre-generated files</a>.</p>}
          {isClh && <p className="pilot-metadata">Distributed by <a href={catalog.source_url} target="_blank" rel="noreferrer">AHRQ CLH</a>; contributing source: {measure?.source}. {measure?.denominator} denominator. Blanks remain missing; no uncertainty estimate is supplied.</p>}
          {isGv && wantsTracts && <p role="status">County values remain displayed. CMS publishes no tract estimates for this product.</p>}
          {isFea && wantsTracts && <p role="status">County values remain displayed. USDA publishes no tract values for these measures, and none is estimated.</p>}
          {!isGv && !isFea && wantsTracts && !tractSupported && <p role="status">County estimates remain displayed; no tract estimate is published for this release.</p>}
          {wantsTracts && tractCapExceeded && <p role="status">This viewport contains more than 5,000 tracts. County estimates remain displayed; zoom in for tracts.</p>}
          <p className="pilot-release">Release {releaseId}</p>
        </>}
        <a href="/">← Main map</a>
      </section>
      {catalog && releaseId && <>
        <section className="pilot-panel pilot-legend" aria-label="Legend">
          <h2>{isAcs ? "Median household income" : isAhrf || isClh || isAqi || isGv || isFea ? measure?.label : "Crude prevalence"}{isFea ? `, ${measure?.observation_period ?? ""}` : ""} — {areaName(geography)} level</h2>
          {ready && legend && isFea ? <>
            <ul className="pilot-swatches">
              <li><i style={{ background: FEA_ZERO_COLOR }} />0 (published zero)</li>
              {feaBinLabels(legend.legend_breaks || [], measure?.kind).map((label, i) => <li key={label}><i style={{ background: feaColors[i] }} />{label}</li>)}
              <li><i style={{ background: FEA_STATUS_COLORS.not_available }} />{FEA_STATUS_TEXT.not_available}</li>
              <li><i style={{ background: FEA_STATUS_COLORS.did_not_exist }} />{FEA_STATUS_TEXT.did_not_exist}</li>
              <li><i className="pilot-swatch-none" style={{ background: FEA_STATUS_COLORS.boundary_not_comparable }} />{FEA_STATUS_TEXT.boundary_not_comparable} or {FEA_STATUS_TEXT.not_covered.toLowerCase()}</li>
            </ul>
            <p>{measure?.unit}, observation year {measure?.observation_period}. Fixed display classes; not statistical groupings.</p>
            <p>{legend.statuses.map((item) => `${item.status === "available" ? "published value" : item.status === "true_zero" ? "published zero" : FEA_STATUS_TEXT[item.status] ?? item.status}: ${item.n}`).join(" · ")}</p>
            <p>Select a county for its value and USDA source value. No confidence interval or margin of error is published.</p>
          </> : ready && legend && isGv ? <>
            <ul className="pilot-swatches">
              {gvBinLabels(legend.legend_breaks || [], measure?.kind).map((label, i) => <li key={label}><i style={{ background: gvColors[i] }} />{label}</li>)}
              <li><i style={{ background: GV_STATUS_COLORS.suppressed }} />{GV_STATUS_TEXT.suppressed}</li>
              <li><i style={{ background: GV_STATUS_COLORS.missing }} />{GV_STATUS_TEXT.missing}</li>
              <li><i className="pilot-swatch-none" style={{ background: GV_STATUS_COLORS.not_published }} />{GV_STATUS_TEXT.not_published} (DC and Puerto Rico counties)</li>
            </ul>
            <p>{measure?.unit}. Fixed display classes{measure?.kind === "count" ? ` for ${areaName(geography)} counts` : ", the same at state and county levels"}; not statistical groupings.</p>
            <p>{legend.statuses.map((item) => `${GV_STATUS_TEXT[item.status] ?? item.status.replace("_", " ")}: ${item.n}`).join(" · ")}</p>
            {legend.national_reference && <p>United States (CMS-published national value, reference only): {gvValueText(legend.national_reference, measure)}</p>}
            <p>Select a {areaName(geography)} for its value. No confidence interval or margin of error is published.</p>
          </> : ready && legend && isAqi ? <>
            <ul className="pilot-swatches">
              {aqiBinLabels(measure?.legend_breaks || [], measure?.unit).map((label, i) => <li key={label}><i style={{ background: aqiColors[i] }} />{label}</li>)}
              <li><i className="pilot-swatch-none" style={{ background: AQI_NO_VALUE_COLOR }} />No reported value (not monitored or not reported; does not mean clean air)</li>
            </ul>
            <p>{measure?.kind === "aqi_index" ? "AQI index values with neutral shading. These annual statistics are not daily AQI health categories, so EPA's category colors are not used." : "Day counts. Read them against each county's Days with AQI; they are not percentages."}</p>
            <p>{legend.statuses.map((item) => `${item.status === AQI_NO_VALUE ? "no reported value" : item.status.replace("_", " ")}: ${item.n}`).join(" · ")}</p>
            {legend.statuses.some((item) => item.days_low != null) && <p>Days with AQI in view: {Math.min(...legend.statuses.filter((item) => item.days_low != null).map((item) => item.days_low))}–{Math.max(...legend.statuses.filter((item) => item.days_high != null).map((item) => item.days_high))}.</p>}
            <p>Select a county for its value, Days with AQI, and EPA source name.</p>
          </> : ready && legend ? <>
            <ul className="pilot-swatches">
              {prevalenceColors.map((shade, i) => <li key={shade}><i style={{ background: shade }} />{breaks ?
                isAcs ? `${dollars.format(i === 0 ? availableRange.low : breaks[i - 1])}–${dollars.format(i === 4 ? availableRange.high : breaks[i])}` : isAhrf ? `${Math.round(i === 0 ? availableRange.low : breaks[i - 1])}–${Math.round(i === 4 ? availableRange.high : breaks[i])} ${measure?.unit}` : isClh ? `${(i === 0 ? availableRange.low : breaks[i - 1]).toFixed(2)}–${(i === 4 ? availableRange.high : breaks[i]).toFixed(2)} ${measure?.unit}` : `${(i === 0 ? availableRange.low : breaks[i - 1]).toFixed(1)}–${(i === 4 ? availableRange.high : breaks[i]).toFixed(1)}%` : "Available"}</li>)}
              {isAcs ? <>
                <li><i style={{ background: "#6d3b9e" }} />Open-ended median</li>
                <li><i style={{ background: "#d8dee3" }} />Missing estimate</li>
                <li><i style={{ background: "#8f6b74" }} />Suppressed estimate</li>
                <li><i style={{ background: "#c4b4d4" }} />Not applicable</li>
              </> : isAhrf || isClh ? <><li><i style={{ background: "#d8dee3" }} />Missing source value</li><li><i style={{ background: "#8f6b74" }} />Suppressed</li></> : <><li><i style={{ background: "#a5a5a5" }} />Not published</li><li><i style={{ background: "#d8dee3" }} />Missing or suppressed</li></>}
            </ul>
            <p>{legend.statuses.map((item) => `${item.status}: ${item.n}`).join(" · ")}</p>
            <p>Click a {areaName(geography)} for its value and {isAcs ? "90% margin of error" : isAhrf || isClh ? "source status" : "95% confidence interval"}. {isAcs ? "Open-ended medians use the published annotation." : isAhrf || isClh ? "Uncertainty was not supplied." : ""}</p>
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
              <p>{areaName(geography)} areas intersecting the map viewport. Map and table use the same geometry rule.{isFea ? " All 2024 boundary counties in view are listed with USDA's published value and status." : isAqi ? " All 2024 boundary counties are listed; counties without an EPA summary are marked No reported value." : isGv ? ` All 2024 boundary ${geography === "state" ? "states" : "counties"} in view are listed with CMS's published value and status.` : ""}</p>
              <div className="pilot-table-scroll"><table><caption>{measure?.label}, {measure?.observation_period}; release {releaseId}</caption>
                {isFea ? <thead><tr><th scope="col">County FIPS</th><th scope="col">County</th><th scope="col">{measure?.label} ({measure?.observation_period})</th><th scope="col">USDA source value</th><th scope="col">Status</th></tr></thead>
                : isGv ? <thead><tr><th scope="col">{geography === "state" ? "State FIPS" : "County FIPS"}</th><th scope="col">{areaName(geography)}</th><th scope="col">{measure?.label}</th><th scope="col">CMS source value</th><th scope="col">Status</th></tr></thead>
                : isAqi ? <thead><tr><th scope="col">County FIPS</th><th scope="col">County</th><th scope="col">{measure?.label} ({measure?.unit})</th><th scope="col">Days with AQI</th><th scope="col">EPA source name</th><th scope="col">Status</th></tr></thead>
                : <thead><tr><th scope="col">{geography === "tract" ? "Tract GEOID" : geography === "state" ? "State FIPS" : "County FIPS"}</th><th scope="col">{areaName(geography)}</th><th scope="col">{isAcs ? "Value (2024 USD)" : isAhrf || isClh ? `Value (${measure?.unit})` : "Value (%)"}</th><th scope="col">{isAcs ? "90% MOE" : isAhrf || isClh ? "Uncertainty" : "95% CI"}</th><th scope="col">Status</th></tr></thead>}
                <tbody>{table.rows.map((row) => {
                  const key = row.geography_id || row.tract_fips || row.county_fips;
                  if (isFea) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{feaValueText(row, measure)}</td><td>{row.source_value ?? "—"}</td><td>{row.status === "available" ? "Published value" : row.status === "true_zero" ? "Published zero" : FEA_STATUS_TEXT[row.status] ?? row.status}</td></tr>;
                  if (isGv) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{gvValueText(row, measure)}</td><td>{row.source_value ?? "—"}</td><td>{GV_STATUS_TEXT[row.status] ?? row.status}</td></tr>;
                  if (isAqi) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{aqiValueText(row, measure)}</td><td>{row.days_with_aqi ?? "—"}</td><td>{row.source_name ?? "—"}</td><td>{row.status === AQI_NO_VALUE ? "No reported value" : row.status}</td></tr>;
                  return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{displayValue(row, isAcs, isAhrf, isClh, measure?.unit)}</td><td>{displayUncertainty(row, isAcs, isAhrf, isClh)}</td><td>{row.status}</td></tr>;
                })}</tbody>
              </table></div>
              <nav aria-label={`${areaName(geography)} table pages`}><button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button> Page {page + 1} of {Math.max(1, Math.ceil(table.total / 100))} <button disabled={(page + 1) * 100 >= table.total} onClick={() => setPage(page + 1)}>Next</button></nav>
            </>}
          </div>}
        </section>
        <div className="pilot-overlays">
          <HealthCenterSitePanel sites={sites} />
          <TriFacilityPanel tri={tri} />
          <NursingHomePanel homes={homes} />
        </div>
      </>}
    </main>
    <Footer />
  </div>;
}
