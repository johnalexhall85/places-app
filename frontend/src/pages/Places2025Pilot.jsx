import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GeoJSON, MapContainer, Pane, TileLayer, ZoomControl, useMap, useMapEvents } from "react-leaflet";
import { API_BASE } from "../config/apiBase";
import Header from "../components/Header";
import Footer from "../components/Footer";
import { HealthCenterSiteLayer, HealthCenterSitePanel, useHealthCenterSites } from "../components/HealthCenterSites";
import { TriFacilityLayer, TriFacilityPanel, useTriFacilities } from "../components/TriFacilities";
import { NursingHomeLayer, NursingHomePanel, useNursingHomes } from "../components/NursingHomes";
import PlaceSearch from "../components/PlaceSearch";
import MapTools from "./areaMap/MapTools";
import { BASE_MAP_OPTIONS } from "../branding/baseMaps";
import { BLUES, HOVER_LINE, SELECTION_CASING, SELECTION_LINE, quantileColor, quantileCuts, quantileLabels, rampColors } from "../branding/mapColors";
import { gridForZoom } from "../utils/mapGrid";
import { MAP_HOVER_TOOLTIP_OPTIONS, areaTooltipHtml, isCoarsePointer } from "../utils/mapTooltip";
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
function areaName(level) { return level === "state" ? "state" : level === "tract" ? "tract" : level === "cd" ? "congressional district" : "county"; }
function profileValue(item, measure) {
  if (item.value == null) return item.status_text || item.status;
  const n = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(item.value);
  return measure?.kind === "percent" ? `${n}%` : `${n} ${measure?.unit || ""}`.trim();
}
function profileUncertainty(item) {
  if (item.moe != null) return `±${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(item.moe)} (90% margin of error)`;
  if (item.moe_annotation === "*****") return "No sampling margin: controlled to official population totals";
  return "90% margin of error unavailable";
}

export const AQI_DATASET_ID = "epa_airdata_aqi_county_2025";
export const AQI_NO_VALUE = "no_reported_value";
const integer = new Intl.NumberFormat("en-US");
// Brand Blues sequential shading. Deliberately not the daily AQI health-category colors:
// these are annual summary statistics, not a day's health category.
const aqiColors = BLUES;
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
export function aqiReportingText(item, year) {
  if (item.days_with_aqi == null) return "No EPA county summary for this year";
  const total = Number(year) % 4 === 0 && (Number(year) % 100 !== 0 || Number(year) % 400 === 0) ? 366 : 365;
  return `${integer.format(item.days_with_aqi)} of ${total} days with AQI`;
}

export const GV_DATASET_ID = "cms_om_geographic_variation";
// Fixed display classes from the registry, shared by map, legend, and table. Not statistics.
const gvColors = BLUES;
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

export const FEA_DATASET_ID = "usda_ers_food_environment_atlas";
export const BRFSS_DATASET_ID = "cdc_brfss_state_prevalence";
export function brfssColor(value, status, breaks = []) {
  if (status === "not_published") return "#a5a5a5";
  if (status === "suppressed") return "#8f6b74";
  if (value == null) return "#d8dee3";
  const index = breaks.findIndex((upper) => value < upper);
  return prevalenceColors[index < 0 ? prevalenceColors.length - 1 : index];
}
export function brfssValueText(item) {
  return item.value == null ? (item.status_text || item.status) : `${item.value}%`;
}
// Fixed registry display classes shared by map, legend, and table; not statistical groupings.
const feaColors = BLUES;
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

export function initialMapView(search = typeof window === "undefined" ? "" : window.location.search) {
  const fallback = { center: [38, -104], zoom: initialMapZoom() };
  const params = new URLSearchParams(search);
  const lat = Number(params.get("lat"));
  const lon = Number(params.get("lon"));
  const zoom = Number(params.get("zoom"));
  if (!params.has("lat") || !params.has("lon") || !params.has("zoom") ||
      !Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(zoom) ||
      Math.abs(lat) > 85 || Math.abs(lon) > 180) return fallback;
  return { center: [lat, lon], zoom: Math.min(18, Math.max(initialMapZoom(), zoom)) };
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
  const report = () => {
    const center = map.getCenter();
    onChange(safeViewportBbox(map.getBounds()), map.getZoom(), [center.lat, center.lng]);
  };
  const map = useMapEvents({ moveend: report, zoomend: report });
  useEffect(() => report(), [map, onChange]);
  return null;
}

const prevalenceColors = BLUES;

function color(value, status, breaks) {
  if (status === "open_ended") return "#6d3b9e";
  if (status === "suppressed") return "#8f6b74";
  if (status === "not_applicable") return "#c4b4d4";
  if (!["available", "true_zero", "open_ended"].includes(status)) return status === "not_published" ? "#a5a5a5" : "#d8dee3";
  if (!breaks) return prevalenceColors[2];
  const index = breaks.findIndex((upper) => value < upper);
  return prevalenceColors[index < 0 ? 4 : index];
}
// Quintile classes over the whole release, so an outlier cannot push most areas into one shade.
export function quintileColor(value, status, cuts) {
  if (!["available", "true_zero"].includes(status) || value == null) return color(value, status, null);
  return cuts.length ? quantileColor(value, cuts) : prevalenceColors[2];
}

const LEVEL_TITLES = { state: "State", county: "County", tract: "Tract", cd: "District" };
const EXPLANATIONS = {
  places: "Modeled adult prevalence estimate from CDC PLACES.",
  brfss: "Direct state survey estimate from CDC BRFSS.",
  acs: "Census Bureau ACS 5-year estimate, 2024 dollars.",
  acs_profile: "Census Bureau ACS 5-year estimate.",
  ahrf: "County count from HRSA Area Health Resources Files.",
  clh: "AHRQ Community-Level Health measure.",
  aqi: "EPA annual AQI summary; historical, not current conditions.",
  cmsgv: "Original Medicare beneficiaries only, not all residents.",
  usdafea: "USDA Food Environment Atlas county measure.",
};
export function featureId(item) { return String(item?.geography_id ?? item?.tract_fips ?? item?.county_fips ?? ""); }
export function areaTitle(name, level, geoid) { return `${name || "Unnamed area"} · ${LEVEL_TITLES[level] || "Area"} ${geoid}`; }

