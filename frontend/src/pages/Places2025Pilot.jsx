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
import MobileMapPanels from "../components/MobileMapPanels";
import { LegendSkeleton, MapLoadingOverlay, MapLoadingStrip } from "../components/MapLoading";
import { BASE_MAP_OPTIONS } from "../branding/baseMaps";
import { BLUES, HOVER_LINE, SELECTION_CASING, SELECTION_LINE, quantileColor, quantileCuts, quantileLabels, rampColors } from "../branding/mapColors";
import { gridForZoom } from "../utils/mapGrid";
import { MAP_HOVER_TOOLTIP_OPTIONS, areaTooltipHtml, isCoarsePointer } from "../utils/mapTooltip";
import SviQuartileBar, {
  SVI_LEVELS,
  SVI_NO_DATA_COLOR,
  SVI_RANGE_TEXT,
  SVI_STATES,
  SVI_THEMES,
  SVI_UNAVAILABLE_MESSAGE,
  normalizeSviStateParam,
  sviCountyHeading,
  sviFormatValue,
  sviIsMissing,
  sviLevel,
  sviLevelIndex,
  sviPaletteColor,
  sviPanelRankTitle,
  sviStateAbbrForGeoid,
  sviStateByFips,
  sviThemeForMeasure,
} from "../components/SviQuartileBar";
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

export const HDS_MORTALITY_DATASET_ID = "cdc_hds_mortality_2022_2024";
export const HDS_STATUS_COLORS = { suppressed: "#8f6b74", not_in_release: "#ffffff" };
export const HDS_STATUS_TEXT = {
  suppressed: "Insufficient data (CDC Heart Disease and Stroke Atlas)",
  not_in_release: "No row in this release",
};
export function hdsNumber(value) {
  if (value == null) return "—";
  return `${gvDecimal.format(value)} per 100,000`;
}
export function hdsValueText(item) {
  if (HDS_STATUS_TEXT[item?.status] || item?.value == null) {
    return item?.status_text || HDS_STATUS_TEXT[item?.status] || item?.status || "Unavailable";
  }
  return hdsNumber(item.value);
}
export function hdsColor(value, status, cuts = []) {
  if (HDS_STATUS_COLORS[status]) return HDS_STATUS_COLORS[status];
  if (value == null) return "#d8dee3";
  return quintileColor(value, status, cuts);
}

export const SVI_DATASET_ID = "cdc_svi_2022";
export const SVI_STATUS_COLORS = { not_available: SVI_NO_DATA_COLOR, not_in_release: SVI_NO_DATA_COLOR };
export const SVI_STATUS_TEXT = {
  not_available: "Not ranked by CDC (−999 in the source file)",
  not_in_release: "No row in this SVI release",
};
export const SVI_DC_SWITCH_MESSAGE = "There is no State comparison data for county, switched to census.";
export const SVI_CHOOSE_STATE_MESSAGE = "Choose a state to see statewide rankings.";
export const SVI_OUTSIDE_STATE_MESSAGE = "Outside the selected state";
export const SVI_STATE_DISABLED_HINT = "Switch Geographic Comparison to Statewide to select a state/district/territory";
export const SVI_COMPARISON_TOOLTIP = "Toggle to view nationwide or statewide data comparison level";
export { SVI_LEVELS, SVI_THEMES, SVI_STATES, SVI_UNAVAILABLE_MESSAGE, sviLevel, sviLevelIndex, sviThemeForMeasure };

export function sviIsInSelectedState(geoid, selectedState) {
  const stateFips = String(selectedState || "").trim();
  if (!stateFips) return false;
  return String(geoid || "").trim().startsWith(stateFips);
}
export function filterSviStateFeatures(features, selectedState) {
  if (!Array.isArray(features) || !selectedState) return [];
  return features.filter((feature) => sviIsInSelectedState(featureId(feature?.properties), selectedState));
}
export function summarizeSviStatuses(rows) {
  const byStatus = new Map();
  for (const row of rows || []) {
    const status = row?.status || "not_in_release";
    const existing = byStatus.get(status) || {
      status,
      n: 0,
      low: null,
      high: null,
      ...(row?.status_text
        ? { status_text: row.status_text }
        : SVI_STATUS_TEXT[status]
          ? { status_text: SVI_STATUS_TEXT[status] }
          : {}),
    };
    existing.n += 1;
    if (row?.value != null && Number.isFinite(Number(row.value))) {
      const num = Number(row.value);
      existing.low = existing.low == null ? num : Math.min(existing.low, num);
      existing.high = existing.high == null ? num : Math.max(existing.high, num);
    }
    byStatus.set(status, existing);
  }
  return [...byStatus.values()].sort((a, b) => a.status.localeCompare(b.status));
}
export function sanitizeSviStateMapData(data, selectedState) {
  if (!data?.features || !selectedState) return data;
  return {
    ...data,
    features: data.features.map((feature) => {
      const props = feature?.properties || {};
      if (sviIsInSelectedState(featureId(props), selectedState)) return feature;
      return {
        ...feature,
        properties: {
          ...props,
          value: null,
          source_value: null,
          status: "outside_selected_state",
          status_text: SVI_OUTSIDE_STATE_MESSAGE,
        },
      };
    }),
  };
}

export function sviNumber(value) {
  return sviFormatValue(value);
}
export function sviValueText(item) {
  if (sviIsMissing(item?.value, item?.status)) {
    return item?.status_text || SVI_STATUS_TEXT[item?.status] || SVI_STATUS_TEXT.not_available;
  }
  return sviNumber(item.value);
}
export function sviColor(value, status, measureIdOrBreaks = "rpl_themes") {
  const measureId = typeof measureIdOrBreaks === "string" ? measureIdOrBreaks : "rpl_themes";
  return sviPaletteColor(value, status, measureId);
}
export function sviBinLabels() {
  return SVI_LEVELS.map((level) => `${level.label} (${level.range})`);
}
export function sviFeatureStyle(feature, { scope = "us", selectedState = "", measureId = "rpl_themes" } = {}) {
  const props = feature?.properties || {};
  if (scope === "state" && !selectedState) {
    return { color: "#b0bec5", weight: 0.5, opacity: 0.85, fill: false, fillOpacity: 0, fillColor: "transparent", dashArray: null };
  }
  const geoid = featureId(props);
  if (scope === "state" && selectedState && (!sviIsInSelectedState(geoid, selectedState) || props.status === "outside_selected_state")) {
    return { color: "#b0bec5", weight: 0.5, opacity: 0.85, fill: true, fillOpacity: 0, fillColor: "transparent", dashArray: null };
  }
  const idx = sviLevelIndex(props.value, props.status);
  if (idx < 0) {
    return {
      color: "#555555",
      weight: 0.6,
      fill: true,
      fillOpacity: props.status === "not_in_release" ? 0.35 : 0.7,
      dashArray: props.status === "not_in_release" ? "2 3" : null,
      fillColor: SVI_NO_DATA_COLOR,
    };
  }
  return {
    color: "#555555",
    weight: idx === 0 ? 1 : 0.6,
    fill: true,
    fillOpacity: 0.88,
    dashArray: null,
    fillColor: sviPaletteColor(props.value, props.status, measureId),
  };
}
export function clipBboxToState(viewportBbox, stateBounds) {
  if (!stateBounds || stateBounds.length !== 4) return viewportBbox;
  const [sW, sS, sE, sN] = stateBounds.map(Number);
  if (![sW, sS, sE, sN].every(Number.isFinite) || sE - sW > 180) return viewportBbox;
  const padLon = Math.max(0.05, (sE - sW) * 0.05);
  const padLat = Math.max(0.05, (sN - sS) * 0.05);
  const pW = Math.max(-180, sW - padLon);
  const pE = Math.min(180, sE + padLon);
  const pS = Math.max(-90, sS - padLat);
  const pN = Math.min(90, sN + padLat);
  if (!viewportBbox) return [pW, pS, pE, pN].join(",");
  const [vW, vS, vE, vN] = viewportBbox.split(",").map(Number);
  const iW = Math.max(vW, pW);
  const iS = Math.max(vS, pS);
  const iE = Math.min(vE, pE);
  const iN = Math.min(vN, pN);
  return iW < iE && iS < iN ? [iW, iS, iE, iN].join(",") : [pW, pS, pE, pN].join(",");
}
export function sviScopeForMeasure(measureId) {
  return String(measureId || "").endsWith("_state") ? "state" : "us";
}
export function swapSviMeasureScope(measureId, targetScope) {
  const base = String(measureId || "rpl_themes").replace(/_state$/, "");
  return targetScope === "state" ? `${base}_state` : base;
}