// One description of a mapped area, used by the hover tooltip and the legend's selected-area block.
// Plain text only: React escapes it in the legend and the tooltip builder escapes it for Leaflet.
export function areaFeatureDetails(dataset, item, measure, context = {}) {
  const { geography = "county", catalog = null, releaseId = null } = context;
  const period = measure?.observation_period;
  const base = { area: areaTitle(item.name, geography, featureId(item)), measure: measure?.label, period, explanation: EXPLANATIONS[dataset] || EXPLANATIONS.places };
  let value; let lines;
  if (dataset === "brfss") {
    value = brfssValueText(item);
    lines = [`95% confidence interval: ${item.ci_low == null ? "unavailable" : `${item.ci_low}–${item.ci_high}%`}`,
      `Respondents giving this response: ${item.sample_size == null ? "unavailable" : item.sample_size}`,
      `CDC BRFSS · ${period} · ${measure?.population}`];
  } else if (dataset === "aqi") {
    value = aqiValueText(item, measure);
    lines = [aqiReportingText(item, period), item.source_name ? `EPA source name: ${item.source_name}` : null,
      `${period} annual summary · historical, not current conditions`];
  } else if (dataset === "cmsgv") {
    value = gvValueText(item, measure);
    lines = [`${period} · ${catalog?.population_label ?? "Original Medicare beneficiaries"}`, item.source_name ? `CMS name: ${item.source_name}` : null,
      "No confidence interval or margin of error is published."];
  } else if (dataset === "usdafea") {
    value = feaValueText(item, measure);
    lines = [`Observation year ${period} · ${measure?.unit}`,
      item.source_value != null ? `USDA value: ${item.source_value} (${measure?.variable_code})` : null,
      item.source_name ? `USDA name: ${item.source_name}` : null];
  } else if (dataset === "acs_profile") {
    value = profileValue(item, measure);
    lines = [profileUncertainty(item), `Census Bureau · ${period} · ${measure?.population}`];
  } else {
    const isAcs = dataset === "acs"; const isAhrf = dataset === "ahrf"; const isClh = dataset === "clh";
    value = `${displayValue(item, isAcs, isAhrf, isClh, measure?.unit)}${isAhrf && item.value != null ? ` ${measure?.unit}` : ""}`;
    lines = [isAcs ? `90% margin of error: ${displayUncertainty(item, true)}` : isAhrf || isClh ? "Uncertainty: not supplied by the source" : `95% confidence interval: ${displayUncertainty(item, false)}`,
      `${period}${isAcs ? " · ACS 5-year · 2024 dollars" : ""}${measure?.population ? ` · ${measure.population}` : ""}`];
  }
  if (item.value == null && item.status_text && !String(value).includes(item.status_text)) lines.unshift(item.status_text);
  if (releaseId) lines.push(`Release ${releaseId}`);
  return { ...base, value, lines: lines.filter(Boolean) };
}
export function areaTooltip(dataset, item, measure, context) {
  const details = areaFeatureDetails(dataset, item, measure, context);
  return areaTooltipHtml(details);
}

export function parseFocus(search = typeof window === "undefined" ? "" : window.location.search) {
  const match = /^(state|county|tract|cd):(\d{2}|\d{4}|\d{5}|\d{11})$/.exec(new URLSearchParams(search).get("focus") || "");
  if (!match) return null;
  const digits = { state: 2, cd: 4, county: 5, tract: 11 }[match[1]];
  return match[2].length === digits ? { level: match[1], geoid: match[2] } : null;
}
export function profileHrefFor(selection) {
  if (!selection) return null;
  if (selection.level === "county") return `/community/county/${selection.geoid}`;
  if (selection.level === "state") return `/community/state/${selection.geoid}`;
  if (selection.level === "cd") return `/district/cd/${selection.geoid}`;
  return null;
}
// Zoom limits that keep a focused area drawn at its own level where the product publishes it.
export function focusZoomRange(level, { stateBelow = null, countyFrom = null, tractFrom = null, min = 4 } = {}) {
  if (level === "state") return { min, max: stateBelow != null ? stateBelow - 0.25 : 8 };
  if (level === "tract") return { min: tractFrom ?? 10, max: 14 };
  return { min: Math.max(min, countyFrom ?? min), max: tractFrom != null ? tractFrom - 0.25 : 11 };
}

function MapReady({ onReady }) {
  const map = useMap();
  // The map instance is fixed for the life of its container, so register it once.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { onReady(map); return () => onReady(null); }, []);
  return null;
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
  const isProfile = dataset === "acs_profile";
  const isAhrf = dataset === "ahrf";
  const isClh = dataset === "clh";
  const isAqi = dataset === "aqi";
  const isGv = dataset === "cmsgv";
  const isFea = dataset === "usdafea";
  const isBrfss = dataset === "brfss";
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState("");
  const [initialView] = useState(initialMapView);
  const [measureId, setMeasureId] = useState(() => new URLSearchParams(window.location.search).get("measure_id") ||
    (isProfile ? "poverty_pct" : isAcs ? "B19013_001E" : isAhrf ? "phys_nf_prim_care_pc_exc_rsdt_23" : isClh ? "ACS_PCT_HH_BROADBAND_ANY" : isAqi ? "median_aqi" : isGv ? "std_payment_per_capita" : isFea ? "low_income_low_access_pct" : isBrfss ? "diabetes" : "dental_crudeprev"));
  const [profileGeography, setProfileGeography] = useState(() => new URLSearchParams(window.location.search).get("geography") || "auto");
  const [bbox, setBBox] = useState(null);
  const [mapZoom, setMapZoom] = useState(initialView.zoom);
  const [viewCenter, setViewCenter] = useState(initialView.center);
  const [copyStatus, setCopyStatus] = useState("");
  const [tractCapKey, setTractCapKey] = useState(null);
  const [page, setPage] = useState(0);
  const [mapData, setMapData] = useState(null);
  const [legend, setLegend] = useState(null);
  const [table, setTable] = useState(null);
  const [error, setError] = useState("");
  const [loadedKey, setLoadedKey] = useState(null);
  const [tableOpen, setTableOpen] = useState(() => typeof window === "undefined" || window.innerWidth > 700);
  const requestId = useRef(0);
  const viewportRef = useRef(null);
  const datasetKey = isBrfss ? "brfss" : isProfile ? "acs_profile" : isAcs ? "acs" : isAhrf ? "ahrf" : isClh ? "clh" : isAqi ? "aqi" : isGv ? "cmsgv" : isFea ? "usdafea" : "places";
  // Selection is state, not a Leaflet layer: the area layer is rebuilt on every viewport change.
  const [selection, setSelection] = useState(null);
  const [focusRequest] = useState(parseFocus);
  const [focusStatus, setFocusStatus] = useState("");
  const [map, setMap] = useState(null);
  const [baseMapId, setBaseMapId] = useState(BASE_MAP_OPTIONS[0].id);
  const [legendOpen, setLegendOpen] = useState(true);
  const [toolsOpen, setToolsOpen] = useState(() => typeof window === "undefined" || window.innerWidth > 1100);
  const focusedOnce = useRef(false);
  const baseMap = BASE_MAP_OPTIONS.find((option) => option.id === baseMapId) || BASE_MAP_OPTIONS[0];
  // Optional point overlay: its own release, filters, and requests; it never changes the area selection.
  const sites = useHealthCenterSites({ bbox, zoom: mapZoom });
  // Second, independent point overlay (EPA TRI). Both overlays may be shown together.
  const tri = useTriFacilities({ bbox, zoom: mapZoom });
  const homes = useNursingHomes({ bbox, zoom: mapZoom });

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/area/catalog${isProfile ? "?dataset_id=census_acs5_2024_community_profile" : isAcs ? "?dataset_id=census_acs5_2024_b19013" : isAhrf ? "?dataset_id=hrsa_ahrf_county_2024_2025" : isClh ? "?dataset_id=ahrq_clh_2023_curated" : isAqi ? `?dataset_id=${AQI_DATASET_ID}` : isGv ? `?dataset_id=${GV_DATASET_ID}` : isFea ? `?dataset_id=${FEA_DATASET_ID}` : isBrfss ? `?dataset_id=${BRFSS_DATASET_ID}` : ""}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(`Catalog unavailable (${response.status})`); return response.json(); })
      .then(setCatalog).catch((err) => { if (err.name !== "AbortError") setCatalogError(err.message); });
    return () => controller.abort();
  }, [isAcs, isProfile, isAhrf, isClh, isAqi, isGv, isFea, isBrfss]);

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
  const geography = isBrfss ? "state" : isProfile && ["state", "county", "tract", "cd"].includes(profileGeography) ? profileGeography
    : isAhrf || isAqi || isFea ? "county" : isGv ? gvGeography(mapZoom, catalog?.state_to_county_zoom) : areaGeography(mapZoom, isAcs || isProfile, tractSupported, tractCapExceeded);
  // One pixel at the current zoom, so shapes sharpen as the map zooms in; the server keeps shared borders identical.
  const simplify = gridForZoom(mapZoom);
  const dataSelection = useMemo(() => releaseId && measure ? {
    datasetId: catalog.dataset_id, releaseId, measure, valueType: catalog.value_type, geography,
  } : null, [releaseId, measure, catalog, geography]);
  const requestKey = useMemo(() => dataSelection && bbox
    ? String(pilotQuery(dataSelection, bbox, { simplify: String(simplify), limit: "100", offset: String(page * 100) }))
    : null, [dataSelection, bbox, page]);
  const onViewport = useCallback((next, zoomLevel, center) => {
    const key = `${next}|${zoomLevel}`;
    if (viewportRef.current === key) return;
    viewportRef.current = key;
    setBBox(next);
    setMapZoom(zoomLevel);
    setViewCenter(center);
    setPage(0);
  }, []);

  useEffect(() => {
    if (!bbox || !releaseId) return;
    const url = new URL(window.location.href);
    url.searchParams.set("measure_id", measureId);
    if (isProfile) url.searchParams.set("geography", profileGeography);
    url.searchParams.set("lat", viewCenter[0].toFixed(5));
    url.searchParams.set("lon", viewCenter[1].toFixed(5));
    url.searchParams.set("zoom", String(mapZoom));
    if (selection) url.searchParams.set("focus", `${selection.level}:${selection.geoid}`);
    else if (!focusRequest || focusedOnce.current) url.searchParams.delete("focus");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }, [bbox, releaseId, measureId, mapZoom, viewCenter, isProfile, profileGeography, selection?.level, selection?.geoid, focusRequest]);

  async function copyMapLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopyStatus("Map link copied.");
    } catch {
      setCopyStatus("Copy this page's URL from the address bar.");
    }
  }

  useEffect(() => {
    if (!dataSelection || !bbox) return;
    const controller = new AbortController();
    const id = ++requestId.current;
    const base = pilotQuery(dataSelection, bbox);
    const withMap = pilotQuery(dataSelection, bbox, { simplify: String(simplify) });
    const withTable = pilotQuery(dataSelection, bbox, { limit: "100", offset: String(page * 100) });
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
  }, [dataSelection, bbox, page, releaseId, requestKey, geography, capSelectionKey]);

  const ready = Boolean(requestKey && loadedKey === requestKey);
  const features = ready ? mapData?.features || [] : [];
  // Quintile cut points for the whole release at this level (PLACES, ACS income, AHRF, CLH).
  const cuts = useMemo(() => quantileCuts(ready ? legend?.quantile_breaks : null), [ready, legend]);
  const cutColors = rampColors(cuts.length + 1);
  const formatCut = (value) => isAcs ? dollars.format(value)
    : isAhrf ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)
    : isClh ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value)
    : `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)}%`;
  const zoom = initialView.zoom;
  const detailContext = useMemo(() => ({ geography, catalog, releaseId }), [geography, catalog, releaseId]);
  const dataKey = `${releaseId}|${measureId}|${geography}`;

  const zoomRange = useCallback((level) => focusZoomRange(level, {
    min: initialMapZoom(),
    stateBelow: isBrfss ? 12 : isGv ? (catalog?.state_to_county_zoom ?? ACS_COUNTY_ZOOM) : isAcs || (isProfile && profileGeography === "auto") ? ACS_COUNTY_ZOOM : null,
    countyFrom: isGv ? (catalog?.state_to_county_zoom ?? ACS_COUNTY_ZOOM) : isAcs || (isProfile && profileGeography === "auto") ? ACS_COUNTY_ZOOM : null,
    tractFrom: tractSupported && !(isProfile && profileGeography !== "auto") ? (isAcs || isProfile ? ACS_TRACT_ZOOM : PILOT_TRACT_ZOOM) : null,
  }), [isBrfss, isGv, isAcs, isProfile, profileGeography, tractSupported, catalog]);

  const fitArea = useCallback((bounds, level) => {
    if (!map || !bounds) return;
    const [west, south, east, north] = bounds;
    const box = [[south, west], [north, east]];
    const range = zoomRange(level);
    const fitted = typeof map.getBoundsZoom === "function" ? map.getBoundsZoom(box, false, [48, 48]) : range.max;
    const target = Math.min(range.max, Math.max(range.min, fitted));
    map.setView([(south + north) / 2, (west + east) / 2], target);
  }, [map, zoomRange]);

  // Search results and links from profile pages land here: fetch the area's box and outline, zoom, select.
  const focusArea = useCallback(async (level, geoid) => {
    setFocusStatus("Finding that place…");
    try {
      const response = await fetch(`${API_BASE}/community/area/${level}/${geoid}`);
      if (!response.ok) throw new Error(response.status === 404 ? "That place is not on the published boundary." : "That place could not be loaded right now.");
      const area = await response.json();
      setSelection({ level, geoid: area.geoid, name: area.name, bbox: area.bbox, geometry: area.geometry, properties: null, propsKey: null });
      fitArea(area.bbox, level);
      setFocusStatus("");
    } catch (failure) {
      setFocusStatus(failure.message);
    }
  }, [fitArea]);

  useEffect(() => {
    if (!map || !focusRequest || focusedOnce.current) return;
    focusedOnce.current = true;
    focusArea(focusRequest.level, focusRequest.geoid);
  }, [map, focusRequest, focusArea]);

  const clearSelection = useCallback(() => { setSelection(null); setFocusStatus(""); }, []);
  useEffect(() => {
    const onKey = (event) => { if (event.key === "Escape") clearSelection(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [clearSelection]);

  // Values for the selected area: the live feature when it is in view, else what was read when it was clicked.
  const liveFeature = selection && selection.level === geography
    ? features.find((feature) => featureId(feature.properties) === selection.geoid) ?? null : null;
  const liveSelected = liveFeature?.properties ?? null;
  // Outline the shape exactly as drawn when it is in view; otherwise the outline read with the selection.
  const outlineGeometry = liveFeature?.geometry ?? selection?.geometry ?? null;
  const selectedProps = liveSelected ?? (selection?.propsKey === dataKey ? selection.properties : null);
  const selectedDetails = selection && selectedProps && measure ? areaFeatureDetails(datasetKey, selectedProps, measure, detailContext) : null;
  const profileHref = profileHrefFor(selection);
  return <div className="app pilot-app">
    <Header />
    <main className="app-content pilot-content">
      <div className="map-wrapper pilot-map" aria-label={catalog && releaseId ? `${geography === "cd" ? "congressional district" : areaName(geography)} ${isBrfss ? "BRFSS" : isAcs || isProfile ? "ACS" : isClh ? "CLH" : isGv ? "CMS Original Medicare" : isFea ? "USDA Food Environment Atlas" : "pilot"} map` : undefined}>
        {catalog && releaseId && <MapContainer center={initialView.center} zoom={zoom} minZoom={initialMapZoom()} zoomSnap={0.25} zoomControl={false}
          maxBounds={[[-85, -180], [85, 180]]} maxBoundsViscosity={1} style={{ height: "100%", width: "100%" }}>
          <TileLayer key={baseMap.id} url={baseMap.url} attribution={baseMap.attribution} maxZoom={baseMap.maxZoom} />
          <ZoomControl position="bottomright" />
          <MapReady onReady={setMap} />
          <Viewport onChange={onViewport} />
          {features.length > 0 && <GeoJSON key={`${releaseId}:${measureId}:${geography}:${bbox}`} data={mapData} style={(feature) => isBrfss ? {
            color: "#516677", weight: 0.5,
            fillOpacity: feature.properties.status === "not_published" ? 0.35 : 0.85,
            dashArray: feature.properties.status === "not_published" ? "2 3" : null,
            fillColor: brfssColor(feature.properties.value, feature.properties.status, mapData?.legend_breaks),
          } : isFea ? {
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
            fillColor: isProfile ? color(feature.properties.value, feature.properties.status, mapData?.legend_breaks)
              : quintileColor(feature.properties.value, feature.properties.status, cuts),
          })} onEachFeature={(feature, layer) => {
            const item = feature.properties;
            // Same hover tooltip as the legacy map; skipped on touch pointers.
            if (!isCoarsePointer() && typeof layer.bindTooltip === "function") {
              layer.bindTooltip(areaTooltip(datasetKey, item, measure, detailContext), MAP_HOVER_TOOLTIP_OPTIONS);
            }
            layer.on?.("mouseover", () => layer.setStyle?.({ weight: 2, color: HOVER_LINE }));
            layer.on?.("mouseout", () => layer.setStyle?.({ weight: 0.5, color: "#516677" }));
            layer.on?.("click", () => {
              const box = typeof layer.getBounds === "function" ? layer.getBounds() : null;
              setSelection({
                level: geography, geoid: featureId(item), name: item.name, geometry: feature.geometry,
                bbox: box?.isValid?.() ? [box.getWest(), box.getSouth(), box.getEast(), box.getNorth()] : null,
                properties: item, propsKey: dataKey,
              });
              setFocusStatus("");
            });
          }} />}
          <Pane name="area-selection" style={{ zIndex: 450, pointerEvents: "none" }}>
            {selection && outlineGeometry && <>
              <GeoJSON key={`casing:${selection.level}:${selection.geoid}:${liveFeature ? requestKey : "read"}`} data={outlineGeometry} interactive={false} pane="area-selection"
                style={{ color: SELECTION_CASING, weight: 6, opacity: 0.95, fill: false }} />
              <GeoJSON key={`line:${selection.level}:${selection.geoid}:${liveFeature ? requestKey : "read"}`} data={outlineGeometry} interactive={false} pane="area-selection"
                style={{ color: SELECTION_LINE, weight: 3, opacity: 1, fill: false }} />
            </>}
          </Pane>
          {sites.enabled && <HealthCenterSiteLayer sites={sites} />}
          {tri.enabled && <TriFacilityLayer tri={tri} />}
          {homes.enabled && <NursingHomeLayer homes={homes} />}
        </MapContainer>}
      </div>
      <section className="pilot-panel pilot-controls" aria-label="Analytical controls">
        <h1>{isBrfss ? "BRFSS state survey estimates" : isProfile ? "ACS 2020–2024 community characteristics" : isAcs ? "ACS 2020–2024 5-year income" : isAhrf ? "AHRF 2023 county resources" : isClh ? "AHRQ CLH community conditions" : isAqi ? "EPA annual AQI by county, 2025" : isGv ? "CMS Original Medicare Geographic Variation, 2024" : isFea ? "USDA Food Environment Atlas: county food access and retailers" : "PLACES 2025 pilot"}</h1>
        {isBrfss ? <div className="pilot-scope">
          <p>CDC BRFSS crude prevalence is a direct state survey estimate, 2023 except dental visits (2022). State values are not computed from PLACES counties. PLACES county figures are modeled from the survey and serve a different geography.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">{(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}</ul>
        </div> : isFea ? <div className="pilot-scope">
          <p>Five published county measures from USDA ERS's Food Environment Atlas, {catalog?.release_label ?? "July 2025"} release. <strong>Each measure has its own observation year (2018–2023)</strong>; none describes 2025 or current conditions. USDA publishes no state value for these measures, so counties are shown at every zoom and none is averaged or summed. No tract values exist.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">
            {(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div> : isGv ? <div className="pilot-scope">
          <p>Published CMS values for the Original Medicare (fee-for-service) population with Part A and Part B, all ages. Medicare Advantage enrollees are excluded. Observation year {catalog?.observation_year ?? "2024"}; source release “{catalog?.source_release_id ?? "OM GV PUF May 2026 update"}”. States are shown at broad zoom and counties from zoom {catalog?.state_to_county_zoom ?? ACS_COUNTY_ZOOM}. No tract values exist.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">
            {(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div> : isAqi ? <div className="pilot-scope">
          <p>EPA AirData annual summary of daily Air Quality Index values for calendar year 2025, from the file EPA generated on 2026-06-25. County values only; no state or tract values are derived.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">
            {(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div> : <p className="pilot-scope">{isProfile ? "Census Bureau published community characteristics for states, counties, tracts, and 119th Congress districts. The percentages and 90% margins of error come from ACS 2020–2024 subject tables; population totals may have no sampling margin." : isAcs ? "Published median household income for states, counties, and census tracts. Values are 2024 inflation-adjusted dollars; margins of error use 90% confidence." : isAhrf ? "HRSA AHRF 2024–2025 release, with 2023 observations. County counts only; no state or tract values are inferred. Connecticut planning-region values are unavailable for four measures. Uncertainty was not supplied." : isClh ? "AHRQ CLH September 2025 release. ACS measures cover 2019–2023 at county and tract levels; business densities describe 2023 counties only. No state estimates or uncertainty fields are supplied." : "Official county and census tract estimates. No state estimates are provided by this pilot."}</p>}
        <label>Data source <select value={isBrfss ? "brfss" : isProfile ? "acs_profile" : isAcs ? "acs" : isAhrf ? "ahrf" : isClh ? "clh" : isAqi ? "aqi" : isGv ? "cmsgv" : isFea ? "usdafea" : "pilot"} onChange={(event) => { const paths = { brfss: "/area/brfss", acs: "/area/acs-2024", acs_profile: "/area/acs-community", ahrf: "/area/ahrf", clh: "/area/clh", aqi: "/area/epa-aqi", cmsgv: "/area/cms-gv", usdafea: "/area/usda-fea", pilot: "/area/places-2025" }; window.location.assign(paths[event.target.value]); }}>
          <option value="pilot">PLACES 2025 county and tract pilot</option><option value="brfss">BRFSS state survey estimates</option><option value="acs">ACS 2020–2024 5-year income</option><option value="acs_profile">ACS 2020–2024 community characteristics</option><option value="ahrf">AHRF 2023 workforce and hospitals</option><option value="clh">AHRQ CLH community conditions</option><option value="aqi">EPA annual AQI by county (2025)</option><option value="cmsgv">CMS Original Medicare 2024 (states and counties)</option><option value="usdafea">USDA Food Environment Atlas (county measures)</option>
        </select></label>
        {catalogError && <p role="alert">{catalogError}</p>}
        {!catalog && !catalogError && <p role="status">Loading catalog…</p>}
        {catalog && !releaseId && <p role="status">The first {isAcs ? "ACS" : "county"} candidate is awaiting supervised review and publication. No {isAcs ? "ACS" : "pilot"} map is published yet.</p>}
        {catalog && releaseId && <>
          <label>Measure <select value={measureId} onChange={(event) => { setMeasureId(event.target.value); setPage(0); }}>
            {catalog.measures.map((item) => <option key={item.measure_id} value={item.measure_id}>{item.label} ({item.observation_period})</option>)}
          </select></label>
          {isProfile && <label>Geography <select value={profileGeography} onChange={(event) => { setProfileGeography(event.target.value); setPage(0); }}>
            <option value="auto">Automatic by zoom</option><option value="state">State</option><option value="county">County</option><option value="tract">Census tract</option><option value="cd">119th Congress district</option>
          </select></label>}
          {isFea && <div className="pilot-fea-measure">
            <p className="pilot-period"><strong>Observation year {measure?.observation_period}</strong> · {measure?.unit} · county values only</p>
            <p className="pilot-metadata">USDA definition ({measure?.variable_code}): {measure?.official_definition}</p>
            <p className="pilot-metadata">Denominator: {measure?.denominator} {measure?.interpretation}</p>
            <p className="pilot-metadata">Contributing sources: {measure?.contributing_sources} County boundary basis in the source: {measure?.source_boundary_basis}; joined by exact FIPS to {catalog.boundary_vintage}. Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">USDA ERS Food Environment Atlas</a> (<a href={catalog.documentation_url} target="_blank" rel="noreferrer">documentation</a>).</p>
            {mapZoom < ACS_COUNTY_ZOOM && <p role="status">State values are not published for this measure; counties are shown at the national view.</p>}
          </div>}
          {!isFea && <p className="pilot-metadata">{geography === "cd" ? "Congressional district" : areaName(geography)} estimates · {isClh || isProfile ? "Observation period" : "Observation year"} {measure?.observation_period} · {measure?.population} · {isBrfss || isProfile || isAhrf || isClh || isAqi || isGv ? measure?.unit : catalog.unit}{isAcs ? " · ACS 5-year Detailed Tables" : isProfile ? " · Census Bureau ACS 5-year Subject Tables" : ""}</p>}
          {isBrfss && <p className="pilot-metadata">CDC BRFSS definition: {measure?.official_definition} {measure?.interpretation} Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">BRFSS Prevalence Data</a>.</p>}
          {isProfile && <p className="pilot-metadata">Source: <a href={catalog.landing_page} target="_blank" rel="noreferrer">Census Bureau ACS 2020–2024</a> · {measure?.official_definition}. {measure?.interpretation}</p>}
          {isAhrf && <p className="pilot-metadata">Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">HRSA Area Health Resources Files</a>, compiled from {measure?.source}. These underlying data are copyright of that organization and are shown here with attribution. Counts have no published uncertainty estimate.</p>}
          {isGv && <p className="pilot-metadata">CMS definition ({measure?.source_field}): {measure?.official_definition} Denominator: {measure?.denominator} {measure?.interpretation} Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">CMS Medicare Geographic Variation</a>.</p>}
          {isAqi && <p className="pilot-metadata">EPA definition: {measure?.official_definition} {measure?.statistic_note} Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">EPA AirData pre-generated files</a>.</p>}
          {isClh && <p className="pilot-metadata">Distributed by <a href={catalog.source_url} target="_blank" rel="noreferrer">AHRQ CLH</a>; contributing source: {measure?.source}. {measure?.denominator} denominator. Blanks remain missing; no uncertainty estimate is supplied.</p>}
          {isGv && wantsTracts && <p role="status">County values remain displayed. CMS publishes no tract estimates for this product.</p>}
          {isFea && wantsTracts && <p role="status">County values remain displayed. USDA publishes no tract values for these measures, and none is estimated.</p>}
          {!isGv && !isFea && !isBrfss && wantsTracts && !tractSupported && <p role="status">County estimates remain displayed; no tract estimate is published for this release.</p>}
          {isBrfss && <p role="status">State estimates remain displayed at every zoom. BRFSS has no county or tract values in this release.</p>}
          {wantsTracts && tractCapExceeded && <p role="status">This viewport contains more than 5,000 tracts. County estimates remain displayed; zoom in for tracts.</p>}
          <p className="pilot-release">Release {releaseId}</p>
          <div className="pilot-share"><button type="button" onClick={copyMapLink}>Copy map link</button><span role="status">{copyStatus}</span></div>
        </>}
      </section>
      {catalog && releaseId && <>
        <section className={`pilot-panel pilot-legend ${legendOpen ? "" : "is-minimized"}`} aria-label="Legend">
          <button type="button" className="pilot-panel-toggle" aria-label={legendOpen ? "Minimize legend" : "Expand legend"} aria-expanded={legendOpen} onClick={() => setLegendOpen((open) => !open)}>{legendOpen ? "\u2212" : "+"}</button>
          <h2>{isAcs ? "Median household income" : isBrfss || isProfile || isAhrf || isClh || isAqi || isGv || isFea ? measure?.label : "Crude prevalence"}{isFea ? `, ${measure?.observation_period ?? ""}` : ""} — {geography === "cd" ? "congressional district" : areaName(geography)} level</h2>
          {legendOpen && <>
          {ready && legend && isBrfss ? <>
            <ul className="pilot-swatches">
              {prevalenceColors.map((shade, i) => <li key={shade}><i style={{ background: shade }} />{i === 0 ? `Under ${measure?.legend_breaks?.[0]}%` : i === 4 ? `${measure?.legend_breaks?.[3]}% or more` : `${measure?.legend_breaks?.[i - 1]}% to under ${measure?.legend_breaks?.[i]}%`}</li>)}
              <li><i style={{ background: "#a5a5a5" }} />Not published by CDC for this state and year</li>
              <li><i style={{ background: "#8f6b74" }} />Suppressed</li>
            </ul>
            <p>Direct state survey crude prevalence. Fixed display classes; select a state to see its 95% confidence interval and response count below.</p>
            <p>{legend.statuses.map((item) => `${item.status_text || item.status}: ${item.n}`).join(" · ")}</p>
          </> : ready && legend && isProfile ? <>
            <ul className="pilot-swatches">
              {prevalenceColors.map((shade, i) => <li key={shade}><i style={{ background: shade }} />{i === 0 ? `Under ${profileValue({ value: legend.legend_breaks?.[0] }, measure)}` : i === 4 ? `${profileValue({ value: legend.legend_breaks?.[3] }, measure)} or more` : `${profileValue({ value: legend.legend_breaks?.[i - 1] }, measure)} to under ${profileValue({ value: legend.legend_breaks?.[i] }, measure)}`}</li>)}
              <li><i style={{ background: "#d8dee3" }} />Missing</li><li><i style={{ background: "#8f6b74" }} />Suppressed</li>
            </ul>
            <p>Source-published {geography === "cd" ? "119th Congress district" : areaName(geography)} estimates. Fixed display classes; select an area to see its 90% margin of error below. No county or tract value is used to calculate a district estimate.</p>
            <p>{legend.statuses.map(item => `${item.status_text || item.status}: ${item.n}`).join(" · ")}</p>
          </> : ready && legend && isFea ? <>
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
            <p>{measure?.kind === "aqi_index" ? "AQI index values in the standard CHIP blue scale. These annual statistics are not daily AQI health categories, so EPA's category colors are not used." : "Day counts. Read them against each county's Days with AQI; they are not percentages."}</p>
            <p>{legend.statuses.map((item) => `${item.status === AQI_NO_VALUE ? "no reported value" : item.status.replace("_", " ")}: ${item.n}`).join(" · ")}</p>
            {legend.statuses.some((item) => item.days_low != null) && <p>Days with AQI in view: {Math.min(...legend.statuses.filter((item) => item.days_low != null).map((item) => item.days_low))}–{Math.max(...legend.statuses.filter((item) => item.days_high != null).map((item) => item.days_high))}.</p>}
            <p>Select a county for its value, Days with AQI, and EPA source name.</p>
          </> : ready && legend ? <>
            <ul className="pilot-swatches">
              {cuts.length ? quantileLabels(cuts, formatCut).map((label, i) => <li key={label}><i style={{ background: cutColors[i] }} />{label}{isAhrf || isClh ? ` ${measure?.unit}` : ""}</li>)
                : <li><i style={{ background: prevalenceColors[2] }} />Published value</li>}
              {isAcs ? <>
                <li><i style={{ background: "#6d3b9e" }} />Open-ended median</li>
                <li><i style={{ background: "#d8dee3" }} />Missing estimate</li>
                <li><i style={{ background: "#8f6b74" }} />Suppressed estimate</li>
                <li><i style={{ background: "#c4b4d4" }} />Not applicable</li>
              </> : isAhrf || isClh ? <><li><i style={{ background: "#d8dee3" }} />Missing source value</li><li><i style={{ background: "#8f6b74" }} />Suppressed</li></> : <><li><i style={{ background: "#a5a5a5" }} />Not published</li><li><i style={{ background: "#d8dee3" }} />Missing or suppressed</li></>}
            </ul>
            {cuts.length > 0 && <p>Classes are quintiles of all published {areaName(geography)} values in this release, so each holds about a fifth of them and the colors do not change as the map moves.</p>}
            <p>In view: {legend.statuses.map((item) => `${item.status}: ${item.n}`).join(" · ")}</p>
            <p>Click a {areaName(geography)} for its value and {isAcs ? "90% margin of error" : isAhrf || isClh ? "source status" : "95% confidence interval"}. {isAcs ? "Open-ended medians use the published annotation." : isAhrf || isClh ? "Uncertainty was not supplied." : ""}</p>
          </> : <p>{error ? "Data unavailable" : "Loading legend…"}</p>}
          {selection && <div className="pilot-selected" data-testid="selected-area">
            <h3>Selected area</h3>
            <p className="pilot-selected-name">{areaTitle(selection.name, selection.level, selection.geoid)}</p>
            {selectedDetails ? <>
              <p className="pilot-selected-value">{selectedDetails.measure}: <strong>{selectedDetails.value}</strong></p>
              {selectedDetails.lines.map((line) => <p key={line}>{line}</p>)}
            </> : selection.level !== geography
              ? <p>The map is showing {geography === "cd" ? "congressional district" : areaName(geography)} values here. No {selection.level === "cd" ? "district" : areaName(selection.level)} value is shown for this measure at this zoom, and none is calculated from the areas inside it.</p>
              : <p>{ready ? "This area is outside the current view. Use Zoom to selected area." : "Loading the selected area…"}</p>}
            {profileHref && <p><a href={profileHref}>Open {selection.level === "cd" ? "district briefing" : `${areaName(selection.level)} profile`} →</a></p>}
          </div>}
          </>}
        </section>
        <div className="pilot-dock">
        <section className={`pilot-panel pilot-tools ${toolsOpen ? "is-open" : ""}`} aria-label="Map tools and search">
          <button type="button" className="pilot-tools-toggle" aria-expanded={toolsOpen} onClick={() => setToolsOpen((open) => !open)}>
            <span>Map Tools</span><span aria-hidden="true">{toolsOpen ? "\u2212" : "+"}</span>
          </button>
          {toolsOpen && <>
            <MapTools map={map} home={initialView} hasSelection={Boolean(selection)}
              zoomToSelectedLabel={selection ? `Zoom to selected ${selection.level === "cd" ? "district" : areaName(selection.level)}` : "Zoom to selected area"}
              onZoomToSelected={() => selection?.bbox && fitArea(selection.bbox, selection.level)} onClearSelection={clearSelection}
              profileHref={profileHref} profileLabel={selection?.level === "cd" ? "Open district briefing" : "Open profile"}
              profileDisabledReason={selection?.level === "tract" ? "Tracts have no profile page" : "Select a county, state, or district first"}
              baseMapId={baseMapId} onBaseMapChange={setBaseMapId} />
            <PlaceSearch variant="map" label="Find a county or state on the map" submitLabel="Zoom to place"
              onSelect={(place) => focusArea(place.type, place.geoid)} />
            {focusStatus && <p className="pilot-focus-status" role="status">{focusStatus}</p>}
          </>}
        </section>
        <section className={`pilot-panel pilot-table ${tableOpen ? "is-open" : ""}`} aria-label={`${areaName(geography)} table`}>
          <button className="pilot-table-toggle" type="button" aria-expanded={tableOpen} onClick={() => setTableOpen((open) => !open)}>
            <span>Displayed {areaName(geography)} values{ready && table ? ` (${table.total})` : ""}</span><span aria-hidden="true">{tableOpen ? "−" : "+"}</span>
          </button>
          {tableOpen && <div className="pilot-table-body">
            {error && <p role="alert">{error}</p>}
            {!ready && !error && <p role="status">Loading selected {areaName(geography)} estimates…</p>}
            {ready && table && <>
              <p>{areaName(geography)} areas intersecting the map viewport. Map and table use the same geometry rule.{isBrfss ? " States without a CDC result for this year are marked Not published." : isFea ? " All 2024 boundary counties in view are listed with USDA's published value and status." : isAqi ? " All 2024 boundary counties are listed; counties without an EPA summary are marked No reported value." : isGv ? ` All 2024 boundary ${geography === "state" ? "states" : "counties"} in view are listed with CMS's published value and status.` : ""}</p>
              <div className="pilot-table-scroll"><table><caption>{measure?.label}, {measure?.observation_period}; release {releaseId}</caption>
                {isBrfss ? <thead><tr><th scope="col">State FIPS</th><th scope="col">State</th><th scope="col">{measure?.label} (%)</th><th scope="col">95% CI</th><th scope="col">Response count</th><th scope="col">Status</th></tr></thead>
                : isFea ? <thead><tr><th scope="col">County FIPS</th><th scope="col">County</th><th scope="col">{measure?.label} ({measure?.observation_period})</th><th scope="col">USDA source value</th><th scope="col">Status</th></tr></thead>
                : isGv ? <thead><tr><th scope="col">{geography === "state" ? "State FIPS" : "County FIPS"}</th><th scope="col">{areaName(geography)}</th><th scope="col">{measure?.label}</th><th scope="col">CMS source value</th><th scope="col">Status</th></tr></thead>
                : isAqi ? <thead><tr><th scope="col">County FIPS</th><th scope="col">County</th><th scope="col">{measure?.label} ({measure?.unit})</th><th scope="col">Days with AQI</th><th scope="col">EPA source name</th><th scope="col">Status</th></tr></thead>
                : <thead><tr><th scope="col">{geography === "cd" ? "District GEOID" : geography === "tract" ? "Tract GEOID" : geography === "state" ? "State FIPS" : "County FIPS"}</th><th scope="col">{geography === "cd" ? "District" : areaName(geography)}</th><th scope="col">{isProfile ? `Value (${measure?.unit})` : isAcs ? "Value (2024 USD)" : isAhrf || isClh ? `Value (${measure?.unit})` : "Value (%)"}</th><th scope="col">{isProfile || isAcs ? "90% MOE" : isAhrf || isClh ? "Uncertainty" : "95% CI"}</th><th scope="col">Status</th></tr></thead>}
                <tbody>{table.rows.map((row) => {
                  const key = row.geography_id || row.tract_fips || row.county_fips;
                  if (isBrfss) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{brfssValueText(row)}</td><td>{row.ci_low == null ? "—" : `${row.ci_low}–${row.ci_high}%`}</td><td>{row.sample_size ?? "—"}</td><td>{row.status_text || row.status}</td></tr>;
                  if (isFea) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{feaValueText(row, measure)}</td><td>{row.source_value ?? "—"}</td><td>{row.status === "available" ? "Published value" : row.status === "true_zero" ? "Published zero" : FEA_STATUS_TEXT[row.status] ?? row.status}</td></tr>;
                  if (isGv) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{gvValueText(row, measure)}</td><td>{row.source_value ?? "—"}</td><td>{GV_STATUS_TEXT[row.status] ?? row.status}</td></tr>;
                  if (isAqi) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{aqiValueText(row, measure)}</td><td>{row.days_with_aqi ?? "—"}</td><td>{row.source_name ?? "—"}</td><td>{row.status === AQI_NO_VALUE ? "No reported value" : row.status}</td></tr>;
                  return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{isProfile ? profileValue(row, measure) : displayValue(row, isAcs, isAhrf, isClh, measure?.unit)}</td><td>{isProfile ? profileUncertainty(row) : displayUncertainty(row, isAcs, isAhrf, isClh)}</td><td>{row.status_text || row.status}</td></tr>;
                })}</tbody>
              </table></div>
              {isBrfss && table.reference?.median?.find((item) => item.geography_id === "98") && <p className="pilot-metadata">Median of states and DC (CDC-published reference, not a national estimate): {brfssValueText(table.reference.median.find((item) => item.geography_id === "98"))}. No confidence interval is published for this median.</p>}
              <nav aria-label={`${areaName(geography)} table pages`}><button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button> Page {page + 1} of {Math.max(1, Math.ceil(table.total / 100))} <button disabled={(page + 1) * 100 >= table.total} onClick={() => setPage(page + 1)}>Next</button></nav>
            </>}
          </div>}
        </section>
        </div>
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