export const NRI_DATASET_ID = "fema_nri_v120";
const nriColors = BLUES;
export const NRI_STATUS_COLORS = { not_available: "#d8dee3", not_in_release: "#ffffff" };
export const NRI_STATUS_TEXT = {
  not_available: "Not published by FEMA for this area",
  not_in_release: "No row in this FEMA NRI release",
};
const nriScoreFmt = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 2 });
const nriFactorFmt = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 3 });
export function nriNumber(value, kind) {
  if (value == null) return "—";
  if (kind === "currency") return dollars.format(value);
  if (kind === "factor") return nriFactorFmt.format(value);
  return nriScoreFmt.format(value);
}
export function nriValueText(item, measure) {
  if (NRI_STATUS_TEXT[item.status] || item.value == null) {
    if (item.status_text) return item.status_text;
    const base = NRI_STATUS_TEXT[item.status] || NRI_STATUS_TEXT.not_available;
    return item.status === "not_available" && item.rating ? `${base} (${item.rating})` : base;
  }
  return nriNumber(item.value, measure?.kind);
}
export function nriColor(value, status, breaks = [20, 40, 60, 80]) {
  if (NRI_STATUS_COLORS[status]) return NRI_STATUS_COLORS[status];
  if (value == null) return NRI_STATUS_COLORS.not_available;
  const index = breaks.findIndex((upper) => value < upper);
  return nriColors[index < 0 ? nriColors.length - 1 : index];
}
export function nriBinLabels(breaks = [20, 40, 60, 80], kind = "score") {
  if (!breaks.length) return [];
  const lastSuffix = kind === "score" || kind === "percentile" ? " to 100" : " or more";
  return [
    `Under ${nriNumber(breaks[0], kind)}`,
    ...breaks.slice(1).map((upper, i) => `${nriNumber(breaks[i], kind)} to under ${nriNumber(upper, kind)}`),
    `${nriNumber(breaks[breaks.length - 1], kind)}${lastSuffix}`,
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

function bboxIntersects(first, second) {
  if (!first || !second) return false;
  const [west, south, east, north] = typeof first === "string" ? first.split(",").map(Number) : first;
  const [otherWest, otherSouth, otherEast, otherNorth] = second;
  return west <= otherEast && east >= otherWest && south <= otherNorth && north >= otherSouth;
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
    period: selection.period ?? selection.measure.observation_period,
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
  hds_mortality:
    "Age-adjusted death rate for adults 35 and older (per 100,000); county rates are spatially smoothed by CDC, while state and national rates are not smoothed.",
  svi: "CDC/ATSDR percentile rank (0–1) among all U.S. areas, not a rate; higher values indicate greater vulnerability.",
  nri: "FEMA National Risk Index v1.20; higher risk, loss, and social vulnerability are worse, higher community resilience is better.",
  usdafea: "USDA Food Environment Atlas county measure.",
};
export function featureId(item) { return String(item?.geography_id ?? item?.tract_fips ?? item?.county_fips ?? ""); }
export function areaTitle(name, level, geoid) { return `${name || "Unnamed area"} · ${LEVEL_TITLES[level] || "Area"} ${geoid}`; }

// One description of a mapped area, used by the hover tooltip and the legend's selected-area block.
// Plain text only: React escapes it in the legend and the tooltip builder escapes it for Leaflet.
export function areaFeatureDetails(dataset, item, measure, context = {}) {
  const { geography = "county", catalog = null, releaseId = null } = context;
  const period = context.period ?? measure?.observation_period;
  const base = { area: areaTitle(item.name, geography, featureId(item)), measure: measure?.label, period,
    explanation: dataset === "acs" && period !== measure?.observation_period ? `Census Bureau ACS 5-year estimate, ${String(period).slice(-4)} dollars.` : EXPLANATIONS[dataset] || EXPLANATIONS.places };
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
  } else if (dataset === "hds_mortality") {
    value = hdsValueText(item);
    lines = [
      `${period} · ${catalog?.population_label ?? "Adults aged 35 and older"}`,
      geography === "county"
        ? "Age-adjusted, spatially smoothed 3-year average rate (county)."
        : "Age-adjusted 3-year average rate (state; not smoothed).",
      item.source_value != null ? `CDC source value: ${item.source_value}` : null,
      "No confidence interval or margin of error is published.",
    ];
  } else if (dataset === "svi") {
    const isStateRank = measure?.source_scope === "state" || sviScopeForMeasure(measure?.measure_id) === "state";
    if (context.sviScope === "state" && (!context.sviState || !sviIsInSelectedState(featureId(item), context.sviState) || item.status === "outside_selected_state")) {
      const msg = context.sviState ? SVI_OUTSIDE_STATE_MESSAGE : SVI_CHOOSE_STATE_MESSAGE;
      base.explanation = msg;
      value = msg;
      lines = [msg];
    } else {
      const rankLabel = measure?.population_by_level?.[geography]
        ?? (isStateRank
          ? (geography === "tract" ? "Rank among census tracts in the same state" : "Rank among counties in the same state")
          : (catalog?.population_by_level?.[geography] ?? (geography === "tract" ? "Rank among all U.S. census tracts" : "Rank among all U.S. counties")));
      base.explanation = isStateRank
        ? "CDC/ATSDR within-state percentile rank (0–1), not a rate; colors compare areas only within their own state."
        : "CDC/ATSDR U.S.-wide percentile rank (0–1), not a rate; higher values indicate greater vulnerability.";
      const level = sviLevel(item.value, item.status);
      value = sviValueText(item);
      lines = [
        level ? `Level of vulnerability: ${level.label} (${level.phrase})` : SVI_UNAVAILABLE_MESSAGE,
        `${period} · ${rankLabel}`,
        item.source_value != null ? `CDC SVI source value: ${item.source_value}` : null,
        isStateRank
          ? "Within-state percentile rank (0–1). Colors compare areas only within their own state. No uncertainty is published."
          : "U.S.-wide percentile rank (0–1), not a rate. No confidence interval or margin of error is published.",
      ];
    }
  } else if (dataset === "nri") {
    const higherBetter = measure?.direction === "higher_better";
    base.explanation = higherBetter
      ? "FEMA NRI v1.20 community resilience; higher values are better (greater resilience)."
      : (measure?.direction_note ? `FEMA NRI v1.20. ${measure.direction_note}` : EXPLANATIONS.nri);
    const formatted = nriValueText(item, measure);
    value = item.value != null && item.rating ? `${formatted} (${item.rating})` : formatted;
    lines = [
      item.rating ? `FEMA rating: ${item.rating}` : null,
      measure?.direction_note || (higherBetter ? "Higher values are better (greater community resilience)." : "Higher values indicate greater modeled risk, loss, or vulnerability."),
      item.source_value != null && item.source_value !== "" ? `FEMA source value: ${item.source_value}` : null,
      "No confidence interval or margin of error is published.",
    ];
  } else if (dataset === "usdafea") {
    value = feaValueText(item, measure);
    lines = [`Observation year ${period} · ${measure?.unit}`,
      item.source_value != null ? `USDA value: ${item.source_value}${period === measure?.observation_period ? ` (${measure?.variable_code})` : ""}` : null,
      item.source_name ? `USDA name: ${item.source_name}` : null];
  } else if (dataset === "acs_profile") {
    value = profileValue(item, measure);
    lines = [profileUncertainty(item), `Census Bureau · ${period} · ${measure?.population}`];
  } else {
    const isAcs = dataset === "acs"; const isAhrf = dataset === "ahrf"; const isClh = dataset === "clh";
    value = `${displayValue(item, isAcs, isAhrf, isClh, measure?.unit)}${isAhrf && item.value != null ? ` ${measure?.unit}` : ""}`;
    lines = [isAcs ? `90% margin of error: ${displayUncertainty(item, true)}` : isAhrf || isClh ? "Uncertainty: not supplied by the source" : `95% confidence interval: ${displayUncertainty(item, false)}`,
      `${period}${isAcs ? ` · ACS 5-year · ${String(period).slice(-4)} dollars` : ""}${measure?.population ? ` · ${measure.population}` : ""}`];
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
  const isHds = dataset === "hds_mortality";
  const isSvi = dataset === "svi";
  const isNri = dataset === "nri";
  const isFea = dataset === "usdafea";
  const isBrfss = dataset === "brfss";
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState("");
  const [initialView] = useState(initialMapView);
  const [measureId, setMeasureId] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const rawMeasure = params.get("measure_id");
    if (isSvi) {
      const scopeParam = params.get("scope");
      const initScope = scopeParam === "state" || (!scopeParam && String(rawMeasure || "").endsWith("_state")) ? "state" : "us";
      return swapSviMeasureScope(rawMeasure || "rpl_themes", initScope);
    }
    return rawMeasure ||
      (isProfile ? "poverty_pct" : isAcs ? "B19013_001E" : isAhrf ? "phys_nf_prim_care_pc_exc_rsdt_23" : isClh ? "ACS_PCT_HH_BROADBAND_ANY" : isAqi ? "median_aqi" : isGv ? "std_payment_per_capita" : isHds ? "heart_disease_death_rate" : isNri ? "eal_score" : isFea ? "low_income_low_access_pct" : isBrfss ? "diabetes" : "dental_crudeprev");
  });
  const [requestedPeriod, setRequestedPeriod] = useState(() => new URLSearchParams(window.location.search).get("period"));
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
  const datasetKey = isBrfss ? "brfss" : isProfile ? "acs_profile" : isAcs ? "acs" : isAhrf ? "ahrf" : isClh ? "clh" : isAqi ? "aqi" : isGv ? "cmsgv" : isHds ? "hds_mortality" : isSvi ? "svi" : isNri ? "nri" : isFea ? "usdafea" : "places";
  // Selection is state, not a Leaflet layer: the area layer is rebuilt on every viewport change.
  const [selection, setSelection] = useState(null);
  const [focusRequest] = useState(parseFocus);
  const [focusStatus, setFocusStatus] = useState("");
  const [sviState, setSviState] = useState(() => {
    if (!isSvi) return "";
    const params = new URLSearchParams(window.location.search);
    const rawMeasure = params.get("measure_id");
    const scopeParam = params.get("scope");
    const initScope = scopeParam === "state" || (!scopeParam && String(rawMeasure || "").endsWith("_state")) ? "state" : "us";
    if (initScope !== "state") return "";
    const fromParam = normalizeSviStateParam(params.get("state"));
    if (fromParam) return fromParam;
    const focus = parseFocus(window.location.search);
    return focus ? normalizeSviStateParam(focus.geoid.slice(0, 2)) : "";
  });
  const [sviStateInfo, setSviStateInfo] = useState(null);
  const [sviDcNotice, setSviDcNotice] = useState(() => isSvi && sviState === "11" && initialView.zoom < PILOT_TRACT_ZOOM);
  const [sviOutlineData, setSviOutlineData] = useState(null);
  const sviStateSelectRef = useRef(null);
  const pendingStateFocusRef = useRef(false);
  const sviZoomStateRef = useRef(isSvi && Boolean(sviState) && !(focusRequest && focusRequest.level !== "state" && focusRequest.geoid.startsWith(sviState)));
  const areaInfoCacheRef = useRef(new Map());
  const [map, setMap] = useState(null);
  const mapSurfaceRef = useRef(null);
  const resizeMap = useCallback(() => map?.invalidateSize?.(), [map]);
  const [baseMapId, setBaseMapId] = useState(BASE_MAP_OPTIONS[0].id);
  const [legendOpen, setLegendOpen] = useState(true);
  const [toolsOpen, setToolsOpen] = useState(() => typeof window === "undefined" || window.innerWidth > 1100);
  const focusedOnce = useRef(false);
  // The full-map loading overlay belongs to the first load of the page only; later loads use the small pill.
  const [firstLoadDone, setFirstLoadDone] = useState(false);
  const [contentEl, setContentEl] = useState(null);
  const [toolsEl, setToolsEl] = useState(null);
  const baseMap = BASE_MAP_OPTIONS.find((option) => option.id === baseMapId) || BASE_MAP_OPTIONS[0];
  // Optional point overlay: its own release, filters, and requests; it never changes the area selection.
  const sites = useHealthCenterSites({ bbox, zoom: mapZoom });
  // Second, independent point overlay (EPA TRI). Both overlays may be shown together.
  const tri = useTriFacilities({ bbox, zoom: mapZoom });
  const homes = useNursingHomes({ bbox, zoom: mapZoom });

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/area/catalog${isProfile ? "?dataset_id=census_acs5_2024_community_profile" : isAcs ? "?dataset_id=census_acs5_2024_b19013" : isAhrf ? "?dataset_id=hrsa_ahrf_county_2024_2025" : isClh ? "?dataset_id=ahrq_clh_2023_curated" : isAqi ? `?dataset_id=${AQI_DATASET_ID}` : isGv ? `?dataset_id=${GV_DATASET_ID}` : isHds ? `?dataset_id=${HDS_MORTALITY_DATASET_ID}` : isSvi ? `?dataset_id=${SVI_DATASET_ID}` : isNri ? `?dataset_id=${NRI_DATASET_ID}` : isFea ? `?dataset_id=${FEA_DATASET_ID}` : isBrfss ? `?dataset_id=${BRFSS_DATASET_ID}` : ""}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(`Catalog unavailable (${response.status})`); return response.json(); })
      .then(setCatalog).catch((err) => { if (err.name !== "AbortError") setCatalogError(err.message); });
    return () => controller.abort();
  }, [isAcs, isProfile, isAhrf, isClh, isAqi, isGv, isHds, isSvi, isNri, isFea, isBrfss]);

  useEffect(() => {
    if (catalog?.measures?.length && !catalog.measures.some((item) => item.measure_id === measureId)) {
      setMeasureId(catalog.measures[0].measure_id);
    }
  }, [catalog, measureId]);

  const measure = useMemo(() => catalog?.measures.find((item) => item.measure_id === measureId), [catalog, measureId]);
  const periods = useMemo(() => measure ? (measure.periods?.length ? measure.periods : [{
    period: measure.observation_period, current: true, available: true, release_id: catalog?.active_release_id,
  }]) : [], [measure, catalog]);
  const periodEntry = periods.find((item) => item.period === requestedPeriod && item.available && item.release_id)
    ?? periods.find((item) => item.current) ?? periods[0];
  const period = periodEntry?.period;
  const releaseId = periodEntry?.release_id;
  const selectedUnit = isGv && period && period !== measure?.observation_period
    ? measure?.unit?.replace(`(${measure.observation_period}, nominal)`, `(${period}, nominal)`) : measure?.unit;
  const feaFormerCounties = isFea && !periodEntry?.current &&
    /TIGER\/Line 2020/.test(periodEntry?.boundary_vintage?.county ?? "");
  const feaLimitations = isFea ? (catalog?.limitations || []).map((item) => {
    if (item.startsWith("Each measure has its own observation year"))
      return `Measures cover different observation years; this map shows ${period}. These values do not describe current conditions.`;
    if (item.startsWith("Connecticut values exist only for its eight former counties") && feaFormerCounties)
      return `Connecticut's eight former counties are drawn on the ${periodEntry.boundary_vintage.county} boundary. Puerto Rico is outside the Atlas.`;
    return item;
  }) : [];
  useEffect(() => {
    if (period && requestedPeriod !== period) setRequestedPeriod(period);
  }, [period, requestedPeriod]);
  const wantsTracts = mapZoom >= (isAcs || isNri ? ACS_TRACT_ZOOM : PILOT_TRACT_ZOOM);
  const supportedLevels = periodEntry?.levels ?? measure?.geographies ?? catalog?.geographies ?? ["county"];
  const tractSupported = supportedLevels.includes("tract");
  const sviScope = isSvi ? sviScopeForMeasure(measureId) : "us";
  const sviStateObj = isSvi && sviScope === "state" && sviState ? sviStateByFips(sviState) : null;
  const sviAwaitingState = isSvi && sviScope === "state" && !sviState;
  const sviWaitingForStateBounds = isSvi && sviScope === "state" && Boolean(sviState) && sviStateInfo?.fips !== sviState;
  const effectiveBbox = useMemo(() => {
    if (!bbox) return null;
    if (isSvi && sviScope === "state" && sviState && sviStateInfo?.fips === sviState && sviStateInfo.bbox) {
      return clipBboxToState(bbox, sviStateInfo.bbox);
    }
    return bbox;
  }, [bbox, isSvi, sviScope, sviState, sviStateInfo]);
  const capSelectionKey = `${releaseId}|${measureId}|${period}|${effectiveBbox}`;
  const tractCapExceeded = tractCapKey === capSelectionKey;
  const sviDcForcedTracts = isSvi && sviScope === "state" && sviState === "11" && tractSupported && !tractCapExceeded;
  // USDA FEA publishes no state value for its selected measures, so counties are shown at every zoom.
  const wantedGeography = isBrfss ? "state" : isProfile && ["state", "county", "tract", "cd"].includes(profileGeography) ? profileGeography
    : isAhrf || isAqi || isFea ? "county" : isGv || isHds ? gvGeography(mapZoom, catalog?.state_to_county_zoom)
    : sviDcForcedTracts ? "tract"
    : areaGeography(mapZoom, isAcs || isProfile || isNri, tractSupported, tractCapExceeded);
  const geography = supportedLevels.includes(wantedGeography) ? wantedGeography
    : supportedLevels.includes("county") ? "county" : supportedLevels.includes("state") ? "state" : supportedLevels[0] ?? wantedGeography;
  const sviHasStateMeasures = isSvi && Boolean(catalog?.measures?.some((item) => sviScopeForMeasure(item.measure_id) === "state"));
  const sviTheme = isSvi ? sviThemeForMeasure(measureId) : null;
  const visibleMeasures = useMemo(() => {
    if (!catalog?.measures) return [];
    if (!isSvi || !sviHasStateMeasures) return catalog.measures;
    const filtered = catalog.measures.filter((item) => (item.source_scope || sviScopeForMeasure(item.measure_id)) === sviScope);
    return filtered.length ? filtered : catalog.measures;
  }, [catalog, isSvi, sviHasStateMeasures, sviScope]);
  // One pixel at the current zoom, so shapes sharpen as the map zooms in; the server keeps shared borders identical.
  const simplify = gridForZoom(mapZoom);
  const dataSelection = useMemo(() => releaseId && measure ? {
    datasetId: catalog.dataset_id, releaseId, period, measure,
    valueType: catalog.value_type_by_level?.[geography] ?? catalog.value_type, geography,
  } : null, [releaseId, period, measure, catalog, geography]);
  const requestKey = useMemo(() => dataSelection && effectiveBbox && !sviAwaitingState && !sviWaitingForStateBounds
    ? String(pilotQuery(dataSelection, effectiveBbox, { simplify: String(simplify), limit: "100", offset: String(page * 100) }))
    : null, [dataSelection, effectiveBbox, page, simplify, sviAwaitingState, sviWaitingForStateBounds]);
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
    if (period) url.searchParams.set("period", period);
    if (isProfile) url.searchParams.set("geography", profileGeography);
    if (isSvi) {
      if (sviScope === "state") {
        url.searchParams.set("scope", "state");
        if (sviState) url.searchParams.set("state", sviState);
        else url.searchParams.delete("state");
      } else {
        url.searchParams.delete("scope");
        url.searchParams.delete("state");
      }
    }
    url.searchParams.set("lat", viewCenter[0].toFixed(5));
    url.searchParams.set("lon", viewCenter[1].toFixed(5));
    url.searchParams.set("zoom", String(mapZoom));
    if (selection) url.searchParams.set("focus", `${selection.level}:${selection.geoid}`);
    else if (!focusRequest || focusedOnce.current) url.searchParams.delete("focus");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }, [bbox, releaseId, measureId, period, mapZoom, viewCenter, isProfile, profileGeography, isSvi, sviScope, sviState, selection?.level, selection?.geoid, focusRequest]);

  async function copyMapLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopyStatus("Map link copied.");
    } catch {
      setCopyStatus("Copy this page's URL from the address bar.");
    }
  }

  useEffect(() => {
    if (!isSvi || sviScope !== "state" || sviState !== "11") {
      setSviDcNotice(false);
    } else if (mapZoom < PILOT_TRACT_ZOOM) {
      setSviDcNotice(true);
    }
  }, [isSvi, sviScope, sviState, mapZoom]);

  useEffect(() => {
    if (isSvi && sviScope === "state" && pendingStateFocusRef.current) {
      pendingStateFocusRef.current = false;
      sviStateSelectRef.current?.focus();
    }
  }, [isSvi, sviScope]);

  useEffect(() => {
    if (!isSvi || sviScope !== "state" || !sviState) {
      setSviStateInfo(null);
      return;
    }
    const cacheKey = `state:${sviState}`;
    if (areaInfoCacheRef.current.has(cacheKey)) {
      const area = areaInfoCacheRef.current.get(cacheKey);
      setSviStateInfo({ fips: sviState, bbox: area?.bbox || null, name: area?.name || sviStateByFips(sviState)?.name || "" });
      return;
    }
    const controller = new AbortController();
    fetch(`${API_BASE}/community/area/state/${sviState}`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((area) => {
        if (area) areaInfoCacheRef.current.set(cacheKey, area);
        setSviStateInfo({ fips: sviState, bbox: area?.bbox || null, name: area?.name || sviStateByFips(sviState)?.name || "" });
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          setSviStateInfo({ fips: sviState, bbox: null, name: sviStateByFips(sviState)?.name || "" });
        }
      });
    return () => controller.abort();
  }, [isSvi, sviScope, sviState]);

  useEffect(() => {
    if (sviAwaitingState) {
      ++requestId.current;
      setError("");
      setLoadedKey(null);
      setMapData(null);
      setLegend(null);
      setTable(null);
      return;
    }
    if (!dataSelection || !effectiveBbox || sviWaitingForStateBounds) return;
    const controller = new AbortController();
    const id = ++requestId.current;
    const base = pilotQuery(dataSelection, effectiveBbox);
    const withMap = pilotQuery(dataSelection, effectiveBbox, { simplify: String(simplify) });
    const withTable = pilotQuery(dataSelection, effectiveBbox, { limit: "100", offset: String(page * 100) });
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
      if ([nextMap, nextLegend, nextTable].some((item) => item.release_id !== releaseId || item.geography !== geography || (item.period != null && item.period !== period))) {
        throw new Error("Release, period, or geography mismatch");
      }
      setMapData(nextMap); setLegend(nextLegend); setTable(nextTable);
      if (isSvi) setSviOutlineData(nextMap);
      setLoadedKey(requestKey);
    }).catch((err) => {
      if (err.name !== "AbortError" && id === requestId.current) {
        if (geography === "tract" && err.status === 413) setTractCapKey(capSelectionKey);
        else { setError(err.message); setLoadedKey(null); setMapData(null); setLegend(null); setTable(null); }
      }
    });
    return () => controller.abort();
  }, [dataSelection, effectiveBbox, page, releaseId, period, requestKey, geography, capSelectionKey, simplify, isSvi, sviAwaitingState, sviWaitingForStateBounds]);

  const ready = Boolean(requestKey && loadedKey === requestKey);
  const settled = ready || sviAwaitingState || Boolean(error) || Boolean(catalogError) || Boolean(catalog && !releaseId);
  useEffect(() => { if (settled) setFirstLoadDone(true); }, [settled]);
  const sourceTitle = isBrfss ? "BRFSS state survey estimates" : isProfile ? `ACS ${period ?? "2020–2024"} community characteristics` : isAcs ? `ACS ${period ?? "2020–2024"} 5-year income` : isAhrf ? `AHRF ${period ?? "2023"} county resources` : isClh ? "AHRQ CLH community conditions" : isAqi ? `EPA annual AQI by county, ${period ?? "2025"}` : isGv ? `CMS Original Medicare Geographic Variation, ${period ?? "2024"}` : isHds ? `CDC heart disease and stroke deaths, ${period ?? "2022–2024"}` : isSvi ? `CDC Social Vulnerability Index, ${period ?? "2018–2022"}` : isNri ? `FEMA National Risk Index, ${period ?? "NRI v1.20 (December 2025)"}` : isFea ? "USDA Food Environment Atlas: county food access and retailers" : `PLACES county and tract estimates${period ? `, ${period}` : ""}`;
  const sviStateFilterActive = isSvi && sviScope === "state" && Boolean(sviState);
  const sviSanitizedMapData = useMemo(
    () => (sviStateFilterActive && ready && mapData ? sanitizeSviStateMapData(mapData, sviState) : mapData),
    [sviStateFilterActive, ready, mapData, sviState],
  );
  const features = ready ? sviSanitizedMapData?.features || [] : [];
  const geoJsonData = isSvi && sviAwaitingState ? sviOutlineData : sviSanitizedMapData;
  const geoJsonFeatures = isSvi && sviAwaitingState ? (sviOutlineData?.features || []) : features;
  const sviInStateRows = useMemo(() => {
    if (!sviStateFilterActive || !ready) return null;
    if (mapData?.features?.length) {
      return filterSviStateFeatures(mapData.features, sviState).map((feature) => feature.properties);
    }
    return (table?.rows || []).filter((row) => sviIsInSelectedState(featureId(row), sviState));
  }, [sviStateFilterActive, ready, mapData, table, sviState]);
  const displayLegend = useMemo(() => {
    if (!sviStateFilterActive || !ready || !legend || !sviInStateRows) return legend;
    return { ...legend, statuses: summarizeSviStatuses(sviInStateRows) };
  }, [sviStateFilterActive, ready, legend, sviInStateRows]);
  const displayTable = useMemo(() => {
    if (!sviStateFilterActive || !ready || !table || !sviInStateRows) return table;
    return {
      ...table,
      total: sviInStateRows.length,
      rows: sviInStateRows.slice(page * 100, (page + 1) * 100),
    };
  }, [sviStateFilterActive, ready, table, sviInStateRows, page]);
  // Quintile cut points for the whole release at this level (PLACES, ACS income, AHRF, CLH).
  const cuts = useMemo(() => quantileCuts(ready ? legend?.quantile_breaks : null), [ready, legend]);
  const cutColors = rampColors(cuts.length + 1);
  const formatCut = (value) => isAcs ? dollars.format(value)
    : isHds ? hdsNumber(value)
    : isAhrf ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)
    : isClh ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value)
    : `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)}%`;
  const zoom = initialView.zoom;
  const detailContext = useMemo(() => ({ geography, catalog, releaseId, period, sviScope, sviState }), [geography, catalog, releaseId, period, sviScope, sviState]);
  const dataKey = `${releaseId}|${measureId}|${period}|${geography}`;

  const zoomRange = useCallback((level) => focusZoomRange(level, {
    min: initialMapZoom(),
    stateBelow: isBrfss ? 12 : isGv || isHds ? (catalog?.state_to_county_zoom ?? ACS_COUNTY_ZOOM) : isAcs || (isProfile && profileGeography === "auto") || (isNri && supportedLevels.includes("state")) ? ACS_COUNTY_ZOOM : null,
    countyFrom: isGv || isHds ? (catalog?.state_to_county_zoom ?? ACS_COUNTY_ZOOM) : isAcs || (isProfile && profileGeography === "auto") || (isNri && supportedLevels.includes("state")) ? ACS_COUNTY_ZOOM : null,
    tractFrom: tractSupported && !(isProfile && profileGeography !== "auto") ? (isAcs || isProfile || isNri ? ACS_TRACT_ZOOM : PILOT_TRACT_ZOOM) : null,
  }), [isBrfss, isGv, isHds, isAcs, isProfile, isNri, supportedLevels, profileGeography, tractSupported, catalog]);

  const fitArea = useCallback((bounds, level) => {
    if (!map || !bounds) return;
    const [west, south, east, north] = bounds;
    const box = [[south, west], [north, east]];
    const range = zoomRange(level);
    const fitted = typeof map.getBoundsZoom === "function" ? map.getBoundsZoom(box, false, [48, 48]) : range.max;
    const target = Math.min(range.max, Math.max(range.min, fitted));
    map.setView([(south + north) / 2, (west + east) / 2], target);
  }, [map, zoomRange]);

  useEffect(() => {
    if (!isSvi || sviScope !== "state" || !sviState || !map || !sviZoomStateRef.current) return;
    if (sviStateInfo?.fips !== sviState || !sviStateInfo.bbox) return;
    sviZoomStateRef.current = false;
    fitArea(sviStateInfo.bbox, sviState === "11" ? "tract" : "state");
  }, [isSvi, sviScope, sviState, map, sviStateInfo, fitArea]);

  // Search results and links from profile pages land here: fetch the area's box and outline, zoom, select.
  const focusArea = useCallback(async (level, geoid) => {
    setFocusStatus("Finding that place…");
    try {
      const response = await fetch(`${API_BASE}/community/area/${level}/${geoid}`);
      if (!response.ok) throw new Error(response.status === 404 ? "That place is not on the published boundary." : "That place could not be loaded right now.");
      const area = await response.json();
      setSelection({ level, geoid: area.geoid, name: area.name, countyName: area.county_name || null, bbox: area.bbox, geometry: area.geometry,
        shapeKey: periodEntry?.current ? dataKey : null, properties: null, propsKey: null });
      fitArea(area.bbox, level);
      setFocusStatus("");
    } catch (failure) {
      setFocusStatus(failure.message);
    }
  }, [fitArea, dataKey, periodEntry?.current]);

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

  // SVI clicked-area panel closes when theme, comparison, state, or geography changes (CDC map behavior).
  const sviPrevContextRef = useRef(null);
  useEffect(() => {
    if (!isSvi) return;
    const prev = sviPrevContextRef.current;
    const next = { measureId, sviScope, sviState, geography };
    sviPrevContextRef.current = next;
    if (!prev) return;
    const nonGeoChanged = prev.measureId !== next.measureId || prev.sviScope !== next.sviScope || prev.sviState !== next.sviState;
    const geoChanged = prev.geography !== next.geography;
    if (nonGeoChanged) {
      clearSelection();
    } else if (geoChanged) {
      setSelection((current) => (current && current.level !== next.geography ? null : current));
    }
  }, [isSvi, measureId, sviScope, sviState, geography, clearSelection]);

  // Look up parent county name when an SVI tract is clicked so the panel shows "Census Tract ..., County Name, ST".
  useEffect(() => {
    if (!isSvi || !selection || selection.level !== "tract" || selection.countyName) return;
    const countyGeoid = String(selection.geoid || "").slice(0, 5);
    if (countyGeoid.length !== 5) return;
    const cacheKey = `county:${countyGeoid}`;
    if (areaInfoCacheRef.current.has(cacheKey)) {
      const cached = areaInfoCacheRef.current.get(cacheKey);
      if (cached?.name) {
        setSelection((cur) => (cur && cur.geoid === selection.geoid ? { ...cur, countyName: cached.name } : cur));
      }
      return;
    }
    const controller = new AbortController();
    fetch(`${API_BASE}/community/area/county/${countyGeoid}`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((area) => {
        if (area?.name) {
          areaInfoCacheRef.current.set(cacheKey, area);
          setSelection((cur) => (cur && cur.geoid === selection.geoid ? { ...cur, countyName: area.name } : cur));
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [isSvi, selection?.level, selection?.geoid, selection?.countyName]);

  function handleSviScopeChange(targetScope) {
    if (targetScope === sviScope) return;
    if (targetScope === "state") {
      const preselect = selection?.geoid ? normalizeSviStateParam(String(selection.geoid).slice(0, 2)) : "";
      clearSelection();
      if (preselect) {
        sviZoomStateRef.current = true;
        setSviState(preselect);
        if (preselect === "11" && mapZoom < PILOT_TRACT_ZOOM) setSviDcNotice(true);
      }
      pendingStateFocusRef.current = true;
      setMeasureId(swapSviMeasureScope(measureId, "state"));
      setPage(0);
    } else {
      clearSelection();
      setSviState("");
      setSviStateInfo(null);
      setSviDcNotice(false);
      sviZoomStateRef.current = false;
      setMeasureId(swapSviMeasureScope(measureId, "us"));
      setPage(0);
    }
  }

  function handleSviStateChange(nextState) {
    clearSelection();
    sviZoomStateRef.current = Boolean(nextState);
    if (nextState === "11" && mapZoom < PILOT_TRACT_ZOOM) setSviDcNotice(true);
    else if (nextState !== "11") setSviDcNotice(false);
    setSviState(nextState);
    setPage(0);
  }

  // Values for the selected area: the live feature when it is in view, else what was read when it was clicked.
  const liveFeature = selection && selection.level === geography
    ? features.find((feature) => featureId(feature.properties) === selection.geoid) ?? null : null;
  const liveSelected = liveFeature?.properties ?? null;
  // Outline the shape exactly as drawn when it is in view; otherwise the outline read with the selection.
  const outlineGeometry = liveFeature?.geometry ?? (selection?.shapeKey === dataKey ? selection.geometry : null);
  const selectedProps = liveSelected ?? (selection?.propsKey === dataKey ? selection.properties : null);
  const selectedDetails = selection && selectedProps && measure ? areaFeatureDetails(datasetKey, selectedProps, measure, detailContext) : null;
  const profileHref = profileHrefFor(selection);
  return <div className="app pilot-app">
    <Header />
    <main className="app-content pilot-content" ref={setContentEl}>
      <div className="map-wrapper pilot-map" ref={mapSurfaceRef} aria-label={catalog && releaseId ? `${geography === "cd" ? "congressional district" : areaName(geography)} ${isBrfss ? "BRFSS" : isAcs || isProfile ? "ACS" : isClh ? "CLH" : isGv ? "CMS Original Medicare" : isHds ? "CDC heart disease and stroke deaths" : isSvi ? "CDC Social Vulnerability Index" : isNri ? "FEMA National Risk Index" : isFea ? "USDA Food Environment Atlas" : "pilot"} map` : undefined}>
        {catalog && releaseId && <MapContainer center={initialView.center} zoom={zoom} minZoom={initialMapZoom()} zoomSnap={0.25} zoomControl={false}
          maxBounds={[[-85, -180], [85, 180]]} maxBoundsViscosity={1} style={{ height: "100%", width: "100%" }}>
          <TileLayer key={baseMap.id} url={baseMap.url} attribution={baseMap.attribution} maxZoom={baseMap.maxZoom} />
          <ZoomControl position="bottomright" />
          <MapReady onReady={setMap} />
          <Viewport onChange={onViewport} />
          {geoJsonFeatures.length > 0 && <GeoJSON key={`${releaseId}:${measureId}:${period}:${geography}:${effectiveBbox}:${isSvi ? `${sviScope}:${sviState}` : ""}`} data={geoJsonData} style={(feature) => isBrfss ? {
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
          } : isHds ? {
            color: "#516677", weight: 0.5,
            fillOpacity: feature.properties.status === "not_in_release" ? 0.35 : 0.85,
            dashArray: feature.properties.status === "not_in_release" ? "2 3" : null,
            fillColor: hdsColor(feature.properties.value, feature.properties.status, cuts),
          } : isSvi ? sviFeatureStyle(feature, { scope: sviScope, selectedState: sviState, measureId }) : isNri ? {
            color: "#516677", weight: 0.5,
            fillOpacity: feature.properties.status === "not_in_release" ? 0.35 : 0.85,
            dashArray: feature.properties.status === "not_in_release" ? "2 3" : null,
            fillColor: nriColor(feature.properties.value, feature.properties.status, mapData?.legend_breaks || measure?.legend_breaks?.[geography] || [20, 40, 60, 80]),
          } : isAqi ? {
            color: "#516677", weight: 0.5,
            fillOpacity: feature.properties.status === AQI_NO_VALUE ? 0.35 : 0.85,
            dashArray: feature.properties.status === AQI_NO_VALUE ? "2 3" : null,
            fillColor: aqiColor(feature.properties.value, feature.properties.status, mapData?.legend_breaks || measure?.legend_breaks || []),
          } : ({
            color: "#516677", weight: 0.5, fillOpacity: 0.78,
            fillColor: isProfile ? color(feature.properties.value, feature.properties.status, mapData?.legend_breaks)
              : quintileColor(feature.properties.value, feature.properties.status, cuts),
          })} onEachFeature={(feature, layer) => {
            const item = feature.properties;
            const baseSviStyle = isSvi ? sviFeatureStyle(feature, { scope: sviScope, selectedState: sviState, measureId }) : null;
            if (baseSviStyle) layer.setStyle?.(baseSviStyle);
            // Same hover tooltip as the legacy map; skipped on touch pointers.
            if (!isCoarsePointer() && typeof layer.bindTooltip === "function") {
              layer.bindTooltip(areaTooltip(datasetKey, item, measure, detailContext), MAP_HOVER_TOOLTIP_OPTIONS);
            }
            layer.on?.("mouseover", () => layer.setStyle?.({ weight: 2, color: HOVER_LINE }));
            layer.on?.("mouseout", () => layer.setStyle?.(baseSviStyle || { weight: 0.5, color: "#516677" }));
            layer.on?.("click", () => {
              if (isSvi && sviAwaitingState) return;
              const box = typeof layer.getBounds === "function" ? layer.getBounds() : null;
              setSelection({
                level: geography, geoid: featureId(item), name: item.name, countyName: item.county_name || null, geometry: feature.geometry,
                bbox: box?.isValid?.() ? [box.getWest(), box.getSouth(), box.getEast(), box.getNorth()] : null,
                properties: item, propsKey: dataKey, shapeKey: dataKey,
              });
              if (isSvi) setLegendOpen(true);
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
      <MobileMapPanels mapSurfaceRef={mapSurfaceRef} onVisibilityChange={resizeMap} className="pilot-mobile-panels">
      <section className="pilot-panel pilot-controls" aria-label="Analytical controls">
        <h1>{sourceTitle}</h1>
        {isBrfss ? <div className="pilot-scope">
          <p>CDC BRFSS crude prevalence is a direct state survey estimate for {period ?? "the selected year"}. State values are not computed from PLACES counties. PLACES county figures are modeled from the survey and serve a different geography.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">{(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}</ul>
        </div> : isFea ? <div className="pilot-scope">
          <p>Five published county measures from USDA ERS's Food Environment Atlas, {catalog?.release_label ?? "July 2025"} release. <strong>Each measure has its own observation year; the selected year is {period ?? "shown below"}</strong>. These values do not describe current conditions. USDA publishes no state value for these measures, so counties are shown at every zoom and none is averaged or summed. No tract values exist.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">
            {feaLimitations.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div> : isGv ? <div className="pilot-scope">
          <p>Published CMS values for the Original Medicare (fee-for-service) population with Part A and Part B, all ages. Medicare Advantage enrollees are excluded. Observation year {period ?? catalog?.observation_year ?? "2024"}{periodEntry?.current ? `; source release “${catalog?.source_release_id ?? "OM GV PUF May 2026 update"}”` : ""}. States are shown at broad zoom and counties from zoom {catalog?.state_to_county_zoom ?? ACS_COUNTY_ZOOM}. No tract values exist.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">
            {(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div> : isHds ? (
          <div className="pilot-scope">
            <p>
              Published CDC age-adjusted death rates for adults 35 and older, averaged over{" "}
              {period ?? catalog?.observation_period ?? "2022–2024"}. County rates are spatially
              smoothed by CDC; state and national rates are not smoothed. States are shown at broad
              zoom and counties from zoom {catalog?.state_to_county_zoom ?? ACS_COUNTY_ZOOM}. No
              tract values exist.
            </p>
            <ul className="pilot-limitations" aria-label="Interpretation limits">
              {(catalog?.limitations || []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : isSvi ? <div className="pilot-scope">
          <p>Published CDC/ATSDR SVI 2022 {sviScope === "state" ? "within-state" : "U.S.-wide"} percentile ranks (0–1) for counties and census tracts, built on ACS {period ?? "2018–2022"} 5-year estimates. These are percentile ranks, not rates; higher values indicate greater vulnerability. Counties are shown at broad zoom and tracts from zoom {PILOT_TRACT_ZOOM}.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">
            {(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div> : isNri ? <div className="pilot-scope">
          <p>Published FEMA National Risk Index ({period ?? "NRI v1.20 (December 2025)"}) scores, within-state percentiles, and modeled expected annual loss. States are shown below zoom {ACS_COUNTY_ZOOM} where published (expected annual loss only), counties from zoom {ACS_COUNTY_ZOOM} to {ACS_TRACT_ZOOM - 1}, and tracts from zoom {ACS_TRACT_ZOOM}.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">
            {(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div> : isAqi ? <div className="pilot-scope">
          <p>EPA AirData annual summary of daily Air Quality Index values for calendar year {period ?? "2025"}{periodEntry?.current ? ", from the file EPA generated on 2026-06-25" : ""}. County values only; no state or tract values are derived.</p>
          <ul className="pilot-limitations" aria-label="Interpretation limits">
            {(catalog?.limitations || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div> : <p className="pilot-scope">{isProfile ? `Census Bureau published community characteristics for states, counties, tracts, and current-period 119th Congress districts. The percentages and 90% margins of error come from ACS ${period ?? "2020–2024"} subject tables; population totals may have no sampling margin.` : isAcs ? `Published median household income for states, counties, and census tracts. Values are in ${String(period ?? "2020–2024").slice(-4)} dollars for this ACS window; margins of error use 90% confidence.` : isAhrf ? `HRSA AHRF county resources, observation year ${period ?? "2023"}. No state or tract values are inferred. Uncertainty was not supplied.` : isClh ? `AHRQ CLH community conditions for ${period ?? "the selected period"}. No state estimates or uncertainty fields are supplied.` : "Official county and census tract estimates. No state estimates are provided by this pilot."}</p>}
        <label>Data source <select value={isBrfss ? "brfss" : isProfile ? "acs_profile" : isAcs ? "acs" : isAhrf ? "ahrf" : isClh ? "clh" : isAqi ? "aqi" : isGv ? "cmsgv" : isHds ? "hds_mortality" : isSvi ? "svi" : isNri ? "nri" : isFea ? "usdafea" : "pilot"} onChange={(event) => { const paths = { brfss: "/area/brfss", acs: "/area/acs-2024", acs_profile: "/area/acs-community", ahrf: "/area/ahrf", clh: "/area/clh", aqi: "/area/epa-aqi", cmsgv: "/area/cms-gv", hds_mortality: "/area/heart-stroke-mortality", svi: "/area/svi", nri: "/area/fema-nri", usdafea: "/area/usda-fea", pilot: "/area/places-2025" }; window.location.assign(paths[event.target.value]); }}>
          <option value="pilot">PLACES 2025 county and tract pilot</option>
          <option value="brfss">BRFSS state survey estimates</option>
          <option value="acs">ACS 2020–2024 5-year income</option>
          <option value="acs_profile">ACS 2020–2024 community characteristics</option>
          <option value="ahrf">AHRF 2023 workforce and hospitals</option>
          <option value="clh">AHRQ CLH community conditions</option>
          <option value="aqi">EPA annual AQI by county (2025)</option>
          <option value="cmsgv">CMS Original Medicare 2024 (states and counties)</option>
          <option value="hds_mortality">CDC heart disease and stroke deaths</option>
          <option value="svi">CDC Social Vulnerability Index</option>
          <option value="nri">FEMA National Risk Index</option>
          <option value="usdafea">USDA Food Environment Atlas (county measures)</option>
        </select></label>
        {catalogError && <p role="alert">{catalogError}</p>}
        {!catalog && !catalogError && <p role="status">Loading catalog…</p>}
        {catalog && !releaseId && <p role="status">The first {isAcs ? "ACS" : "county"} candidate is awaiting supervised review and publication. No {isAcs ? "ACS" : "pilot"} map is published yet.</p>}
        {catalog && releaseId && <>
          <label>Measure <select value={measureId} onChange={(event) => { setMeasureId(event.target.value); setPage(0); }}>
            {visibleMeasures.map((item) => <option key={item.measure_id} value={item.measure_id}>{item.label} ({item.observation_period})</option>)}
          </select></label>
          {isSvi && <div className="pilot-svi-controls">
            <fieldset className="pilot-svi-scope" title={SVI_COMPARISON_TOOLTIP}>
              <legend>Geographic Comparison</legend>
              <div className="pilot-svi-toggle" role="group" aria-label="Geographic Comparison" title={SVI_COMPARISON_TOOLTIP}>
                <button
                  type="button"
                  className={sviScope === "us" ? "is-active" : ""}
                  aria-pressed={sviScope === "us"}
                  title={SVI_COMPARISON_TOOLTIP}
                  onClick={() => handleSviScopeChange("us")}
                >
                  Nationwide
                </button>
                <button
                  type="button"
                  className={sviScope === "state" ? "is-active" : ""}
                  aria-pressed={sviScope === "state"}
                  title={SVI_COMPARISON_TOOLTIP}
                  onClick={() => handleSviScopeChange("state")}
                >
                  Statewide
                </button>
              </div>
            </fieldset>
            <div className="pilot-svi-state-picker">
              <label htmlFor="svi-state-select">State Selection</label>
              <select
                id="svi-state-select"
                ref={sviStateSelectRef}
                value={sviState}
                disabled={sviScope !== "state"}
                title={sviScope !== "state" ? SVI_STATE_DISABLED_HINT : undefined}
                aria-describedby={sviScope !== "state" ? "svi-state-hint" : undefined}
                onChange={(event) => handleSviStateChange(event.target.value)}
              >
                <option value="">Select a state…</option>
                {SVI_STATES.map((st) => (
                  <option key={st.fips} value={st.fips}>{st.name}</option>
                ))}
              </select>
              {sviScope !== "state" && (
                <p id="svi-state-hint" className="pilot-svi-hint">{SVI_STATE_DISABLED_HINT}</p>
              )}
              {sviAwaitingState && (
                <p role="status" className="pilot-svi-state-note">{SVI_CHOOSE_STATE_MESSAGE}</p>
              )}
              {sviScope === "state" && sviState && (
                <p role="status" className="pilot-svi-state-note">Colors compare areas only within their own state.</p>
              )}
              {sviDcNotice && (
                <p role="status" className="pilot-svi-dc-note">{SVI_DC_SWITCH_MESSAGE}</p>
              )}
            </div>
          </div>}
          <label>Year <select value={period ?? ""} onChange={(event) => { setRequestedPeriod(event.target.value); setPage(0); }}>
            {periods.map((item) => <option key={item.period} value={item.period} disabled={!item.available || !item.release_id}>
              {item.period}{item.current ? " (latest)" : !item.available || !item.release_id ? " (not published)" : ""}
            </option>)}
          </select></label>
          {isProfile && <label>Geography <select value={profileGeography} onChange={(event) => { setProfileGeography(event.target.value); setPage(0); }}>
            <option value="auto">Automatic by zoom</option><option value="state">State</option><option value="county">County</option><option value="tract">Census tract</option><option value="cd">119th Congress district</option>
          </select></label>}
          {isFea && <div className="pilot-fea-measure">
            <p className="pilot-period"><strong>Observation year {period}</strong> · {measure?.unit} · county values only</p>
            <p className="pilot-metadata">USDA definition{periodEntry?.current ? ` (${measure?.variable_code})` : ""}: {measure?.official_definition}</p>
            <p className="pilot-metadata">Denominator: {measure?.denominator} {periodEntry?.current && measure?.interpretation}</p>
            <p className="pilot-metadata">{periodEntry?.current && <>Contributing sources: {measure?.contributing_sources} County boundary basis in the source: {measure?.source_boundary_basis}; </>}Joined by exact FIPS to {periodEntry?.boundary_vintage?.county ?? catalog.boundary_vintage}. Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">USDA ERS Food Environment Atlas</a> (<a href={catalog.documentation_url} target="_blank" rel="noreferrer">documentation</a>).</p>
            {mapZoom < ACS_COUNTY_ZOOM && <p role="status">State values are not published for this measure; counties are shown at the national view.</p>}
          </div>}
          {!isFea && <p className="pilot-metadata">{geography === "cd" ? "Congressional district" : areaName(geography)} {isSvi ? "ranks" : isNri || isHds ? "values" : "estimates"} · {isClh || isProfile || isSvi || isNri || isHds ? "Observation period" : "Observation year"} {period} · {isSvi ? (measure?.population_by_level?.[geography] ?? catalog?.population_by_level?.[geography] ?? measure?.population) : measure?.population} · {isBrfss || isProfile || isAhrf || isClh || isAqi || isGv || isHds || isSvi || isNri ? selectedUnit : catalog.unit}{isAcs ? " · ACS 5-year Detailed Tables" : isProfile ? " · Census Bureau ACS 5-year Subject Tables" : ""}</p>}
          {!periodEntry?.current && wantedGeography !== geography && <p role="status">{wantedGeography === "cd"
            ? "Districts have no earlier years in CHIP: older Congresses had different districts."
            : `${areaName(wantedGeography)} values are not published for ${period}; ${areaName(geography)} values remain displayed.`}</p>}
          {isBrfss && <p className="pilot-metadata">CDC BRFSS definition: {measure?.official_definition} {measure?.interpretation} Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">BRFSS Prevalence Data</a>.</p>}
          {isProfile && <p className="pilot-metadata">Source: <a href={catalog.landing_page} target="_blank" rel="noreferrer">Census Bureau ACS {period}</a> · {measure?.official_definition}. {measure?.interpretation}</p>}
          {isAhrf && <p className="pilot-metadata">Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">HRSA Area Health Resources Files</a>, compiled from {measure?.source}. These underlying data are copyright of that organization and are shown here with attribution. Counts have no published uncertainty estimate.</p>}
          {isGv && <p className="pilot-metadata">CMS definition ({measure?.source_field}): {measure?.official_definition} Denominator: {measure?.denominator} {measure?.interpretation} Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">CMS Medicare Geographic Variation</a>.</p>}
          {isHds && (
            <p className="pilot-metadata">
              CDC definition ({measure?.source_dataset_id}): {measure?.official_definition}{" "}
              Denominator: {measure?.denominator} {measure?.interpretation} Source:{" "}
              <a href={catalog.source_url} target="_blank" rel="noreferrer">
                CDC Interactive Atlas of Heart Disease and Stroke
              </a>
              .
            </p>
          )}
          {isSvi && <p className="pilot-metadata">CDC/ATSDR SVI ({measure?.source_field}): {measure?.official_definition} {measure?.interpretation} Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">CDC/ATSDR Social Vulnerability Index</a>.</p>}
          {isNri && <p className="pilot-metadata">FEMA NRI ({measure?.source_field}): {measure?.official_definition} {measure?.interpretation} Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">OpenFEMA National Risk Index</a>.</p>}
          {isNri && !supportedLevels.includes("state") && mapZoom < ACS_COUNTY_ZOOM && <p role="status">FEMA publishes no state value for this measure; counties are shown below zoom {ACS_TRACT_ZOOM}.</p>}
          {isAqi && <p className="pilot-metadata">EPA definition: {measure?.official_definition} {measure?.statistic_note} Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">EPA AirData pre-generated files</a>.</p>}
          {isClh && <p className="pilot-metadata">Distributed by <a href={catalog.source_url} target="_blank" rel="noreferrer">AHRQ CLH</a>; contributing source: {measure?.source}. {measure?.denominator} denominator. Blanks remain missing; no uncertainty estimate is supplied.</p>}
          {isGv && wantsTracts && <p role="status">County values remain displayed. CMS publishes no tract estimates for this product.</p>}
          {isHds && wantsTracts && (
            <p role="status">
              County values remain displayed. CDC publishes no tract estimates for this product.
            </p>
          )}
          {isFea && wantsTracts && <p role="status">County values remain displayed. USDA publishes no tract values for these measures, and none is estimated.</p>}
          {!isGv && !isHds && !isFea && !isBrfss && wantsTracts && !tractSupported && <p role="status">County estimates remain displayed; no tract estimate is published for this release.</p>}
          {isBrfss && <p role="status">State estimates remain displayed at every zoom. BRFSS has no county or tract values in this release.</p>}
          {wantsTracts && tractCapExceeded && <p role="status">This viewport contains more than 5,000 tracts. County estimates remain displayed; zoom in for tracts.</p>}
          <p className="pilot-release">Release {releaseId}</p>
          <div className="pilot-share"><button type="button" onClick={copyMapLink}>Copy map link</button><span role="status">{copyStatus}</span></div>
        </>}
      </section>
      {catalog && releaseId && <>
        <section className={`pilot-panel pilot-legend ${legendOpen ? "" : "is-minimized"}`} aria-label="Legend">
          <button type="button" className="pilot-panel-toggle" aria-label={legendOpen ? "Minimize legend" : "Expand legend"} aria-expanded={legendOpen} onClick={() => setLegendOpen((open) => !open)}>{legendOpen ? "\u2212" : "+"}</button>
          <h2>{isSvi
            ? (sviScope === "state" && sviStateObj ? `Levels of Vulnerability (within ${sviStateObj.name})` : "Levels of Vulnerability")
            : `${isAcs ? "Median household income" : isBrfss || isProfile || isAhrf || isClh || isAqi || isGv || isHds || isNri || isFea ? measure?.label : "Crude prevalence"}, ${period} — ${geography === "cd" ? "congressional district" : areaName(geography)} level`}</h2>
          {legendOpen && <>
          {!periodEntry?.current && <div className="pilot-history-notes">
            {periodEntry?.note && <p>{periodEntry.note}</p>}
            {(periodEntry?.boundary_vintage?.[geography] || legend?.boundary_vintage) && <p>Boundary: {periodEntry?.boundary_vintage?.[geography] || legend?.boundary_vintage}.</p>}
            {ready && legend?.colour_note && <p>{legend.colour_note}</p>}
            {ready && Number(legend?.published_without_boundary) > 0 && <p>{legend.published_without_boundary} {Number(legend.published_without_boundary) === 1 ? "area published for this year has" : "areas published for this year have"} no matching boundary and {Number(legend.published_without_boundary) === 1 ? "is" : "are"} not drawn.</p>}
          </div>}
          {ready && legend && isBrfss ? <>
            <ul className="pilot-swatches">
              {prevalenceColors.map((shade, i) => <li key={shade}><i style={{ background: shade }} />{i === 0 ? `Under ${(legend.legend_breaks || measure?.legend_breaks)?.[0]}%` : i === 4 ? `${(legend.legend_breaks || measure?.legend_breaks)?.[3]}% or more` : `${(legend.legend_breaks || measure?.legend_breaks)?.[i - 1]}% to under ${(legend.legend_breaks || measure?.legend_breaks)?.[i]}%`}</li>)}
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
              <li><i className="pilot-swatch-none" style={{ background: FEA_STATUS_COLORS.not_covered }} />{feaFormerCounties ? FEA_STATUS_TEXT.not_covered : `${FEA_STATUS_TEXT.boundary_not_comparable} or ${FEA_STATUS_TEXT.not_covered.toLowerCase()}`}</li>
            </ul>
            <p>{measure?.unit}, observation year {period}. Fixed display classes; not statistical groupings.</p>
            <p>{legend.statuses.map((item) => `${item.status === "available" ? "published value" : item.status === "true_zero" ? "published zero" : FEA_STATUS_TEXT[item.status] ?? item.status}: ${item.n}`).join(" · ")}</p>
            <p>Select a county for its value and USDA source value. No confidence interval or margin of error is published.</p>
          </> : ready && legend && isGv ? <>
            <ul className="pilot-swatches">
              {gvBinLabels(legend.legend_breaks || [], measure?.kind).map((label, i) => <li key={label}><i style={{ background: gvColors[i] }} />{label}</li>)}
              <li><i style={{ background: GV_STATUS_COLORS.suppressed }} />{GV_STATUS_TEXT.suppressed}</li>
              <li><i style={{ background: GV_STATUS_COLORS.missing }} />{GV_STATUS_TEXT.missing}</li>
              <li><i className="pilot-swatch-none" style={{ background: GV_STATUS_COLORS.not_published }} />{GV_STATUS_TEXT.not_published} (DC and Puerto Rico counties)</li>
            </ul>
            <p>{selectedUnit}. Fixed display classes{measure?.kind === "count" ? ` for ${areaName(geography)} counts` : ", the same at state and county levels"}; not statistical groupings.</p>
            <p>{legend.statuses.map((item) => `${GV_STATUS_TEXT[item.status] ?? item.status.replace("_", " ")}: ${item.n}`).join(" · ")}</p>
            {legend.national_reference && <p>United States (CMS-published national value, reference only): {gvValueText(legend.national_reference, measure)}</p>}
            <p>Select a {areaName(geography)} for its value. No confidence interval or margin of error is published.</p>
          </> : ready && legend && isHds ? (
            <>
              <ul className="pilot-swatches">
                {cuts.length ? (
                  quantileLabels(cuts, formatCut).map((label, i) => (
                    <li key={label}>
                      <i style={{ background: cutColors[i] }} />
                      {label}
                    </li>
                  ))
                ) : (
                  <li>
                    <i style={{ background: prevalenceColors[2] }} />
                    Published value
                  </li>
                )}
                <li>
                  <i style={{ background: HDS_STATUS_COLORS.suppressed }} />
                  {HDS_STATUS_TEXT.suppressed}
                </li>
                <li>
                  <i
                    className="pilot-swatch-none"
                    style={{ background: HDS_STATUS_COLORS.not_in_release }}
                  />
                  {HDS_STATUS_TEXT.not_in_release} (Connecticut planning regions)
                </li>
              </ul>
              {cuts.length > 0 && (
                <p>
                  Classes are quintiles of all published {areaName(geography)} rates in this
                  release, so each holds about a fifth of them and colors do not change as the map
                  moves. Higher values mean more deaths.
                </p>
              )}
              <p>
                {legend.statuses
                  .map(
                    (item) =>
                      `${item.status_text || HDS_STATUS_TEXT[item.status] || item.status.replace("_", " ")}: ${item.n}`,
                  )
                  .join(" · ")}
              </p>
              {legend.national_reference && (
                <p>
                  United States (CDC-published national value, reference only):{" "}
                  {hdsValueText(legend.national_reference)}
                </p>
              )}
              <p>
                Select a {areaName(geography)} for its value. No confidence interval or margin of
                error is published.
              </p>
            </>
          ) : isSvi && (sviAwaitingState || (ready && legend)) ? <>
            {sviAwaitingState && <p className="pilot-svi-state-note">{SVI_CHOOSE_STATE_MESSAGE}</p>}
            <ul className="pilot-swatches pilot-svi-swatches">
              {SVI_LEVELS.map((level, i) => (
                <li key={level.key}>
                  <i style={{ background: sviTheme.palette[i], borderColor: "#555555" }} />
                  {level.label} ({level.range})
                </li>
              ))}
              <li>
                <i className="pilot-swatch-svi-nodata" style={{ background: SVI_NO_DATA_COLOR, borderColor: "#555555" }} />
                No Data
              </li>
            </ul>
            <p>{sviScope === "state"
              ? "Colors compare areas only within their own state."
              : `2022 National ${sviTheme.title} (${geography === "tract" ? "census tracts" : "counties"}). Higher values indicate greater vulnerability.`}</p>
            {ready && displayLegend && <p>{displayLegend.statuses.map((item) => `${item.status_text || SVI_STATUS_TEXT[item.status] || item.status.replace("_", " ")}: ${item.n}`).join(" · ")}</p>}
            {!sviAwaitingState && <p>Select a {areaName(geography)} for its rank and vulnerability level.</p>}
          </> : ready && legend && isNri ? <>
            <ul className="pilot-swatches">
              {nriBinLabels(legend.legend_breaks || measure?.legend_breaks?.[geography] || [20, 40, 60, 80], measure?.kind).map((label, i) => <li key={label}><i style={{ background: nriColors[i] }} />{label}</li>)}
              <li><i style={{ background: NRI_STATUS_COLORS.not_available }} />{NRI_STATUS_TEXT.not_available}</li>
              <li><i className="pilot-swatch-none" style={{ background: NRI_STATUS_COLORS.not_in_release }} />{NRI_STATUS_TEXT.not_in_release}</li>
            </ul>
            <p>{measure?.direction === "higher_better"
              ? "Higher values are better: higher community resilience indicates greater capacity to prepare for, adapt to, and recover from natural hazards."
              : (measure?.direction_note || "Higher values indicate greater modeled natural-hazard risk, loss, or social vulnerability.")}{measure?.measure_id === "eal_valt" ? ` Fixed display classes for ${areaName(geography)}-level expected annual loss.` : ""}</p>
            <p>{legend.statuses.map((item) => `${item.status_text || NRI_STATUS_TEXT[item.status] || item.status.replace("_", " ")}: ${item.n}`).join(" · ")}</p>
            <p>Select a {areaName(geography)} for its value, FEMA rating, and source value. No confidence interval or margin of error is published.</p>
          </> : ready && legend && isAqi ? <>
            <ul className="pilot-swatches">
              {aqiBinLabels(legend.legend_breaks || measure?.legend_breaks || [], measure?.unit).map((label, i) => <li key={label}><i style={{ background: aqiColors[i] }} />{label}</li>)}
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
          </> : error ? <p>Data unavailable</p> : <LegendSkeleton />}
          {selection && (isSvi && (selection.level === "county" || selection.level === "tract") ? (() => {
            const countyGeoid = selection.level === "tract" ? String(selection.geoid).slice(0, 5) : String(selection.geoid);
            const countyLine = selection.level === "tract"
              ? (sviCountyHeading(selection.countyName || selectedProps?.county_name, countyGeoid)
                || (sviStateAbbrForGeoid(selection.geoid) ? `County ${countyGeoid}, ${sviStateAbbrForGeoid(selection.geoid)}` : selection.name))
              : sviCountyHeading(selection.name, selection.geoid);
            const outsideSelectedState = sviScope === "state" && (!sviState || !sviIsInSelectedState(selection.geoid, sviState));
            const unavailable = !outsideSelectedState && selectedProps && sviIsMissing(selectedProps.value, selectedProps.status);
            const sviRankFormatted = selectedProps && !outsideSelectedState && !unavailable ? sviFormatValue(selectedProps.value) : null;
            const sviRankLevel = selectedProps && !outsideSelectedState && !unavailable ? sviLevel(selectedProps.value, selectedProps.status) : null;
            return (
              <div className="pilot-selected pilot-svi-selected" data-testid="selected-area">
                <div className="pilot-svi-selected-head">
                  <h3 className="pilot-svi-heading">
                    {selection.level === "tract" && (
                      <span className="pilot-svi-tract-line">Census Tract {selection.geoid},</span>
                    )}
                    <span className="pilot-svi-county-line">{countyLine}</span>
                  </h3>
                  <button type="button" className="pilot-svi-close" aria-label="Close panel" onClick={clearSelection}>×</button>
                </div>
                {outsideSelectedState ? (
                  <p className="pilot-svi-unavailable">{sviState ? SVI_OUTSIDE_STATE_MESSAGE : SVI_CHOOSE_STATE_MESSAGE}</p>
                ) : unavailable ? (
                  <p className="pilot-svi-unavailable">{SVI_UNAVAILABLE_MESSAGE}</p>
                ) : selectedProps && sviRankLevel ? (
                  <>
                    <p className="pilot-svi-rank-title">{sviPanelRankTitle(measureId, sviScope)}: {sviRankFormatted}</p>
                    <SviQuartileBar value={selectedProps.value} status={selectedProps.status} measureId={measureId} />
                    <p className="pilot-svi-range">{SVI_RANGE_TEXT}</p>
                    <p className="pilot-svi-phrase">
                      A rank of <strong>{sviRankFormatted}</strong> indicates a <strong>{sviRankLevel.phrase}</strong> level of vulnerability.
                    </p>
                  </>
                ) : (
                  <p>{ready ? "This area is outside the current view. Use Zoom to selected area." : "Loading the selected area…"}</p>
                )}
                {countyGeoid.length === 5 && (
                  <p className="pilot-svi-profile-link"><a href={`/community/county/${countyGeoid}`}>Open county profile</a></p>
                )}
              </div>
            );
          })() : <div className="pilot-selected" data-testid="selected-area">
            <h3>Selected area</h3>
            <p className="pilot-selected-name">{areaTitle(selection.name, selection.level, selection.geoid)}</p>
            {selectedDetails ? <>
              <p className="pilot-selected-value">{selectedDetails.measure}: <strong>{selectedDetails.value}</strong></p>
              {selectedDetails.lines.map((line) => <p key={line}>{line}</p>)}
            </> : selection.level !== geography
              ? <p>The map is showing {geography === "cd" ? "congressional district" : areaName(geography)} values here. No {selection.level === "cd" ? "district" : areaName(selection.level)} value is shown for this measure at this zoom, and none is calculated from the areas inside it.</p>
              : <p>{ready && !periodEntry?.current && bboxIntersects(bbox, selection.bbox)
                ? "This area has no shape on this year's boundary, so no value is shown or inferred."
                : ready ? "This area is outside the current view. Use Zoom to selected area." : "Loading the selected area…"}</p>}
            {profileHref && <p><a href={profileHref}>Open {selection.level === "cd" ? "district briefing" : `${areaName(selection.level)} profile`} →</a></p>}
          </div>)}
          </>}
        </section>
        <div className="pilot-dock">
        <section ref={setToolsEl} className={`pilot-panel pilot-tools ${toolsOpen ? "is-open" : ""}`} aria-label="Map tools and search">
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
            <span>Displayed {areaName(geography)} values{ready && displayTable ? ` (${displayTable.total})` : ""}</span><span aria-hidden="true">{tableOpen ? "−" : "+"}</span>
          </button>
          {tableOpen && <div className="pilot-table-body">
            {error && <p role="alert">{error}</p>}
            {isSvi && sviAwaitingState && <p role="status">{SVI_CHOOSE_STATE_MESSAGE}</p>}
            {!ready && !error && !sviAwaitingState && <p role="status">Loading selected {areaName(geography)} estimates…</p>}
            {ready && displayTable && <>
              <p>{areaName(geography)} areas intersecting the map viewport. Map and table use the same geometry rule.{isBrfss ? " States without a CDC result for this year are marked Not published." : isFea ? ` All ${legend?.boundary_vintage ?? periodEntry?.boundary_vintage?.county ?? "published"} boundary counties in view are listed with USDA's published value and status.` : isAqi ? ` All ${legend?.boundary_vintage ?? periodEntry?.boundary_vintage?.county ?? "published"} boundary counties are listed; counties without an EPA summary are marked No reported value.` : isGv ? ` All ${legend?.boundary_vintage ?? periodEntry?.boundary_vintage?.[geography] ?? "published"} boundary ${geography === "state" ? "states" : "counties"} in view are listed with CMS's published value and status.` : isHds ? ` All ${legend?.boundary_vintage ?? catalog?.boundary_vintage ?? "published"} boundary ${geography === "state" ? "states" : "counties"} in view are listed with CDC's published death rate and status.` : isSvi ? (sviStateFilterActive ? ` All ${legend?.boundary_vintage ?? catalog?.boundary_vintage?.[geography] ?? "published"} boundary ${geography === "tract" ? "tracts" : "counties"} in ${sviStateObj?.name || "the selected state"} in view are listed with CDC/ATSDR's published percentile rank and status.` : ` All ${legend?.boundary_vintage ?? catalog?.boundary_vintage?.[geography] ?? "published"} boundary ${geography === "tract" ? "tracts" : "counties"} in view are listed with CDC/ATSDR's published percentile rank and status.`) : isNri ? ` All ${legend?.boundary_vintage ?? catalog?.boundary_vintage?.[geography] ?? "published"} boundary ${geography === "state" ? "states" : geography === "tract" ? "tracts" : "counties"} in view are listed with FEMA's published NRI value, rating, and status.` : ""}</p>
              <div className="pilot-table-scroll"><table><caption>{measure?.label}, {period}; release {releaseId}</caption>
                {isBrfss ? <thead><tr><th scope="col">State FIPS</th><th scope="col">State</th><th scope="col">{measure?.label} (%)</th><th scope="col">95% CI</th><th scope="col">Response count</th><th scope="col">Status</th></tr></thead>
                : isFea ? <thead><tr><th scope="col">County FIPS</th><th scope="col">County</th><th scope="col">{measure?.label} ({period})</th><th scope="col">USDA source value</th><th scope="col">Status</th></tr></thead>
                : isGv ? <thead><tr><th scope="col">{geography === "state" ? "State FIPS" : "County FIPS"}</th><th scope="col">{areaName(geography)}</th><th scope="col">{measure?.label}</th><th scope="col">CMS source value</th><th scope="col">Status</th></tr></thead>
                : isHds ? (
                  <thead>
                    <tr>
                      <th scope="col">{geography === "state" ? "State FIPS" : "County FIPS"}</th>
                      <th scope="col">{areaName(geography)}</th>
                      <th scope="col">{measure?.label}</th>
                      <th scope="col">CDC source value</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                )
                : isSvi ? <thead><tr><th scope="col">{geography === "tract" ? "Tract GEOID" : "County FIPS"}</th><th scope="col">{areaName(geography)}</th><th scope="col">{measure?.label}</th><th scope="col">CDC SVI source value</th><th scope="col">Status</th></tr></thead>
                : isNri ? <thead><tr><th scope="col">{geography === "state" ? "State FIPS" : geography === "tract" ? "Tract GEOID" : "County FIPS"}</th><th scope="col">{areaName(geography)}</th><th scope="col">{measure?.label}</th><th scope="col">FEMA rating</th><th scope="col">FEMA source value</th><th scope="col">Status</th></tr></thead>
                : isAqi ? <thead><tr><th scope="col">County FIPS</th><th scope="col">County</th><th scope="col">{measure?.label} ({measure?.unit})</th><th scope="col">Days with AQI</th><th scope="col">EPA source name</th><th scope="col">Status</th></tr></thead>
                : <thead><tr><th scope="col">{geography === "cd" ? "District GEOID" : geography === "tract" ? "Tract GEOID" : geography === "state" ? "State FIPS" : "County FIPS"}</th><th scope="col">{geography === "cd" ? "District" : areaName(geography)}</th><th scope="col">{isProfile ? `Value (${measure?.unit})` : isAcs ? `Value (${String(period).slice(-4)} USD)` : isAhrf || isClh ? `Value (${measure?.unit})` : "Value (%)"}</th><th scope="col">{isProfile || isAcs ? "90% MOE" : isAhrf || isClh ? "Uncertainty" : "95% CI"}</th><th scope="col">Status</th></tr></thead>}
                <tbody>{displayTable.rows.map((row) => {
                  const key = row.geography_id || row.tract_fips || row.county_fips;
                  if (isBrfss) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{brfssValueText(row)}</td><td>{row.ci_low == null ? "—" : `${row.ci_low}–${row.ci_high}%`}</td><td>{row.sample_size ?? "—"}</td><td>{row.status_text || row.status}</td></tr>;
                  if (isFea) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{feaValueText(row, measure)}</td><td>{row.source_value ?? "—"}</td><td>{row.status === "available" ? "Published value" : row.status === "true_zero" ? "Published zero" : FEA_STATUS_TEXT[row.status] ?? row.status}</td></tr>;
                  if (isGv) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{gvValueText(row, measure)}</td><td>{row.source_value ?? "—"}</td><td>{GV_STATUS_TEXT[row.status] ?? row.status}</td></tr>;
                  if (isHds) {
                    return (
                      <tr key={key}>
                        <th scope="row">{key}</th>
                        <td>{row.name}</td>
                        <td>{hdsValueText(row)}</td>
                        <td>{row.source_value ?? "—"}</td>
                        <td>
                          {row.status === "available"
                            ? "Published rate"
                            : row.status_text || HDS_STATUS_TEXT[row.status] || row.status}
                        </td>
                      </tr>
                    );
                  }
                  if (isSvi) {
                    return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{sviValueText(row)}</td><td>{row.source_value ?? "—"}</td><td>{row.status === "available" ? "Published rank" : row.status === "true_zero" ? "Published zero" : row.status_text || SVI_STATUS_TEXT[row.status] || row.status}</td></tr>;
                  }
                  if (isNri) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{nriValueText(row, measure)}</td><td>{row.rating ?? "—"}</td><td>{row.source_value ?? "—"}</td><td>{row.status === "available" ? "Published value" : row.status === "true_zero" ? "Published zero" : row.status_text || NRI_STATUS_TEXT[row.status] || row.status}</td></tr>;
                  if (isAqi) return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{aqiValueText(row, measure)}</td><td>{row.days_with_aqi ?? "—"}</td><td>{row.source_name ?? "—"}</td><td>{row.status === AQI_NO_VALUE ? "No reported value" : row.status}</td></tr>;
                  return <tr key={key}><th scope="row">{key}</th><td>{row.name}</td><td>{isProfile ? profileValue(row, measure) : displayValue(row, isAcs, isAhrf, isClh, measure?.unit)}</td><td>{isProfile ? profileUncertainty(row) : displayUncertainty(row, isAcs, isAhrf, isClh)}</td><td>{row.status_text || row.status}</td></tr>;
                })}</tbody>
              </table></div>
              {isBrfss && displayTable.reference?.median?.find((item) => item.geography_id === "98") && <p className="pilot-metadata">Median of states and DC (CDC-published reference, not a national estimate): {brfssValueText(displayTable.reference.median.find((item) => item.geography_id === "98"))}. No confidence interval is published for this median.</p>}
              <nav aria-label={`${areaName(geography)} table pages`}><button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button> Page {page + 1} of {Math.max(1, Math.ceil(displayTable.total / 100))} <button disabled={(page + 1) * 100 >= displayTable.total} onClick={() => setPage(page + 1)}>Next</button></nav>
            </>}
          </div>}
        </section>
        </div>
        <div className="pilot-overlays">
          <HealthCenterSitePanel sites={sites} />
          <TriFacilityPanel tri={tri} />
          <NursingHomePanel homes={homes} />
        </div>
        <MapLoadingStrip active={firstLoadDone && Boolean(requestKey) && !ready && !error && !sviAwaitingState} anchor={toolsEl} container={contentEl}
          watch={[toolsOpen, tableOpen]} label={`Loading ${geography === "cd" ? "district" : areaName(geography)} shapes…`} />
      </>}
      </MobileMapPanels>
      <MapLoadingOverlay active={!firstLoadDone} detail={sourceTitle} />
    </main>
    <Footer />
  </div>;
}
