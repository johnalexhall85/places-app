import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Pane,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import SearchBar from "./SearchBar";
import AskMapChat from "./components/AskMapChat";
import FullProfilePanel from "./components/FullProfilePanel";
import Header from "./components/Header";
import {
  getSviBins,
  getSviLabel,
  getSviLevel,
  sviMeasureGroups,
} from "./sviCatalog";
import {
  buildInterpretationLines,
  formatNumberWithCommas,
  formatPercent,
  formatRatio,
  formatTierRanges,
  getSeverityLabel,
} from "./content/hpsaLegendCopy";
import { buildMapContext } from "./mapContext";
import useSelectedAreaProfileTarget from "./hooks/useSelectedAreaProfileTarget";
import {
  fetchCmsGvCountyGeo,
  fetchCmsMeasures,
  fetchCmsYears,
} from "./api/cms";
import {
  fetchUsdaFoodEnvironmentLegend,
  fetchUsdaFoodEnvironmentMap,
  fetchUsdaFoodEnvironmentVariables,
} from "./api/usdaFoodEnvironment";
import {
  fetchFemaNriLegend,
  fetchFemaNriMap,
  fetchFemaNriMeasures,
} from "./api/femaNri";
import {
  fetchCdcFundingDetail,
  fetchCdcFundingFilters,
  fetchCdcFundingLegend,
  fetchCdcFundingMap,
  fetchCdcFundingTop,
  searchCdcFunding,
} from "./api/cdcFunding";

const API_BASE = "http://localhost:8000";
const DATA_SOURCES = {
  PLACES: "places",
  ACS_NMF: "acs_nmf",
  SVI: "svi",
  HPSA: "hpsa",
  CMS: "cms",
  CDC_FUNDING: "cdc_funding",
  USDA_FOOD_ENV: "usda_food_environment",
  FEMA_NRI: "fema_nri",
};
const CDC_BASIS_OPTIONS = [
  { value: "prime", label: "Prime Awards" },
  { value: "subaward", label: "Subawards" },
];
const CDC_GEOGRAPHY_OPTIONS = [
  { value: "county", label: "County" },
  { value: "state", label: "State" },
];
const CDC_DEFAULT_METRIC_BY_BASIS = {
  prime: "total_funding",
  subaward: "total_subaward",
};
const USDA_DEFAULT_VARIABLE = "PCT_LACCESS_POP19";
const FEMA_DEFAULT_MEASURE = "RISK_SCORE";
const USDA_PLAIN_LABELS = {
  LA1and10: "People with low food access (1 mile urban / 10 miles rural)",
  LAhalfand10: "People with low food access (0.5 mile urban / 10 miles rural)",
  LA1and20: "People with low food access (1 mile urban / 20 miles rural)",
  LILATracts_1And10: "Low-income and low-access tract (1/10 standard)",
  LILATracts_halfAnd10: "Low-income and low-access tract (0.5/10 standard)",
  LILATracts_1And20: "Low-income and low-access tract (1/20 standard)",
  LILATracts_Vehicle: "Low-income and low-access tract (vehicle access)",
  LowIncomeTracts: "Low-income tract (yes/no)",
  PovertyRate: "Poverty rate",
  MedianFamilyIncome: "Median family income",
  LAPOP1_10: "Residents with low food access (1/10 standard)",
  LAPOP05_10: "Residents with low food access (0.5/10 standard)",
  LAPOP1_20: "Residents with low food access (1/20 standard)",
  LALOWI1_10: "Low-income residents with low food access (1/10 standard)",
  LALOWI05_10: "Low-income residents with low food access (0.5/10 standard)",
  LALOWI1_20: "Low-income residents with low food access (1/20 standard)",
};
const USDA_PLAIN_DESCRIPTIONS = {
  LA1and10:
    "Share of residents living far from a supermarket: at least 1 mile in urban areas or 10 miles in rural areas.",
  LAhalfand10:
    "Share of residents living at least 0.5 mile from a supermarket in urban areas, or 10 miles in rural areas.",
  LA1and20:
    "Share of residents living at least 1 mile from a supermarket in urban areas, or 20 miles in rural areas.",
  LILATracts_1And10:
    "Indicates whether this tract meets both low-income and low-access criteria under the 1/10 distance standard.",
  LILATracts_halfAnd10:
    "Indicates whether this tract meets both low-income and low-access criteria under the 0.5/10 distance standard.",
  LILATracts_1And20:
    "Indicates whether this tract meets both low-income and low-access criteria under the 1/20 distance standard.",
  LILATracts_Vehicle:
    "Indicates whether this tract is low-income and has limited vehicle access for reaching nearby food stores.",
  LowIncomeTracts:
    "Indicates whether this census tract is classified as low income.",
  PovertyRate:
    "Estimated share of residents in poverty in this tract.",
  MedianFamilyIncome:
    "Median family income in this tract.",
  LAPOP1_10:
    "Number of residents living far from a supermarket using the 1/10 distance standard.",
  LAPOP05_10:
    "Number of residents living far from a supermarket using the 0.5/10 distance standard.",
  LAPOP1_20:
    "Number of residents living far from a supermarket using the 1/20 distance standard.",
  LALOWI1_10:
    "Number of low-income residents living far from a supermarket using the 1/10 distance standard.",
  LALOWI05_10:
    "Number of low-income residents living far from a supermarket using the 0.5/10 distance standard.",
  LALOWI1_20:
    "Number of low-income residents living far from a supermarket using the 1/20 distance standard.",
};
const USDA_PLAIN_LABELS_BY_FIELD = Object.entries(USDA_PLAIN_LABELS).reduce((acc, [field, label]) => {
  acc[field.toLowerCase()] = label;
  return acc;
}, {});
const USDA_PLAIN_DESCRIPTIONS_BY_FIELD = Object.entries(USDA_PLAIN_DESCRIPTIONS).reduce((acc, [field, description]) => {
  acc[field.toLowerCase()] = description;
  return acc;
}, {});
const DEFAULT_SVI_YEAR = 2022;
const SVI_FALLBACK_YEARS = [2022, 2020, 2018];
const HEADER_HEIGHT = 56;
const DEFAULT_CENTER = [39.5, -98.35];
const DEFAULT_ZOOM = 4;
const BASE_MAP_OPTIONS = [
  {
    id: "street",
    label: "Street",
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  },
  {
    id: "topographic",
    label: "Topographic",
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attribution:
      'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, ' +
      '<a href="https://viewfinderpanoramas.org/">SRTM</a> | ' +
      'Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)',
    maxZoom: 17,
  },
  {
    id: "satellite",
    label: "Satellite",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution:
      "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, " +
      "Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
    maxZoom: 19,
  },
];
const DEFAULT_BASE_MAP_ID = BASE_MAP_OPTIONS[0].id;
const TRACT_ZOOM = 10;
const USDA_TRACT_ZOOM = 10;
const COUNTY_RELOAD_ZOOM = 8;
const BBOX_PRECISION = 4;
const BIN_COUNT = 5;
const COLORS = ["#F2FBFB", "#AADDDD", "#7FCACB", "#42A6A8", "#0F2D46"];
const NO_DATA_COLOR = "#DDE5EB";
const USDA_HEAT_LAYER_GRADIENT = {
  0.10: "#e6f4f1",
  0.35: "#a8dadc",
  0.55: "#5fb3b3",
  0.75: "#2a9d8f",
  1.0: "#1b4965",
};
const USDA_HEAT_RAMP_CSS = "linear-gradient(to right, #e6f4f1, #a8dadc, #5fb3b3, #2a9d8f, #1b4965)";
const FEMA_RATING_COLORS = {
  "Very Low": "#edf8e9",
  Low: "#bae4b3",
  Moderate: "#74c476",
  High: "#31a354",
  "Very High": "#006d2c",
};
const HPSA_TIER_COLORS = {
  1: COLORS[0],
  2: COLORS[1],
  3: COLORS[2],
  4: COLORS[4],
};
const HPSA_SEVERITY_BADGE_STYLES = {
  1: { background: "#2E7D32", border: "#1B5E20", color: "#FFFFFF" },
  2: { background: "#FACC15", border: "#CA8A04", color: "#111827" },
  3: { background: "#EA580C", border: "#C2410C", color: "#FFFFFF" },
  4: { background: "#B91C1C", border: "#991B1B", color: "#FFFFFF" },
  designatedNoScore: { background: "#B8C2CC", border: "#94A3B8", color: "#0F172A" },
};
const HPSA_NOT_DESIGNATED_COLOR = "#D1D5DB";
const HPSA_DESIGNATED_NO_SCORE_COLOR = "#B8C2CC";
const HPSA_DOMAIN_OPTIONS = [
  { value: "pc", label: "Primary Care" },
  { value: "mh", label: "Mental Health" },
  { value: "dh", label: "Dental" },
];
const HPSA_DOMAIN_LABELS = HPSA_DOMAIN_OPTIONS.reduce((acc, option) => {
  acc[option.value] = option.label;
  return acc;
}, {});
const COUNTY_HOVER_TOOLTIP_OPTIONS = {
  sticky: true,
  direction: "top",
  opacity: 0.95,
  interactive: false,
};
const CMS_AGE_OPTIONS = [
  { value: "all", label: "All", apiValue: "All" },
  { value: "65_plus", label: "65 and older", apiValue: "65+" },
  { value: "under_65", label: "Under 65", apiValue: "<65" },
];
const CMS_CURATED_MEASURES = [
  {
    key: "spending_standardized",
    label: "Medicare spending per person (standardized)",
    unitType: "usd",
    candidateMeasureIds: [
      "TOT_MDCR_STDZD_PYMT_PC",
      "TOT_MDCR_PYMT_PC",
      "TOT_MDCR_STDZD_PYMT_AMT",
      "TOT_MDCR_PYMT_AMT",
    ],
  },
  {
    key: "er_visits_per_1000",
    label: "Emergency room visits (per 1,000 beneficiaries)",
    unitType: "per_1000",
    candidateMeasureIds: [
      "ER_VISITS_PER_1000_BENES",
      "ER_VISITS_PER_1000",
      "BENES_ER_VISITS_PCT",
    ],
  },
  {
    key: "readmission_30_day",
    label: "Hospital readmissions (30-day, %)",
    unitType: "percent",
    candidateMeasureIds: [
      "READMIT_RATE_30D",
      "ACUTE_HOSP_READMSN_PCT",
    ],
  },
  {
    key: "average_risk_score",
    label: "Average risk score (HCC)",
    unitType: "risk",
    candidateMeasureIds: [
      "AVG_RISK_SCORE",
      "BENE_AVG_RISK_SCRE",
    ],
  },
];
const STATE_BORDER_COLOR = "#4c1d95";
const FALLBACK_YEARS = [2023];
const CACHE_TTL_MS = 10 * 60 * 1000; // 10 minutes
const VIEWPORT_DEBOUNCE_MS = 250;
const HISTORY_START_YEAR = 2018;
const HISTORY_END_YEAR = 2023;
const ASSISTANT_POST_CONTEXT_ACTION_DELAY_MS = 200;
const ASSISTANT_STREAM_CHUNK_CHARS = 4;
const ASSISTANT_STREAM_INTERVAL_MS = 18;
const ANALYSIS_PROMPT_PATTERN = /\b(analy[sz]e|analysis|full profile|profile)\b/i;
const USDA_RECENT_MEASURES_STORAGE_KEY = "places.usdaFoodEnv.recentMeasures.v1";

function parseYearFromToken(value) {
  if (value == null) return null;
  const text = String(value).trim();
  if (!text) return null;
  const directYear = text.match(/\b(19\d{2}|20\d{2})\b/);
  if (!directYear) return null;
  const parsed = Number(directYear[1]);
  return Number.isFinite(parsed) ? parsed : null;
}

function pickFirstDefined(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined) {
      return value;
    }
  }
  return null;
}

function findCmsMeasureId(availableIds, preferredIds) {
  for (const preferredId of preferredIds) {
    if (availableIds.has(preferredId)) {
      return preferredId;
    }
  }
  return null;
}

function buildCmsCuratedMeasures(apiMeasures) {
  const list = Array.isArray(apiMeasures) ? apiMeasures : [];
  const byId = new Map();
  list.forEach((measure) => {
    const measureId = String(measure?.measure_id ?? "").trim();
    if (!measureId) return;
    byId.set(measureId, measure);
  });

  const availableIds = new Set(byId.keys());
  const curatedFromApi = CMS_CURATED_MEASURES
    .map((config) => {
      const resolvedId = findCmsMeasureId(availableIds, config.candidateMeasureIds);
      if (!resolvedId) return null;
      const sourceMeasure = byId.get(resolvedId) ?? {};
      return {
        measure_id: resolvedId,
        name: config.label,
        measure: config.label,
        label: config.label,
        unit: sourceMeasure?.unit ?? null,
        domain: sourceMeasure?.domain ?? null,
        cms_unit_type: config.unitType,
        source: "cms",
      };
    })
    .filter(Boolean);

  if (curatedFromApi.length > 0) {
    return curatedFromApi;
  }

  return CMS_CURATED_MEASURES.map((config) => ({
    measure_id: config.candidateMeasureIds[0],
    name: config.label,
    measure: config.label,
    label: config.label,
    unit: null,
    domain: null,
    cms_unit_type: config.unitType,
    source: "cms",
  }));
}

function quantile(sortedValues, q) {
  if (sortedValues.length === 0) return null;
  if (sortedValues.length === 1) return sortedValues[0];
  const position = (sortedValues.length - 1) * q;
  const base = Math.floor(position);
  const rest = position - base;
  const lower = sortedValues[base];
  const upper = sortedValues[base + 1] ?? lower;
  return lower + rest * (upper - lower);
}

function toFiniteNumericValue(value) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    if (trimmed.toLowerCase() === "no data") return null;
    const numericValue = Number(trimmed);
    return Number.isFinite(numericValue) ? numericValue : null;
  }
  return null;
}

function computeBreaks(values, bins = BIN_COUNT) {
  const numeric = values
    .map((value) => toFiniteNumericValue(value))
    .filter((value) => value != null)
    .sort((a, b) => a - b);

  if (numeric.length === 0) {
    return [];
  }

  const breaks = [];
  for (let i = 0; i <= bins; i += 1) {
    breaks.push(quantile(numeric, i / bins));
  }

  const deduped = [breaks[0]];
  for (let i = 1; i < breaks.length; i += 1) {
    const current = breaks[i];
    const last = deduped[deduped.length - 1];
    if (current > last) {
      deduped.push(current);
    }
  }

  if (deduped.length < 2) {
    deduped.push(deduped[0]);
  }

  return deduped;
}

function computeFixedQuantileBreaks(values, bins = BIN_COUNT) {
  const numeric = values
    .map((value) => toFiniteNumericValue(value))
    .filter((value) => value != null)
    .sort((a, b) => a - b);

  if (numeric.length === 0) {
    return [];
  }

  const breaks = [];
  for (let i = 0; i <= bins; i += 1) {
    breaks.push(quantile(numeric, i / bins));
  }
  return breaks;
}

function tagMeasuresForSource(measuresList, source) {
  const sourceTag = source === DATA_SOURCES.ACS_NMF
    ? "acs"
    : source === DATA_SOURCES.SVI
      ? "svi"
      : source === DATA_SOURCES.CMS
        ? "cms"
        : source === DATA_SOURCES.CDC_FUNDING
          ? "cdc"
        : source === DATA_SOURCES.USDA_FOOD_ENV
          ? "usda"
          : source === DATA_SOURCES.FEMA_NRI
            ? "fema"
            : "places";
  return (measuresList ?? []).map((measure) => ({
    ...measure,
    source: measure?.source ?? sourceTag,
  }));
}

function getValueFromProperties(properties) {
  if (!properties) return null;
  if (properties.value != null) return properties.value;
  if (properties.data_value != null) return properties.data_value;
  return null;
}

function getFeatureId(properties) {
  if (!properties) return "Unknown";
  return properties.locationid
    ?? properties.location_id
    ?? properties.id
    ?? properties.geoid
    ?? properties.state_fips
    ?? "Unknown";
}

function getFeatureLocationId(properties) {
  if (!properties) return null;
  const locationId = properties.locationid
    ?? properties.location_id
    ?? properties.id
    ?? properties.geoid
    ?? properties.state_fips
    ?? null;
  if (locationId == null) return null;
  const normalized = String(locationId).trim();
  return normalized.length > 0 ? normalized : null;
}

function pushGeometryPoints(coordinates, output) {
  if (!Array.isArray(coordinates)) return;
  if (
    coordinates.length >= 2
    && typeof coordinates[0] === "number"
    && typeof coordinates[1] === "number"
  ) {
    const lng = Number(coordinates[0]);
    const lat = Number(coordinates[1]);
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      output.push([lat, lng]);
    }
    return;
  }
  coordinates.forEach((item) => pushGeometryPoints(item, output));
}

function getGeometryCenter(geometry) {
  if (!geometry || typeof geometry !== "object") return null;
  const points = [];
  pushGeometryPoints(geometry.coordinates, points);
  if (points.length === 0) return null;

  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLng = Infinity;
  let maxLng = -Infinity;
  points.forEach(([lat, lng]) => {
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
    if (lng < minLng) minLng = lng;
    if (lng > maxLng) maxLng = lng;
  });
  if (
    !Number.isFinite(minLat)
    || !Number.isFinite(maxLat)
    || !Number.isFinite(minLng)
    || !Number.isFinite(maxLng)
  ) {
    return null;
  }
  return {
    lat: (minLat + maxLat) / 2,
    lng: (minLng + maxLng) / 2,
  };
}

function getCountyName(properties) {
  if (!properties) return "Unknown";
  return properties.county_name ?? properties.name ?? getFeatureId(properties);
}

function normalizeCountyFips(value) {
  if (value == null) return null;
  const digits = String(value).replace(/[^0-9]/g, "");
  if (!digits) return null;
  if (digits.length === 5) return digits;
  if (digits.length < 5) return digits.padStart(5, "0");
  return null;
}

function getCountyFipsFromProperties(properties) {
  if (!properties) return null;
  return normalizeCountyFips(
    properties.county_fips
    ?? properties.location_id
    ?? properties.locationid
    ?? properties.geoid
    ?? (
      properties.statefp != null && properties.countyfp != null
        ? `${properties.statefp}${properties.countyfp}`
        : null
    )
  );
}

function getCmsAgeOption(value) {
  return CMS_AGE_OPTIONS.find((option) => option.value === value) ?? CMS_AGE_OPTIONS[0];
}

function getCmsUnitType(measure) {
  const explicit = String(measure?.cms_unit_type ?? "").trim().toLowerCase();
  if (["usd", "per_1000", "percent", "risk"].includes(explicit)) {
    return explicit;
  }
  const measureId = String(measure?.measure_id ?? "").trim().toUpperCase();
  if (
    measureId.includes("PYMT")
    || measureId.endsWith("_AMT")
    || measureId.endsWith("_PC")
  ) {
    return "usd";
  }
  if (measureId.includes("PER_1000")) {
    return "per_1000";
  }
  if (measureId.endsWith("_PCT") || measureId.endsWith("_RATE")) {
    return "percent";
  }
  if (measureId.includes("RISK")) {
    return "risk";
  }
  return "number";
}

function formatCmsValue(value, unitType, { includeUnits = false } = {}) {
  const numericValue = toFiniteNumericValue(value);
  if (numericValue == null) return "Not shown";

  if (unitType === "usd") {
    const formatted = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(numericValue);
    return includeUnits ? `${formatted} per person` : formatted;
  }
  if (unitType === "per_1000") {
    const formatted = numericValue.toLocaleString("en-US", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });
    return includeUnits ? `${formatted} per 1,000` : formatted;
  }
  if (unitType === "percent") {
    return `${numericValue.toFixed(1)}%`;
  }
  if (unitType === "risk") {
    const formatted = numericValue.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return includeUnits ? `${formatted} risk score` : formatted;
  }
  return numericValue.toLocaleString("en-US", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

function formatCmsRange(min, max, unitType) {
  const minValue = toFiniteNumericValue(min);
  const maxValue = toFiniteNumericValue(max);
  if (minValue == null || maxValue == null) return "Not shown";
  return `${formatCmsValue(minValue, unitType, { includeUnits: true })} - ${
    formatCmsValue(maxValue, unitType, { includeUnits: true })
  }`;
}

function getCmsUnitsLabel(unitType) {
  if (unitType === "usd") return "USD per person";
  if (unitType === "per_1000") return "per 1,000 beneficiaries";
  if (unitType === "percent") return "%";
  if (unitType === "risk") return "risk score";
  return "reported value";
}

function shortenMeasureLabelForTooltip(value) {
  const text = String(value ?? "").trim();
  if (!text) return "Measure";

  const cleaned = text
    .replace(/\s+among adults aged.*$/i, "")
    .replace(/\s+for adults aged.*$/i, "")
    .replace(/\s+for adults\b.*$/i, "")
    .replace(/\s*\(.*adults.*\)\s*$/i, "")
    .replace(/\s{2,}/g, " ")
    .trim();

  if (!cleaned) return "Measure";
  if (cleaned.length <= 68) return cleaned;
  return `${cleaned.slice(0, 65).trimEnd()}...`;
}

function inferTooltipUnitType({ measureId, measureLabel, dataValueTypeId, source, explicitUnitType }) {
  const explicit = String(explicitUnitType ?? "").trim().toLowerCase();
  if (["percent", "usd", "per_1000", "risk", "number"].includes(explicit)) {
    return explicit;
  }

  if (source === DATA_SOURCES.PLACES) {
    return "percent";
  }

  const typeId = String(dataValueTypeId ?? "").trim().toLowerCase();
  if (typeId === "percent" || typeId === "crdprv" || typeId === "ageadjprv") {
    return "percent";
  }

  const id = String(measureId ?? "").trim().toUpperCase();
  const label = String(measureLabel ?? "").trim().toLowerCase();
  if (id.includes("PER_1000") || /per\s*1,?000/.test(label)) return "per_1000";
  if (
    id.includes("PYMT")
    || id.endsWith("_AMT")
    || /\b(dollar|cost|payment|spending|income|usd)\b/.test(label)
  ) {
    return "usd";
  }
  if (id.endsWith("_PCT") || id.endsWith("_RATE") || /percent|prevalence|rate/.test(label)) {
    return "percent";
  }
  if (id.includes("RISK")) return "risk";
  return "number";
}

function inferUsdaUnitTypeFromText(unitText) {
  const token = String(unitText ?? "").trim().toLowerCase();
  if (!token) return null;
  if (token.includes("percent") || token === "% change" || token === "percentage points") {
    return "percent";
  }
  if (token.includes("# per 1,000") || token.includes("per 1,000")) {
    return "per_1000";
  }
  if (token.includes("dollar")) {
    return "usd";
  }
  return "number";
}

function formatTooltipValue(value, unitType, { noDataLabel = "No data" } = {}) {
  const numeric = toFiniteNumericValue(value);
  if (numeric == null) return noDataLabel;

  if (unitType === "percent") {
    return `${numeric.toFixed(1)}%`;
  }
  if (unitType === "per_1000") {
    return `${numeric.toLocaleString("en-US", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    })} per 1,000`;
  }
  if (unitType === "usd") {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(numeric);
  }
  if (unitType === "risk") {
    return numeric.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  return numeric.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  });
}

function formatTooltipMetaLine(valueText, periodText) {
  const safeValue = String(valueText ?? "").trim() || "No data";
  const safePeriod = String(periodText ?? "").trim();
  if (!safePeriod) return safeValue;
  return `${safeValue} • ${safePeriod}`;
}

function toHpsaStatus(designatedValue, coveragePctValue) {
  const hasDesignated = designatedValue !== null && designatedValue !== undefined;
  if (!hasDesignated) return "No data";

  const designated = Boolean(designatedValue);
  if (!designated) return "No";

  const coveragePct = toFiniteNumericValue(coveragePctValue);
  if (coveragePct != null && coveragePct > 0 && coveragePct < 100) {
    return "Partial";
  }
  return "Yes";
}

function getColor(value, breaks) {
  if (value == null || !Array.isArray(breaks) || breaks.length < 2) {
    return NO_DATA_COLOR;
  }

  const numericValue = toFiniteNumericValue(value);
  if (numericValue == null) {
    return NO_DATA_COLOR;
  }

  for (let i = 0; i < breaks.length - 1; i += 1) {
    if (numericValue >= breaks[i] && numericValue <= breaks[i + 1]) {
      return COLORS[i] ?? COLORS[COLORS.length - 1];
    }
  }

  return COLORS[COLORS.length - 1];
}

function formatRange(min, max) {
  if (min == null || max == null) return "No data";
  return `${Number(min).toFixed(1)} - ${Number(max).toFixed(1)}`;
}

function formatValue(value) {
  const numericValue = toFiniteNumericValue(value);
  if (numericValue == null) return "No data";
  return numericValue.toFixed(1);
}

function formatYearWindowDisplay(value) {
  if (value == null) return "N/A";
  const text = String(value).trim();
  if (!text) return "N/A";
  return text.replace("-", "\u2013");
}

function formatDataValueTypeLabel(typeId) {
  const normalized = String(typeId ?? "").trim();
  if (!normalized) return "Data value";
  if (normalized === "CrdPrv") return "Crude Prevalence";
  if (normalized === "AgeAdjPrv") return "Age-Adjusted Prevalence";
  if (normalized === "Percent") return "Percent";
  return normalized
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function truncateText(value, maxLength = 140) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(1, maxLength - 1)).trimEnd()}...`;
}

function getMeasureDisplayName(measure) {
  if (!measure) return "";
  return measure.name ?? measure.measure ?? measure.short_question_text ?? measure.measure_id ?? "";
}

function getUsdaPlainLabel(field, fallbackLongName) {
  const normalizedField = String(field ?? "").trim().toLowerCase();
  if (normalizedField && USDA_PLAIN_LABELS_BY_FIELD[normalizedField]) {
    return USDA_PLAIN_LABELS_BY_FIELD[normalizedField];
  }
  const fallback = String(fallbackLongName ?? "").trim();
  if (fallback) return fallback;
  const fieldText = String(field ?? "").trim();
  return fieldText || "USDA Food Environment";
}

function getUsdaPlainDescription(field, fallbackDescription) {
  const normalizedField = String(field ?? "").trim().toLowerCase();
  if (normalizedField && USDA_PLAIN_DESCRIPTIONS_BY_FIELD[normalizedField]) {
    return USDA_PLAIN_DESCRIPTIONS_BY_FIELD[normalizedField];
  }
  return String(fallbackDescription ?? "").trim();
}

function getFemaMeasureLabel(measure, fallbackId = "") {
  return String(
    measure?.name
    ?? measure?.label
    ?? measure?.display_label
    ?? measure?.measure
    ?? fallbackId
    ?? ""
  ).trim() || fallbackId || "FEMA NRI measure";
}

function normalizeFemaRatingLabel(value) {
  const token = String(value ?? "").trim();
  if (!token) return null;
  const normalized = token.toLowerCase();
  if (normalized === "very low" || normalized === "verylow" || normalized === "vlow") return "Very Low";
  if (normalized === "low") return "Low";
  if (normalized === "moderate" || normalized === "mod") return "Moderate";
  if (normalized === "high") return "High";
  if (normalized === "very high" || normalized === "veryhigh" || normalized === "vhigh") return "Very High";
  return token;
}

function formatCompactUsd(value) {
  const numeric = toFiniteNumericValue(value);
  if (numeric == null) return "No data";
  const abs = Math.abs(numeric);
  if (abs >= 1_000_000_000) {
    return `$${(numeric / 1_000_000_000).toFixed(1)}B`;
  }
  if (abs >= 1_000_000) {
    return `$${(numeric / 1_000_000).toFixed(1)}M`;
  }
  if (abs >= 1_000) {
    return `$${(numeric / 1_000).toFixed(1)}K`;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(numeric);
}

function formatFemaValue(value, measure = {}, { noDataLabel = "No data" } = {}) {
  const valueType = String(measure?.fema_value_type ?? measure?.value_type ?? "").trim().toLowerCase();
  const formatter = String(measure?.fema_tooltip_formatter ?? measure?.tooltip_formatter ?? "").trim().toLowerCase();
  const ratingValue = normalizeFemaRatingLabel(value);
  if (valueType === "rating" || formatter === "rating") {
    return ratingValue || noDataLabel;
  }

  const numeric = toFiniteNumericValue(value);
  if (numeric == null) return noDataLabel;

  if (valueType === "dollars" || formatter === "usd_compact" || String(measure?.unit ?? "").toUpperCase() === "USD") {
    return formatCompactUsd(numeric);
  }
  if (valueType === "count") {
    return numeric.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }
  if (valueType === "frequency") {
    return numeric.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (formatter === "decimal_1") {
    return numeric.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  }
  return numeric.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function formatSviLevelText(level) {
  const normalized = String(level ?? "").trim().toLowerCase();
  if (normalized === "low") return "low";
  if (normalized === "low-medium") return "low-medium";
  if (normalized === "medium-high") return "medium-high";
  if (normalized === "high") return "high";
  return "unknown";
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function buildUsdaHeatRenderModel(rawPoints, agg) {
  const aggToken = String(agg ?? "median").trim().toLowerCase();
  const points = Array.isArray(rawPoints) ? rawPoints : [];

  const validPoints = [];
  for (const point of points) {
    const lat = Number(point?.lat);
    const lon = Number(point?.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      continue;
    }

    const value = toFiniteNumericValue(point?.value);
    const normalizedValue = value == null
      ? null
      : (
        aggToken === "pct_flagged"
          ? value / 100
          : value
      );
    const tractCount = Number(point?.n);

    validPoints.push({
      lat,
      lon,
      value,
      normalizedValue,
      n: Number.isFinite(tractCount) ? Math.max(0, Math.round(tractCount)) : 0,
    });
  }

  const scalingValues = validPoints
    .map((point) => point.normalizedValue)
    .filter((value) => value != null)
    .sort((left, right) => left - right);

  const hasRobustScale = scalingValues.length >= 10;
  const p10 = hasRobustScale ? (quantile(scalingValues, 0.10) ?? scalingValues[0]) : null;
  const p90 = hasRobustScale
    ? (quantile(scalingValues, 0.90) ?? scalingValues[scalingValues.length - 1])
    : null;
  const spread = hasRobustScale
    ? Math.max(((p90 ?? 1) - (p10 ?? 0)), 1e-9)
    : 1;

  const heatLatLngs = [];
  const hoverPoints = [];
  let minIntensity = Number.POSITIVE_INFINITY;
  let maxIntensity = Number.NEGATIVE_INFINITY;
  for (const point of validPoints) {
    if (point.normalizedValue == null) {
      continue;
    }

    const densityFactor = clamp(
      Math.log(point.n + 1) / Math.log(200 + 1),
      0,
      1
    );

    let intensity;
    if (!hasRobustScale) {
      intensity = clamp(0.15 + (0.25 * densityFactor), 0.05, 0.4);
    } else {
      const clampedValue = clamp(point.normalizedValue, p10, p90);
      let scaled = (clampedValue - p10) / spread;
      scaled = clamp(scaled, 0, 1);
      scaled = Math.pow(scaled, 1.25);
      intensity = 0.15 + (0.85 * (scaled * (0.6 + (0.4 * densityFactor))));
      intensity = clamp(intensity, 0.05, 0.95);
    }

    minIntensity = Math.min(minIntensity, intensity);
    maxIntensity = Math.max(maxIntensity, intensity);

    heatLatLngs.push([
      point.lat,
      point.lon,
      clamp(Number.isFinite(intensity) ? intensity : 0.2, 0.05, 0.95),
    ]);
    hoverPoints.push({
      lat: point.lat,
      lon: point.lon,
      value: point.value,
      n: point.n,
    });
  }

  return {
    heatLatLngs,
    hoverPoints,
    stats: {
      pointCount: validPoints.length,
      p10,
      p90,
      minIntensity: Number.isFinite(minIntensity) ? minIntensity : null,
      maxIntensity: Number.isFinite(maxIntensity) ? maxIntensity : null,
    },
  };
}

function boundsToPaddedBbox(bounds, zoom) {
  const west = bounds.getWest();
  const south = bounds.getSouth();
  const east = bounds.getEast();
  const north = bounds.getNorth();

  const dx = east - west;
  const dy = north - south;
  const padX = dx * 0.15;
  const padY = dy * 0.15;

  const paddedWest = clamp(west - padX, -180, 180);
  const paddedSouth = clamp(south - padY, -90, 90);
  const paddedEast = clamp(east + padX, -180, 180);
  const paddedNorth = clamp(north + padY, -90, 90);

  void zoom;
  return [
    paddedWest.toFixed(BBOX_PRECISION),
    paddedSouth.toFixed(BBOX_PRECISION),
    paddedEast.toFixed(BBOX_PRECISION),
    paddedNorth.toFixed(BBOX_PRECISION),
  ].join(",");
}

function makeCacheKey(layer, year, measureId, typeId, bboxString) {
  return `${layer}|${year}|${measureId}|${typeId}|${bboxString}`;
}

function getUsdaHeatZoomBucket(zoom) {
  const normalizedZoom = Math.max(0, Number(zoom) || 0);
  return normalizedZoom <= 6 ? "z0_6" : "z7_9";
}

function getHeatStyle(zoom) {
  const normalizedZoom = Number.isFinite(Number(zoom)) ? Number(zoom) : 0;

  if (normalizedZoom <= 4) {
    return { radius: 12, blur: 10 };
  }

  if (normalizedZoom <= 6) {
    return { radius: 16, blur: 14 };
  }

  if (normalizedZoom <= 8) {
    return { radius: 20, blur: 18 };
  }

  if (normalizedZoom <= 9) {
    return { radius: 24, blur: 20 };
  }

  return { radius: 28, blur: 22 };
}

function getUsdaSimplifyToleranceDegrees(zoom) {
  const normalizedZoom = Math.max(0, Number(zoom) || 0);
  if (normalizedZoom <= 5) return 0.04;
  if (normalizedZoom === 6) return 0.03;
  if (normalizedZoom === 7) return 0.02;
  if (normalizedZoom === 8) return 0.015;
  if (normalizedZoom === 9) return 0.01;
  return 0.005;
}

function darkenHexColor(hexColor, amount = 0.15) {
  const color = String(hexColor ?? "").trim();
  const match = color.match(/^#([0-9a-f]{6})$/i);
  if (!match) return "#1f2937";
  const hex = match[1];
  const clampChannel = (value) => Math.max(0, Math.min(255, value));
  const toHex = (value) => clampChannel(Math.round(value)).toString(16).padStart(2, "0");
  const ratio = Math.max(0, Math.min(0.95, Number(amount) || 0));
  const red = parseInt(hex.slice(0, 2), 16);
  const green = parseInt(hex.slice(2, 4), 16);
  const blue = parseInt(hex.slice(4, 6), 16);
  return `#${toHex(red * (1 - ratio))}${toHex(green * (1 - ratio))}${toHex(blue * (1 - ratio))}`;
}

function roundBboxString(value, precision = 3) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const parts = text.split(",").map((part) => Number(part.trim()));
  if (parts.length !== 4 || parts.some((part) => !Number.isFinite(part))) {
    return text;
  }
  return parts.map((part) => part.toFixed(precision)).join(",");
}

function parseErrorBody(response) {
  return response
    .text()
    .then((body) => body || "No body")
    .catch(() => "No body");
}

function isAbortLikeError(error, signal) {
  if (signal?.aborted) return true;
  if (!error) return false;
  const name = String(error?.name ?? "");
  const message = String(error?.message ?? "");
  return (
    name === "AbortError"
    || /aborted without reason/i.test(message)
    || /operation was aborted/i.test(message)
  );
}

function toLeafletBounds(value) {
  if (!value) return null;

  if (Array.isArray(value) && value.length === 2) {
    const sw = value[0];
    const ne = value[1];
    if (Array.isArray(sw) && Array.isArray(ne) && sw.length === 2 && ne.length === 2) {
      const south = Number(sw[0]);
      const west = Number(sw[1]);
      const north = Number(ne[0]);
      const east = Number(ne[1]);
      if (
        Number.isFinite(south)
        && Number.isFinite(west)
        && Number.isFinite(north)
        && Number.isFinite(east)
        && south < north
        && west < east
      ) {
        return [[south, west], [north, east]];
      }
    }
  }

  if (Array.isArray(value) && value.length === 4) {
    const west = Number(value[0]);
    const south = Number(value[1]);
    const east = Number(value[2]);
    const north = Number(value[3]);
    if (
      Number.isFinite(south)
      && Number.isFinite(west)
      && Number.isFinite(north)
      && Number.isFinite(east)
      && south < north
      && west < east
    ) {
      return [[south, west], [north, east]];
    }
  }

  if (typeof value === "object") {
    const south = Number(value.min_lat ?? value.south ?? value.south_lat);
    const west = Number(value.min_lon ?? value.west ?? value.west_lon);
    const north = Number(value.max_lat ?? value.north ?? value.north_lat);
    const east = Number(value.max_lon ?? value.east ?? value.east_lon);
    if (
      Number.isFinite(south)
      && Number.isFinite(west)
      && Number.isFinite(north)
      && Number.isFinite(east)
      && south < north
      && west < east
    ) {
      return [[south, west], [north, east]];
    }
  }

  return null;
}

function MapViewportWatcher({ onViewportChange, onMapReady }) {
  const map = useMapEvents({
    moveend() {
      onViewportChange(map.getZoom(), map.getBounds());
    },
    zoomend() {
      requestAnimationFrame(() => {
        map.invalidateSize({ pan: false });
      });
      onViewportChange(map.getZoom(), map.getBounds());
    },
    resize() {
      requestAnimationFrame(() => {
        map.invalidateSize({ pan: false });
      });
    },
  });

  useEffect(() => {
    if (typeof onMapReady === "function") {
      onMapReady(map);
    }
    requestAnimationFrame(() => {
      map.invalidateSize({ pan: false });
    });
    onViewportChange(map.getZoom(), map.getBounds());
  }, [map, onMapReady, onViewportChange]);

  return null;
}

function UsdaHeatLayer({ points, options, pane = "overlayPane" }) {
  const map = useMap();
  const layerRef = useRef(null);

  useEffect(() => {
    if (typeof L.heatLayer !== "function") {
      console.warn("Leaflet.heat is not available; USDA heat layer cannot render.");
      return () => {};
    }

    const initialStyle = getHeatStyle(map.getZoom());
    const layer = L.heatLayer(Array.isArray(points) ? points : [], {
      ...(options ?? {}),
      radius: initialStyle.radius,
      blur: initialStyle.blur,
      pane,
    });
    layer.addTo(map);
    layerRef.current = layer;

    const handleZoomEnd = () => {
      const currentLayer = layerRef.current;
      if (!currentLayer || typeof currentLayer.setOptions !== "function") {
        return;
      }
      const nextStyle = getHeatStyle(map.getZoom());
      currentLayer.setOptions({
        radius: nextStyle.radius,
        blur: nextStyle.blur,
      });
      if (typeof currentLayer.redraw === "function") {
        currentLayer.redraw();
      }
    };
    map.on("zoomend", handleZoomEnd);

    return () => {
      map.off("zoomend", handleZoomEnd);
      if (layerRef.current) {
        map.removeLayer(layerRef.current);
        layerRef.current = null;
      }
    };
  }, [map, pane]);

  useEffect(() => {
    const layer = layerRef.current;
    if (!layer) return;
    if (typeof layer.setOptions === "function") {
      layer.setOptions({
        ...(options ?? {}),
        pane,
      });
    }
    if (typeof layer.setLatLngs === "function") {
      layer.setLatLngs(Array.isArray(points) ? points : []);
    }
    if (typeof layer.redraw === "function") {
      layer.redraw();
    }
  }, [options, pane, points]);

  return null;
}

function UsdaHeatHoverWatcher({ enabled, points, onHover }) {
  const lastHoverKeyRef = useRef("");

  const emitHover = useCallback((candidate) => {
    const nextKey = candidate
      ? `${candidate.lat}|${candidate.lon}|${candidate.value}|${candidate.n}`
      : "";
    if (lastHoverKeyRef.current === nextKey) {
      return;
    }
    lastHoverKeyRef.current = nextKey;
    onHover(candidate);
  }, [onHover]);

  const map = useMapEvents({
    mousemove(event) {
      if (!enabled || !Array.isArray(points) || points.length === 0) {
        emitHover(null);
        return;
      }

      const cursor = map.latLngToContainerPoint(event.latlng);
      const thresholdPx = map.getZoom() <= 6 ? 34 : 24;
      const thresholdSq = thresholdPx * thresholdPx;

      let nearest = null;
      let nearestSq = Number.POSITIVE_INFINITY;
      for (const point of points) {
        const projected = map.latLngToContainerPoint([point.lat, point.lon]);
        const dx = projected.x - cursor.x;
        const dy = projected.y - cursor.y;
        const distanceSq = (dx * dx) + (dy * dy);
        if (distanceSq < nearestSq) {
          nearestSq = distanceSq;
          nearest = point;
        }
      }

      if (nearest && nearestSq <= thresholdSq) {
        emitHover(nearest);
      } else {
        emitHover(null);
      }
    },
    mouseout() {
      emitHover(null);
    },
    zoomstart() {
      emitHover(null);
    },
    movestart() {
      emitHover(null);
    },
  });

  useEffect(() => {
    if (!enabled || !Array.isArray(points) || points.length === 0) {
      emitHover(null);
    }
  }, [emitHover, enabled, points]);

  return null;
}

function UsdaMeasureSelector({
  selectedMeasureId,
  selectedMeasure,
  isOpen,
  onToggleOpen,
  onClose,
  searchValue,
  onSearchChange,
  includeArchive,
  onToggleIncludeArchive,
  showStateMeasures,
  onToggleShowStateMeasures,
  recentMeasures,
  recommendedMeasures,
  commonMeasures,
  categoryGroups,
  archiveMeasures,
  stateMeasures,
  onSelectMeasure,
}) {
  const selectorButtonStyle = {
    minHeight: 36,
    borderRadius: 8,
    border: "1px solid #c4d2e0",
    background: "#ffffff",
    color: "#0f2d46",
    fontSize: 12,
    fontWeight: 600,
    padding: "6px 10px",
    width: "100%",
  };
  const selectedLabel = getUsdaPlainLabel(
    selectedMeasure?.measure_id ?? selectedMeasureId,
    getMeasureDisplayName(selectedMeasure)
  );
  const selectedText = selectedLabel || "Select USDA measure";
  const hasAnyMeasures = (
    recentMeasures.length > 0
    || recommendedMeasures.length > 0
    || commonMeasures.length > 0
    || categoryGroups.some((group) => group.measures.length > 0)
    || archiveMeasures.length > 0
    || stateMeasures.length > 0
  );

  const renderPill = (label, styles = {}) => (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: 999,
        border: "1px solid #cbd5e1",
        background: "#f8fafc",
        color: "#334155",
        fontSize: 10,
        fontWeight: 700,
        padding: "1px 6px",
        ...styles,
      }}
    >
      {label}
    </span>
  );

  const renderMeasureButton = (measure) => {
    const measureId = String(measure?.measure_id ?? "").trim();
    if (!measureId) return null;
    const isSelected = measureId === selectedMeasureId;
    const yearValue = Number.isFinite(Number(measure?.usda_year))
      ? Number(measure.usda_year)
      : null;
    const isState = String(measure?.usda_level ?? measure?.level ?? "county").toLowerCase() === "state";
    const isArchive = Boolean(measure?.usda_is_archival ?? measure?.is_archival);
    const label = getUsdaPlainLabel(measureId, getMeasureDisplayName(measure));
    const description = String(measure?.description ?? "").trim();
    return (
      <button
        key={measureId}
        type="button"
        onClick={() => onSelectMeasure(measureId)}
        style={{
          display: "grid",
          gap: 4,
          width: "100%",
          textAlign: "left",
          padding: "8px 10px",
          borderRadius: 8,
          border: `1px solid ${isSelected ? "#1d4ed8" : "#dbe3eb"}`,
          background: isSelected ? "#eff6ff" : "#ffffff",
          cursor: "pointer",
        }}
      >
        <div style={{ color: "#0f172a", fontWeight: isSelected ? 700 : 600, fontSize: 12 }}>
          {label}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {renderPill(isState ? "State" : "County")}
          {isArchive ? renderPill("Archive", {
            border: "1px solid #f59e0b",
            background: "#fff7ed",
            color: "#b45309",
          }) : null}
          {yearValue != null ? renderPill(String(yearValue), {
            border: "1px solid #bfdbfe",
            background: "#eff6ff",
            color: "#1d4ed8",
          }) : null}
        </div>
        {description ? (
          <div style={{ color: "#475569", fontSize: 11 }}>
            {truncateText(description, 140)}
          </div>
        ) : null}
      </button>
    );
  };

  const sectionTitleStyle = {
    fontSize: 11,
    fontWeight: 700,
    color: "#0f2d46",
    letterSpacing: 0.2,
    textTransform: "uppercase",
  };

  return (
    <div style={{ display: "grid", gap: 6, position: "relative" }}>
      <button
        type="button"
        aria-label="Measure"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        onClick={onToggleOpen}
        style={{
          ...selectorButtonStyle,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          textAlign: "left",
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%" }}>
          {selectedText}
        </span>
        <span style={{ marginLeft: 8, color: "#64748b", fontSize: 11 }}>▼</span>
      </button>

      {isOpen ? (
        <div
          role="dialog"
          aria-label="USDA measure selector"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            zIndex: 2600,
            border: "1px solid #dbe3eb",
            borderRadius: 10,
            background: "#ffffff",
            boxShadow: "0 14px 30px rgba(15, 23, 42, 0.16)",
            padding: 10,
            display: "grid",
            gap: 8,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <input
              type="search"
              placeholder="Search measures..."
              value={searchValue}
              onChange={(event) => onSearchChange(event.target.value)}
              autoFocus
              style={{
                flex: 1,
                height: 30,
                borderRadius: 8,
                border: "1px solid #cbd5e1",
                padding: "0 10px",
                fontSize: 12,
              }}
            />
            <button
              type="button"
              onClick={onClose}
              style={{
                height: 30,
                borderRadius: 8,
                border: "1px solid #cbd5e1",
                background: "#f8fafc",
                color: "#334155",
                fontSize: 11,
                fontWeight: 600,
                padding: "0 8px",
                cursor: "pointer",
              }}
            >
              Close
            </button>
          </div>

          <div style={{ display: "grid", gap: 6 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#334155" }}>
              <input
                type="checkbox"
                checked={includeArchive}
                onChange={(event) => onToggleIncludeArchive(Boolean(event.target.checked))}
              />
              Include archive / older years
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#334155" }}>
              <input
                type="checkbox"
                checked={showStateMeasures}
                onChange={(event) => onToggleShowStateMeasures(Boolean(event.target.checked))}
              />
              Show state-level measures
            </label>
          </div>

          <div style={{ maxHeight: 420, overflowY: "auto", display: "grid", gap: 10, paddingRight: 2 }}>
            {recentMeasures.length > 0 ? (
              <section style={{ display: "grid", gap: 6 }}>
                <div style={sectionTitleStyle}>Recent</div>
                <div style={{ display: "grid", gap: 6 }}>
                  {recentMeasures.map((measure) => renderMeasureButton(measure))}
                </div>
              </section>
            ) : null}

            <section style={{ display: "grid", gap: 6 }}>
              <div style={sectionTitleStyle}>Recommended</div>
              <div style={{ display: "grid", gap: 6 }}>
                {recommendedMeasures.length > 0
                  ? recommendedMeasures.map((measure) => renderMeasureButton(measure))
                  : <div style={{ color: "#64748b", fontSize: 11 }}>No recommended measures match.</div>}
              </div>
            </section>

            <section style={{ display: "grid", gap: 6 }}>
              <div style={sectionTitleStyle}>Common</div>
              <div style={{ display: "grid", gap: 6 }}>
                {commonMeasures.length > 0
                  ? commonMeasures.map((measure) => renderMeasureButton(measure))
                  : <div style={{ color: "#64748b", fontSize: 11 }}>No common county measures available.</div>}
              </div>
            </section>

            <section style={{ display: "grid", gap: 6 }}>
              <div style={sectionTitleStyle}>By Category</div>
              {categoryGroups.length > 0 ? categoryGroups.map((group, index) => (
                <details key={`usda-category-${group.category}`} open={index === 0}>
                  <summary style={{ cursor: "pointer", color: "#0f172a", fontWeight: 600 }}>
                    {group.category} ({group.measures.length})
                  </summary>
                  <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
                    {group.measures.map((measure) => renderMeasureButton(measure))}
                  </div>
                </details>
              )) : (
                <div style={{ color: "#64748b", fontSize: 11 }}>No category matches.</div>
              )}
            </section>

            <details>
              <summary style={{ cursor: "pointer", color: "#0f172a", fontWeight: 700 }}>
                Archive / Year ({archiveMeasures.length})
              </summary>
              <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
                {archiveMeasures.length > 0
                  ? archiveMeasures.map((measure) => renderMeasureButton(measure))
                  : <div style={{ color: "#64748b", fontSize: 11 }}>Enable archive toggle to load more.</div>}
              </div>
            </details>

            <details>
              <summary style={{ cursor: "pointer", color: "#0f172a", fontWeight: 700 }}>
                State-level measures ({stateMeasures.length})
              </summary>
              <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
                {stateMeasures.length > 0
                  ? stateMeasures.map((measure) => renderMeasureButton(measure))
                  : <div style={{ color: "#64748b", fontSize: 11 }}>Enable state-level toggle to load more.</div>}
              </div>
            </details>

            {!hasAnyMeasures ? (
              <div style={{ color: "#64748b", fontSize: 11 }}>No USDA measures match the current filters.</div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function FemaMeasureSelector({
  selectedMeasureId,
  selectedMeasure,
  isOpen,
  onToggleOpen,
  onClose,
  searchValue,
  onSearchChange,
  groupedMeasures,
  totalVisibleMeasures,
  onSelectMeasure,
}) {
  const selectorButtonStyle = {
    minHeight: 36,
    borderRadius: 8,
    border: "1px solid #c4d2e0",
    background: "#ffffff",
    color: "#0f2d46",
    fontSize: 12,
    fontWeight: 600,
    padding: "6px 10px",
    width: "100%",
  };
  const selectedLabel = getFemaMeasureLabel(selectedMeasure, selectedMeasureId);
  const selectedText = selectedLabel || "Select FEMA measure";

  const renderPill = (label, styles = {}) => (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: 999,
        border: "1px solid #cbd5e1",
        background: "#f8fafc",
        color: "#334155",
        fontSize: 10,
        fontWeight: 700,
        padding: "1px 6px",
        ...styles,
      }}
    >
      {label}
    </span>
  );

  const renderMeasureButton = (measure) => {
    const measureId = String(measure?.measure_id ?? "").trim();
    if (!measureId) return null;
    const isSelected = measureId === selectedMeasureId;
    const label = getFemaMeasureLabel(measure, measureId);
    const description = String(measure?.description ?? "").trim();
    const valueType = String(measure?.fema_value_type ?? "").trim().toLowerCase();
    const hazardName = String(measure?.fema_hazard_name ?? "").trim();
    const valueTypeLabel = valueType
      ? valueType.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase())
      : "";
    return (
      <button
        key={measureId}
        type="button"
        onClick={() => onSelectMeasure(measureId)}
        style={{
          display: "grid",
          gap: 4,
          width: "100%",
          textAlign: "left",
          padding: "8px 10px",
          borderRadius: 8,
          border: `1px solid ${isSelected ? "#1d4ed8" : "#dbe3eb"}`,
          background: isSelected ? "#eff6ff" : "#ffffff",
          cursor: "pointer",
        }}
      >
        <div style={{ color: "#0f172a", fontWeight: isSelected ? 700 : 600, fontSize: 12 }}>
          {label}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {valueTypeLabel ? renderPill(valueTypeLabel) : null}
          {hazardName ? renderPill(hazardName, {
            border: "1px solid #bfdbfe",
            background: "#eff6ff",
            color: "#1d4ed8",
          }) : null}
        </div>
        {description ? (
          <div style={{ color: "#475569", fontSize: 11 }}>
            {truncateText(description, 140)}
          </div>
        ) : null}
      </button>
    );
  };

  const hasAnyMeasures = totalVisibleMeasures > 0;

  return (
    <div style={{ display: "grid", gap: 6, position: "relative" }}>
      <button
        type="button"
        aria-label="Measure"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        onClick={onToggleOpen}
        style={{
          ...selectorButtonStyle,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          textAlign: "left",
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%" }}>
          {selectedText}
        </span>
        <span style={{ marginLeft: 8, color: "#64748b", fontSize: 11 }}>▼</span>
      </button>

      {isOpen ? (
        <div
          role="dialog"
          aria-label="FEMA measure selector"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            zIndex: 2600,
            border: "1px solid #dbe3eb",
            borderRadius: 10,
            background: "#ffffff",
            boxShadow: "0 14px 30px rgba(15, 23, 42, 0.16)",
            padding: 10,
            display: "grid",
            gap: 8,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <input
              type="search"
              placeholder="Search FEMA measures..."
              value={searchValue}
              onChange={(event) => onSearchChange(event.target.value)}
              autoFocus
              style={{
                flex: 1,
                height: 30,
                borderRadius: 8,
                border: "1px solid #cbd5e1",
                padding: "0 10px",
                fontSize: 12,
              }}
            />
            <button
              type="button"
              onClick={onClose}
              style={{
                height: 30,
                borderRadius: 8,
                border: "1px solid #cbd5e1",
                background: "#f8fafc",
                color: "#334155",
                fontSize: 11,
                fontWeight: 600,
                padding: "0 8px",
                cursor: "pointer",
              }}
            >
              Close
            </button>
          </div>

          <div style={{ maxHeight: 420, overflowY: "auto", display: "grid", gap: 10, paddingRight: 2 }}>
            {groupedMeasures.length > 0 ? groupedMeasures.map((group, groupIndex) => (
              <details key={`fema-group-${group.group}`} open={groupIndex === 0}>
                <summary style={{ cursor: "pointer", color: "#0f172a", fontWeight: 700 }}>
                  {group.group} ({group.count})
                </summary>
                <div style={{ display: "grid", gap: 8, marginTop: 6 }}>
                  {group.subgroups.map((subgroup, subgroupIndex) => (
                    <details key={`fema-subgroup-${group.group}-${subgroup.subgroup}`} open={groupIndex === 0 && subgroupIndex === 0}>
                      <summary style={{ cursor: "pointer", color: "#0f172a", fontWeight: 600 }}>
                        {subgroup.subgroup} ({subgroup.measures.length})
                      </summary>
                      <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
                        {subgroup.measures.map((measure) => renderMeasureButton(measure))}
                      </div>
                    </details>
                  ))}
                </div>
              </details>
            )) : null}
            {!hasAnyMeasures ? (
              <div style={{ color: "#64748b", fontSize: 11 }}>
                No FEMA measures match the current search.
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PlacesMeasureSelector({
  selectedMeasureId,
  selectedMeasure,
  isOpen,
  onToggleOpen,
  onClose,
  searchValue,
  onSearchChange,
  categoryGroups,
  totalVisibleMeasures,
  onSelectMeasure,
}) {
  const selectorButtonStyle = {
    minHeight: 36,
    borderRadius: 8,
    border: "1px solid #c4d2e0",
    background: "#ffffff",
    color: "#0f2d46",
    fontSize: 12,
    fontWeight: 600,
    padding: "6px 10px",
    width: "100%",
  };
  const selectedLabel = getMeasureDisplayName(selectedMeasure);
  const selectedText = selectedMeasureId
    ? `${selectedMeasureId}${selectedLabel ? ` - ${selectedLabel}` : ""}`
    : "Select PLACES measure";

  const renderMeasureButton = (measure) => {
    const measureId = String(measure?.measure_id ?? "").trim();
    if (!measureId) return null;
    const isSelected = measureId === selectedMeasureId;
    const label = getMeasureDisplayName(measure);
    const optionLabel = `${measureId}${label ? ` - ${label}` : ""}`;
    const description = String(measure?.short_question_text ?? measure?.description ?? "").trim();
    return (
      <button
        key={measureId}
        type="button"
        onClick={() => onSelectMeasure(measureId)}
        style={{
          display: "grid",
          gap: 4,
          width: "100%",
          textAlign: "left",
          padding: "8px 10px",
          borderRadius: 8,
          border: `1px solid ${isSelected ? "#1d4ed8" : "#dbe3eb"}`,
          background: isSelected ? "#eff6ff" : "#ffffff",
          cursor: "pointer",
        }}
      >
        <div style={{ color: "#0f172a", fontWeight: isSelected ? 700 : 600, fontSize: 12 }}>
          {optionLabel}
        </div>
        {description ? (
          <div style={{ color: "#475569", fontSize: 11 }}>
            {truncateText(description, 140)}
          </div>
        ) : null}
      </button>
    );
  };

  return (
    <div style={{ display: "grid", gap: 6, position: "relative" }}>
      <button
        type="button"
        aria-label="Measure"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        onClick={onToggleOpen}
        style={{
          ...selectorButtonStyle,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          textAlign: "left",
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%" }}>
          {selectedText}
        </span>
        <span style={{ marginLeft: 8, color: "#64748b", fontSize: 11 }}>▼</span>
      </button>

      {isOpen ? (
        <div
          role="dialog"
          aria-label="PLACES measure selector"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            zIndex: 2600,
            border: "1px solid #dbe3eb",
            borderRadius: 10,
            background: "#ffffff",
            boxShadow: "0 14px 30px rgba(15, 23, 42, 0.16)",
            padding: 10,
            display: "grid",
            gap: 8,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <input
              type="search"
              placeholder="Search PLACES measures..."
              value={searchValue}
              onChange={(event) => onSearchChange(event.target.value)}
              autoFocus
              style={{
                flex: 1,
                height: 30,
                borderRadius: 8,
                border: "1px solid #cbd5e1",
                padding: "0 10px",
                fontSize: 12,
              }}
            />
            <button
              type="button"
              onClick={onClose}
              style={{
                height: 30,
                borderRadius: 8,
                border: "1px solid #cbd5e1",
                background: "#f8fafc",
                color: "#334155",
                fontSize: 11,
                fontWeight: 600,
                padding: "0 8px",
                cursor: "pointer",
              }}
            >
              Close
            </button>
          </div>

          <div style={{ maxHeight: 420, overflowY: "auto", display: "grid", gap: 10, paddingRight: 2 }}>
            {categoryGroups.length > 0 ? categoryGroups.map((group, index) => (
              <details key={`places-category-${group.category}`} open={index === 0}>
                <summary style={{ cursor: "pointer", color: "#0f172a", fontWeight: 700 }}>
                  {group.category} ({group.measures.length})
                </summary>
                <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
                  {group.measures.map((measure) => renderMeasureButton(measure))}
                </div>
              </details>
            )) : null}
            {totalVisibleMeasures === 0 ? (
              <div style={{ color: "#64748b", fontSize: 11 }}>
                No PLACES measures match the current search.
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MapToolbar({
  defaultCenter,
  defaultZoom,
  baseMapOptions = [],
  selectedBaseMapId,
  onBaseMapChange,
  compactLayout = false,
  rightInset = 16,
  hasSelectedLocation = false,
  onZoomToSelected,
  onAnalyzeSelectedArea,
  zoomToSelectedLabel = "Zoom to selected area",
  zoomToSelectedRef,
  profileGenerating = false,
  profileTarget,
  onOpenProfile,
}) {
  const map = useMap();
  const profileEnabled = Boolean(profileTarget?.enabled && profileTarget?.href);
  const profileTooltip = profileEnabled
    ? "Open County/Tract Profile"
    : "Select a county or tract first";
  const mapTypeSelectStyle = {
    height: 32,
    minWidth: 160,
    padding: "0 10px",
    borderRadius: 8,
    border: "1px solid #C4D2E0",
    background: "#ffffff",
    color: "#0F2D46",
    fontSize: 12,
    fontWeight: 600,
  };

  return (
    <div
      style={{
        position: "absolute",
        left: compactLayout ? 16 : 392,
        right: compactLayout ? 16 : rightInset,
        bottom: 86,
        zIndex: 2300,
        display: "grid",
        gap: 6,
        justifyContent: "flex-start",
        alignItems: "stretch",
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: 0.3,
          color: "#0F2D46",
          textTransform: "uppercase",
        }}
      >
        Map Tools
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
        <button
          type="button"
          onClick={() => map.setView(defaultCenter, defaultZoom)}
          className="chip-secondary-btn"
        >
          Home
        </button>
        <button
          type="button"
          onClick={() => map.zoomIn()}
          className="chip-secondary-btn"
        >
          Zoom In
        </button>
        <button
          type="button"
          onClick={() => map.zoomOut()}
          className="chip-secondary-btn"
        >
          Zoom Out
        </button>
        <button
          type="button"
          ref={zoomToSelectedRef}
          onClick={onZoomToSelected}
          disabled={!hasSelectedLocation}
          className={`chip-secondary-btn ${hasSelectedLocation ? "" : "is-disabled"}`}
        >
          {zoomToSelectedLabel}
        </button>
        <button
          type="button"
          onClick={onAnalyzeSelectedArea}
          disabled={!hasSelectedLocation || profileGenerating}
          className="chip-primary-btn"
        >
          {profileGenerating ? "Analyzing..." : "Analyze this area"}
        </button>
        <button
          type="button"
          onClick={onOpenProfile}
          disabled={!profileEnabled}
          aria-disabled={!profileEnabled}
          title={profileTooltip}
          className={`chip-secondary-btn ${profileEnabled ? "" : "is-disabled"}`}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              <path
                d="M3 1.5h6.5L13.5 5v9a.5.5 0 0 1-.5.5H3a.5.5 0 0 1-.5-.5V2a.5.5 0 0 1 .5-.5zm6 .8V5h2.7L9 2.3zM5 7h6v1H5V7zm0 2.5h6v1H5v-1zm0 2.5h4v1H5v-1z"
                fill="currentColor"
              />
            </svg>
            Open County/Tract Profile
          </span>
        </button>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6, marginLeft: 4 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#0F2D46", letterSpacing: 0.2 }}>
            Base map
          </span>
          <select
            value={selectedBaseMapId}
            onChange={(event) => onBaseMapChange?.(event.target.value)}
            style={mapTypeSelectStyle}
            aria-label="Select base map"
          >
            {baseMapOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}

function SviRankBar({ value }) {
  const numeric = toFiniteNumericValue(value);
  const clamped = numeric == null ? null : clamp(numeric, 0, 1);
  const dotLeftPercent = clamped == null ? null : clamped * 100;

  return (
    <div style={{ marginTop: 8, marginBottom: 6 }}>
      <div
        style={{
          position: "relative",
          height: 12,
          borderRadius: 999,
          background: "linear-gradient(90deg, #F2FBFB 0%, #42A6A8 65%, #0F2D46 100%)",
          border: "1px solid #C4D2E0",
        }}
      >
        {[0.25, 0.5, 0.75].map((tick) => (
          <span
            key={`svi-rank-tick-${tick}`}
            style={{
              position: "absolute",
              top: -2,
              left: `${tick * 100}%`,
              width: 1,
              height: 16,
              background: "#64748b",
              opacity: 0.75,
            }}
          />
        ))}
        {dotLeftPercent == null ? null : (
          <span
            style={{
              position: "absolute",
              top: "50%",
              left: `${dotLeftPercent}%`,
              width: 14,
              height: 14,
              borderRadius: "50%",
              background: "#0F2D46",
              border: "2px solid #ffffff",
              boxShadow: "0 0 0 1px rgba(15, 45, 70, 0.3)",
              transform: "translate(-50%, -50%)",
            }}
          />
        )}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: 4,
          color: "#64748b",
          fontSize: 11,
          lineHeight: 1.2,
        }}
      >
        <span>0</span>
        <span>0.25</span>
        <span>0.50</span>
        <span>0.75</span>
        <span>1.0</span>
      </div>
    </div>
  );
}

function MiniHistoryChart({
  series,
  startYear = HISTORY_START_YEAR,
  endYear = HISTORY_END_YEAR,
  yLabel = "Value",
}) {
  const width = 260;
  const height = 150;
  const marginTop = 12;
  const marginRight = 14;
  const marginBottom = 30;
  const marginLeft = 42;
  const plotWidth = width - marginLeft - marginRight;
  const plotHeight = height - marginTop - marginBottom;

  const years = [];
  for (let year = startYear; year <= endYear; year += 1) {
    years.push(year);
  }

  const valueByYear = new Map();
  for (const point of series ?? []) {
    const year = Number(point?.year);
    const value = point?.value;
    if (Number.isFinite(year)) {
      valueByYear.set(year, value == null ? null : Number(value));
    }
  }

  const points = years.map((year, index) => {
    const x =
      marginLeft + (years.length > 1 ? (index / (years.length - 1)) * plotWidth : 0);
    const value = valueByYear.has(year) ? valueByYear.get(year) : null;
    return { year, x, value };
  });

  const numericValues = points
    .map((point) => point.value)
    .filter((value) => Number.isFinite(value));
  const hasData = numericValues.length > 0;

  const minValue = hasData ? Math.min(...numericValues) : 0;
  const maxValue = hasData ? Math.max(...numericValues) : 1;
  const paddedMin = hasData ? minValue - Math.max((maxValue - minValue) * 0.1, 0.5) : 0;
  const paddedMax = hasData ? maxValue + Math.max((maxValue - minValue) * 0.1, 0.5) : 1;
  const valueRange = Math.max(paddedMax - paddedMin, 1);

  const yForValue = (value) =>
    marginTop + ((paddedMax - value) / valueRange) * plotHeight;

  let path = "";
  let segmentOpen = false;
  for (const point of points) {
    if (!Number.isFinite(point.value)) {
      segmentOpen = false;
      continue;
    }
    const command = segmentOpen ? "L" : "M";
    path += `${command}${point.x},${yForValue(point.value)} `;
    segmentOpen = true;
  }

  const yTicks = [];
  const yTickCount = 4;
  for (let i = 0; i <= yTickCount; i += 1) {
    const ratio = i / yTickCount;
    const value = paddedMax - ratio * valueRange;
    yTicks.push({
      value,
      y: marginTop + ratio * plotHeight,
    });
  }

  return (
    <div style={{ marginTop: 8 }}>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`History chart from ${startYear} to ${endYear}`}
      >
        <line
          x1={marginLeft}
          y1={marginTop + plotHeight}
          x2={width - marginRight}
          y2={marginTop + plotHeight}
          stroke="#475569"
          strokeWidth={1}
        />
        <line
          x1={marginLeft}
          y1={marginTop}
          x2={marginLeft}
          y2={marginTop + plotHeight}
          stroke="#475569"
          strokeWidth={1}
        />

        {yTicks.map((tick) => (
          <g key={`y-${tick.y}`}>
            <line
              x1={marginLeft}
              y1={tick.y}
              x2={width - marginRight}
              y2={tick.y}
              stroke="#e2e8f0"
              strokeWidth={1}
            />
            <text
              x={marginLeft - 6}
              y={tick.y + 3}
              textAnchor="end"
              fontSize={9}
              fill="#64748b"
            >
              {tick.value.toFixed(1)}
            </text>
          </g>
        ))}

        {points.map((point) => (
          <text
            key={`x-${point.year}`}
            x={point.x}
            y={height - 10}
            textAnchor="middle"
            fontSize={9}
            fill="#64748b"
          >
            {point.year}
          </text>
        ))}

        {path ? (
          <path
            d={path.trim()}
            fill="none"
            stroke="#2563eb"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}

        {points
          .filter((point) => Number.isFinite(point.value))
          .map((point) => (
            <circle
              key={`point-${point.year}`}
              cx={point.x}
              cy={yForValue(point.value)}
              r={2.8}
              fill="#1d4ed8"
            />
          ))}

        <text
          x={marginLeft + plotWidth / 2}
          y={height - 2}
          textAnchor="middle"
          fontSize={10}
          fill="#334155"
        >
          Year
        </text>
        <text
          x={12}
          y={marginTop + plotHeight / 2}
          transform={`rotate(-90 12 ${marginTop + plotHeight / 2})`}
          textAnchor="middle"
          fontSize={10}
          fill="#334155"
        >
          {yLabel}
        </text>
      </svg>
      {!hasData ? (
        <div style={{ fontSize: 11, color: "#64748b" }}>
          No values available in this period.
        </div>
      ) : null}
    </div>
  );
}

export default function App() {
  const [assistantInput, setAssistantInput] = useState("");
  const [assistantMessages, setAssistantMessages] = useState([]);
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [assistantScrollSignal, setAssistantScrollSignal] = useState(0);
  const [assistantOpenSignal, setAssistantOpenSignal] = useState(0);
  const [assistantMapContext, setAssistantMapContext] = useState(null);
  const [analyzeGenerating, setAnalyzeGenerating] = useState(false);
  const [profilePanelOpen, setProfilePanelOpen] = useState(false);
  const [activeProfileId, setActiveProfileId] = useState(null);
  const [profileGenerating, setProfileGenerating] = useState(false);
  const [placesProfileContext, setPlacesProfileContext] = useState({
    year: null,
    measureId: "CASTHMA",
    dataValueTypeId: "CrdPrv",
  });

  const [selectedDataSource, setSelectedDataSource] = useState(DATA_SOURCES.PLACES);
  const [selectedHpsaDomain, setSelectedHpsaDomain] = useState("pc");
  const [selectedCmsAgeGroup, setSelectedCmsAgeGroup] = useState(CMS_AGE_OPTIONS[0].value);
  const [cdcBasis, setCdcBasis] = useState("prime");
  const [cdcGeography, setCdcGeography] = useState("county");
  const [cdcAssistanceType, setCdcAssistanceType] = useState("");
  const [cdcFiscalYear, setCdcFiscalYear] = useState("");
  const [cdcAwardingOffice, setCdcAwardingOffice] = useState("");
  const [cdcFundingOffice, setCdcFundingOffice] = useState("");
  const [cdcCenter, setCdcCenter] = useState("");
  const [cdcStateFilter, setCdcStateFilter] = useState("");
  const [cdcMapMessage, setCdcMapMessage] = useState(null);
  const [cdcFilterOptions, setCdcFilterOptions] = useState({
    basis: "all",
    metric_options: [],
    assistance_types: [],
    fiscal_years: [],
    awarding_offices: [],
    funding_offices: [],
    centers: [],
    states: [],
  });
  const [cdcLegend, setCdcLegend] = useState(null);
  const [isCdcLegendLoading, setIsCdcLegendLoading] = useState(false);
  const [cdcSearchQuery, setCdcSearchQuery] = useState("");
  const [cdcSearchResults, setCdcSearchResults] = useState([]);
  const [cdcSearchTotal, setCdcSearchTotal] = useState(0);
  const [cdcSearchPage, setCdcSearchPage] = useState(1);
  const [isCdcSearchLoading, setIsCdcSearchLoading] = useState(false);
  const [cdcSearchError, setCdcSearchError] = useState(null);
  const [cdcSelectedResult, setCdcSelectedResult] = useState(null);
  const [cdcDetailRecord, setCdcDetailRecord] = useState(null);
  const [isCdcDetailLoading, setIsCdcDetailLoading] = useState(false);
  const [cdcDetailError, setCdcDetailError] = useState(null);
  const [cdcTopRows, setCdcTopRows] = useState([]);
  const [cdcTopNote, setCdcTopNote] = useState(null);
  const [isCdcTopLoading, setIsCdcTopLoading] = useState(false);
  const [cdcTopError, setCdcTopError] = useState(null);
  const [measures, setMeasures] = useState([]);
  const [selectedMeasureId, setSelectedMeasureId] = useState("CASTHMA");
  const [years, setYears] = useState([]);
  const [selectedYear, setSelectedYear] = useState(null);
  const [sviYears, setSviYears] = useState(SVI_FALLBACK_YEARS);
  const [selectedSviYear, setSelectedSviYear] = useState(DEFAULT_SVI_YEAR);
  const [selectedYearWindow, setSelectedYearWindow] = useState(null);
  const [selectedType, setSelectedType] = useState("CrdPrv");
  const [isYearsLoading, setIsYearsLoading] = useState(true);
  const [yearsError, setYearsError] = useState(null);
  const [isSviYearsLoading, setIsSviYearsLoading] = useState(false);
  const [sviYearsError, setSviYearsError] = useState(null);
  const [acsLegend, setAcsLegend] = useState(null);
  const [usdaLegend, setUsdaLegend] = useState(null);
  const [femaLegend, setFemaLegend] = useState(null);
  const [isLegendLoading, setIsLegendLoading] = useState(false);
  const [isUsdaLegendLoading, setIsUsdaLegendLoading] = useState(false);
  const [isFemaLegendLoading, setIsFemaLegendLoading] = useState(false);
  const [usdaMapMessage, setUsdaMapMessage] = useState(null);
  const [femaMapMessage, setFemaMapMessage] = useState(null);
  const [usdaMapLevel, setUsdaMapLevel] = useState("county");
  const [usdaIncludeArchive, setUsdaIncludeArchive] = useState(false);
  const [usdaShowStateMeasures, setUsdaShowStateMeasures] = useState(false);
  const [usdaMeasureSearch, setUsdaMeasureSearch] = useState("");
  const [usdaMeasurePickerOpen, setUsdaMeasurePickerOpen] = useState(false);
  const [placesMeasureSearch, setPlacesMeasureSearch] = useState("");
  const [placesMeasurePickerOpen, setPlacesMeasurePickerOpen] = useState(false);
  const [usdaShowMapDiagnostics, setUsdaShowMapDiagnostics] = useState(false);
  const [usdaMapDiagnostics, setUsdaMapDiagnostics] = useState(null);
  const [usdaVariableMeta, setUsdaVariableMeta] = useState({
    recommended: [],
    categories: [],
    defaults: {
      county: USDA_DEFAULT_VARIABLE,
      state: null,
    },
  });
  const [femaCatalogMeta, setFemaCatalogMeta] = useState({
    dataset_name: "FEMA National Risk Index",
    dataset_vintage: "",
    notes: "",
    default_measure_id: FEMA_DEFAULT_MEASURE,
  });
  const [femaMeasureSearch, setFemaMeasureSearch] = useState("");
  const [femaMeasurePickerOpen, setFemaMeasurePickerOpen] = useState(false);
  const [usdaRecentMeasureIds, setUsdaRecentMeasureIds] = useState(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = window.localStorage.getItem(USDA_RECENT_MEASURES_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .map((value) => String(value ?? "").trim())
        .filter(Boolean)
        .slice(0, 5);
    } catch {
      return [];
    }
  });
  const [usdaHeatLayer, setUsdaHeatLayer] = useState(null);
  const [usdaHeatHoverPoint, setUsdaHeatHoverPoint] = useState(null);
  const [hpsaChoropleth, setHpsaChoropleth] = useState(null);
  const [isHpsaChoroplethLoading, setIsHpsaChoroplethLoading] = useState(false);
  const [hpsaChoroplethError, setHpsaChoroplethError] = useState(null);

  const [selectedBaseMapId, setSelectedBaseMapId] = useState(DEFAULT_BASE_MAP_ID);
  const [mapZoom, setMapZoom] = useState(DEFAULT_ZOOM);
  const [bbox, setBbox] = useState(null);

  const [countyGeojson, setCountyGeojson] = useState(null);
  const [tractGeojson, setTractGeojson] = useState(null);
  const [countyBoundaryOverlay, setCountyBoundaryOverlay] = useState(null);
  const [stateBoundaryOverlay, setStateBoundaryOverlay] = useState(null);

  const [selectedProps, setSelectedProps] = useState(null);
  const [hpsaSummary, setHpsaSummary] = useState(null);
  const [isHpsaLoading, setIsHpsaLoading] = useState(false);
  const [hpsaError, setHpsaError] = useState(null);
  const [hpsaDomainDetails, setHpsaDomainDetails] = useState(null);
  const [isHpsaDomainDetailsLoading, setIsHpsaDomainDetailsLoading] = useState(false);
  const [hpsaDomainDetailsError, setHpsaDomainDetailsError] = useState(null);
  const [, setHoveredProps] = useState(null);
  const [isCountyLoading, setIsCountyLoading] = useState(false);
  const [isTractLoading, setIsTractLoading] = useState(false);
  const [isUsdaHeatLoading, setIsUsdaHeatLoading] = useState(false);
  const [isOutlineLoading, setIsOutlineLoading] = useState(false);
  const [countyReloadNonce, setCountyReloadNonce] = useState(0);
  const [error, setError] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historySeries, setHistorySeries] = useState([]);
  const [historyMeta, setHistoryMeta] = useState(null);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const [highlightedGeoid, setHighlightedGeoid] = useState(null);
  const [highlightedLevel, setHighlightedLevel] = useState(null);
  const [isMeasurePanelMinimized, setIsMeasurePanelMinimized] = useState(false);
  const [isLegendPanelMinimized, setIsLegendPanelMinimized] = useState(false);
  const [viewportWidth, setViewportWidth] = useState(
    typeof window === "undefined" ? 1440 : window.innerWidth
  );
  const [viewportHeight, setViewportHeight] = useState(
    typeof window === "undefined" ? 900 : window.innerHeight
  );
  const [measurePanelHeight, setMeasurePanelHeight] = useState(0);
  const [cmsBreaks, setCmsBreaks] = useState([]);

  const geoJsonRef = useRef(null);
  const selectedLayerRef = useRef(null);
  const zoomToSelectedButtonRef = useRef(null);
  const measurePanelRef = useRef(null);
  const pendingCountySelectionRef = useRef(null);
  const pendingCountySelectionTimerRef = useRef(null);
  const pendingAssistantCountyZoomRef = useRef(false);
  const usdaMeasureSelectorRef = useRef(null);
  const placesMeasureSelectorRef = useRef(null);
  const femaMeasureSelectorRef = useRef(null);
  const previousTractsActiveRef = useRef(null);
  const assistantStreamTimerRef = useRef(null);
  const assistantStreamRunIdRef = useRef(0);
  const mapRef = useRef(null);
  const previousZoomRef = useRef(DEFAULT_ZOOM);
  
  // Per-layer request tracking
  const latestCountyReqRef = useRef(0);
  const latestTractReqRef = useRef(0);
  const latestOutlineReqRef = useRef(0);
  const latestStateReqRef = useRef(0);
  
  // Per-layer abort controllers
  const countyAbortRef = useRef(null);
  const tractAbortRef = useRef(null);
  const outlineAbortRef = useRef(null);
  const stateAbortRef = useRef(null);
  const historyAbortRef = useRef(null);
  const usdaLegendAbortRef = useRef(null);
  const femaLegendAbortRef = useRef(null);
  const cdcLegendAbortRef = useRef(null);
  const cdcSearchAbortRef = useRef(null);
  const cdcDetailAbortRef = useRef(null);
  const cdcTopAbortRef = useRef(null);
  
  // Caching
  const cacheRef = useRef(new Map()); // { key: { data, ts } }
  const inflightRef = useRef(new Map()); // { key: Promise }
  const measuresCacheRef = useRef(new Map()); // { source: measures[] }
  const cmsSelectionCacheRef = useRef(new Map()); // { `${year}|${age}|${measure}`: { rowsByCounty, breaks } }
  const cmsSelectionInflightRef = useRef(new Map()); // { `${year}|${age}|${measure}`: Promise }
  
  // Viewport debouncing
  const viewportDebounceRef = useRef(null);

  useEffect(() => {
    return () => {
      if (pendingCountySelectionTimerRef.current) {
        clearTimeout(pendingCountySelectionTimerRef.current);
      }
      pendingAssistantCountyZoomRef.current = false;
      if (assistantStreamTimerRef.current) {
        clearTimeout(assistantStreamTimerRef.current);
        assistantStreamTimerRef.current = null;
      }
      assistantStreamRunIdRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return () => {};
    }
    const handleResize = () => {
      setViewportWidth(window.innerWidth);
      setViewportHeight(window.innerHeight);
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  useEffect(() => {
    if (!usdaMeasurePickerOpen) return () => {};
    const handlePointerDown = (event) => {
      const container = usdaMeasureSelectorRef.current;
      if (!container) return;
      if (!container.contains(event.target)) {
        setUsdaMeasurePickerOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [usdaMeasurePickerOpen]);

  useEffect(() => {
    if (!placesMeasurePickerOpen) return () => {};
    const handlePointerDown = (event) => {
      const container = placesMeasureSelectorRef.current;
      if (!container) return;
      if (!container.contains(event.target)) {
        setPlacesMeasurePickerOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [placesMeasurePickerOpen]);

  useEffect(() => {
    if (!femaMeasurePickerOpen) return () => {};
    const handlePointerDown = (event) => {
      const container = femaMeasureSelectorRef.current;
      if (!container) return;
      if (!container.contains(event.target)) {
        setFemaMeasurePickerOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [femaMeasurePickerOpen]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(
        USDA_RECENT_MEASURES_STORAGE_KEY,
        JSON.stringify((usdaRecentMeasureIds ?? []).slice(0, 5))
      );
    } catch {
      // ignore storage write failures
    }
  }, [usdaRecentMeasureIds]);

  useEffect(() => {
    const node = measurePanelRef.current;
    if (!node || typeof ResizeObserver === "undefined") {
      return () => {};
    }

    const updateHeight = () => {
      const nextHeight = Math.ceil(node.getBoundingClientRect().height);
      setMeasurePanelHeight((currentHeight) => (
        currentHeight === nextHeight ? currentHeight : nextHeight
      ));
    };

    updateHeight();
    const observer = new ResizeObserver(updateHeight);
    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, []);

  const isAcsDataSource = selectedDataSource === DATA_SOURCES.ACS_NMF;
  const isSviDataSource = selectedDataSource === DATA_SOURCES.SVI;
  const isHpsaDataSource = selectedDataSource === DATA_SOURCES.HPSA;
  const isCmsDataSource = selectedDataSource === DATA_SOURCES.CMS;
  const isCdcDataSource = selectedDataSource === DATA_SOURCES.CDC_FUNDING;
  const isUsdaDataSource = selectedDataSource === DATA_SOURCES.USDA_FOOD_ENV;
  const isFemaDataSource = selectedDataSource === DATA_SOURCES.FEMA_NRI;
  const isPlacesDataSource = selectedDataSource === DATA_SOURCES.PLACES;
  const selectedCmsAgeOption = getCmsAgeOption(selectedCmsAgeGroup);
  const selectedCmsAgeLevel = selectedCmsAgeOption.apiValue;
  const selectedCmsAgeLabel = selectedCmsAgeOption.label;
  const datasetCachePrefix = isAcsDataSource
    ? "acs-nmf"
    : isSviDataSource
      ? "svi"
      : isHpsaDataSource
        ? "hpsa"
        : isCmsDataSource
          ? "cms"
        : isCdcDataSource
          ? "cdc-funding"
        : isUsdaDataSource
          ? "usda-food-environment"
        : isFemaDataSource
          ? "fema-nri"
        : "places";
  const historySupported = selectedDataSource === DATA_SOURCES.PLACES;
  const tractsActive = !isUsdaDataSource && !isHpsaDataSource && !isCmsDataSource && !isCdcDataSource && mapZoom >= TRACT_ZOOM;
  const isUsdaHeatMode = false;
  const activeGeography = tractsActive ? "tract" : "county";
  const acsGeography = isAcsDataSource && tractsActive ? "tract" : "county";
  const selectedMeasure = measures.find(
    (measure) => measure.measure_id === selectedMeasureId
  );
  const usdaSelectedLevel = String(
    selectedMeasure?.usda_level ?? selectedMeasure?.level ?? "county"
  ).trim().toLowerCase() === "state"
    ? "state"
    : "county";
  const usdaLowZoomStateFallback = isUsdaDataSource && mapZoom <= 5;
  const usdaRequestLevel = isUsdaDataSource
    ? (
      usdaSelectedLevel === "state"
        ? "state"
        : (usdaLowZoomStateFallback ? "state" : "county")
    )
    : null;
  const usdaRenderLevel = isUsdaDataSource
    ? (usdaRequestLevel || usdaMapLevel || usdaSelectedLevel)
    : null;
  const selectedTemporalValue = isHpsaDataSource
    ? selectedHpsaDomain
    : isCdcDataSource
      ? `${cdcBasis}|${cdcGeography}|${selectedMeasureId}|${cdcAssistanceType || "all"}|${cdcFiscalYear || "all"}|${cdcAwardingOffice || "all"}|${cdcFundingOffice || "all"}|${cdcCenter || "all"}|${cdcStateFilter || "all"}`
    : isUsdaDataSource
      ? `food_environment_atlas_2025|${usdaRenderLevel ?? "county"}`
    : isFemaDataSource
      ? `fema_nri_december_2025|${tractsActive ? "tract" : "county"}`
    : isAcsDataSource
      ? selectedYearWindow
      : isSviDataSource
        ? selectedSviYear
        : isCmsDataSource
          ? (
            selectedYear == null
              ? null
              : `${selectedYear}|${selectedCmsAgeLevel}`
          )
        : selectedYear;

  useEffect(() => {
    if (isUsdaDataSource) return;
    setUsdaMeasurePickerOpen(false);
    setUsdaMeasureSearch("");
    setUsdaShowMapDiagnostics(false);
  }, [isUsdaDataSource]);

  useEffect(() => {
    if (isPlacesDataSource) return;
    setPlacesMeasurePickerOpen(false);
    setPlacesMeasureSearch("");
  }, [isPlacesDataSource]);

  useEffect(() => {
    if (isFemaDataSource) return;
    setFemaMeasurePickerOpen(false);
    setFemaMeasureSearch("");
  }, [isFemaDataSource]);

  useEffect(() => {
    if (isCdcDataSource) return;
    setCdcSearchQuery("");
    setCdcSearchResults([]);
    setCdcSearchTotal(0);
    setCdcSearchPage(1);
    setCdcSelectedResult(null);
    setCdcDetailRecord(null);
    setCdcDetailError(null);
    setCdcSearchError(null);
    setCdcTopRows([]);
    setCdcTopError(null);
    setCdcTopNote(null);
  }, [isCdcDataSource]);

  useEffect(() => {
    if (!isUsdaDataSource) return;
    const measureId = String(selectedMeasureId ?? "").trim();
    if (!measureId) return;
    if (!measures.some((measure) => String(measure?.measure_id ?? "").trim() === measureId)) {
      return;
    }
    setUsdaRecentMeasureIds((previous) => {
      const deduped = [measureId, ...previous.filter((value) => value !== measureId)];
      return deduped.slice(0, 5);
    });
  }, [isUsdaDataSource, measures, selectedMeasureId]);

  const sviMeasureById = useMemo(() => {
    if (!isSviDataSource) return new Map();
    const map = new Map();
    for (const measure of measures ?? []) {
      const normalizedId = String(measure?.measure_id ?? "").trim().toUpperCase();
      if (!normalizedId) continue;
      map.set(normalizedId, measure);
    }
    return map;
  }, [isSviDataSource, measures]);
  const placesSearchToken = String(placesMeasureSearch ?? "").trim().toLowerCase();
  const placesVisibleMeasures = useMemo(() => {
    if (!isPlacesDataSource) return [];
    return [...(measures ?? [])]
      .filter((measure) => {
        if (!placesSearchToken) return true;
        const haystack = [
          measure?.measure_id,
          measure?.name,
          measure?.measure,
          measure?.short_question_text,
          measure?.category,
        ]
          .map((value) => String(value ?? "").trim().toLowerCase())
          .join(" ");
        return haystack.includes(placesSearchToken);
      })
      .sort((left, right) => {
        const leftLabel = getMeasureDisplayName(left);
        const rightLabel = getMeasureDisplayName(right);
        return String(leftLabel).localeCompare(String(rightLabel));
      });
  }, [isPlacesDataSource, measures, placesSearchToken]);
  const placesMeasureGroups = useMemo(() => {
    if (!isPlacesDataSource) return [];
    const grouped = new Map();
    for (const measure of placesVisibleMeasures) {
      const categoryName = String(measure?.category ?? "Other").trim() || "Other";
      if (!grouped.has(categoryName)) {
        grouped.set(categoryName, []);
      }
      grouped.get(categoryName).push(measure);
    }
    return Array.from(grouped.entries())
      .sort((left, right) => String(left[0]).localeCompare(String(right[0])))
      .map(([category, groupMeasures]) => ({
        category,
        measures: groupMeasures,
      }));
  }, [isPlacesDataSource, placesVisibleMeasures]);
  const usdaMeasureById = useMemo(() => {
    if (!isUsdaDataSource) return new Map();
    return new Map(
      (measures ?? [])
        .map((measure) => [String(measure?.measure_id ?? "").trim(), measure])
        .filter(([measureId]) => measureId.length > 0)
    );
  }, [isUsdaDataSource, measures]);
  const usdaSearchToken = String(usdaMeasureSearch ?? "").trim().toLowerCase();
  const usdaVisibleMeasures = useMemo(() => {
    if (!isUsdaDataSource) return [];
    const matchesSearch = (measure) => {
      if (!usdaSearchToken) return true;
      const haystack = [
        measure?.measure_id,
        measure?.name,
        measure?.display_name,
        measure?.description,
        measure?.category,
      ]
        .map((value) => String(value ?? "").trim().toLowerCase())
        .join(" ");
      return haystack.includes(usdaSearchToken);
    };
    return [...(measures ?? [])]
      .filter((measure) => matchesSearch(measure))
      .sort((left, right) => {
        const leftLabel = getUsdaPlainLabel(left?.measure_id, getMeasureDisplayName(left));
        const rightLabel = getUsdaPlainLabel(right?.measure_id, getMeasureDisplayName(right));
        return leftLabel.localeCompare(rightLabel);
      });
  }, [isUsdaDataSource, measures, usdaSearchToken]);
  const usdaRecentMeasures = useMemo(() => {
    if (!isUsdaDataSource) return [];
    const visibleIds = new Set(usdaVisibleMeasures.map((measure) => String(measure?.measure_id ?? "").trim()));
    return usdaRecentMeasureIds
      .map((measureId) => usdaMeasureById.get(String(measureId ?? "").trim()))
      .filter((measure) => {
        const id = String(measure?.measure_id ?? "").trim();
        return Boolean(id) && visibleIds.has(id);
      })
      .slice(0, 5);
  }, [isUsdaDataSource, usdaMeasureById, usdaRecentMeasureIds, usdaVisibleMeasures]);
  const usdaRecommendedMeasures = useMemo(() => {
    if (!isUsdaDataSource) return [];
    return usdaVisibleMeasures
      .filter((measure) => (
        String(measure?.usda_level ?? "county").toLowerCase() === "county"
        && !Boolean(measure?.usda_is_archival)
        && Boolean(measure?.usda_recommended)
      ))
      .slice(0, 20);
  }, [isUsdaDataSource, usdaVisibleMeasures]);
  const usdaCommonMeasures = useMemo(() => {
    if (!isUsdaDataSource) return [];
    const recommendedIds = new Set(
      usdaRecommendedMeasures.map((measure) => String(measure?.measure_id ?? "").trim())
    );
    return usdaVisibleMeasures
      .filter((measure) => (
        String(measure?.usda_level ?? "county").toLowerCase() === "county"
        && !Boolean(measure?.usda_is_archival)
        && !recommendedIds.has(String(measure?.measure_id ?? "").trim())
      ))
      .slice(0, 24);
  }, [isUsdaDataSource, usdaRecommendedMeasures, usdaVisibleMeasures]);
  const usdaCategoryGroups = useMemo(() => {
    if (!isUsdaDataSource) return [];
    const excludeIds = new Set([
      ...usdaRecommendedMeasures.map((measure) => String(measure?.measure_id ?? "").trim()),
      ...usdaCommonMeasures.map((measure) => String(measure?.measure_id ?? "").trim()),
    ]);
    const grouped = new Map();
    for (const measure of usdaVisibleMeasures) {
      const measureId = String(measure?.measure_id ?? "").trim();
      const isCounty = String(measure?.usda_level ?? "county").toLowerCase() === "county";
      if (!measureId || !isCounty || Boolean(measure?.usda_is_archival) || excludeIds.has(measureId)) {
        continue;
      }
      const categoryName = String(measure?.category ?? "Other").trim() || "Other";
      if (!grouped.has(categoryName)) {
        grouped.set(categoryName, []);
      }
      grouped.get(categoryName).push(measure);
    }
    return Array.from(grouped.entries())
      .sort((left, right) => String(left[0]).localeCompare(String(right[0])))
      .map(([category, groupedMeasures]) => ({
        category,
        measures: groupedMeasures.sort((left, right) => (
          getUsdaPlainLabel(left?.measure_id, getMeasureDisplayName(left))
            .localeCompare(getUsdaPlainLabel(right?.measure_id, getMeasureDisplayName(right)))
        )),
      }));
  }, [isUsdaDataSource, usdaVisibleMeasures, usdaRecommendedMeasures, usdaCommonMeasures]);
  const usdaArchiveMeasures = useMemo(() => {
    if (!isUsdaDataSource) return [];
    return usdaVisibleMeasures.filter((measure) => (
      String(measure?.usda_level ?? "county").toLowerCase() === "county"
      && Boolean(measure?.usda_is_archival)
    ));
  }, [isUsdaDataSource, usdaVisibleMeasures]);
  const usdaStateMeasures = useMemo(() => {
    if (!isUsdaDataSource) return [];
    return usdaVisibleMeasures.filter((measure) => (
      String(measure?.usda_level ?? "county").toLowerCase() === "state"
    ));
  }, [isUsdaDataSource, usdaVisibleMeasures]);
  const femaSearchToken = String(femaMeasureSearch ?? "").trim().toLowerCase();
  const femaVisibleMeasures = useMemo(() => {
    if (!isFemaDataSource) return [];
    return [...(measures ?? [])]
      .filter((measure) => {
        if (!femaSearchToken) return true;
        const haystack = [
          measure?.measure_id,
          measure?.name,
          measure?.label,
          measure?.description,
          measure?.fema_group,
          measure?.fema_subgroup,
          measure?.fema_hazard_name,
        ]
          .map((value) => String(value ?? "").trim().toLowerCase())
          .join(" ");
        return haystack.includes(femaSearchToken);
      })
      .sort((left, right) => (
        getFemaMeasureLabel(left, left?.measure_id)
          .localeCompare(getFemaMeasureLabel(right, right?.measure_id))
      ));
  }, [femaSearchToken, isFemaDataSource, measures]);
  const femaGroupedMeasures = useMemo(() => {
    if (!isFemaDataSource) return [];
    const grouped = new Map();
    for (const measure of femaVisibleMeasures) {
      const groupName = String(measure?.fema_group ?? measure?.category ?? "Other").trim() || "Other";
      const subgroupName = String(measure?.fema_subgroup ?? "General").trim() || "General";
      if (!grouped.has(groupName)) {
        grouped.set(groupName, new Map());
      }
      const subgroupMap = grouped.get(groupName);
      if (!subgroupMap.has(subgroupName)) {
        subgroupMap.set(subgroupName, []);
      }
      subgroupMap.get(subgroupName).push(measure);
    }
    return Array.from(grouped.entries())
      .sort((left, right) => String(left[0]).localeCompare(String(right[0])))
      .map(([groupName, subgroupMap]) => {
        const subgroups = Array.from(subgroupMap.entries())
          .sort((left, right) => String(left[0]).localeCompare(String(right[0])))
          .map(([subgroupName, subgroupMeasures]) => ({
            subgroup: subgroupName,
            measures: subgroupMeasures,
          }));
        const count = subgroups.reduce((sum, subgroup) => sum + subgroup.measures.length, 0);
        return {
          group: groupName,
          count,
          subgroups,
        };
      });
  }, [femaVisibleMeasures, isFemaDataSource]);
  useEffect(() => {
    if (!isFemaDataSource) return;
    if (!selectedMeasureId) return;
    if ((measures ?? []).some((measure) => measure?.measure_id === selectedMeasureId)) return;
    const fallback = measures[0]?.measure_id ?? "";
    if (fallback) {
      setSelectedMeasureId(fallback);
    }
  }, [isFemaDataSource, measures, selectedMeasureId]);
  const selectedMeasureSource = selectedMeasure?.source ?? null;
  const isAcsMeasureSelected = isAcsDataSource && selectedMeasureSource === "acs";
  const acsYearWindows = useMemo(() => {
    if (!isAcsDataSource) return [];
    if (!selectedMeasure || !Array.isArray(selectedMeasure.year_windows)) return [];
    return selectedMeasure.year_windows;
  }, [isAcsDataSource, selectedMeasure]);
  const acsDataValueTypeIds = useMemo(() => {
    if (!isAcsDataSource) return [];
    if (!selectedMeasure || !Array.isArray(selectedMeasure.data_value_type_ids)) return [];
    return selectedMeasure.data_value_type_ids;
  }, [isAcsDataSource, selectedMeasure]);

  useEffect(() => {
    if (
      isAcsDataSource
      || isSviDataSource
      || isHpsaDataSource
      || isCmsDataSource
      || isUsdaDataSource
      || isFemaDataSource
    ) return;
    if (!selectedMeasureId) return;
    if (selectedYear == null || !Number.isFinite(Number(selectedYear))) return;
    if (selectedType !== "CrdPrv" && selectedType !== "AgeAdjPrv") return;
    setPlacesProfileContext({
      year: Number(selectedYear),
      measureId: selectedMeasureId,
      dataValueTypeId: selectedType,
    });
  }, [
    isAcsDataSource,
    isSviDataSource,
    isHpsaDataSource,
    isCmsDataSource,
    isCdcDataSource,
    isUsdaDataSource,
    isFemaDataSource,
    selectedMeasureId,
    selectedType,
    selectedYear,
  ]);

  const activeGeojson = isUsdaHeatMode ? null : (tractsActive ? tractGeojson : countyGeojson);
  const activeFeatures = activeGeojson?.features ?? [];
  const selectedLocationId = useMemo(() => {
    return getFeatureLocationId(selectedProps);
  }, [selectedProps]);

  // Cache helper functions
  const getCached = useCallback((key) => {
    const entry = cacheRef.current.get(key);
    if (!entry) return null;
    const { data, ts } = entry;
    if (Date.now() - ts > CACHE_TTL_MS) {
      cacheRef.current.delete(key);
      return null;
    }
    return data;
  }, []);

  const setCached = useCallback((key, data) => {
    cacheRef.current.set(key, { data, ts: Date.now() });
  }, []);

  const fetchWithDedupe = useCallback(async (key, fetcher) => {
    // If already inflight, return existing promise
    if (inflightRef.current.has(key)) {
      return inflightRef.current.get(key);
    }

    // Create new promise
    const promise = fetcher()
      .finally(() => {
        inflightRef.current.delete(key);
      });

    inflightRef.current.set(key, promise);
    return promise;
  }, []);

  const loadCmsSelectionData = useCallback(
    async ({ year, ageLevel, measureId, signal }) => {
      const key = `${year}|${ageLevel}|${measureId}`;
      const cached = cmsSelectionCacheRef.current.get(key);
      if (cached) {
        return cached;
      }

      if (cmsSelectionInflightRef.current.has(key)) {
        return cmsSelectionInflightRef.current.get(key);
      }

      const promise = (async () => {
        const rows = await fetchCmsGvCountyGeo({
          apiBase: API_BASE,
          year,
          age_level: ageLevel,
          measure_id: measureId,
          signal,
        });
        const rowsByCounty = new Map();
        const eligibleValues = [];

        for (const row of Array.isArray(rows) ? rows : []) {
          const countyFips = normalizeCountyFips(row?.county_fips ?? row?.geo_code);
          if (!countyFips) continue;
          const numericValue = toFiniteNumericValue(row?.value);
          const isSuppressed = Boolean(row?.is_suppressed);
          const effectiveValue = isSuppressed ? null : numericValue;
          if (effectiveValue != null) {
            eligibleValues.push(effectiveValue);
          }
          rowsByCounty.set(countyFips, {
            county_fips: countyFips,
            geo_name: row?.geo_name ?? null,
            year: Number(row?.year ?? year),
            age_level: row?.age_level ?? ageLevel,
            measure_id: row?.measure_id ?? measureId,
            value: effectiveValue,
            is_suppressed: isSuppressed,
          });
        }

        const payload = {
          rowsByCounty,
          breaks: computeFixedQuantileBreaks(eligibleValues, BIN_COUNT),
        };
        cmsSelectionCacheRef.current.set(key, payload);
        return payload;
      })().finally(() => {
        cmsSelectionInflightRef.current.delete(key);
      });

      cmsSelectionInflightRef.current.set(key, promise);
      return promise;
    },
    []
  );

  const computedBreaks = useMemo(() => {
    return computeBreaks(
      activeFeatures.map((feature) => getValueFromProperties(feature.properties))
    );
  }, [activeFeatures]);
  const usdaHeatValues = useMemo(() => {
    if (!isUsdaDataSource || !isUsdaHeatMode) return [];
    return (usdaHeatLayer?.points ?? []).map((point) => point?.value);
  }, [isUsdaDataSource, isUsdaHeatMode, usdaHeatLayer]);
  const sviBins = useMemo(() => getSviBins(), []);

  const breaks = useMemo(() => {
    if (isSviDataSource) {
      return [];
    }
    if (isCmsDataSource) {
      return cmsBreaks;
    }
    if (isCdcDataSource) {
      const bins = Array.isArray(cdcLegend?.bins) ? cdcLegend.bins : [];
      if (bins.length === 0) return computedBreaks;
      const values = [Number(bins[0]?.min)];
      bins.forEach((bin) => {
        values.push(Number(bin?.max));
      });
      const numeric = values.filter((value) => Number.isFinite(value));
      return numeric.length >= 2 ? numeric : computedBreaks;
    }
    if (isUsdaDataSource) {
      if (isUsdaHeatMode) {
        return computeBreaks(usdaHeatValues);
      }
      const bins = Array.isArray(usdaLegend?.bins) ? usdaLegend.bins : [];
      if (bins.length === 0) return computedBreaks;
      const values = [Number(bins[0]?.min)];
      bins.forEach((bin) => {
        values.push(Number(bin?.max));
      });
      const numeric = values.filter((value) => Number.isFinite(value));
      return numeric.length >= 2 ? numeric : computedBreaks;
    }
    if (isFemaDataSource) {
      const femaValueType = String(selectedMeasure?.fema_value_type ?? "").trim().toLowerCase();
      const femaLegendMode = String(selectedMeasure?.fema_legend_mode ?? "").trim().toLowerCase();
      const isRatingMeasure = femaValueType === "rating" || femaLegendMode === "ordered_category";
      if (isRatingMeasure) return [];
      const bins = Array.isArray(femaLegend?.bins) ? femaLegend.bins : [];
      if (bins.length === 0) return computedBreaks;
      const values = [Number(bins[0]?.min)];
      bins.forEach((bin) => {
        values.push(Number(bin?.max));
      });
      const numeric = values.filter((value) => Number.isFinite(value));
      return numeric.length >= 2 ? numeric : computedBreaks;
    }
    if (!isAcsDataSource) {
      return computedBreaks;
    }
    const bins = Array.isArray(acsLegend?.bins) ? acsLegend.bins : [];
    if (bins.length === 0) return [];

    const values = [Number(bins[0]?.min)];
    bins.forEach((bin) => {
      values.push(Number(bin?.max));
    });
    const numeric = values.filter((value) => Number.isFinite(value));
    if (numeric.length < 2) return [];
    return numeric;
  }, [
    acsLegend,
    cdcLegend,
    cmsBreaks,
    computedBreaks,
    isAcsDataSource,
    isCdcDataSource,
    isCmsDataSource,
    isFemaDataSource,
    isSviDataSource,
    femaLegend,
    isUsdaDataSource,
    isUsdaHeatMode,
    selectedMeasure,
    usdaLegend,
    usdaHeatValues,
  ]);
  const legendBbox = acsGeography === "tract" ? bbox : null;

  useEffect(() => {
    if (!isCmsDataSource || selectedYear == null || !selectedMeasureId) {
      setCmsBreaks([]);
      return;
    }

    let isMounted = true;
    loadCmsSelectionData({
      year: Number(selectedYear),
      ageLevel: selectedCmsAgeLevel,
      measureId: selectedMeasureId,
    })
      .then((payload) => {
        if (!isMounted) return;
        setCmsBreaks(Array.isArray(payload?.breaks) ? payload.breaks : []);
      })
      .catch((cmsLoadError) => {
        if (!isMounted) return;
        if (isAbortLikeError(cmsLoadError)) return;
        console.error("CMS selection load failed:", cmsLoadError);
        setCmsBreaks([]);
      });

    return () => {
      isMounted = false;
    };
  }, [isCmsDataSource, loadCmsSelectionData, selectedCmsAgeLevel, selectedMeasureId, selectedYear]);

  useEffect(() => {
    let isMounted = true;
    const source = selectedDataSource;
    if (source === DATA_SOURCES.HPSA) {
      setMeasures([]);
      setError(null);
      return () => {
        isMounted = false;
      };
    }

    const sourceKey = source === DATA_SOURCES.ACS_NMF
      ? `acs_nmf:${acsGeography}`
      : source === DATA_SOURCES.SVI
        ? `svi:${activeGeography}:${selectedSviYear}`
        : source === DATA_SOURCES.CMS
          ? DATA_SOURCES.CMS
        : source === DATA_SOURCES.CDC_FUNDING
          ? `${DATA_SOURCES.CDC_FUNDING}:${cdcBasis}`
        : source === DATA_SOURCES.USDA_FOOD_ENV
          ? `${DATA_SOURCES.USDA_FOOD_ENV}:${usdaShowStateMeasures ? "all" : "county"}:${usdaIncludeArchive ? "archive" : "current"}`
        : source === DATA_SOURCES.FEMA_NRI
          ? DATA_SOURCES.FEMA_NRI
        : DATA_SOURCES.PLACES;
    const cachedMeasures = source === DATA_SOURCES.USDA_FOOD_ENV
      ? null
      : measuresCacheRef.current.get(sourceKey);
    let endpoint = "/measures";
    if (source === DATA_SOURCES.ACS_NMF) {
      endpoint = acsGeography === "tract" ? "/acs-nmf/tracts/measures" : "/acs-nmf/measures";
    } else if (source === DATA_SOURCES.SVI) {
      endpoint = `/svi/measures?geography_level=${activeGeography}&year=${selectedSviYear}`;
    }

    const applyMeasureDefaults = (nextMeasures, options = {}) => {
      const usdaPreferredIds = Array.isArray(options?.usdaPreferredIds)
        ? options.usdaPreferredIds.map((value) => String(value ?? "").trim()).filter(Boolean)
        : [];
      setSelectedMeasureId((currentId) => {
        if (
          currentId
          && nextMeasures.some((measure) => (
            measure.measure_id === currentId
            && (source !== DATA_SOURCES.SVI || measure.svi_available !== false)
          ))
        ) {
          return currentId;
        }
        if (
          source === DATA_SOURCES.PLACES
          && nextMeasures.some((measure) => measure.measure_id === "CASTHMA")
        ) {
          return "CASTHMA";
        }
        if (
          source === DATA_SOURCES.CMS
          && nextMeasures.some((measure) => measure.measure_id === "TOT_MDCR_STDZD_PYMT_PC")
        ) {
          return "TOT_MDCR_STDZD_PYMT_PC";
        }
        if (source === DATA_SOURCES.CDC_FUNDING) {
          const preferredMetric = String(
            options?.cdcPreferredMetric
            ?? CDC_DEFAULT_METRIC_BY_BASIS[cdcBasis]
            ?? "total_funding"
          ).trim();
          if (
            preferredMetric
            && nextMeasures.some((measure) => measure.measure_id === preferredMetric)
          ) {
            return preferredMetric;
          }
          return nextMeasures[0]?.measure_id ?? "";
        }
        if (
          source === DATA_SOURCES.USDA_FOOD_ENV
          && usdaPreferredIds.some((preferredId) => (
            nextMeasures.some((measure) => measure.measure_id === preferredId)
          ))
        ) {
          return usdaPreferredIds.find((preferredId) => (
            nextMeasures.some((measure) => measure.measure_id === preferredId)
          )) ?? USDA_DEFAULT_VARIABLE;
        }
        if (
          source === DATA_SOURCES.USDA_FOOD_ENV
          && nextMeasures.some((measure) => measure.measure_id === USDA_DEFAULT_VARIABLE)
        ) {
          return USDA_DEFAULT_VARIABLE;
        }
        if (
          source === DATA_SOURCES.FEMA_NRI
          && usdaPreferredIds.some((preferredId) => (
            nextMeasures.some((measure) => measure.measure_id === preferredId)
          ))
        ) {
          return usdaPreferredIds.find((preferredId) => (
            nextMeasures.some((measure) => measure.measure_id === preferredId)
          )) ?? FEMA_DEFAULT_MEASURE;
        }
        if (
          source === DATA_SOURCES.FEMA_NRI
          && nextMeasures.some((measure) => measure.measure_id === FEMA_DEFAULT_MEASURE)
        ) {
          return FEMA_DEFAULT_MEASURE;
        }
        if (
          source === DATA_SOURCES.SVI
          && nextMeasures.some(
            (measure) => measure.measure_id === "RPL_THEMES" && measure.svi_available !== false
          )
        ) {
          return "RPL_THEMES";
        }
        if (source === DATA_SOURCES.SVI) {
          const firstAvailable = nextMeasures.find((measure) => measure.svi_available !== false);
          if (firstAvailable) {
            return firstAvailable.measure_id;
          }
        }
        return nextMeasures[0]?.measure_id ?? "";
      });
    };

    if (cachedMeasures) {
      const taggedCachedMeasures = tagMeasuresForSource(cachedMeasures, source);
      setMeasures(taggedCachedMeasures);
      applyMeasureDefaults(taggedCachedMeasures);
      return () => {
        isMounted = false;
      };
    }

    const fetchMeasuresPromise = source === DATA_SOURCES.CMS
      ? fetchCmsMeasures({ apiBase: API_BASE })
      : source === DATA_SOURCES.CDC_FUNDING
        ? fetchCdcFundingFilters({
          apiBase: API_BASE,
          basis: cdcBasis,
        })
      : source === DATA_SOURCES.USDA_FOOD_ENV
        ? fetchUsdaFoodEnvironmentVariables({
          apiBase: API_BASE,
          level: usdaShowStateMeasures ? "all" : "county",
          include_archival: usdaIncludeArchive,
        })
        : source === DATA_SOURCES.FEMA_NRI
          ? fetchFemaNriMeasures({
            apiBase: API_BASE,
            level: "all",
            include_hidden: true,
          })
        : fetch(`${API_BASE}${endpoint}`)
          .then((response) => {
            if (!response.ok) {
              throw new Error("Failed to load measures.");
            }
            return response.json();
          });

    fetchMeasuresPromise
      .then((data) => {
        if (!isMounted) return;
        const list = (() => {
          if (Array.isArray(data)) return data;
          if (Array.isArray(data?.measures)) return data.measures;
          if (Array.isArray(data?.metric_options)) return data.metric_options;
          if (Array.isArray(data?.variables)) return data.variables;
          if (Array.isArray(data?.groups)) {
            const flattened = [];
            for (const group of data.groups) {
              const subgroups = Array.isArray(group?.subgroups) ? group.subgroups : [];
              for (const subgroup of subgroups) {
                const subgroupMeasures = Array.isArray(subgroup?.measures) ? subgroup.measures : [];
                flattened.push(...subgroupMeasures);
              }
            }
            return flattened;
          }
          return [];
        })();
        let sorted = [];
        if (source === DATA_SOURCES.CMS) {
          sorted = buildCmsCuratedMeasures(list);
        } else if (source === DATA_SOURCES.CDC_FUNDING) {
          const metricOptions = Array.isArray(data?.metric_options) ? data.metric_options : [];
          sorted = metricOptions
            .map((option) => {
              const metricValue = String(option?.value ?? "").trim();
              const metricLabel = String(option?.label ?? metricValue).trim() || metricValue;
              if (!metricValue) return null;
              return {
                measure_id: metricValue,
                name: metricLabel,
                measure: metricLabel,
                label: metricLabel,
                source: "cdc",
              };
            })
            .filter(Boolean);
          setCdcFilterOptions({
            basis: String(data?.basis ?? cdcBasis),
            metric_options: metricOptions,
            assistance_types: Array.isArray(data?.assistance_types) ? data.assistance_types : [],
            fiscal_years: Array.isArray(data?.fiscal_years) ? data.fiscal_years : [],
            awarding_offices: Array.isArray(data?.awarding_offices) ? data.awarding_offices : [],
            funding_offices: Array.isArray(data?.funding_offices) ? data.funding_offices : [],
            centers: Array.isArray(data?.centers) ? data.centers : [],
            states: Array.isArray(data?.states) ? data.states : [],
          });
        } else if (source === DATA_SOURCES.USDA_FOOD_ENV) {
          const notes = typeof data?.notes === "string" ? data.notes : "";
          const defaults = data?.defaults && typeof data.defaults === "object"
            ? data.defaults
            : {};
          const recommendedList = Array.isArray(data?.recommended) ? data.recommended : [];
          const recommendedSet = new Set(
            recommendedList.map((value) => String(value ?? "").trim()).filter(Boolean)
          );
          const recommendedCountyDefault = String(
            defaults?.county ?? data?.recommended_defaults?.county ?? USDA_DEFAULT_VARIABLE
          ).trim();
          const recommendedStateDefault = String(
            defaults?.state ?? data?.recommended_defaults?.state ?? ""
          ).trim();
          setUsdaVariableMeta({
            recommended: recommendedList,
            categories: Array.isArray(data?.categories) ? data.categories : [],
            defaults: {
              county: recommendedCountyDefault || USDA_DEFAULT_VARIABLE,
              state: recommendedStateDefault || null,
            },
          });
          sorted = list.map((item) => {
            const field = String(item?.var_name ?? item?.measure_id ?? "").trim();
            const longName = String(item?.display_name ?? field).trim() || field;
            const description = item?.description ?? null;
            const plainLabel = getUsdaPlainLabel(field, longName);
            const plainDescription = getUsdaPlainDescription(field, description);
            const derivedYear = Number.isFinite(Number(item?.year)) ? Number(item.year) : null;
            const isArchival = Boolean(item?.is_archival);
            const isDefault = Boolean(item?.is_default);
            return {
              ...item,
              measure_id: field,
              name: plainLabel,
              measure: plainLabel,
              long_name: longName,
              description: plainDescription || null,
              category: item?.category ?? "Other",
              usda_unit: item?.unit ?? null,
              usda_level: item?.level ?? "county",
              usda_year: derivedYear,
              usda_is_archival: isArchival,
              usda_is_default: isDefault,
              usda_recommended: Boolean(item?.recommended) || recommendedSet.has(field),
              usda_plain_label: plainLabel,
              usda_description_raw: description,
              usda_notes: notes,
            };
          })
            .filter((item) => item.measure_id)
            .sort((left, right) => {
              const leftIsRecommended = left.usda_recommended ? 0 : 1;
              const rightIsRecommended = right.usda_recommended ? 0 : 1;
              if (leftIsRecommended !== rightIsRecommended) {
                return leftIsRecommended - rightIsRecommended;
              }
              const leftIsDefault = left.usda_is_default ? 0 : 1;
              const rightIsDefault = right.usda_is_default ? 0 : 1;
              if (leftIsDefault !== rightIsDefault) {
                return leftIsDefault - rightIsDefault;
              }
              const leftCategory = String(left.category ?? "").toLowerCase();
              const rightCategory = String(right.category ?? "").toLowerCase();
              if (leftCategory !== rightCategory) {
                return leftCategory.localeCompare(rightCategory);
              }
              return String(getMeasureDisplayName(left)).localeCompare(String(getMeasureDisplayName(right)));
            });
        } else if (source === DATA_SOURCES.FEMA_NRI) {
          const defaultMeasureId = String(
            data?.default_measure_id
            ?? data?.defaults?.county
            ?? FEMA_DEFAULT_MEASURE
          ).trim() || FEMA_DEFAULT_MEASURE;
          setFemaCatalogMeta({
            dataset_name: String(data?.dataset_name ?? "FEMA National Risk Index"),
            dataset_vintage: String(data?.dataset_vintage ?? ""),
            notes: String(data?.notes ?? ""),
            default_measure_id: defaultMeasureId,
          });
          sorted = list
            .map((item) => {
              const measureId = String(item?.measure_id ?? item?.raw_field ?? "").trim();
              if (!measureId) return null;
              const label = String(item?.display_label ?? item?.label ?? measureId).trim() || measureId;
              return {
                ...item,
                measure_id: measureId,
                name: label,
                measure: label,
                label,
                description: String(item?.description ?? "").trim() || null,
                category: String(item?.group ?? "Other").trim() || "Other",
                fema_group: String(item?.group ?? "Other").trim() || "Other",
                fema_subgroup: String(item?.subgroup ?? "General").trim() || "General",
                fema_unit: item?.unit ?? null,
                fema_value_type: String(item?.value_type ?? "").trim() || "continuous",
                fema_legend_mode: String(item?.legend_mode ?? "").trim() || "quantile",
                fema_tooltip_formatter: String(item?.tooltip_formatter ?? "").trim() || "decimal_1",
                fema_supported_levels: Array.isArray(item?.supported_levels) ? item.supported_levels : [],
                fema_visible_by_default: Boolean(item?.visible_by_default),
                fema_companion_rating_field: String(item?.companion_rating_field ?? "").trim() || null,
                fema_hazard_name: String(item?.hazard_name ?? "").trim() || null,
                fema_sort_order: Number.isFinite(Number(item?.sort_order)) ? Number(item.sort_order) : null,
              };
            })
            .filter(Boolean)
            .sort((left, right) => {
              const leftOrder = Number.isFinite(left?.fema_sort_order) ? Number(left.fema_sort_order) : 1_000_000;
              const rightOrder = Number.isFinite(right?.fema_sort_order) ? Number(right.fema_sort_order) : 1_000_000;
              if (leftOrder !== rightOrder) return leftOrder - rightOrder;
              const leftLabel = getFemaMeasureLabel(left).toLowerCase();
              const rightLabel = getFemaMeasureLabel(right).toLowerCase();
              return leftLabel.localeCompare(rightLabel);
            });
        } else if (source === DATA_SOURCES.SVI) {
          const apiById = new Map();
          for (const measure of list) {
            const key = String(measure?.measure_id ?? "").trim().toUpperCase();
            if (!key) continue;
            apiById.set(key, measure);
          }
          sorted = sviMeasureGroups.flatMap((group) =>
            group.options.map((option) => {
              const normalizedId = String(option.measure_id).trim().toUpperCase();
              const apiMeasure = apiById.get(normalizedId);
              return {
                ...apiMeasure,
                measure_id: normalizedId,
                name: option.label,
                measure: option.label,
                svi_label: option.label,
                svi_group_id: group.id,
                svi_group_label: group.label,
                svi_available: Boolean(apiMeasure),
                value_type: apiMeasure?.value_type ?? "percentile",
              };
            })
          );
        } else {
          const byId = new Map();
          if (source === DATA_SOURCES.PLACES) {
            for (const measure of list) {
              if (!byId.has(measure.measure_id)) {
                byId.set(measure.measure_id, measure);
              }
            }
          } else {
            for (const measure of list) {
              byId.set(measure.measure_id, measure);
            }
          }
          const deduped = Array.from(byId.values());
          sorted = deduped.sort((a, b) => {
            const labelA = getMeasureDisplayName(a).toLowerCase();
            const labelB = getMeasureDisplayName(b).toLowerCase();
            return labelA.localeCompare(labelB);
          });
        }

        const taggedMeasures = tagMeasuresForSource(sorted, source);
        if (source === DATA_SOURCES.FEMA_NRI && taggedMeasures.length === 0) {
          throw new Error("FEMA measures payload was empty. Check /api/fema/nri/measures.");
        }
        measuresCacheRef.current.set(sourceKey, taggedMeasures);
        setMeasures(taggedMeasures);
        if (source === DATA_SOURCES.USDA_FOOD_ENV) {
          const countyDefault = String(
            data?.defaults?.county
            ?? data?.recommended_defaults?.county
            ?? USDA_DEFAULT_VARIABLE
          ).trim();
          const stateDefault = String(
            data?.defaults?.state
            ?? data?.recommended_defaults?.state
            ?? ""
          ).trim();
          applyMeasureDefaults(taggedMeasures, {
            usdaPreferredIds: [countyDefault, stateDefault],
          });
        } else if (source === DATA_SOURCES.FEMA_NRI) {
          const femaDefault = String(
            data?.default_measure_id
            ?? data?.defaults?.county
            ?? FEMA_DEFAULT_MEASURE
          ).trim() || FEMA_DEFAULT_MEASURE;
          applyMeasureDefaults(taggedMeasures, {
            usdaPreferredIds: [femaDefault],
          });
        } else if (source === DATA_SOURCES.CDC_FUNDING) {
          applyMeasureDefaults(taggedMeasures, {
            cdcPreferredMetric: CDC_DEFAULT_METRIC_BY_BASIS[cdcBasis] ?? "total_funding",
          });
        } else {
          applyMeasureDefaults(taggedMeasures);
        }
      })
      .catch((errorResponse) => {
        if (!isMounted) return;
        if (source === DATA_SOURCES.CMS) {
          const fallbackCmsMeasures = tagMeasuresForSource(buildCmsCuratedMeasures([]), source);
          measuresCacheRef.current.set(sourceKey, fallbackCmsMeasures);
          setMeasures(fallbackCmsMeasures);
          applyMeasureDefaults(fallbackCmsMeasures);
        } else if (source === DATA_SOURCES.CDC_FUNDING) {
          measuresCacheRef.current.delete(sourceKey);
          setMeasures([]);
          setCdcFilterOptions({
            basis: cdcBasis,
            metric_options: [],
            assistance_types: [],
            fiscal_years: [],
            awarding_offices: [],
            funding_offices: [],
            centers: [],
            states: [],
          });
        } else if (source === DATA_SOURCES.FEMA_NRI) {
          measuresCacheRef.current.delete(sourceKey);
          setMeasures([]);
        }
        setError(errorResponse.message ?? "Failed to load measures.");
      });

    return () => {
      isMounted = false;
    };
  }, [
    acsGeography,
    activeGeography,
    cdcBasis,
    selectedDataSource,
    selectedSviYear,
    usdaIncludeArchive,
    usdaShowStateMeasures,
  ]);

  useEffect(() => {
    if (selectedDataSource === DATA_SOURCES.HPSA) {
      setIsYearsLoading(false);
      setYearsError(null);
      setIsSviYearsLoading(false);
      setSviYearsError(null);
      return;
    }

    if (selectedDataSource === DATA_SOURCES.USDA_FOOD_ENV) {
      setIsYearsLoading(false);
      setYearsError(null);
      setYears([]);
      setSelectedYear(null);
      setIsSviYearsLoading(false);
      setSviYearsError(null);
      return;
    }

    if (selectedDataSource === DATA_SOURCES.CDC_FUNDING) {
      setIsYearsLoading(false);
      setYearsError(null);
      setYears([]);
      setSelectedYear(null);
      setIsSviYearsLoading(false);
      setSviYearsError(null);
      return;
    }

    if (selectedDataSource === DATA_SOURCES.FEMA_NRI) {
      setIsYearsLoading(false);
      setYearsError(null);
      setYears([]);
      setSelectedYear(null);
      setIsSviYearsLoading(false);
      setSviYearsError(null);
      return;
    }

    if (selectedDataSource === DATA_SOURCES.CMS) {
      let isMounted = true;
      setIsYearsLoading(true);
      setYearsError(null);
      setIsSviYearsLoading(false);
      setSviYearsError(null);

      fetchCmsYears({ apiBase: API_BASE })
        .then((fetchedYears) => {
          if (!isMounted) return;
          const uniqueSortedYears = Array.from(new Set(fetchedYears)).sort((a, b) => b - a);
          const nextYears = uniqueSortedYears.length > 0 ? uniqueSortedYears : FALLBACK_YEARS;
          setYears(nextYears);
          setSelectedYear((currentYear) => {
            if (currentYear != null && nextYears.includes(currentYear)) {
              return currentYear;
            }
            if (nextYears.includes(2023)) {
              return 2023;
            }
            return nextYears[0];
          });
          setYearsError(null);
        })
        .catch((cmsYearsFetchError) => {
          if (!isMounted) return;
          console.error("Failed to load CMS years:", cmsYearsFetchError);
          setYears(FALLBACK_YEARS);
          setSelectedYear((currentYear) => (
            currentYear != null && FALLBACK_YEARS.includes(currentYear)
              ? currentYear
              : FALLBACK_YEARS[0]
          ));
          setYearsError("Could not load CMS years from API. Falling back to 2023.");
        })
        .finally(() => {
          if (!isMounted) return;
          setIsYearsLoading(false);
        });

      return () => {
        isMounted = false;
      };
    }

    if (selectedDataSource === DATA_SOURCES.SVI) {
      let isMounted = true;
      setIsYearsLoading(false);
      setYearsError(null);
      setIsSviYearsLoading(true);
      setSviYearsError(null);

      fetch(`${API_BASE}/svi/years?geography_level=${activeGeography}`)
        .then((response) => {
          if (!response.ok) {
            throw new Error("Failed to load SVI years.");
          }
          return response.json();
        })
        .then((data) => {
          if (!isMounted) return;
          const fetchedYears = Array.isArray(data?.years)
            ? data.years.map((value) => Number(value)).filter((value) => Number.isFinite(value))
            : [];
          const uniqueSortedYears = Array.from(new Set(fetchedYears)).sort((a, b) => b - a);
          const nextYears = uniqueSortedYears.length > 0 ? uniqueSortedYears : SVI_FALLBACK_YEARS;
          setSviYears(nextYears);
          setSelectedSviYear((currentYear) => {
            if (currentYear != null && nextYears.includes(currentYear)) {
              return currentYear;
            }
            if (nextYears.includes(DEFAULT_SVI_YEAR)) {
              return DEFAULT_SVI_YEAR;
            }
            return nextYears[0];
          });
          setSviYearsError(null);
        })
        .catch((sviYearsFetchError) => {
          if (!isMounted) return;
          console.error("Failed to load SVI years:", sviYearsFetchError);
          setSviYears(SVI_FALLBACK_YEARS);
          setSelectedSviYear((currentYear) => (
            currentYear != null && SVI_FALLBACK_YEARS.includes(currentYear)
              ? currentYear
              : DEFAULT_SVI_YEAR
          ));
          setSviYearsError("Could not load SVI years from API. Falling back to 2022/2020/2018.");
        })
        .finally(() => {
          if (!isMounted) return;
          setIsSviYearsLoading(false);
        });

      return () => {
        isMounted = false;
      };
    }

    if (selectedDataSource === DATA_SOURCES.ACS_NMF) {
      setIsYearsLoading(false);
      setYearsError(null);
      setIsSviYearsLoading(false);
      setSviYearsError(null);
      return;
    }

    let isMounted = true;
    setIsYearsLoading(true);
    setIsSviYearsLoading(false);
    setSviYearsError(null);
    const yearsGeography = tractsActive ? "tract" : "county";

    fetch(`${API_BASE}/meta/years?geography=${yearsGeography}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Failed to load available years.");
        }
        return response.json();
      })
      .then((data) => {
        if (!isMounted) return;
        const fetchedYears = Array.isArray(data?.years)
          ? data.years.map((value) => Number(value)).filter((value) => Number.isFinite(value))
          : [];
        const uniqueSortedYears = Array.from(new Set(fetchedYears)).sort((a, b) => b - a);
        if (uniqueSortedYears.length === 0) {
          throw new Error("No years returned from API.");
        }
        console.log(`Available ${yearsGeography} years:`, uniqueSortedYears);
        setYears(uniqueSortedYears);
        setYearsError(null);
        setSelectedYear((currentYear) => (
          currentYear != null && uniqueSortedYears.includes(currentYear)
            ? currentYear
            : uniqueSortedYears[0]
        ));
      })
      .catch((yearsFetchError) => {
        if (!isMounted) return;
        console.error("Failed to load years:", yearsFetchError);
        setYearsError(
          `Could not load ${yearsGeography} years from API. Falling back to 2023.`
        );
        setYears(FALLBACK_YEARS);
        setSelectedYear((currentYear) => (
          currentYear != null && FALLBACK_YEARS.includes(currentYear)
            ? currentYear
            : FALLBACK_YEARS[0]
        ));
      })
      .finally(() => {
        if (!isMounted) return;
        setIsYearsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [selectedDataSource, tractsActive, activeGeography]);

  useEffect(() => {
    if (!isAcsDataSource) return;
    if (acsYearWindows.length === 0) {
      setSelectedYearWindow(null);
      return;
    }
    setSelectedYearWindow((currentYearWindow) => (
      currentYearWindow != null && acsYearWindows.includes(currentYearWindow)
        ? currentYearWindow
        : acsYearWindows[0]
    ));
  }, [acsYearWindows, isAcsDataSource]);

  useEffect(() => {
    if (!isAcsDataSource) {
      if (selectedType !== "CrdPrv" && selectedType !== "AgeAdjPrv") {
        setSelectedType("CrdPrv");
      }
      return;
    }

    if (acsDataValueTypeIds.length === 0) {
      setSelectedType("");
      return;
    }

    setSelectedType((currentType) => {
      if (currentType && acsDataValueTypeIds.includes(currentType)) {
        return currentType;
      }
      if (acsDataValueTypeIds.includes("Percent")) {
        return "Percent";
      }
      return acsDataValueTypeIds[0];
    });
  }, [acsDataValueTypeIds, isAcsDataSource, selectedType]);

  useEffect(() => {
    if (!isHpsaDataSource) {
      setIsHpsaChoroplethLoading(false);
      setHpsaChoroplethError(null);
      setHpsaChoropleth(null);
      return;
    }
  }, [isHpsaDataSource]);

  const syncHpsaMetadataFromCountyPayload = useCallback((payload) => {
    const metadata = payload?.metadata && typeof payload.metadata === "object"
      ? payload.metadata
      : null;
    const quartiles = metadata?.quartiles && typeof metadata.quartiles === "object"
      ? metadata.quartiles
      : null;
    const domain = typeof metadata?.domain === "string"
      ? metadata.domain
      : selectedHpsaDomain;
    setHpsaChoropleth({
      domain,
      quartiles,
    });
  }, [selectedHpsaDomain]);

  const fetchCountyChoropleth = useCallback(
    async (bboxValue) => {
      if (isAcsDataSource && !isAcsMeasureSelected) {
        return { type: "FeatureCollection", features: [] };
      }

      // Abort previous request if any
      if (countyAbortRef.current) {
        countyAbortRef.current.abort();
      }
      const controller = new AbortController();
      countyAbortRef.current = controller;

      if (isCdcDataSource) {
        const metric = String(
          selectedMeasureId || CDC_DEFAULT_METRIC_BY_BASIS[cdcBasis] || "total_funding"
        ).trim();
        const payload = await fetchCdcFundingMap({
          apiBase: API_BASE,
          basis: cdcBasis,
          geography: cdcGeography,
          metric,
          assistance_type: cdcBasis === "prime" ? cdcAssistanceType : null,
          fiscal_year: cdcFiscalYear || null,
          awarding_office: cdcAwardingOffice || null,
          funding_office: cdcFundingOffice || null,
          center: cdcCenter || null,
          state: cdcStateFilter || null,
          bbox: bboxValue || null,
          zoom: mapZoom,
          limit: cdcGeography === "state" ? 200 : 7000,
          signal: controller.signal,
        });
        const features = Array.isArray(payload?.features) ? payload.features : [];
        const note = String(payload?.meta?.note ?? "").trim();
        const noData = features.length === 0 ? "No CDC funding data in view." : "";
        setCdcMapMessage([note, noData].filter(Boolean).join(" ") || null);
        return payload;
      }

      if (isFemaDataSource) {
        if (!bboxValue) {
          throw new Error("bbox is required for FEMA NRI map requests.");
        }
        const payload = await fetchFemaNriMap({
          apiBase: API_BASE,
          measure: selectedMeasureId,
          bbox: bboxValue,
          zoom: mapZoom,
          level: "county",
          limit: 7000,
          signal: controller.signal,
        });

        const features = Array.isArray(payload?.features) ? payload.features : [];
        const warningNote = typeof payload?.meta?.warning === "string"
          ? payload.meta.warning.trim()
          : "";
        const noDataNote = features.length === 0 ? "No FEMA NRI data in view." : "";
        const combinedNote = [warningNote, noDataNote]
          .map((item) => String(item || "").trim())
          .filter(Boolean)
          .join(" ");
        setFemaMapMessage(combinedNote || null);
        return payload;
      }

      if (isUsdaDataSource) {
        if (!bboxValue) {
          throw new Error("bbox is required for USDA Food Environment map requests.");
        }
        const requestLevel = usdaRequestLevel ?? "county";
        const payload = await fetchUsdaFoodEnvironmentMap({
          apiBase: API_BASE,
          variable: selectedMeasureId,
          bbox: bboxValue,
          zoom: mapZoom,
          level: requestLevel,
          limit: 5000,
          signal: controller.signal,
        });

        const resolvedLevel = String(
          payload?.level
          ?? (requestLevel === "state" ? "state" : usdaSelectedLevel)
        ).trim().toLowerCase() === "state"
          ? "state"
          : "county";
        setUsdaMapLevel(resolvedLevel);

        const features = Array.isArray(payload?.features) ? payload.features : [];
        const warningNote = typeof payload?.meta?.warning === "string"
          ? payload.meta.warning.trim()
          : "";
        const zoomNote = (
          usdaLowZoomStateFallback
          && usdaSelectedLevel !== "state"
        ) ? "Zoom in to view county-level detail." : "";
        const noDataNote = features.length === 0 ? "No data in view." : "";
        const combinedNote = [zoomNote, warningNote, noDataNote]
          .map((item) => String(item || "").trim())
          .filter(Boolean)
          .join(" ");
        setUsdaMapMessage(combinedNote || null);

        const diagnosticsMeta = payload?.meta && typeof payload.meta === "object"
          ? payload.meta
          : {};
        const simplifyTolerance = Number(
          diagnosticsMeta?.simplify_tolerance_degrees ?? diagnosticsMeta?.simplify_tolerance_meters
        );
        const geoPrecision = Number(diagnosticsMeta?.geojson_precision);
        setUsdaMapDiagnostics({
          zoom: Number(payload?.zoom ?? mapZoom),
          level: resolvedLevel,
          simplifyToleranceDegrees: Number.isFinite(simplifyTolerance)
            ? simplifyTolerance
            : getUsdaSimplifyToleranceDegrees(mapZoom),
          geojsonPrecision: Number.isFinite(geoPrecision) ? geoPrecision : 6,
        });
        return payload;
      }

      setUsdaMapMessage(null);
      setUsdaMapLevel("county");
      setUsdaMapDiagnostics(null);
      setFemaMapMessage(null);
      setCdcMapMessage(null);

      if (isHpsaDataSource) {
        const hpsaUrl = new URL(`${API_BASE}/hpsa/counties`);
        hpsaUrl.searchParams.set("domain", selectedHpsaDomain);
        hpsaUrl.searchParams.set("simplify", "0.02");
        hpsaUrl.searchParams.set("limit", "5000");
        if (bboxValue) {
          hpsaUrl.searchParams.set("bbox", bboxValue);
        }

        setIsHpsaChoroplethLoading(true);
        setHpsaChoroplethError(null);
        try {
          const hpsaResponse = await fetch(hpsaUrl, { signal: controller.signal });
          if (!hpsaResponse.ok) {
            const body = await parseErrorBody(hpsaResponse);
            throw new Error(`HPSA county request failed (${hpsaResponse.status}): ${body}`);
          }
          const payload = await hpsaResponse.json();
          syncHpsaMetadataFromCountyPayload(payload);
          return payload;
        } catch (fetchError) {
          if (isAbortLikeError(fetchError, controller.signal)) {
            throw fetchError;
          }
          const isNetworkFetchError =
            fetchError instanceof TypeError
            && /failed to fetch/i.test(fetchError.message ?? "");
          setHpsaChoropleth(null);
          setHpsaChoroplethError(
            isNetworkFetchError
              ? `Could not reach API at ${API_BASE}. Start/restart backend on port 8000.`
              : (fetchError.message ?? "Failed to load HPSA county map.")
          );
          throw fetchError;
        } finally {
          setIsHpsaChoroplethLoading(false);
        }
      }

      if (isCmsDataSource) {
        const boundaryUrl = new URL(`${API_BASE}/counties/boundaries/geojson`);
        boundaryUrl.searchParams.set("simplify", "0.02");
        boundaryUrl.searchParams.set("limit", "5000");
        if (bboxValue) {
          boundaryUrl.searchParams.set("bbox", bboxValue);
        }

        const [boundaryResponse, cmsSelectionData] = await Promise.all([
          fetch(boundaryUrl, { signal: controller.signal }),
          loadCmsSelectionData({
            year: Number(selectedYear),
            ageLevel: selectedCmsAgeLevel,
            measureId: selectedMeasureId,
            signal: controller.signal,
          }),
        ]);

        if (!boundaryResponse.ok) {
          const body = await parseErrorBody(boundaryResponse);
          throw new Error(`County request failed (${boundaryResponse.status}): ${body}`);
        }

        const boundaryGeojson = await boundaryResponse.json();
        const rowsByCounty = cmsSelectionData?.rowsByCounty ?? new Map();
        const mergedFeatures = (boundaryGeojson?.features ?? []).map((feature) => {
          const baseProperties = feature?.properties ?? {};
          const countyFips = getCountyFipsFromProperties(baseProperties);
          const cmsRow = countyFips ? rowsByCounty.get(countyFips) : null;
          const cmsValue = cmsRow?.value ?? null;
          const cmsIsSuppressed = Boolean(cmsRow?.is_suppressed);
          return {
            ...feature,
            properties: {
              ...baseProperties,
              county_fips: countyFips ?? baseProperties.county_fips ?? null,
              county_name: baseProperties.county_name ?? baseProperties.name ?? cmsRow?.geo_name ?? null,
              cms_value: cmsValue,
              cms_is_suppressed: cmsIsSuppressed,
              cms_measure_id: selectedMeasureId,
              year: cmsRow?.year ?? Number(selectedYear),
              age_level: cmsRow?.age_level ?? selectedCmsAgeLevel,
              measure_id: selectedMeasureId,
              value: cmsIsSuppressed ? null : cmsValue,
              data_value: cmsIsSuppressed ? null : cmsValue,
            },
          };
        });

        setCmsBreaks(Array.isArray(cmsSelectionData?.breaks) ? cmsSelectionData.breaks : []);
        return {
          ...(boundaryGeojson ?? {}),
          type: "FeatureCollection",
          features: mergedFeatures,
        };
      }

      const url = isAcsDataSource
        ? new URL(`${API_BASE}/acs-nmf/counties`)
        : isSviDataSource
          ? new URL(`${API_BASE}/svi/counties`)
          : new URL(`${API_BASE}/counties/boundaries/geojson/estimates`);
      url.searchParams.set("measure_id", selectedMeasureId);
      if (isAcsDataSource) {
        if (selectedYearWindow) {
          url.searchParams.set("year_window", String(selectedYearWindow));
        }
      } else if (isSviDataSource) {
        url.searchParams.set("year", String(selectedSviYear));
      } else {
        url.searchParams.set("year", String(selectedYear));
      }
      if (!isSviDataSource && selectedType) {
        url.searchParams.set("data_value_type_id", selectedType);
      }
      if (bboxValue) {
        url.searchParams.set("bbox", bboxValue);
      }

      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) {
        const body = await parseErrorBody(response);
        throw new Error(`County request failed (${response.status}): ${body}`);
      }
      return response.json();
    },
    [
      isAcsDataSource,
      isSviDataSource,
      isHpsaDataSource,
      isCmsDataSource,
      isCdcDataSource,
      isUsdaDataSource,
      isFemaDataSource,
      isAcsMeasureSelected,
      cdcAssistanceType,
      cdcAwardingOffice,
      cdcBasis,
      cdcCenter,
      cdcFiscalYear,
      cdcFundingOffice,
      cdcGeography,
      cdcStateFilter,
      mapZoom,
      loadCmsSelectionData,
      syncHpsaMetadataFromCountyPayload,
      selectedHpsaDomain,
      selectedCmsAgeLevel,
      selectedMeasureId,
      selectedSviYear,
      selectedYear,
      selectedYearWindow,
      selectedType,
      usdaLowZoomStateFallback,
      usdaRequestLevel,
      usdaSelectedLevel,
    ]
  );

  const fetchCountyBoundaryOverlay = useCallback(async (bboxValue) => {
    const url = new URL(`${API_BASE}/counties/boundaries/geojson`);
    url.searchParams.set("bbox", bboxValue);
    url.searchParams.set("boundaries_only", "true");
    url.searchParams.set("simplify", "0.01");

    // Abort previous request if any
    if (outlineAbortRef.current) {
      outlineAbortRef.current.abort();
    }
    const controller = new AbortController();
    outlineAbortRef.current = controller;

    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      const body = await parseErrorBody(response);
      throw new Error(
        `County boundary overlay request failed (${response.status}): ${body}`
      );
    }
    return response.json();
  }, []);

  const fetchStateBoundaryOverlay = useCallback(async () => {
    const url = new URL(`${API_BASE}/states/boundaries/geojson`);
    url.searchParams.set("simplify", "0.02");

    if (stateAbortRef.current) {
      stateAbortRef.current.abort();
    }
    const controller = new AbortController();
    stateAbortRef.current = controller;

    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      const body = await parseErrorBody(response);
      throw new Error(`State boundary request failed (${response.status}): ${body}`);
    }
    return response.json();
  }, []);

  const fetchAcsLegend = useCallback(async () => {
    const url = new URL(
      acsGeography === "tract"
        ? `${API_BASE}/acs-nmf/tracts/legend`
        : `${API_BASE}/acs-nmf/legend`
    );
    url.searchParams.set("measure_id", selectedMeasureId);
    if (selectedYearWindow) {
      url.searchParams.set("year_window", String(selectedYearWindow));
    }
    if (acsGeography === "tract" && legendBbox) {
      url.searchParams.set("bbox", legendBbox);
    }
    if (selectedType) {
      url.searchParams.set("data_value_type_id", selectedType);
    }
    url.searchParams.set("bins", String(BIN_COUNT));

    const response = await fetch(url);
    if (!response.ok) {
      const body = await parseErrorBody(response);
      throw new Error(`ACS legend request failed (${response.status}): ${body}`);
    }
    return response.json();
  }, [acsGeography, legendBbox, selectedMeasureId, selectedType, selectedYearWindow]);

  useEffect(() => {
    if (!isAcsDataSource || !isAcsMeasureSelected || !selectedMeasureId || !selectedType) {
      setAcsLegend(null);
      setIsLegendLoading(false);
      return;
    }

    const legendKey = (
      `legend|acs-nmf|${acsGeography}|${selectedMeasureId}|`
      + `${selectedYearWindow ?? "latest"}|${selectedType}|${legendBbox ?? "nationwide"}|${BIN_COUNT}`
    );
    const cachedLegend = getCached(legendKey);
    if (cachedLegend) {
      setAcsLegend(cachedLegend);
      return;
    }

    setIsLegendLoading(true);
    fetchWithDedupe(legendKey, async () => {
      try {
        const data = await fetchAcsLegend();
        setCached(legendKey, data);
        setAcsLegend(data);
      } catch (legendError) {
        if (isAbortLikeError(legendError)) {
          return;
        }
        console.error("ACS legend fetch failed:", legendError);
        setAcsLegend(null);
      } finally {
        setIsLegendLoading(false);
      }
    }).catch(() => {
      setIsLegendLoading(false);
    });
  }, [
    fetchAcsLegend,
    fetchWithDedupe,
    getCached,
    isAcsDataSource,
    isAcsMeasureSelected,
    acsGeography,
    selectedMeasureId,
    selectedType,
    selectedYearWindow,
    legendBbox,
    setCached,
  ]);

  const usdaLegendBbox = isUsdaHeatMode ? bbox : null;

  const fetchUsdaLegendPayload = useCallback(async ({ signal } = {}) => {
    if (!selectedMeasureId) return null;
    return fetchUsdaFoodEnvironmentLegend({
      apiBase: API_BASE,
      variable: selectedMeasureId,
      bbox: usdaLegendBbox,
      level: usdaRequestLevel ?? "auto",
      signal,
    });
  }, [selectedMeasureId, usdaLegendBbox, usdaRequestLevel]);

  useEffect(() => {
    if (!isUsdaDataSource || !selectedMeasureId) {
      if (usdaLegendAbortRef.current) {
        usdaLegendAbortRef.current.abort();
        usdaLegendAbortRef.current = null;
      }
      setUsdaLegend(null);
      setIsUsdaLegendLoading(false);
      return;
    }

    const legendKey = `legend|usda|${selectedMeasureId}|${usdaRenderLevel ?? "county"}|${usdaLegendBbox ?? "global"}|${BIN_COUNT}`;
    const cachedLegend = getCached(legendKey);
    if (cachedLegend) {
      setUsdaLegend(cachedLegend);
      return;
    }

    if (usdaLegendAbortRef.current) {
      usdaLegendAbortRef.current.abort();
    }
    const controller = new AbortController();
    usdaLegendAbortRef.current = controller;

    setIsUsdaLegendLoading(true);
    fetchUsdaLegendPayload({ signal: controller.signal })
      .then((data) => {
        if (!data) return;
        setCached(legendKey, data);
        setUsdaLegend(data);
      })
      .catch((legendError) => {
        if (isAbortLikeError(legendError, controller.signal)) {
          return;
        }
        console.error("USDA legend fetch failed:", legendError);
        setUsdaLegend(null);
      })
      .finally(() => {
        if (usdaLegendAbortRef.current === controller) {
          usdaLegendAbortRef.current = null;
        }
        setIsUsdaLegendLoading(false);
      });

    return () => {
      controller.abort();
      if (usdaLegendAbortRef.current === controller) {
        usdaLegendAbortRef.current = null;
      }
    };
  }, [
    fetchUsdaLegendPayload,
    getCached,
    isUsdaDataSource,
    selectedMeasureId,
    usdaLegendBbox,
    usdaRenderLevel,
    setCached,
  ]);

  const femaLegendBbox = tractsActive ? bbox : null;

  const fetchFemaLegendPayload = useCallback(async ({ signal } = {}) => {
    if (!selectedMeasureId) return null;
    return fetchFemaNriLegend({
      apiBase: API_BASE,
      measure: selectedMeasureId,
      bbox: femaLegendBbox,
      level: tractsActive ? "tract" : "county",
      signal,
    });
  }, [femaLegendBbox, selectedMeasureId, tractsActive]);

  useEffect(() => {
    if (!isFemaDataSource || !selectedMeasureId) {
      if (femaLegendAbortRef.current) {
        femaLegendAbortRef.current.abort();
        femaLegendAbortRef.current = null;
      }
      setFemaLegend(null);
      setIsFemaLegendLoading(false);
      return;
    }

    const femaLevel = tractsActive ? "tract" : "county";
    const legendKey = `legend|fema|${selectedMeasureId}|${femaLevel}|${femaLegendBbox ?? "global"}|${BIN_COUNT}`;
    const cachedLegend = getCached(legendKey);
    if (cachedLegend) {
      setFemaLegend(cachedLegend);
      return;
    }

    if (femaLegendAbortRef.current) {
      femaLegendAbortRef.current.abort();
    }
    const controller = new AbortController();
    femaLegendAbortRef.current = controller;

    setIsFemaLegendLoading(true);
    fetchFemaLegendPayload({ signal: controller.signal })
      .then((data) => {
        if (!data) return;
        setCached(legendKey, data);
        setFemaLegend(data);
      })
      .catch((legendError) => {
        if (isAbortLikeError(legendError, controller.signal)) {
          return;
        }
        console.error("FEMA legend fetch failed:", legendError);
        setFemaLegend(null);
      })
      .finally(() => {
        if (femaLegendAbortRef.current === controller) {
          femaLegendAbortRef.current = null;
        }
        setIsFemaLegendLoading(false);
      });

    return () => {
      controller.abort();
      if (femaLegendAbortRef.current === controller) {
        femaLegendAbortRef.current = null;
      }
    };
  }, [
    fetchFemaLegendPayload,
    femaLegendBbox,
    getCached,
    isFemaDataSource,
    selectedMeasureId,
    setCached,
    tractsActive,
  ]);

  const cdcLegendBbox = bbox;

  const fetchCdcLegendPayload = useCallback(async ({ signal } = {}) => {
    if (!selectedMeasureId) return null;
    return fetchCdcFundingLegend({
      apiBase: API_BASE,
      basis: cdcBasis,
      geography: cdcGeography,
      metric: selectedMeasureId,
      assistance_type: cdcBasis === "prime" ? cdcAssistanceType : null,
      fiscal_year: cdcFiscalYear || null,
      awarding_office: cdcAwardingOffice || null,
      funding_office: cdcFundingOffice || null,
      center: cdcCenter || null,
      state: cdcStateFilter || null,
      bbox: cdcLegendBbox,
      signal,
    });
  }, [
    cdcAssistanceType,
    cdcAwardingOffice,
    cdcBasis,
    cdcCenter,
    cdcFiscalYear,
    cdcFundingOffice,
    cdcGeography,
    cdcLegendBbox,
    cdcStateFilter,
    selectedMeasureId,
  ]);

  useEffect(() => {
    if (!isCdcDataSource || !selectedMeasureId) {
      if (cdcLegendAbortRef.current) {
        cdcLegendAbortRef.current.abort();
        cdcLegendAbortRef.current = null;
      }
      setCdcLegend(null);
      setIsCdcLegendLoading(false);
      return;
    }

    const legendKey = `legend|cdc|${cdcBasis}|${cdcGeography}|${selectedMeasureId}|${cdcAssistanceType || "all"}|${cdcFiscalYear || "all"}|${cdcAwardingOffice || "all"}|${cdcFundingOffice || "all"}|${cdcCenter || "all"}|${cdcStateFilter || "all"}|${cdcLegendBbox ?? "global"}`;
    const cachedLegend = getCached(legendKey);
    if (cachedLegend) {
      setCdcLegend(cachedLegend);
      return;
    }

    if (cdcLegendAbortRef.current) {
      cdcLegendAbortRef.current.abort();
    }
    const controller = new AbortController();
    cdcLegendAbortRef.current = controller;

    setIsCdcLegendLoading(true);
    fetchCdcLegendPayload({ signal: controller.signal })
      .then((data) => {
        if (!data) return;
        setCached(legendKey, data);
        setCdcLegend(data);
      })
      .catch((legendError) => {
        if (isAbortLikeError(legendError, controller.signal)) {
          return;
        }
        console.error("CDC legend fetch failed:", legendError);
        setCdcLegend(null);
      })
      .finally(() => {
        if (cdcLegendAbortRef.current === controller) {
          cdcLegendAbortRef.current = null;
        }
        setIsCdcLegendLoading(false);
      });

    return () => {
      controller.abort();
      if (cdcLegendAbortRef.current === controller) {
        cdcLegendAbortRef.current = null;
      }
    };
  }, [
    cdcAssistanceType,
    cdcAwardingOffice,
    cdcBasis,
    cdcCenter,
    cdcFiscalYear,
    cdcFundingOffice,
    cdcGeography,
    cdcLegendBbox,
    cdcStateFilter,
    fetchCdcLegendPayload,
    getCached,
    isCdcDataSource,
    selectedMeasureId,
    setCached,
  ]);

  const fetchTractsForBbox = useCallback(
    async (bboxValue) => {
      if (!bboxValue) {
        throw new Error("bbox is required for tract requests.");
      }
      if (isAcsDataSource && !isAcsMeasureSelected) {
        return { type: "FeatureCollection", features: [] };
      }

      // Abort previous request if any
      if (tractAbortRef.current) {
        tractAbortRef.current.abort();
      }
      const controller = new AbortController();
      tractAbortRef.current = controller;

      setUsdaMapMessage(null);
      setUsdaMapDiagnostics(null);
      setFemaMapMessage(null);

      if (isFemaDataSource) {
        const payload = await fetchFemaNriMap({
          apiBase: API_BASE,
          measure: selectedMeasureId,
          bbox: bboxValue,
          zoom: mapZoom,
          level: "tract",
          limit: 15000,
          signal: controller.signal,
        });
        const features = Array.isArray(payload?.features) ? payload.features : [];
        const warningNote = typeof payload?.meta?.warning === "string"
          ? payload.meta.warning.trim()
          : "";
        const noDataNote = features.length === 0 ? "No FEMA NRI tract data in view." : "";
        const combinedNote = [warningNote, noDataNote]
          .map((item) => String(item || "").trim())
          .filter(Boolean)
          .join(" ");
        setFemaMapMessage(combinedNote || null);
        return payload;
      }

      const url = isAcsDataSource
        ? new URL(`${API_BASE}/acs-nmf/tracts`)
        : isSviDataSource
          ? new URL(`${API_BASE}/svi/tracts`)
          : new URL(`${API_BASE}/geojson/tracts`);
      if (isAcsDataSource) {
        if (selectedYearWindow) {
          url.searchParams.set("year_window", String(selectedYearWindow));
        }
      } else if (isSviDataSource) {
        url.searchParams.set("year", String(selectedSviYear));
      } else {
        url.searchParams.set("year", String(selectedYear));
      }
      url.searchParams.set("measure_id", selectedMeasureId);
      if (!isSviDataSource && selectedType) {
        url.searchParams.set("data_value_type_id", selectedType);
      }
      url.searchParams.set("bbox", bboxValue);

      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) {
        const body = await parseErrorBody(response);
        throw new Error(`Tract request failed (${response.status}): ${body}`);
      }
      return response.json();
    },
    [
      isAcsDataSource,
      isSviDataSource,
      isFemaDataSource,
      isAcsMeasureSelected,
      mapZoom,
      selectedMeasureId,
      selectedSviYear,
      selectedYear,
      selectedType,
      selectedYearWindow,
    ]
  );

  // Clear cache when data-source context changes
  useEffect(() => {
    cacheRef.current.clear();
    // Abort all in-flight requests
    if (countyAbortRef.current) countyAbortRef.current.abort();
    if (tractAbortRef.current) tractAbortRef.current.abort();
    if (outlineAbortRef.current) outlineAbortRef.current.abort();
    if (stateAbortRef.current) stateAbortRef.current.abort();
    if (historyAbortRef.current) historyAbortRef.current.abort();
    if (usdaLegendAbortRef.current) usdaLegendAbortRef.current.abort();
    if (femaLegendAbortRef.current) femaLegendAbortRef.current.abort();
    if (cdcLegendAbortRef.current) cdcLegendAbortRef.current.abort();
    if (cdcSearchAbortRef.current) cdcSearchAbortRef.current.abort();
    if (cdcDetailAbortRef.current) cdcDetailAbortRef.current.abort();
    if (cdcTopAbortRef.current) cdcTopAbortRef.current.abort();
    // Clear currently-displayed geojson so the map updates for the new measure
    setCountyGeojson(null);
    setTractGeojson(null);
    setCountyBoundaryOverlay(null);
    setStateBoundaryOverlay(null);
    setAcsLegend(null);
    setUsdaLegend(null);
    setFemaLegend(null);
    setCdcLegend(null);
    setIsUsdaLegendLoading(false);
    setIsFemaLegendLoading(false);
    setIsCdcLegendLoading(false);
    setUsdaMapMessage(null);
    setFemaMapMessage(null);
    setCdcMapMessage(null);
    setUsdaMapLevel("county");
    setUsdaMapDiagnostics(null);
    setUsdaHeatLayer(null);
    setUsdaHeatHoverPoint(null);
    setIsUsdaHeatLoading(false);
    setHpsaChoropleth(null);
    setHpsaChoroplethError(null);
    setIsHpsaChoroplethLoading(false);
    setHistoryOpen(false);
    setCdcTopRows([]);
    setCdcTopNote(null);
    setCdcTopError(null);
    setIsCdcTopLoading(false);
    // Keep selection across measure/year/type changes; only clear transient hover state.
    setHoveredProps(null);
    if (pendingCountySelectionTimerRef.current) {
      clearTimeout(pendingCountySelectionTimerRef.current);
      pendingCountySelectionTimerRef.current = null;
    }
    pendingCountySelectionRef.current = null;
  }, [selectedDataSource, selectedMeasureId, selectedTemporalValue, selectedType]);

  // Ensure we have a bbox and clear the inactive layer when crossing the tract zoom
  useEffect(() => {
    // Recompute bbox from the current map immediately so the newly-active
    // layer fetch uses the correct viewport (ensures counties render when
    // zooming out from tracts).
    if (mapRef.current) {
      try {
        const m = mapRef.current;
        const bboxString = boundsToPaddedBbox(m.getBounds(), m.getZoom());
        setBbox(bboxString);
      } catch (err) {
        // ignore
      }
    }

    // Clear the layer that's not active to avoid showing stale geometry
    if (tractsActive) {
      setCountyGeojson(null);
    } else {
      setTractGeojson(null);
      setCountyBoundaryOverlay(null);
      setUsdaHeatLayer(null);
    }
  }, [tractsActive]);

  // Prefetch tract data when approaching zoom threshold
  useEffect(() => {
    if (!bbox || selectedTemporalValue == null || mapZoom !== TRACT_ZOOM - 1) {
      return;
    }
    if (isHpsaDataSource) {
      return;
    }
    if (isCmsDataSource) {
      return;
    }
    if (isUsdaDataSource) {
      return;
    }
    if (isAcsDataSource && !isAcsMeasureSelected) {
      return;
    }

    const key = makeCacheKey(
      `${datasetCachePrefix}-tracts`,
      selectedTemporalValue,
      selectedMeasureId,
      selectedType,
      bbox
    );
    
    fetchWithDedupe(key, async () => {
      try {
        const data = await fetchTractsForBbox(bbox);
        setCached(key, data);
      } catch (prefetchError) {
        if (isAbortLikeError(prefetchError)) {
          return;
        }
        console.warn("Tract prefetch failed:", prefetchError);
      }
    }).catch(() => {
      // Silently ignore prefetch errors
    });
  }, [
    bbox,
    datasetCachePrefix,
    fetchTractsForBbox,
    fetchWithDedupe,
    isHpsaDataSource,
    isCmsDataSource,
    isUsdaDataSource,
    isAcsDataSource,
    isAcsMeasureSelected,
    mapZoom,
    selectedMeasureId,
    selectedTemporalValue,
    selectedType,
    setCached,
  ]);

  // Fetch state boundary overlay for county view
  useEffect(() => {
    if (tractsActive) {
      setStateBoundaryOverlay(null);
      return;
    }

    const stateReqId = latestStateReqRef.current + 1;
    latestStateReqRef.current = stateReqId;
    const stateKey = "stateOutline|nationwide|simplify:0.02";

    const cachedStateData = getCached(stateKey);
    if (cachedStateData) {
      setStateBoundaryOverlay(cachedStateData);
      return;
    }

    fetchWithDedupe(stateKey, async () => {
      try {
        const data = await fetchStateBoundaryOverlay();
        if (latestStateReqRef.current === stateReqId) {
          setCached(stateKey, data);
          setStateBoundaryOverlay(data);
        }
      } catch (err) {
        if (latestStateReqRef.current === stateReqId) {
          if (isAbortLikeError(err)) {
            return;
          }
          console.error("State boundary fetch failed:", err);
        }
      }
    }).catch(() => {
      // Ignore
    });
  }, [tractsActive, fetchStateBoundaryOverlay, getCached, setCached, fetchWithDedupe]);

  // Main data-fetching effect with caching, deduping, and stale-while-revalidate
  useEffect(() => {
    const missingMeasureContext = !isHpsaDataSource && !selectedMeasureId;
    const missingTypeContext = (
      !isSviDataSource
      && !isHpsaDataSource
      && !isCmsDataSource
      && !isCdcDataSource
      && !isUsdaDataSource
      && !isFemaDataSource
      && !selectedType
    );
    if (
      !bbox
      || selectedTemporalValue == null
      || missingMeasureContext
      || missingTypeContext
    ) {
      return;
    }
    if (isAcsDataSource && !isAcsMeasureSelected) {
      setCountyGeojson(null);
      setTractGeojson(null);
      setCountyBoundaryOverlay(null);
      return;
    }

    if (tractsActive) {
      // Fetch active tract-level layer
      {
        const tractReqId = latestTractReqRef.current + 1;
        latestTractReqRef.current = tractReqId;

        const tractKey = makeCacheKey(
          `${datasetCachePrefix}-tracts`,
          selectedTemporalValue,
          selectedMeasureId,
          selectedType,
          bbox
        );
        const applyTractLayerData = (data) => {
          setTractGeojson(data);
          setUsdaHeatLayer(null);
        };
        const fetchTractPayload = () => fetchTractsForBbox(bbox);

        // Check cache first
        const cachedTractData = getCached(tractKey);
        if (cachedTractData) {
          applyTractLayerData(cachedTractData);
          // Background refresh
          fetchWithDedupe(tractKey, fetchTractPayload)
            .then((data) => {
              if (latestTractReqRef.current !== tractReqId) {
                return;
              }
              setCached(tractKey, data);
              applyTractLayerData(data);
            })
            .catch((err) => {
              if (latestTractReqRef.current !== tractReqId) {
                return;
              }
              if (isAbortLikeError(err)) {
                return;
              }
              console.error("Tract background refresh failed:", err);
            });
        } else {
          // No cache, do a for-real fetch (with loading state)
          setIsTractLoading(true);
          fetchWithDedupe(tractKey, fetchTractPayload)
            .then((data) => {
              if (latestTractReqRef.current !== tractReqId) {
                return;
              }
              setCached(tractKey, data);
              applyTractLayerData(data);
              setError(null);
            })
            .catch((err) => {
              if (latestTractReqRef.current !== tractReqId) {
                return;
              }
              if (isAbortLikeError(err)) {
                return;
              }
              console.error(err);
              setError(err.message ?? "Failed to load tract map data.");
            })
            .finally(() => {
              if (latestTractReqRef.current !== tractReqId) {
                return;
              }
              setIsTractLoading(false);
            });
        }
      }

      const outlineReqId = latestOutlineReqRef.current + 1;
      latestOutlineReqRef.current = outlineReqId;

      const outlineKey = makeCacheKey(
        "countyOutline",
        selectedTemporalValue,
        selectedMeasureId,
        selectedType,
        bbox
      );

      // Check cache first
      const cachedOutlineData = getCached(outlineKey);
      if (cachedOutlineData) {
        setCountyBoundaryOverlay(cachedOutlineData);
        // Background refresh
        fetchWithDedupe(outlineKey, async () => {
          try {
            const data = await fetchCountyBoundaryOverlay(bbox);
            if (latestOutlineReqRef.current === outlineReqId) {
              setCached(outlineKey, data);
              setCountyBoundaryOverlay(data);
            }
          } catch (err) {
            if (latestOutlineReqRef.current === outlineReqId) {
              if (isAbortLikeError(err)) {
                return;
              }
              console.error("Outline background refresh failed:", err);
            }
          }
        }).catch(() => {
          // Ignore errors
        });
      } else {
        // No cache
        setIsOutlineLoading(true);

        fetchWithDedupe(outlineKey, async () => {
          try {
            const data = await fetchCountyBoundaryOverlay(bbox);
            if (latestOutlineReqRef.current === outlineReqId) {
              setCached(outlineKey, data);
              setCountyBoundaryOverlay(data);
            }
          } catch (err) {
            if (latestOutlineReqRef.current === outlineReqId) {
              if (isAbortLikeError(err)) {
                return;
              }
              console.error(err);
              // Don't set error for overlay; it's secondary
            }
          } finally {
            if (latestOutlineReqRef.current === outlineReqId) {
              setIsOutlineLoading(false);
            }
          }
        }).catch(() => {
          // Ignore
        });
      }
    } else {
      // Fetch county choropleth only
      const countyReqId = latestCountyReqRef.current + 1;
      latestCountyReqRef.current = countyReqId;
      
      const countyKey = `${makeCacheKey(
        `${datasetCachePrefix}-counties`,
        selectedTemporalValue,
        selectedMeasureId,
        selectedType,
        bbox
      )}|reload:${countyReloadNonce}`;
      
      // Check cache first
      const cachedCountyData = getCached(countyKey);
      if (cachedCountyData) {
        setCountyGeojson(cachedCountyData);
        setCountyBoundaryOverlay(null);
        if (isHpsaDataSource) {
          syncHpsaMetadataFromCountyPayload(cachedCountyData);
          setHpsaChoroplethError(null);
          setIsHpsaChoroplethLoading(false);
        }
        // Background refresh
        fetchWithDedupe(countyKey, async () => {
          try {
            const data = await fetchCountyChoropleth(bbox);
            if (latestCountyReqRef.current === countyReqId) {
              setCached(countyKey, data);
              setCountyGeojson(data);
            }
          } catch (err) {
            if (latestCountyReqRef.current === countyReqId) {
              if (isAbortLikeError(err)) {
                return;
              }
              console.error("County background refresh failed:", err);
            }
          }
        }).catch(() => {
          // Ignore
        });
      } else {
        // No cache
        setIsCountyLoading(true);
        
        fetchWithDedupe(countyKey, async () => {
          try {
            const data = await fetchCountyChoropleth(bbox);
            if (latestCountyReqRef.current === countyReqId) {
              setCached(countyKey, data);
              setCountyGeojson(data);
              setCountyBoundaryOverlay(null);
              setError(null);
            }
          } catch (err) {
            if (latestCountyReqRef.current === countyReqId) {
              if (isAbortLikeError(err)) {
                return;
              }
              console.error(err);
              setError(err.message ?? "Failed to load county map data.");
              // Don't clear county geojson—keep it visible
            }
          } finally {
            if (latestCountyReqRef.current === countyReqId) {
              setIsCountyLoading(false);
            }
          }
        }).catch(() => {
          // Ignore
        });
      }
    }
  }, [
    bbox,
    countyReloadNonce,
    fetchCountyBoundaryOverlay,
    fetchCountyChoropleth,
    fetchTractsForBbox,
    fetchWithDedupe,
    getCached,
    datasetCachePrefix,
    isAcsDataSource,
    isSviDataSource,
    isHpsaDataSource,
    isCmsDataSource,
    isUsdaDataSource,
    isFemaDataSource,
    syncHpsaMetadataFromCountyPayload,
    isAcsMeasureSelected,
    selectedMeasureId,
    selectedTemporalValue,
    selectedType,
    selectedYear,
    setCached,
    tractsActive,
  ]);

  const femaRatingColorByLabel = useMemo(() => {
    const output = new Map();
    const categories = Array.isArray(femaLegend?.categories) ? femaLegend.categories : [];
    categories.forEach((category) => {
      const label = normalizeFemaRatingLabel(category?.label ?? category?.value);
      if (!label) return;
      if (FEMA_RATING_COLORS[label]) {
        output.set(label, FEMA_RATING_COLORS[label]);
      }
    });
    return output;
  }, [femaLegend]);

  const choroplethStyle = useCallback(
    (feature) => {
      const value = getValueFromProperties(feature?.properties);
      let fillColor = getColor(value, breaks);
      let strokeColor = tractsActive ? "#334155" : "#555";
      let strokeWeight = tractsActive ? 0.6 : 1;
      let fillOpacity = isHpsaDataSource ? 0.78 : 0.72;
      if (isHpsaDataSource) {
        const tier = Number(feature?.properties?.tier);
        const designated = Boolean(feature?.properties?.designated);
        if ([1, 2, 3, 4].includes(tier)) {
          fillColor = HPSA_TIER_COLORS[tier] ?? HPSA_TIER_COLORS[4];
        } else {
          fillColor = designated
            ? HPSA_DESIGNATED_NO_SCORE_COLOR
            : HPSA_NOT_DESIGNATED_COLOR;
        }
      } else if (isSviDataSource) {
        const level = getSviLevel(value);
        const bin = sviBins.find((item) => item.level === level);
        fillColor = level == null
          ? NO_DATA_COLOR
          : (COLORS[bin?.colorIndex ?? 0] ?? COLORS[COLORS.length - 1]);
      } else if (isUsdaDataSource) {
        fillColor = fillColor || NO_DATA_COLOR;
        strokeColor = darkenHexColor(fillColor, 0.18);
        strokeWeight = 0.7;
        fillOpacity = 0.85;
      } else if (isFemaDataSource) {
        const isRatingMeasure = (
          String(selectedMeasure?.fema_value_type ?? "").trim().toLowerCase() === "rating"
          || String(selectedMeasure?.fema_legend_mode ?? "").trim().toLowerCase() === "ordered_category"
        );
        if (isRatingMeasure) {
          const ratingLabel = normalizeFemaRatingLabel(
            feature?.properties?.value_text
            ?? feature?.properties?.rating
            ?? feature?.properties?.value
          );
          fillColor = ratingLabel
            ? (femaRatingColorByLabel.get(ratingLabel) ?? FEMA_RATING_COLORS[ratingLabel] ?? NO_DATA_COLOR)
            : NO_DATA_COLOR;
        } else {
          fillColor = fillColor || NO_DATA_COLOR;
        }
        strokeColor = darkenHexColor(fillColor, 0.18);
        strokeWeight = tractsActive ? 0.6 : 0.8;
        fillOpacity = 0.84;
      }
      return {
        color: strokeColor,
        weight: strokeWeight,
        opacity: 1,
        fillColor,
        fillOpacity,
        lineJoin: "round",
        lineCap: "round",
      };
    },
    [
      breaks,
      femaRatingColorByLabel,
      isFemaDataSource,
      isHpsaDataSource,
      isSviDataSource,
      isUsdaDataSource,
      selectedMeasure,
      sviBins,
      tractsActive,
    ]
  );

  const countyBoundaryLineStyle = useCallback(() => {
    return {
      color: "#1f2937",
      weight: 1,
      opacity: 0.8,
      fill: false,
    };
  }, []);

  const stateBoundaryLineStyle = useCallback(() => {
    return {
      color: STATE_BORDER_COLOR,
      weight: 2.0,
      opacity: 0.95,
      fill: false,
    };
  }, []);

  const applySelectedStyle = useCallback((layer) => {
    if (isUsdaDataSource || isFemaDataSource) {
      layer.setStyle({
        color: "#0f2d46",
        weight: 2,
        opacity: 1,
        lineJoin: "round",
        lineCap: "round",
      });
      return;
    }
    layer.setStyle({ color: "orange", weight: 2.5 });
  }, [isFemaDataSource, isUsdaDataSource]);

  const handleFeatureClick = useCallback(
    (feature, layer, options = {}) => {
      const shouldOpenHistory = options.openHistory !== false && historySupported;
      const geoJsonLayer = geoJsonRef.current;
      if (!geoJsonLayer) return;

      if (selectedLayerRef.current && selectedLayerRef.current !== layer) {
        geoJsonLayer.resetStyle(selectedLayerRef.current);
      }

      selectedLayerRef.current = layer;
      const nextSelectedProps = { ...(feature.properties ?? {}) };
      if (
        nextSelectedProps.lat == null
        || nextSelectedProps.lng == null
        || Number.isNaN(Number(nextSelectedProps.lat))
        || Number.isNaN(Number(nextSelectedProps.lng))
      ) {
        if (layer && typeof layer.getBounds === "function") {
          const bounds = layer.getBounds();
          if (bounds && typeof bounds.isValid === "function" && bounds.isValid()) {
            const center = bounds.getCenter();
            nextSelectedProps.lat = center.lat;
            nextSelectedProps.lng = center.lng;
          }
        } else if (layer && typeof layer.getLatLng === "function") {
          const center = layer.getLatLng();
          nextSelectedProps.lat = center.lat;
          nextSelectedProps.lng = center.lng;
        }
      }
      setSelectedProps(nextSelectedProps);
      if (shouldOpenHistory) {
        setHistoryOpen(true);
      } else if (!historySupported) {
        setHistoryOpen(false);
      }
      applySelectedStyle(layer);
    },
    [applySelectedStyle, historySupported]
  );

  const buildCountyHoverTooltipHtml = useCallback(
    (featureProps) => {
      if (!featureProps || (tractsActive && !isUsdaDataSource && !isFemaDataSource)) {
        return null;
      }

      // Keep mobile behavior stable by skipping hover tooltips on coarse pointers.
      if (
        typeof window !== "undefined"
        && typeof window.matchMedia === "function"
        && window.matchMedia("(pointer: coarse)").matches
      ) {
        return null;
      }

      const countyName = getCountyName(featureProps);
      const stateAbbr = String(featureProps?.state_abbr ?? "").trim();
      const countyLine = stateAbbr ? `${countyName}, ${stateAbbr}` : countyName;

      if (isUsdaDataSource) {
        const featureLevel = String(
          featureProps?.level ?? featureProps?.geo_level ?? usdaRenderLevel ?? "county"
        ).trim().toLowerCase() === "state"
          ? "state"
          : "county";
        const areaLine = featureLevel === "state"
          ? String(
            pickFirstDefined(
              featureProps?.state_name,
              featureProps?.name,
              featureProps?.state_abbr,
              "Unknown"
            )
          ).trim()
          : countyLine;
        const usdaField = String(
          pickFirstDefined(featureProps?.variable, selectedMeasureId, "")
        ).trim();
        const usdaLabel = getUsdaPlainLabel(
          usdaField,
          pickFirstDefined(
            featureProps?.label,
            featureProps?.measure,
            getMeasureDisplayName(selectedMeasure),
            selectedMeasureId
          )
        );
        const usdaUnitType = inferTooltipUnitType({
          source: DATA_SOURCES.USDA_FOOD_ENV,
          measureId: usdaField || selectedMeasureId,
          measureLabel: usdaLabel,
          explicitUnitType: inferUsdaUnitTypeFromText(
            pickFirstDefined(featureProps?.unit, selectedMeasure?.usda_unit, "")
          ),
        });
        const usdaValueText = formatTooltipValue(featureProps?.value, usdaUnitType);
        return `${areaLine}<br/>${usdaLabel}: ${usdaValueText}`;
      }

      if (isFemaDataSource) {
        const featureLevel = String(
          featureProps?.level ?? featureProps?.geo_level ?? (tractsActive ? "tract" : "county")
        ).trim().toLowerCase() === "tract"
          ? "tract"
          : "county";
        const areaLine = featureLevel === "tract"
          ? String(
            pickFirstDefined(
              featureProps?.tract_name,
              featureProps?.name,
              featureProps?.tract_geoid,
              "Unknown tract"
            )
          ).trim()
          : countyLine;
        const femaLabel = getFemaMeasureLabel(selectedMeasure, selectedMeasureId);
        const femaValueText = formatFemaValue(
          pickFirstDefined(featureProps?.value_text, featureProps?.value),
          selectedMeasure
        );
        const ratingText = normalizeFemaRatingLabel(featureProps?.rating);
        const hazardName = String(
          pickFirstDefined(featureProps?.hazard_name, selectedMeasure?.fema_hazard_name, "")
        ).trim();
        const extra = [];
        if (
          ratingText
          && String(selectedMeasure?.fema_value_type ?? "").trim().toLowerCase() !== "rating"
        ) {
          extra.push(`Rating: ${ratingText}`);
        }
        if (hazardName) {
          extra.push(`Hazard: ${hazardName}`);
        }
        const extraLine = extra.length > 0 ? `<br/>${extra.join(" • ")}` : "";
        return `${areaLine}<br/>${femaLabel}: ${femaValueText}${extraLine}`;
      }

      if (isCmsDataSource) {
        const cmsUnitType = getCmsUnitType(selectedMeasure);
        const cmsValueText = Boolean(featureProps?.cms_is_suppressed)
          ? "Not shown"
          : formatCmsValue(featureProps?.cms_value, cmsUnitType, { includeUnits: true });
        const cmsYearText = String(featureProps?.year ?? selectedYear ?? "").trim() || "N/A";
        return `${countyLine}<br/>${cmsValueText}<br/>Medicare Fee-for-Service • ${cmsYearText}`;
      }

      if (isCdcDataSource) {
        const featureGeoLevel = String(
          featureProps?.geo_level ?? featureProps?.level ?? cdcGeography ?? "county"
        ).trim().toLowerCase() === "state"
          ? "state"
          : "county";
        const areaLine = featureGeoLevel === "state"
          ? String(
            pickFirstDefined(
              featureProps?.state_name,
              featureProps?.name,
              featureProps?.state_abbr,
              featureProps?.state_code,
              "Unknown state"
            )
          ).trim()
          : countyLine;
        const metricLabel = String(
          pickFirstDefined(
            featureProps?.metric_label,
            selectedMeasure?.label,
            selectedMeasure?.name,
            selectedMeasureId,
            "Value"
          )
        ).trim();
        const value = toFiniteNumericValue(
          pickFirstDefined(featureProps?.value, featureProps?.metric_value, featureProps?.data_value)
        );
        const metricId = String(selectedMeasureId ?? "").trim();
        const isCountMetric = metricId === "award_count" || metricId === "subaward_count";
        const valueText = value == null
          ? "No data"
          : isCountMetric
            ? Math.round(value).toLocaleString("en-US")
            : `$${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
        const countValue = toFiniteNumericValue(
          pickFirstDefined(
            featureProps?.award_count,
            cdcBasis === "subaward" ? featureProps?.subaward_count : null
          )
        );
        const countText = countValue == null ? "No data" : Math.round(countValue).toLocaleString("en-US");
        return `${areaLine}<br/>${metricLabel}: ${valueText}<br/>Award count: ${countText}`;
      }

      if (isHpsaDataSource) {
        const domain = String(featureProps?.hpsa_domain ?? selectedHpsaDomain ?? "").trim().toLowerCase();
        const currentDesignated = featureProps?.designated;
        const currentCoveragePct = featureProps?.coverage_pct;
        const pcStatus = toHpsaStatus(
          featureProps?.pc_designated ?? (domain === "pc" ? currentDesignated : undefined),
          featureProps?.pc_coverage_pct ?? (domain === "pc" ? currentCoveragePct : undefined)
        );
        const mhStatus = toHpsaStatus(
          featureProps?.mh_designated ?? (domain === "mh" ? currentDesignated : undefined),
          featureProps?.mh_coverage_pct ?? (domain === "mh" ? currentCoveragePct : undefined)
        );
        const dhStatus = toHpsaStatus(
          featureProps?.dh_designated ?? (domain === "dh" ? currentDesignated : undefined),
          featureProps?.dh_coverage_pct ?? (domain === "dh" ? currentCoveragePct : undefined)
        );
        const statusLine = `Primary: ${pcStatus} • Dental: ${dhStatus} • Mental: ${mhStatus}`;
        return `${countyLine}<br/>HPSA coverage<br/>${statusLine}`;
      }

      if (isSviDataSource) {
        const sviLabel = shortenMeasureLabelForTooltip(
          pickFirstDefined(
            featureProps?.measure_name,
            featureProps?.measure,
            getSviLabel(featureProps?.measure_id ?? selectedMeasureId),
            getMeasureDisplayName(selectedMeasure),
            selectedMeasureId
          )
        );
        const sviValue = toFiniteNumericValue(featureProps?.value ?? featureProps?.data_value);
        const percentileText = sviValue == null
          ? "No data"
          : `Percentile: ${sviValue.toFixed(sviValue <= 1 ? 2 : 1)}`;
        const sviYearText = String(featureProps?.year ?? selectedSviYear ?? "").trim();
        return `${countyLine}<br/>${sviLabel}<br/>${formatTooltipMetaLine(percentileText, sviYearText)}`;
      }

      if (isAcsDataSource) {
        const acsLabel = shortenMeasureLabelForTooltip(
          pickFirstDefined(
            featureProps?.measure,
            featureProps?.measure_name,
            getMeasureDisplayName(selectedMeasure),
            selectedMeasureId
          )
        );
        const acsUnitType = inferTooltipUnitType({
          source: DATA_SOURCES.ACS_NMF,
          measureId: featureProps?.measure_id ?? selectedMeasureId,
          measureLabel: acsLabel,
          dataValueTypeId: featureProps?.data_value_type_id ?? selectedType,
        });
        const acsValueText = formatTooltipValue(
          featureProps?.value ?? featureProps?.data_value,
          acsUnitType
        );
        const acsPeriod = formatYearWindowDisplay(
          featureProps?.year_window ?? selectedYearWindow ?? featureProps?.year ?? ""
        );
        return `${countyLine}<br/>${acsLabel}<br/>${formatTooltipMetaLine(acsValueText, acsPeriod)}`;
      }

      const placesLabelBase = shortenMeasureLabelForTooltip(
        pickFirstDefined(
          featureProps?.measure_name,
          featureProps?.measure,
          featureProps?.short_question_text,
          getMeasureDisplayName(selectedMeasure),
          selectedMeasureId
        )
      );
      const placesTypeLabel = formatDataValueTypeLabel(featureProps?.data_value_type_id ?? selectedType);
      const placesLabel = placesTypeLabel
        ? `${placesLabelBase} (${placesTypeLabel})`
        : placesLabelBase;
      const placesValueText = formatTooltipValue(
        featureProps?.value ?? featureProps?.data_value,
        "percent"
      );
      const placesYear = String(featureProps?.year ?? selectedYear ?? "").trim();
      return `${countyLine}<br/>${placesLabel}<br/>${formatTooltipMetaLine(placesValueText, placesYear)}`;
    },
    [
      isAcsDataSource,
      isCdcDataSource,
      isCmsDataSource,
      isFemaDataSource,
      isHpsaDataSource,
      isSviDataSource,
      isUsdaDataSource,
      cdcBasis,
      cdcGeography,
      selectedHpsaDomain,
      selectedMeasure,
      selectedMeasureId,
      selectedSviYear,
      selectedType,
      selectedYear,
      selectedYearWindow,
      tractsActive,
      usdaRenderLevel,
    ]
  );

  const handleEachFeature = useCallback(
    (feature, layer) => {
      const featureProps = feature?.properties ?? {};
      layer.on("click", () => {
        handleFeatureClick(feature, layer, { openHistory: true });
      });
      layer.on("mouseover", () => {
        setHoveredProps(featureProps);
        if (selectedLayerRef.current !== layer) {
          if (isUsdaDataSource || isFemaDataSource) {
            layer.setStyle({
              weight: 2,
              color: "#0f172a",
              opacity: 1,
              lineJoin: "round",
              lineCap: "round",
            });
          } else {
            layer.setStyle({ weight: tractsActive ? 1.2 : 2, color: "#0f172a" });
          }
        }
        const tooltipHtml = buildCountyHoverTooltipHtml(featureProps);
        if (tooltipHtml) {
          layer.bindTooltip(tooltipHtml, COUNTY_HOVER_TOOLTIP_OPTIONS);
          layer.openTooltip();
        }
      });
      layer.on("mouseout", () => {
        setHoveredProps(null);
        if (selectedLayerRef.current === layer) {
          applySelectedStyle(layer);
        } else if (geoJsonRef.current) {
          geoJsonRef.current.resetStyle(layer);
        }
        if (typeof layer.getTooltip === "function" && layer.getTooltip()) {
          layer.closeTooltip();
          layer.unbindTooltip();
        }
      });
    },
    [
      applySelectedStyle,
      buildCountyHoverTooltipHtml,
      handleFeatureClick,
      isFemaDataSource,
      isUsdaDataSource,
      tractsActive,
    ]
  );

  const selectActiveFeatureByLocationId = useCallback(
    (locationId, options = {}) => {
      const safeLocationId = String(locationId ?? "").trim();
      if (!safeLocationId) return false;
      const geoJsonLayer = geoJsonRef.current;
      if (!geoJsonLayer) return false;

      let didSelect = false;
      geoJsonLayer.eachLayer((layer) => {
        if (didSelect || !layer?.feature) return;
        const featureLocationId = getFeatureLocationId(layer.feature.properties ?? {});
        if (featureLocationId && featureLocationId === safeLocationId) {
          handleFeatureClick(layer.feature, layer, options);
          didSelect = true;
        }
      });
      return didSelect;
    },
    [handleFeatureClick]
  );

  const selectCountyFeatureByFips = useCallback(
    (countyFips, options = {}) => {
      if (tractsActive || !countyFips) return false;
      return selectActiveFeatureByLocationId(countyFips, options);
    },
    [tractsActive, selectActiveFeatureByLocationId]
  );

  const handleCountySearchSelection = useCallback(
    (countyFips) => {
      if (!countyFips) return;
      pendingCountySelectionRef.current = String(countyFips);
      selectCountyFeatureByFips(countyFips, { openHistory: historySupported });
      if (pendingCountySelectionTimerRef.current) {
        clearTimeout(pendingCountySelectionTimerRef.current);
      }
      pendingCountySelectionTimerRef.current = setTimeout(() => {
        pendingCountySelectionRef.current = null;
        pendingCountySelectionTimerRef.current = null;
        pendingAssistantCountyZoomRef.current = false;
      }, 10000);
    },
    [historySupported, selectCountyFeatureByFips]
  );

  const handleAssistantHighlight = useCallback(
    ({ level, geoid }) => {
      const safeLevel = String(level ?? "").trim().toLowerCase();
      const safeGeoid = String(geoid ?? "").trim();
      setHighlightedLevel(safeLevel || null);
      setHighlightedGeoid(safeGeoid || null);

      if (safeLevel === "county" && safeGeoid) {
        pendingAssistantCountyZoomRef.current = true;
        handleCountySearchSelection(safeGeoid);
        return;
      }
      if (safeLevel === "tract" && safeGeoid && tractsActive) {
        selectActiveFeatureByLocationId(safeGeoid, { openHistory: true });
      }
    },
    [handleCountySearchSelection, selectActiveFeatureByLocationId, tractsActive]
  );

  const executeAssistantActions = useCallback(
    (actions) => {
      if (!Array.isArray(actions)) return;
      const map = mapRef.current;
      const contextActions = [];
      const mapActions = [];

      actions.forEach((action) => {
        const type = String(action?.type ?? "").toUpperCase();
        if (type === "SET_MEASURE_CONTEXT") {
          contextActions.push(action);
          return;
        }
        mapActions.push(action);
      });

      contextActions.forEach((action) => {
        const payload = action?.payload && typeof action.payload === "object"
          ? action.payload
          : {};
        const measureId = String(action?.measure_id ?? payload.measure_id ?? "").trim();
        const year = Number(action?.year ?? payload.year);
        const dataValueTypeId = String(
          action?.data_value_type_id ?? payload.data_value_type_id ?? ""
        ).trim();

        if (measureId) {
          setSelectedMeasureId(measureId);
        }
        if (Number.isFinite(year)) {
          setSelectedYear(year);
        }
        if (dataValueTypeId) {
          setSelectedType(dataValueTypeId);
        }
      });

      const hasCountyHighlight = mapActions.some(
        (action) =>
          String(action?.type ?? "").toUpperCase() === "MAP_HIGHLIGHT"
          && String(action?.level ?? "").toLowerCase() === "county"
          && String(
            action?.geoid
            ?? action?.county_fips
            ?? action?.location_id
            ?? action?.fips
            ?? ""
          ).trim().length > 0
      );

      const runMapActions = () => mapActions.forEach((action) => {
        const type = String(action?.type ?? "").toUpperCase();

        if (type === "MAP_FLY_TO") {
          if (!map) return;
          const lat = Number(action?.lat ?? action?.latitude ?? action?.centroid_lat);
          const lng = Number(
            action?.lng
            ?? action?.lon
            ?? action?.longitude
            ?? action?.centroid_lng
          );
          const zoom = Number(action?.zoom);
          if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
          if (hasCountyHighlight) {
            // Mirror SearchBar county selection behavior exactly.
            map.setView([lat, lng], 9);
          } else {
            map.flyTo([lat, lng], Number.isFinite(zoom) ? zoom : 9);
          }
          return;
        }

        if (type === "MAP_FIT_BOUNDS") {
          if (!map) return;
          const bounds = toLeafletBounds(action?.bounds ?? action?.bbox ?? action);
          if (!bounds) return;
          map.fitBounds(bounds);
          return;
        }

        if (type === "MAP_HIGHLIGHT") {
          const level = String(action?.level ?? "county").toLowerCase();
          const geoid = String(
            action?.geoid
            ?? action?.county_fips
            ?? action?.location_id
            ?? action?.fips
            ?? ""
          ).trim();
          if (!geoid) return;
          handleAssistantHighlight({ level, geoid });
        }
      });

      if (contextActions.length > 0 && mapActions.length > 0) {
        window.setTimeout(runMapActions, ASSISTANT_POST_CONTEXT_ACTION_DELAY_MS);
      } else {
        runMapActions();
      }
    },
    [handleAssistantHighlight]
  );

  const openProfilePanel = useCallback((profileId) => {
    if (!profileId) return;
    setActiveProfileId(profileId);
    setProfilePanelOpen(true);
  }, []);

  const generateProfileForArea = useCallback(
    async ({ geography, locationId, openPanel = false }) => {
      const safeGeography = String(geography ?? "").trim().toLowerCase();
      const safeLocationId = String(locationId ?? "").trim();
      if (!safeLocationId || (safeGeography !== "county" && safeGeography !== "tract")) {
        return null;
      }

      const placesYear = placesProfileContext.year ?? selectedYear;
      const placesMeasureId = placesProfileContext.measureId ?? selectedMeasureId;
      const placesTypeId = placesProfileContext.dataValueTypeId ?? "CrdPrv";
      if (placesYear == null || !placesMeasureId || !placesTypeId) {
        setAssistantMessages((current) => [
          ...current,
          {
            role: "assistant",
            text: "Profile generation needs an available PLACES year and measure context.",
          },
        ]);
        setAssistantScrollSignal((value) => value + 1);
        return null;
      }

      setProfileGenerating(true);
      try {
        const response = await fetch(`${API_BASE}/profiles/generate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            geography: safeGeography,
            location_id: safeLocationId,
            places: {
              year: Number(placesYear),
              measure_id: placesMeasureId,
              data_value_type_id: placesTypeId,
            },
            acs_nmf: {
              year_window: selectedYearWindow ?? null,
              data_value_type_id: isAcsDataSource ? (selectedType || "Percent") : "Percent",
            },
            include_charts: true,
            include_full_narrative: true,
          }),
        });

        if (!response.ok) {
          const body = await parseErrorBody(response);
          throw new Error(`Profile request failed (${response.status}): ${body}`);
        }

        const payload = await response.json();
        const summaryText = String(payload?.summary_text ?? "").trim() || "Profile generated.";
        const profileId = payload?.profile_id ? String(payload.profile_id) : null;

        setAssistantMessages((current) => [
          ...current,
          {
            role: "assistant",
            text: summaryText,
            profileId,
          },
        ]);
        setAssistantScrollSignal((value) => value + 1);

        if (openPanel && profileId) {
          openProfilePanel(profileId);
        }
        return payload;
      } catch (profileError) {
        console.error("profile generation failed:", profileError);
        setAssistantMessages((current) => [
          ...current,
          {
            role: "assistant",
            text: "Sorry, profile generation failed for that area.",
          },
        ]);
        setAssistantScrollSignal((value) => value + 1);
        return null;
      } finally {
        setProfileGenerating(false);
      }
    },
    [
      isAcsDataSource,
      openProfilePanel,
      placesProfileContext,
      selectedMeasureId,
      selectedType,
      selectedYear,
      selectedYearWindow,
    ]
  );

  const cancelAssistantStream = useCallback(() => {
    assistantStreamRunIdRef.current += 1;
    if (assistantStreamTimerRef.current) {
      clearTimeout(assistantStreamTimerRef.current);
      assistantStreamTimerRef.current = null;
    }
  }, []);

  const streamAssistantAnswer = useCallback((answerText) => {
    const safeText = String(answerText ?? "").trim() || "Data unavailable";
    const runId = assistantStreamRunIdRef.current + 1;
    assistantStreamRunIdRef.current = runId;

    let messageIndex = -1;
    setAssistantMessages((current) => {
      messageIndex = current.length;
      return [...current, { role: "assistant", text: "" }];
    });

    return new Promise((resolve) => {
      let cursor = 0;
      const pushChunk = () => {
        if (assistantStreamRunIdRef.current !== runId) {
          resolve();
          return;
        }

        cursor = Math.min(safeText.length, cursor + ASSISTANT_STREAM_CHUNK_CHARS);
        const nextText = safeText.slice(0, cursor);
        setAssistantMessages((current) => {
          if (messageIndex < 0 || messageIndex >= current.length) return current;
          const updated = [...current];
          updated[messageIndex] = { ...updated[messageIndex], text: nextText };
          return updated;
        });

        if (cursor >= safeText.length) {
          assistantStreamTimerRef.current = null;
          resolve();
          return;
        }

        assistantStreamTimerRef.current = setTimeout(
          pushChunk,
          ASSISTANT_STREAM_INTERVAL_MS
        );
      };

      pushChunk();
    });
  }, []);

  const handleAssistantSubmit = useCallback(
    async () => {
      if (assistantLoading) return;
      const trimmedInput = assistantInput.trim();
      if (!trimmedInput) return;

      const mapContext = assistantMapContext ?? null;
      const requestYear = isAcsDataSource
        ? (parseYearFromToken(selectedYearWindow) ?? 0)
        : isSviDataSource
          ? (parseYearFromToken(selectedSviYear) ?? 0)
          : isHpsaDataSource
            ? 0
            : (parseYearFromToken(selectedYear) ?? 0);
      const requestMeasureId = isAcsDataSource
        ? (selectedMeasureId || "ACS")
        : isSviDataSource
          ? (selectedMeasureId || "RPL_THEMES")
          : isHpsaDataSource
            ? "HPSA"
            : (selectedMeasureId || "PLACES");
      const requestValueType = isAcsDataSource
        ? (selectedType || "Percent")
        : isSviDataSource
          ? "Rank"
          : isHpsaDataSource
            ? (selectedHpsaDomain || "pc")
            : isCmsDataSource
              ? selectedCmsAgeLevel
            : (selectedType || "CrdPrv");

      setAssistantScrollSignal((value) => value + 1);
      setAssistantMessages((current) => [
        ...current,
        { role: "user", text: trimmedInput },
      ]);
      setAssistantInput("");
      setAssistantLoading(true);
      cancelAssistantStream();

      try {
        const response = await fetch(`${API_BASE}/assistant/query`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: trimmedInput,
            context: {
              measure_id: requestMeasureId,
              year: requestYear,
              data_value_type_id: requestValueType,
              zoom: mapZoom,
              bbox,
              active_layer: tractsActive ? "tract" : "county",
            },
            map_context: mapContext ?? undefined,
          }),
        });

        if (!response.ok) {
          const body = await parseErrorBody(response);
          throw new Error(`Assistant request failed (${response.status}): ${body}`);
        }

        const resp = await response.json();
        console.log("assistant actions:", resp.actions);

        const actions = Array.isArray(resp?.actions) ? resp.actions : [];
        executeAssistantActions(actions);

        const contextSummary = (
          resp?.context_summary && typeof resp.context_summary === "object"
        )
          ? resp.context_summary
          : null;
        if (contextSummary) {
          setAssistantMessages((current) => [
            ...current,
            {
              role: "assistant",
              text: "",
              contextSummary,
            },
          ]);
          setAssistantScrollSignal((value) => value + 1);
        } else {
          const answerMarkdown = typeof resp?.answer_markdown === "string"
            ? resp.answer_markdown
            : "";
          await streamAssistantAnswer(answerMarkdown);
        }

        if (ANALYSIS_PROMPT_PATTERN.test(trimmedInput)) {
          let target = null;
          for (let index = actions.length - 1; index >= 0; index -= 1) {
            const action = actions[index];
            const type = String(action?.type ?? "").toUpperCase();
            if (type !== "MAP_HIGHLIGHT") continue;
            const geoid = String(
              action?.geoid
              ?? action?.county_fips
              ?? action?.location_id
              ?? action?.fips
              ?? ""
            ).trim();
            if (!geoid) continue;
            const level = String(action?.level ?? "").toLowerCase() === "tract" ? "tract" : "county";
            target = { geography: level, locationId: geoid };
            break;
          }

          if (!target && selectedLocationId) {
            target = {
              geography: tractsActive ? "tract" : "county",
              locationId: selectedLocationId,
            };
          }

          if (target) {
            await generateProfileForArea({
              geography: target.geography,
              locationId: target.locationId,
              openPanel: false,
            });
          } else {
            setAssistantMessages((current) => [
              ...current,
              {
                role: "assistant",
                text: "Select a county or tract first, then ask for analysis.",
              },
            ]);
            setAssistantScrollSignal((value) => value + 1);
          }
        }
      } catch (submitError) {
        cancelAssistantStream();
        console.error("assistant submit failed:", submitError);
        setAssistantMessages((current) => [
          ...current,
          { role: "assistant", text: "Sorry, the assistant request failed." },
        ]);
      } finally {
        setAssistantLoading(false);
      }
    },
    [
      assistantInput,
      assistantMapContext,
      assistantLoading,
      bbox,
      cancelAssistantStream,
      executeAssistantActions,
      generateProfileForArea,
      isAcsDataSource,
      isCmsDataSource,
      isHpsaDataSource,
      isSviDataSource,
      mapZoom,
      selectedLocationId,
      selectedMeasureId,
      selectedHpsaDomain,
      selectedCmsAgeLevel,
      selectedSviYear,
      selectedType,
      selectedYear,
      selectedYearWindow,
      streamAssistantAnswer,
      tractsActive,
    ]
  );

  useEffect(() => {
    const geoJsonLayer = geoJsonRef.current;
    if (!geoJsonLayer) return;

    geoJsonLayer.eachLayer((layer) => {
      if (layer?.feature) {
        geoJsonLayer.resetStyle(layer);
      }
    });

    selectedLayerRef.current = null;
    if (!selectedLocationId) {
      return;
    }

    if (!selectActiveFeatureByLocationId(selectedLocationId, { openHistory: false })) {
      selectedLayerRef.current = null;
      setSelectedProps(null);
    }
  }, [activeGeojson, choroplethStyle, selectedLocationId, selectActiveFeatureByLocationId]);

  useEffect(() => {
    const previousTractsActive = previousTractsActiveRef.current;
    if (previousTractsActive == null) {
      previousTractsActiveRef.current = tractsActive;
      return;
    }
    if (previousTractsActive === tractsActive) {
      return;
    }
    previousTractsActiveRef.current = tractsActive;

    pendingAssistantCountyZoomRef.current = false;
    selectedLayerRef.current = null;
    setSelectedProps(null);
    setHoveredProps(null);
    setHistoryOpen(false);
    setHistorySeries([]);
    setHistoryMeta(null);
    setHistoryError(null);
    setIsHistoryLoading(false);
  }, [tractsActive]);

  useEffect(() => {
    if (!isUsdaHeatMode) {
      setUsdaHeatHoverPoint(null);
      return;
    }
    selectedLayerRef.current = null;
    setSelectedProps(null);
    setHistoryOpen(false);
    setHistorySeries([]);
    setHistoryMeta(null);
    setHistoryError(null);
    setIsHistoryLoading(false);
  }, [isUsdaHeatMode]);

  useEffect(() => {
    if (tractsActive) return;
    const pendingCountyFips = pendingCountySelectionRef.current;
    if (!pendingCountyFips) return;
    if (selectCountyFeatureByFips(pendingCountyFips, { openHistory: historySupported })) {
      pendingCountySelectionRef.current = null;
      if (pendingCountySelectionTimerRef.current) {
        clearTimeout(pendingCountySelectionTimerRef.current);
        pendingCountySelectionTimerRef.current = null;
      }
    }
  }, [activeGeojson, historySupported, tractsActive, selectCountyFeatureByFips]);

  useEffect(() => {
    if (!pendingAssistantCountyZoomRef.current) return;
    if (tractsActive) return;
    if (String(highlightedLevel ?? "").toLowerCase() !== "county") return;
    if (!selectedLocationId) return;
    const highlightedCountyGeoid = String(highlightedGeoid ?? "").trim();
    if (!highlightedCountyGeoid || highlightedCountyGeoid !== String(selectedLocationId)) {
      return;
    }
    const zoomButton = zoomToSelectedButtonRef.current;
    if (!zoomButton || typeof zoomButton.click !== "function") return;
    zoomButton.click();
    pendingAssistantCountyZoomRef.current = false;
  }, [highlightedGeoid, highlightedLevel, selectedLocationId, tractsActive]);

  useEffect(() => {
    if (!historySupported) {
      setIsHistoryLoading(false);
      setHistoryError(null);
      setHistorySeries([]);
      setHistoryMeta(null);
      return;
    }

    if (!historyOpen || !selectedLocationId) {
      return;
    }

    const geography = tractsActive ? "tract" : "county";
    const historyKey = `history|${geography}|${selectedLocationId}|${selectedMeasureId}|${selectedType}|${HISTORY_START_YEAR}|${HISTORY_END_YEAR}`;
    const cachedHistory = getCached(historyKey);
    if (cachedHistory) {
      setHistorySeries(cachedHistory.series ?? []);
      setHistoryMeta({
        measure_id: cachedHistory.measure_id ?? selectedMeasureId,
        measure: cachedHistory.measure ?? selectedMeasure?.measure ?? selectedMeasureId,
        data_value_type_id: cachedHistory.data_value_type_id ?? selectedType,
        data_value_type: cachedHistory.data_value_type ?? selectedType,
      });
      setHistoryError(null);
      setIsHistoryLoading(false);
      return;
    }

    if (historyAbortRef.current) {
      historyAbortRef.current.abort();
    }
    const controller = new AbortController();
    historyAbortRef.current = controller;

    setIsHistoryLoading(true);
    setHistoryError(null);

    const url = new URL(`${API_BASE}/history`);
    url.searchParams.set("geography", geography);
    url.searchParams.set("location_id", String(selectedLocationId));
    url.searchParams.set("measure_id", selectedMeasureId);
    url.searchParams.set("data_value_type_id", selectedType);
    url.searchParams.set("start_year", String(HISTORY_START_YEAR));
    url.searchParams.set("end_year", String(HISTORY_END_YEAR));

    fetch(url, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          const body = await parseErrorBody(response);
          throw new Error(`History request failed (${response.status}): ${body}`);
        }
        return response.json();
      })
      .then((data) => {
        if (controller.signal.aborted) return;
        setCached(historyKey, data);
        setHistorySeries(Array.isArray(data?.series) ? data.series : []);
        setHistoryMeta({
          measure_id: data?.measure_id ?? selectedMeasureId,
          measure: data?.measure ?? selectedMeasure?.measure ?? selectedMeasureId,
          data_value_type_id: data?.data_value_type_id ?? selectedType,
          data_value_type: data?.data_value_type ?? selectedType,
        });
        setHistoryError(null);
      })
      .catch((historyFetchError) => {
        if (isAbortLikeError(historyFetchError, controller.signal)) return;
        console.error("History fetch failed:", historyFetchError);
        const isNetworkFetchError =
          historyFetchError instanceof TypeError
          && /failed to fetch/i.test(historyFetchError.message ?? "");
        setHistorySeries([]);
        setHistoryMeta({
          measure_id: selectedMeasureId,
          measure: selectedMeasure?.measure ?? selectedMeasureId,
          data_value_type_id: selectedType,
          data_value_type: selectedType,
        });
        setHistoryError(
          isNetworkFetchError
            ? `Could not reach API at ${API_BASE}. Start/restart backend on port 8000.`
            : (historyFetchError.message ?? "Failed to load history.")
        );
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setIsHistoryLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [
    historyOpen,
    selectedLocationId,
    tractsActive,
    selectedMeasureId,
    selectedType,
    selectedMeasure,
    historySupported,
    getCached,
    setCached,
  ]);

  const currentLayerLabel = isCdcDataSource
    ? (cdcGeography === "state" ? "state" : "county")
    : (tractsActive ? "tract" : "county");
  const zoomToSelectedLabel = isCdcDataSource
    ? `Zoom to Selected ${cdcGeography === "state" ? "State" : "County"}`
    : tractsActive
      ? "Zoom to Selected Census Tract"
      : "Zoom to Selected County";
  const selectedFeature = selectedProps ? { properties: selectedProps } : null;
  const selectedFeatureProps = selectedFeature?.properties ?? null;
  const selectedProfileTarget = useSelectedAreaProfileTarget({
    selectedFeatureProps,
    tractsActive,
  });
  const handleOpenSelectedProfile = useCallback(() => {
    if (!selectedProfileTarget?.enabled || !selectedProfileTarget?.href) return;
    window.open(selectedProfileTarget.href, "_blank", "noopener,noreferrer");
  }, [selectedProfileTarget]);
  const firstDefined = (...values) => {
    for (const value of values) {
      if (value !== null && value !== undefined) {
        return value;
      }
    }
    return null;
  };
  const hasText = (value) =>
    value !== null && value !== undefined && String(value).trim().length > 0;
  const fmt1 = (x) => (x === null || x === undefined ? "N/A" : Number(x).toFixed(1));
  const fmtPercent = (x) => (x === null || x === undefined ? "No data" : `${Number(x).toFixed(1)}%`);
  const fmtPop = (x) => (x === null || x === undefined ? "N/A" : Number(x).toLocaleString());
  const ciText = (lci, uci) =>
    lci === null || lci === undefined || uci === null || uci === undefined
      ? "N/A"
      : `${fmt1(lci)}, ${fmt1(uci)}`;
  const normalizeMeasureName = (value) => {
    if (!hasText(value)) return "N/A";
    const text = String(value).trim();
    const simplified = text.replace(/\s+among adults aged.*$/i, "").trim();
    return simplified || text;
  };
  const normalizeCountyParishName = (value) => {
    if (!hasText(value)) return "";
    let text = String(value).trim();
    if (text.includes(",")) {
      text = text.split(",")[0].trim();
    }
    text = text.replace(/\b(county|parish)\b\.?$/i, "").trim();
    return text;
  };
  const selectedGeoToken = String(
    firstDefined(selectedFeatureProps?.geo_level, selectedFeatureProps?.level, tractsActive ? "tract" : "county")
  ).toLowerCase();
  const selectedGeoLevel = selectedGeoToken === "tract"
    ? "tract"
    : selectedGeoToken === "state"
      ? "state"
      : "county";
  const crudeValue = firstDefined(
    selectedFeatureProps?.data_value,
    selectedFeatureProps?.data_value_type_id === "CrdPrv"
      ? selectedFeatureProps?.value
      : null
  );
  const crudeLow = firstDefined(
    selectedFeatureProps?.low_confidence_limit,
    selectedFeatureProps?.data_value_type_id === "CrdPrv" ? selectedFeatureProps?.low : null
  );
  const crudeHigh = firstDefined(
    selectedFeatureProps?.high_confidence_limit,
    selectedFeatureProps?.data_value_type_id === "CrdPrv" ? selectedFeatureProps?.high : null
  );
  const ageAdjustedValue = firstDefined(
    selectedFeatureProps?.age_adjusted_data_value,
    selectedFeatureProps?.data_value_type_id === "AgeAdjPrv"
      ? selectedFeatureProps?.value
      : null
  );
  const ageAdjustedLow = firstDefined(
    selectedFeatureProps?.age_adjusted_low_confidence_limit,
    selectedFeatureProps?.data_value_type_id === "AgeAdjPrv" ? selectedFeatureProps?.low : null
  );
  const ageAdjustedHigh = firstDefined(
    selectedFeatureProps?.age_adjusted_high_confidence_limit,
    selectedFeatureProps?.data_value_type_id === "AgeAdjPrv" ? selectedFeatureProps?.high : null
  );
  const selectedMeasureDisplayName = isHpsaDataSource
    ? `${HPSA_DOMAIN_LABELS[selectedHpsaDomain] ?? "Primary Care"} HPSA score`
    : isCdcDataSource
      ? String(selectedMeasure?.label ?? selectedMeasure?.name ?? selectedMeasureId ?? "CDC metric")
    : isSviDataSource
      ? getSviLabel(selectedMeasureId)
      : isFemaDataSource
        ? getFemaMeasureLabel(selectedMeasure, selectedMeasureId)
      : isUsdaDataSource
        ? getUsdaPlainLabel(selectedMeasureId, getMeasureDisplayName(selectedMeasure))
      : getMeasureDisplayName(selectedMeasure);
  const cmsUnitType = getCmsUnitType(selectedMeasure);
  const cmsUnitLabel = getCmsUnitsLabel(cmsUnitType);
  const measureNameValue = normalizeMeasureName(
    firstDefined(
      selectedFeatureProps?.measure_name,
      selectedFeatureProps?.measure,
      selectedFeatureProps?.short_question_text,
      selectedMeasure?.name,
      selectedMeasure?.short_question_text,
      selectedMeasure?.measure
    )
  );
  const yearValue = isHpsaDataSource
    ? firstDefined(
      hpsaDomainDetails?.methodology?.as_of_date,
      hpsaChoropleth?.quartiles?.as_of_date
    )
    : isAcsDataSource
      ? firstDefined(selectedFeatureProps?.year_window, selectedYearWindow)
      : isSviDataSource
        ? firstDefined(selectedFeatureProps?.year, selectedSviYear)
        : isCdcDataSource
          ? firstDefined(selectedFeatureProps?.fiscal_year, cdcFiscalYear || null)
        : isCmsDataSource
          ? firstDefined(selectedFeatureProps?.year, selectedYear)
        : firstDefined(selectedFeatureProps?.year, selectedYear);
  const cmsValue = firstDefined(
    selectedFeatureProps?.cms_value,
    selectedFeatureProps?.value,
    selectedFeatureProps?.data_value
  );
  const cmsIsSuppressed = Boolean(firstDefined(selectedFeatureProps?.cms_is_suppressed, false));
  const cmsValueNumeric = cmsIsSuppressed ? null : toFiniteNumericValue(cmsValue);
  const cmsCountyName = normalizeCountyParishName(
    firstDefined(
      selectedFeatureProps?.county_name,
      selectedFeatureProps?.location_name,
      selectedFeatureProps?.name
    )
  );
  const acsValue = firstDefined(selectedFeatureProps?.value, selectedFeatureProps?.data_value);
  const acsMoe = firstDefined(selectedFeatureProps?.moe);
  const usdaValue = firstDefined(selectedFeatureProps?.value, selectedFeatureProps?.data_value);
  const usdaField = String(
    firstDefined(selectedFeatureProps?.variable, selectedMeasureId, "")
  ).trim();
  const usdaLabel = getUsdaPlainLabel(
    usdaField,
    firstDefined(
      selectedFeatureProps?.label,
      selectedFeatureProps?.measure,
      selectedMeasure?.name,
      selectedMeasureId,
      "USDA Food Environment"
    )
  );
  const usdaUnitType = inferTooltipUnitType({
    source: DATA_SOURCES.USDA_FOOD_ENV,
    measureId: usdaField || selectedMeasureId,
    measureLabel: usdaLabel,
    explicitUnitType: inferUsdaUnitTypeFromText(
      firstDefined(selectedFeatureProps?.unit, selectedMeasure?.usda_unit, "")
    ),
  });
  const usdaValueText = formatTooltipValue(usdaValue, usdaUnitType);
  const usdaGeoLevel = String(
    firstDefined(selectedFeatureProps?.level, selectedFeatureProps?.geo_level, usdaRenderLevel, "county")
  ).trim().toLowerCase() === "state"
    ? "state"
    : "county";
  const usdaCounty = String(firstDefined(selectedFeatureProps?.county_name, selectedFeatureProps?.county, "")).trim();
  const usdaState = String(firstDefined(selectedFeatureProps?.state_abbr, selectedFeatureProps?.state, "")).trim();
  const usdaCountyLine = usdaCounty
    ? (usdaState ? `${usdaCounty}, ${usdaState}` : usdaCounty)
    : String(firstDefined(selectedFeatureProps?.name, "Unknown")).trim();
  const usdaStateLine = String(
    firstDefined(selectedFeatureProps?.state_name, selectedFeatureProps?.name, selectedFeatureProps?.state_abbr, "Unknown")
  ).trim();
  const usdaLocationLine = usdaGeoLevel === "state" ? usdaStateLine : usdaCountyLine;
  const cdcMetricValue = firstDefined(
    selectedFeatureProps?.value,
    selectedFeatureProps?.metric_value,
    selectedFeatureProps?.data_value
  );
  const cdcMetricNumeric = toFiniteNumericValue(cdcMetricValue);
  const cdcMetricId = String(selectedMeasureId ?? "").trim();
  const cdcMetricIsCount = cdcMetricId === "award_count" || cdcMetricId === "subaward_count";
  const cdcMetricValueText = cdcMetricNumeric == null
    ? "No data"
    : cdcMetricIsCount
      ? Math.round(cdcMetricNumeric).toLocaleString("en-US")
      : `$${cdcMetricNumeric.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  const cdcGeoLevel = String(
    firstDefined(selectedFeatureProps?.geo_level, selectedFeatureProps?.level, cdcGeography, "county")
  ).trim().toLowerCase() === "state"
    ? "state"
    : "county";
  const cdcStateCode = String(
    firstDefined(selectedFeatureProps?.state_abbr, selectedFeatureProps?.state_code, "")
  ).trim().toUpperCase();
  const cdcCountyName = String(firstDefined(selectedFeatureProps?.name, selectedFeatureProps?.county_name, "")).trim();
  const cdcStateName = String(firstDefined(selectedFeatureProps?.state_name, selectedFeatureProps?.name, "")).trim();
  const cdcLocationLine = cdcGeoLevel === "state"
    ? (cdcStateName || cdcStateCode || "Unknown state")
    : (
      cdcCountyName
        ? (cdcStateCode ? `${cdcCountyName}, ${cdcStateCode}` : cdcCountyName)
        : String(firstDefined(selectedFeatureProps?.id, "Unknown county")).trim()
    );
  const cdcAwardCountNumeric = toFiniteNumericValue(
    firstDefined(
      selectedFeatureProps?.award_count,
      cdcBasis === "subaward" ? selectedFeatureProps?.subaward_count : null
    )
  );
  const cdcAwardCountText = cdcAwardCountNumeric == null
    ? "No data"
    : Math.round(cdcAwardCountNumeric).toLocaleString("en-US");
  const cdcSummaryNote = cdcBasis === "prime"
    ? "Funds awarded to recipients located in this geography."
    : "Subawards reported to entities in this geography.";
  const femaMeasureLabel = getFemaMeasureLabel(selectedMeasure, selectedMeasureId);
  const femaLevel = String(
    firstDefined(selectedFeatureProps?.level, selectedFeatureProps?.geo_level, tractsActive ? "tract" : "county")
  ).trim().toLowerCase() === "tract"
    ? "tract"
    : "county";
  const femaStateAbbr = String(firstDefined(selectedFeatureProps?.state_abbr, selectedFeatureProps?.state_fips, "")).trim();
  const femaCountyName = String(
    firstDefined(selectedFeatureProps?.county_name, selectedFeatureProps?.county, selectedFeatureProps?.name, "")
  ).trim();
  const femaCountyLine = femaCountyName
    ? (femaStateAbbr ? `${femaCountyName}, ${femaStateAbbr}` : femaCountyName)
    : String(firstDefined(selectedFeatureProps?.county_geoid, selectedFeatureProps?.location_id, "Unknown county")).trim();
  const femaTractName = String(
    firstDefined(selectedFeatureProps?.tract_name, selectedFeatureProps?.name, "")
  ).trim();
  const femaTractGeoid = String(
    firstDefined(selectedFeatureProps?.tract_geoid, selectedFeatureProps?.location_id, selectedFeatureProps?.id, "")
  ).trim();
  const femaTractLine = femaTractName
    ? `${femaTractName}${femaCountyLine ? ` • ${femaCountyLine}` : ""}`
    : (femaTractGeoid || "Unknown tract");
  const femaLocationLine = femaLevel === "tract" ? femaTractLine : femaCountyLine;
  const femaValueRaw = firstDefined(selectedFeatureProps?.value_text, selectedFeatureProps?.value, selectedFeatureProps?.data_value);
  const femaValueText = formatFemaValue(femaValueRaw, selectedMeasure);
  const femaRatingText = normalizeFemaRatingLabel(
    firstDefined(selectedFeatureProps?.rating, selectedFeatureProps?.value_text)
  );
  const femaHazardName = String(
    firstDefined(selectedFeatureProps?.hazard_name, selectedMeasure?.fema_hazard_name, "")
  ).trim();
  const femaMeasureDescription = truncateText(
    String(firstDefined(selectedMeasure?.description, "")).trim(),
    170
  );
  const sviValue = firstDefined(selectedFeatureProps?.value, selectedFeatureProps?.data_value);
  const sviMeasureId = String(
    firstDefined(selectedFeatureProps?.measure_id, selectedMeasureId, "")
  ).trim().toUpperCase();
  const sviMeasureName = getSviLabel(sviMeasureId || selectedMeasureId);
  const sviValueNumeric = toFiniteNumericValue(sviValue);
  const sviRankValueText = sviValueNumeric == null ? "No data" : sviValueNumeric.toFixed(4);
  const sviLevel = getSviLevel(sviValueNumeric);
  const sviLevelText = formatSviLevelText(sviLevel);
  const isSviThemeMeasure = /^RPL_THEME[1-4]$/i.test(String(sviMeasureId ?? "").trim());
  const sviThemeLabel = isSviThemeMeasure ? getSviLabel(sviMeasureId) : null;
  const acsGeoLabel = tractsActive ? "tract" : "county";
  const acsLocationLabel = firstDefined(
    selectedFeatureProps?.location_name,
    selectedFeatureProps?.county_name,
    selectedFeatureProps?.name,
    selectedFeatureProps?.location_id,
    selectedFeatureProps?.locationid,
    selectedFeatureProps?.geoid
  );
  const populationValue = firstDefined(
    selectedFeatureProps?.population,
    selectedFeatureProps?.pop_18plus,
    selectedFeatureProps?.total_pop_18_plus,
    selectedFeatureProps?.pop_total,
    selectedFeatureProps?.total_population
  );
  const selectedLocationIdForLink = firstDefined(
    selectedFeatureProps?.location_id,
    selectedFeatureProps?.locationid,
    selectedFeatureProps?.id
  );
  const selectedLocationNameForLink = firstDefined(
    selectedFeatureProps?.location_name,
    selectedFeatureProps?.county_name,
    selectedFeatureProps?.name
  );
  const selectedStateAbbr = String(
    firstDefined(selectedFeatureProps?.state_abbr, "")
  ).trim().toUpperCase();
  const countySubdivisionLabel = selectedStateAbbr === "LA" ? "Parish" : "County";
  const countyOrParishName = normalizeCountyParishName(
    firstDefined(
      selectedFeatureProps?.county_name,
      selectedFeatureProps?.location_name,
      selectedFeatureProps?.name
    )
  );
  const cmsCountyDisplayName = cmsCountyName || countyOrParishName || getCountyName(selectedFeatureProps);
  const cmsCountyStateLine = selectedStateAbbr
    ? `${cmsCountyDisplayName}, ${selectedStateAbbr}`
    : cmsCountyDisplayName;
  const countyOrParishLabel = countyOrParishName
    ? `${countyOrParishName} ${countySubdivisionLabel}`
    : `this ${countySubdivisionLabel.toLowerCase()}`;
  const selectedAreaLabel = selectedGeoLevel === "county"
    ? countyOrParishLabel
    : `this ${selectedGeoLevel}`;
  const acsAreaLabel = acsGeoLabel === "county"
    ? countyOrParishLabel
    : (hasText(acsLocationLabel) ? String(acsLocationLabel).trim() : `this ${acsGeoLabel}`);
  const sviAreaName = String(
    firstDefined(
      selectedFeatureProps?.location_name,
      selectedFeatureProps?.county_name,
      selectedFeatureProps?.name,
      getFeatureId(selectedFeatureProps),
      selectedAreaLabel
    )
  ).trim();
  const sviStateLabel = String(
    firstDefined(selectedFeatureProps?.state_desc, selectedFeatureProps?.state_abbr, "")
  ).trim();
  const sviAreaTitle = (
    sviStateLabel && !sviAreaName.toLowerCase().includes(sviStateLabel.toLowerCase())
      ? `${sviAreaName}, ${sviStateLabel}`
      : sviAreaName
  );
  const censusProfileHref = hasText(selectedLocationIdForLink)
    ? `https://data.census.gov/profile/${String(selectedLocationIdForLink).trim()}`
    : hasText(selectedLocationNameForLink)
      ? `https://data.census.gov/profile/${encodeURIComponent(
        String(selectedLocationNameForLink).trim()
      )}`
      : "https://data.census.gov/";
  const selectedCountyFipsForHpsa = selectedGeoLevel === "county"
    ? normalizeCountyFips(
      firstDefined(
        selectedFeatureProps?.county_fips,
        selectedFeatureProps?.location_id,
        selectedFeatureProps?.locationid,
        selectedFeatureProps?.geoid
      )
    )
    : null;
  const hpsaDomainLabel = HPSA_DOMAIN_LABELS[selectedHpsaDomain] ?? "Primary Care";
  const hpsaQuartiles = hpsaChoropleth?.quartiles ?? null;
  const selectedHpsaTier = firstDefined(selectedFeatureProps?.tier, hpsaDomainDetails?.tier);
  const selectedHpsaScore = firstDefined(selectedFeatureProps?.value, hpsaDomainDetails?.score_max);
  const selectedHpsaScoreNumeric = toFiniteNumericValue(selectedHpsaScore);
  const hpsaSelectedScoreText = selectedHpsaScoreNumeric == null
    ? "Not available"
    : selectedHpsaScoreNumeric.toFixed(1);
  const selectedHpsaCoveragePct = firstDefined(
    hpsaDomainDetails?.coverage_pct,
    selectedFeatureProps?.coverage_pct
  );
  const hpsaPcCoverageText = (() => {
    const value = toFiniteNumericValue(hpsaSummary?.pc_coverage_pct);
    return value == null ? "No data" : `${value.toFixed(3)}%`;
  })();
  const hpsaMhCoverageText = (() => {
    const value = toFiniteNumericValue(hpsaSummary?.mh_coverage_pct);
    return value == null ? "No data" : `${value.toFixed(3)}%`;
  })();
  const hpsaDhCoverageText = (() => {
    const value = toFiniteNumericValue(hpsaSummary?.dh_coverage_pct);
    return value == null ? "No data" : `${value.toFixed(3)}%`;
  })();
  const hpsaMethodology = hpsaSummary?.methodology && typeof hpsaSummary.methodology === "object"
    ? hpsaSummary.methodology
    : null;
  const hpsaDenominatorValueText = hpsaSummary?.population_denominator == null
    ? "No data"
    : Number(hpsaSummary.population_denominator).toLocaleString();
  const hpsaDenominatorTypeText = hpsaSummary?.population_denominator_type === "adult_18p"
    ? "Adult population (18+)"
    : hpsaSummary?.population_denominator_type === "total"
      ? "Total population"
      : "Unknown denominator";
  const hpsaDataNoteSource = firstDefined(
    hpsaMethodology?.source,
    hpsaSummary?.population_denominator_source
      ? `HRSA HPSA Data Mart; denominator: ${hpsaSummary.population_denominator_source}`
      : null,
    "HRSA HPSA Data Mart"
  );
  const hpsaDataNoteAsOf = firstDefined(hpsaMethodology?.as_of_date, hpsaSummary?.as_of_date);
  const hpsaDataNoteCaveat = firstDefined(
    Array.isArray(hpsaMethodology?.caveats) && hpsaMethodology.caveats.length > 0
      ? hpsaMethodology.caveats[0]
      : null,
    hpsaSummary?.coverage_overlap_caveat,
    "Designation populations may overlap; coverage should be treated as approximate."
  );
  const hpsaAggregationMethodText = firstDefined(
    hpsaSummary?.coverage_population_aggregation_method,
    "MAX"
  );
  const hpsaDomainMethodology = (
    hpsaDomainDetails?.methodology && typeof hpsaDomainDetails.methodology === "object"
      ? hpsaDomainDetails.methodology
      : null
  );
  const hpsaSelectedFteText = (() => {
    const value = toFiniteNumericValue(hpsaDomainDetails?.fte);
    return value == null ? "Not available" : value.toFixed(2);
  })();
  const hpsaTierValue = Number(selectedHpsaTier);
  const hpsaHasTier = [1, 2, 3, 4].includes(hpsaTierValue);
  const hpsaIsDesignated = Boolean(firstDefined(hpsaDomainDetails?.designated, selectedFeatureProps?.designated));
  const hpsaSeverityLabel = getSeverityLabel(selectedHpsaTier);
  const hpsaSeverityBadgeLabel = hpsaHasTier
    ? hpsaSeverityLabel
    : hpsaIsDesignated
      ? "Score unavailable"
      : null;
  const hpsaSeverityLine = hpsaHasTier
    ? (
      hpsaTierValue === 4
        ? `${hpsaSeverityLabel} Shortage Severity (Highest quartile)`
        : `${hpsaSeverityLabel} Shortage Severity`
    )
    : hpsaIsDesignated
      ? "Severity unavailable"
      : "Not designated";
  const hpsaWhatThisMeansLines = buildInterpretationLines({
    designated: hpsaIsDesignated,
    domainLabel: hpsaDomainLabel,
  });
  const hpsaProviderRatioText = formatRatio(hpsaDomainDetails?.hpsa_formal_ratio);
  const hpsaProviderGoalText = formatRatio(hpsaDomainDetails?.provider_ratio_goal);
  const hpsaPopulationCoveredText = formatNumberWithCommas(hpsaDomainDetails?.population_covered);
  const hpsaCoveragePercentText = formatPercent(selectedHpsaCoveragePct, 1);
  const hpsaCoveragePercentNumeric = toFiniteNumericValue(selectedHpsaCoveragePct);
  const hpsaCoverageInterpretationLine = hpsaCoveragePercentNumeric == null
    ? null
    : hpsaCoveragePercentNumeric === 100
      ? "This suggests the entire county falls within a designated shortage area."
      : "This suggests part of the county population falls within a designated shortage area.";
  const hpsaHasProviderSection = hpsaIsDesignated && (
    hpsaDomainDetails?.hpsa_formal_ratio
    || hpsaDomainDetails?.provider_ratio_goal
    || toFiniteNumericValue(hpsaDomainDetails?.fte) != null
  );
  const hpsaHasPopulationSection = hpsaIsDesignated && (
    toFiniteNumericValue(hpsaDomainDetails?.population_covered) != null
    || hpsaCoveragePercentNumeric != null
  );
  const hpsaSeverityBadgeStyle = hpsaHasTier
    ? HPSA_SEVERITY_BADGE_STYLES[hpsaTierValue]
    : hpsaIsDesignated
      ? HPSA_SEVERITY_BADGE_STYLES.designatedNoScore
      : null;
  const hpsaAsOfText = firstDefined(
    hpsaDomainMethodology?.as_of_date,
    hpsaDataNoteAsOf,
    hpsaQuartiles?.as_of_date
  );
  const hpsaDataNoteCalculation = firstDefined(
    hpsaDomainMethodology?.calculation,
    hpsaMethodology?.calculation,
    "Tiering uses county score quartiles among designated counties."
  );
  const hpsaDenominatorSourceText = hpsaSummary?.population_denominator_source ?? "Unknown";
  const hpsaCountyDisplayLabel = hasText(countyOrParishLabel)
    ? countyOrParishLabel
    : getCountyName(selectedFeatureProps);
  const hpsaCountyStateLine = selectedStateAbbr
    ? `${hpsaCountyDisplayLabel}, ${selectedStateAbbr}`
    : hpsaCountyDisplayLabel;
  const selectedCountyFipsForContext = normalizeCountyFips(
    firstDefined(
      selectedFeatureProps?.county_fips,
      selectedFeatureProps?.location_id,
      selectedFeatureProps?.locationid,
      selectedFeatureProps?.geoid,
      selectedFeatureProps?.id,
      selectedGeoLevel === "tract" && selectedLocationId
        ? String(selectedLocationId).slice(0, 5)
        : null
    )
  );
  const selectedAreaNameForContext = String(
    firstDefined(
      selectedFeatureProps?.location_name,
      selectedFeatureProps?.county_name,
      selectedFeatureProps?.name,
      selectedGeoLevel === "county" ? countyOrParishLabel : selectedAreaLabel,
      selectedLocationId
    ) ?? ""
  ).trim();
  const selectedAsOfDateForContext = isHpsaDataSource
    ? (hpsaAsOfText != null ? String(hpsaAsOfText) : undefined)
    : isFemaDataSource
      ? (
        hasText(femaCatalogMeta?.dataset_vintage)
          ? String(femaCatalogMeta.dataset_vintage).trim()
          : undefined
      )
    : isCdcDataSource
      ? (cdcFiscalYear ? String(cdcFiscalYear) : undefined)
    : isAcsDataSource
      ? (selectedYearWindow != null ? String(selectedYearWindow) : undefined)
      : isSviDataSource
        ? (selectedSviYear != null ? String(selectedSviYear) : undefined)
        : (selectedYear != null ? String(selectedYear) : undefined);

  const buildAssistantLegacyContext = useCallback(() => {
    const defaultYear = isAcsDataSource
      ? parseYearFromToken(selectedYearWindow)
      : isSviDataSource
        ? parseYearFromToken(selectedSviYear)
        : isHpsaDataSource
          ? parseYearFromToken(selectedAsOfDateForContext)
          : isFemaDataSource
            ? parseYearFromToken(selectedAsOfDateForContext)
          : isCdcDataSource
            ? parseYearFromToken(cdcFiscalYear)
          : isUsdaDataSource
            ? 2025
          : parseYearFromToken(selectedYear);
    const resolvedYear = defaultYear ?? 0;
    const resolvedMeasureId = isAcsDataSource
      ? (selectedMeasureId || "ACS")
      : isSviDataSource
        ? (selectedMeasureId || "RPL_THEMES")
        : isHpsaDataSource
          ? "HPSA"
        : isFemaDataSource
          ? (selectedMeasureId || FEMA_DEFAULT_MEASURE)
          : isCdcDataSource
            ? (selectedMeasureId || CDC_DEFAULT_METRIC_BY_BASIS[cdcBasis] || "total_funding")
          : isUsdaDataSource
            ? (selectedMeasureId || USDA_DEFAULT_VARIABLE)
          : (selectedMeasureId || "PLACES");
    const resolvedType = isAcsDataSource
      ? (selectedType || "Percent")
      : isSviDataSource
        ? "Rank"
        : isHpsaDataSource
          ? (selectedHpsaDomain || "pc")
        : isFemaDataSource
          ? "FEMA_NRI"
          : isCdcDataSource
            ? cdcBasis
          : isUsdaDataSource
            ? "USDA"
          : isCmsDataSource
            ? selectedCmsAgeLevel
          : (selectedType || "CrdPrv");

    return {
      measure_id: resolvedMeasureId,
      year: resolvedYear,
      data_value_type_id: resolvedType,
      zoom: mapZoom,
      bbox,
      active_layer: isCdcDataSource ? cdcGeography : (tractsActive ? "tract" : "county"),
    };
  }, [
    bbox,
    isAcsDataSource,
    isCmsDataSource,
    isCdcDataSource,
    isFemaDataSource,
    isHpsaDataSource,
    isSviDataSource,
    isUsdaDataSource,
    mapZoom,
    cdcBasis,
    cdcFiscalYear,
    cdcGeography,
    selectedCmsAgeLevel,
    selectedAsOfDateForContext,
    selectedHpsaDomain,
    selectedMeasureId,
    selectedSviYear,
    selectedType,
    selectedYear,
    selectedYearWindow,
    tractsActive,
  ]);

  const buildCurrentMapContext = useCallback(() => {
    if (!selectedLocationId) return null;

    const selection = isHpsaDataSource
      ? {
        hpsaDomain: selectedHpsaDomain,
      }
      : isAcsDataSource
        ? {
          acsVariable: selectedMeasureId,
          acsYearWindow: selectedYearWindow,
          acsDataValueTypeId: selectedType || "Percent",
        }
        : isFemaDataSource
          ? {
            femaMeasureId: selectedMeasureId,
          }
        : isCdcDataSource
          ? {
            cdcBasis,
            cdcMetric: selectedMeasureId,
            cdcGeography,
            cdcFiscalYear: parseYearFromToken(cdcFiscalYear),
          }
        : isUsdaDataSource
          ? {
            usdaField: selectedMeasureId,
          }
        : isSviDataSource
          ? {
            sviTheme: sviThemeLabel || null,
            sviMeasureId: selectedMeasureId,
            sviYear: selectedSviYear,
          }
          : isCmsDataSource
            ? {
              cmsMeasureId: selectedMeasureId,
              cmsYear: parseYearFromToken(selectedYear),
              cmsAgeLevel: selectedCmsAgeLevel,
            }
          : {
            placesMeasureId: selectedMeasureId,
            placesYear: parseYearFromToken(selectedYear),
            placesValueTypeId: selectedType,
          };

    return buildMapContext({
      dataSource: selectedDataSource,
      geoLevel: selectedGeoLevel,
      selectedArea: {
        countyFips: selectedCountyFipsForContext,
        tractGeoid: selectedGeoLevel === "tract" ? selectedLocationId : null,
        name: selectedAreaNameForContext || null,
        stateAbbr: selectedStateAbbr || null,
      },
      selection,
      mapState: {
        zoom: mapZoom,
        bbox,
      },
      asOfDate: selectedAsOfDateForContext,
    });
  }, [
    bbox,
    isAcsDataSource,
    isCmsDataSource,
    isCdcDataSource,
    isFemaDataSource,
    isHpsaDataSource,
    isSviDataSource,
    isUsdaDataSource,
    mapZoom,
    cdcBasis,
    cdcFiscalYear,
    cdcGeography,
    selectedCmsAgeLevel,
    selectedAreaNameForContext,
    selectedAsOfDateForContext,
    selectedCountyFipsForContext,
    selectedDataSource,
    selectedGeoLevel,
    selectedHpsaDomain,
    selectedLocationId,
    selectedMeasureId,
    selectedStateAbbr,
    selectedSviYear,
    selectedType,
    selectedYear,
    selectedYearWindow,
    sviThemeLabel,
  ]);

  useEffect(() => {
    setCdcSearchPage(1);
  }, [cdcSearchQuery, cdcAssistanceType, cdcFiscalYear, cdcStateFilter]);

  useEffect(() => {
    if (!isCdcDataSource) {
      if (cdcSearchAbortRef.current) {
        cdcSearchAbortRef.current.abort();
        cdcSearchAbortRef.current = null;
      }
      setIsCdcSearchLoading(false);
      return;
    }

    const queryToken = String(cdcSearchQuery ?? "").trim();
    if (queryToken.length < 2) {
      setCdcSearchResults([]);
      setCdcSearchTotal(0);
      setCdcSearchError(null);
      setIsCdcSearchLoading(false);
      return;
    }

    if (cdcSearchAbortRef.current) {
      cdcSearchAbortRef.current.abort();
    }
    const controller = new AbortController();
    cdcSearchAbortRef.current = controller;

    setIsCdcSearchLoading(true);
    setCdcSearchError(null);
    searchCdcFunding({
      apiBase: API_BASE,
      q: queryToken,
      basis: "all",
      assistance_type: cdcBasis === "prime" ? cdcAssistanceType : null,
      fiscal_year: cdcFiscalYear || null,
      state: cdcStateFilter || null,
      page: cdcSearchPage,
      page_size: 20,
      signal: controller.signal,
    })
      .then((payload) => {
        setCdcSearchResults(Array.isArray(payload?.results) ? payload.results : []);
        setCdcSearchTotal(Number(payload?.total ?? 0));
      })
      .catch((searchError) => {
        if (isAbortLikeError(searchError, controller.signal)) {
          return;
        }
        console.error("CDC search failed:", searchError);
        setCdcSearchResults([]);
        setCdcSearchTotal(0);
        setCdcSearchError(searchError.message ?? "Failed to search CDC funding.");
      })
      .finally(() => {
        if (cdcSearchAbortRef.current === controller) {
          cdcSearchAbortRef.current = null;
        }
        setIsCdcSearchLoading(false);
      });

    return () => {
      controller.abort();
      if (cdcSearchAbortRef.current === controller) {
        cdcSearchAbortRef.current = null;
      }
    };
  }, [
    cdcAssistanceType,
    cdcBasis,
    cdcFiscalYear,
    cdcSearchPage,
    cdcSearchQuery,
    cdcStateFilter,
    isCdcDataSource,
  ]);

  useEffect(() => {
    if (!isCdcDataSource || !cdcSelectedResult) {
      if (cdcDetailAbortRef.current) {
        cdcDetailAbortRef.current.abort();
        cdcDetailAbortRef.current = null;
      }
      setCdcDetailRecord(null);
      setIsCdcDetailLoading(false);
      setCdcDetailError(null);
      return;
    }

    if (cdcDetailAbortRef.current) {
      cdcDetailAbortRef.current.abort();
    }
    const controller = new AbortController();
    cdcDetailAbortRef.current = controller;

    const detailRequest = cdcSelectedResult.record_type === "prime_award"
      ? { prime_unique_key: cdcSelectedResult.record_id }
      : { subaward_id: Number(cdcSelectedResult.record_id) };

    setIsCdcDetailLoading(true);
    setCdcDetailError(null);
    fetchCdcFundingDetail({
      apiBase: API_BASE,
      ...detailRequest,
      signal: controller.signal,
    })
      .then((payload) => {
        setCdcDetailRecord(payload ?? null);
      })
      .catch((detailError) => {
        if (isAbortLikeError(detailError, controller.signal)) {
          return;
        }
        console.error("CDC detail fetch failed:", detailError);
        setCdcDetailRecord(null);
        setCdcDetailError(detailError.message ?? "Failed to load CDC funding detail.");
      })
      .finally(() => {
        if (cdcDetailAbortRef.current === controller) {
          cdcDetailAbortRef.current = null;
        }
        setIsCdcDetailLoading(false);
      });

    return () => {
      controller.abort();
      if (cdcDetailAbortRef.current === controller) {
        cdcDetailAbortRef.current = null;
      }
    };
  }, [cdcSelectedResult, isCdcDataSource]);

  useEffect(() => {
    if (!isCdcDataSource || !selectedFeatureProps || !selectedMeasureId) {
      if (cdcTopAbortRef.current) {
        cdcTopAbortRef.current.abort();
        cdcTopAbortRef.current = null;
      }
      setCdcTopRows([]);
      setCdcTopNote(null);
      setCdcTopError(null);
      setIsCdcTopLoading(false);
      return;
    }

    const featureGeoLevel = String(
      firstDefined(selectedFeatureProps?.geo_level, selectedFeatureProps?.level, cdcGeography)
    ).trim().toLowerCase() === "state"
      ? "state"
      : "county";
    const geographyId = String(
      featureGeoLevel === "state"
        ? firstDefined(
          selectedFeatureProps?.state_abbr,
          selectedFeatureProps?.state_code,
          selectedFeatureProps?.id,
          selectedFeatureProps?.location_id,
          ""
        )
        : firstDefined(
          selectedFeatureProps?.location_id,
          selectedFeatureProps?.county_fips,
          selectedFeatureProps?.id,
          ""
        )
    ).trim();
    if (!geographyId) {
      setCdcTopRows([]);
      setCdcTopNote(null);
      setCdcTopError(null);
      setIsCdcTopLoading(false);
      return;
    }

    if (cdcTopAbortRef.current) {
      cdcTopAbortRef.current.abort();
    }
    const controller = new AbortController();
    cdcTopAbortRef.current = controller;

    setIsCdcTopLoading(true);
    setCdcTopError(null);
    fetchCdcFundingTop({
      apiBase: API_BASE,
      basis: cdcBasis,
      geography: featureGeoLevel,
      geography_id: geographyId,
      metric: selectedMeasureId,
      assistance_type: cdcBasis === "prime" ? cdcAssistanceType : null,
      fiscal_year: cdcFiscalYear || null,
      awarding_office: cdcAwardingOffice || null,
      funding_office: cdcFundingOffice || null,
      center: cdcCenter || null,
      limit: 5,
      signal: controller.signal,
    })
      .then((payload) => {
        setCdcTopRows(Array.isArray(payload?.rows) ? payload.rows : []);
        setCdcTopNote(String(payload?.note ?? "").trim() || null);
      })
      .catch((topError) => {
        if (isAbortLikeError(topError, controller.signal)) {
          return;
        }
        console.error("CDC top awards fetch failed:", topError);
        setCdcTopRows([]);
        setCdcTopNote(null);
        setCdcTopError(topError.message ?? "Failed to load top CDC awards.");
      })
      .finally(() => {
        if (cdcTopAbortRef.current === controller) {
          cdcTopAbortRef.current = null;
        }
        setIsCdcTopLoading(false);
      });

    return () => {
      controller.abort();
      if (cdcTopAbortRef.current === controller) {
        cdcTopAbortRef.current = null;
      }
    };
  }, [
    cdcAssistanceType,
    cdcAwardingOffice,
    cdcBasis,
    cdcCenter,
    cdcFiscalYear,
    cdcFundingOffice,
    cdcGeography,
    isCdcDataSource,
    selectedFeatureProps,
    selectedMeasureId,
  ]);

  useEffect(() => {
    if (isCmsDataSource || !selectedCountyFipsForHpsa) {
      setHpsaSummary(null);
      setHpsaError(null);
      setIsHpsaLoading(false);
      return () => {};
    }

    const controller = new AbortController();
    const cacheKey = `hpsa|county|${selectedCountyFipsForHpsa}`;
    const cached = getCached(cacheKey);
    if (cached) {
      setHpsaSummary(cached);
      setHpsaError(null);
      setIsHpsaLoading(false);
      return () => {
        controller.abort();
      };
    }

    setIsHpsaLoading(true);
    setHpsaError(null);

    fetchWithDedupe(cacheKey, async () => {
      const response = await fetch(
        `${API_BASE}/hpsa/counties/${selectedCountyFipsForHpsa}`,
        { signal: controller.signal }
      );
      if (response.status === 404) {
        return null;
      }
      if (!response.ok) {
        const body = await parseErrorBody(response);
        throw new Error(`HPSA request failed (${response.status}) - ${body}`);
      }
      return response.json();
    })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setHpsaSummary(payload);
        if (payload) {
          setCached(cacheKey, payload);
        }
      })
      .catch((fetchError) => {
        if (controller.signal.aborted) return;
        const isNetworkFetchError = fetchError instanceof TypeError;
        setHpsaSummary(null);
        setHpsaError(
          isNetworkFetchError
            ? `Could not reach API at ${API_BASE}. Start/restart backend on port 8000.`
            : (fetchError.message ?? "Failed to load HPSA county summary.")
        );
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setIsHpsaLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [
    fetchWithDedupe,
    getCached,
    isCmsDataSource,
    isHpsaDataSource,
    selectedCountyFipsForHpsa,
    setCached,
  ]);

  useEffect(() => {
    if (!isHpsaDataSource || !selectedCountyFipsForHpsa) {
      setHpsaDomainDetails(null);
      setHpsaDomainDetailsError(null);
      setIsHpsaDomainDetailsLoading(false);
      return () => {};
    }

    const controller = new AbortController();
    const cacheKey = `hpsa|county|${selectedCountyFipsForHpsa}|domain:${selectedHpsaDomain}`;
    const cached = getCached(cacheKey);
    if (cached) {
      setHpsaDomainDetails(cached);
      setHpsaDomainDetailsError(null);
      setIsHpsaDomainDetailsLoading(false);
      return () => {
        controller.abort();
      };
    }

    setIsHpsaDomainDetailsLoading(true);
    setHpsaDomainDetailsError(null);

    fetchWithDedupe(cacheKey, async () => {
      const response = await fetch(
        `${API_BASE}/hpsa/counties/${selectedCountyFipsForHpsa}?domain=${encodeURIComponent(selectedHpsaDomain)}`,
        { signal: controller.signal }
      );
      if (response.status === 404) {
        return null;
      }
      if (!response.ok) {
        const body = await parseErrorBody(response);
        throw new Error(`HPSA detail request failed (${response.status}) - ${body}`);
      }
      return response.json();
    })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setHpsaDomainDetails(payload);
        if (payload) {
          setCached(cacheKey, payload);
        }
      })
      .catch((fetchError) => {
        if (controller.signal.aborted) return;
        const isNetworkFetchError = fetchError instanceof TypeError;
        setHpsaDomainDetails(null);
        setHpsaDomainDetailsError(
          isNetworkFetchError
            ? `Could not reach API at ${API_BASE}. Start/restart backend on port 8000.`
            : (fetchError.message ?? "Failed to load HPSA county details.")
        );
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setIsHpsaDomainDetailsLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [
    fetchWithDedupe,
    getCached,
    isHpsaDataSource,
    selectedCountyFipsForHpsa,
    selectedHpsaDomain,
    setCached,
  ]);

  const handleAnalyzeSelectedArea = useCallback(
    async () => {
      if (!selectedLocationId || assistantLoading || analyzeGenerating) return;

      const mapContext = buildCurrentMapContext();
      if (!mapContext) {
        await generateProfileForArea({
          geography: selectedGeoLevel === "tract" ? "tract" : "county",
          locationId: selectedLocationId,
          openPanel: false,
        });
        return;
      }

      setAssistantOpenSignal((value) => value + 1);
      setAssistantMapContext(mapContext);
      setAssistantScrollSignal((value) => value + 1);
      setAssistantMessages((current) => [
        ...current,
        { role: "user", text: "Analyze this area" },
      ]);
      setAssistantLoading(true);
      setAnalyzeGenerating(true);
      cancelAssistantStream();

      try {
        const response = await fetch(`${API_BASE}/assistant/query`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: "Analyze this area",
            analyze: true,
            context: buildAssistantLegacyContext(),
            map_context: mapContext,
          }),
        });

        if (!response.ok) {
          const body = await parseErrorBody(response);
          throw new Error(`Analyze request failed (${response.status}): ${body}`);
        }

        const resp = await response.json();
        const actions = Array.isArray(resp?.actions) ? resp.actions : [];
        executeAssistantActions(actions);

        const contextSummary = (
          resp?.context_summary && typeof resp.context_summary === "object"
        )
          ? resp.context_summary
          : null;
        if (contextSummary) {
          setAssistantMessages((current) => [
            ...current,
            {
              role: "assistant",
              text: "",
              contextSummary,
            },
          ]);
          setAssistantScrollSignal((value) => value + 1);
          return;
        }

        const answerMarkdown = typeof resp?.answer_markdown === "string"
          ? resp.answer_markdown
          : "";
        if (answerMarkdown.trim()) {
          await streamAssistantAnswer(answerMarkdown);
          return;
        }

        await generateProfileForArea({
          geography: selectedGeoLevel === "tract" ? "tract" : "county",
          locationId: selectedLocationId,
          openPanel: false,
        });
      } catch (analyzeError) {
        console.error("analyze selected area failed:", analyzeError);
        await generateProfileForArea({
          geography: selectedGeoLevel === "tract" ? "tract" : "county",
          locationId: selectedLocationId,
          openPanel: false,
        });
      } finally {
        setAnalyzeGenerating(false);
        setAssistantLoading(false);
      }
    },
    [
      analyzeGenerating,
      assistantLoading,
      buildAssistantLegacyContext,
      buildCurrentMapContext,
      cancelAssistantStream,
      executeAssistantActions,
      generateProfileForArea,
      selectedGeoLevel,
      selectedLocationId,
      streamAssistantAnswer,
    ]
  );

  const handleZoomToSelected = useCallback(() => {
    const map = mapRef.current;
    if (!map || !selectedLocationId) {
      return;
    }

    const targetZoom = isCdcDataSource
      ? (cdcGeography === "state" ? 6.0 : 8.5)
      : tractsActive
        ? 10.0
        : 9.0;
    if (!selectedLayerRef.current) {
      selectActiveFeatureByLocationId(selectedLocationId);
    }
    const selectedLayer = selectedLayerRef.current;

    let center = null;
    if (selectedLayer && typeof selectedLayer.getBounds === "function") {
      const bounds = selectedLayer.getBounds();
      if (bounds && typeof bounds.isValid === "function" && bounds.isValid()) {
        center = bounds.getCenter();
      }
    }

    if (!center && selectedLayer && typeof selectedLayer.getLatLng === "function") {
      center = selectedLayer.getLatLng();
    }

    if (!center) {
      const lat = Number(
        selectedProps.lat ?? selectedProps.latitude ?? selectedProps.centroid_lat
      );
      const lng = Number(
        selectedProps.lng
        ?? selectedProps.lon
        ?? selectedProps.longitude
        ?? selectedProps.centroid_lng
      );
      if (Number.isFinite(lat) && Number.isFinite(lng)) {
        center = { lat, lng };
      }
    }

    if (!center) {
      const selectedFeature = activeFeatures.find((feature) => {
        const featureLocationId = getFeatureLocationId(feature?.properties ?? {});
        return featureLocationId && featureLocationId === selectedLocationId;
      });
      center = getGeometryCenter(selectedFeature?.geometry);
    }

    if (!center) {
      return;
    }

    map.setView([center.lat, center.lng], targetZoom);
  }, [
    activeFeatures,
    cdcGeography,
    isCdcDataSource,
    selectedLocationId,
    selectedProps,
    selectActiveFeatureByLocationId,
    tractsActive,
  ]);

  const handleCdcResultSelect = useCallback((resultRow) => {
    if (!resultRow) return;
    setCdcSelectedResult(resultRow);

    const countyFips = String(resultRow?.county_fips ?? "").trim();
    const stateCode = String(resultRow?.state_code ?? "").trim().toUpperCase();
    const preferredLocation = cdcGeography === "state"
      ? (stateCode || countyFips)
      : (countyFips || stateCode);
    if (!preferredLocation) {
      return;
    }
    const didSelect = selectActiveFeatureByLocationId(preferredLocation, { openHistory: false });
    if (didSelect) {
      setTimeout(() => {
        handleZoomToSelected();
      }, 40);
    }
  }, [cdcGeography, handleZoomToSelected, selectActiveFeatureByLocationId]);

  const handleToggleHistoryClick = useCallback(() => {
    setHistoryOpen((current) => !current);
  }, []);

  const hpsaTierRanges = useMemo(() => formatTierRanges(hpsaQuartiles), [hpsaQuartiles]);

  const legendRows = useMemo(() => {
    if (isHpsaDataSource) {
      return [
        ...hpsaTierRanges.map((tierRange) => ({
          key: `hpsa-tier-${tierRange.tier}`,
          color: HPSA_TIER_COLORS[tierRange.tier],
          label: tierRange.severityLabel,
          subLabel: `${tierRange.rangeLabel} • ${tierRange.tierMeta}`,
        })),
        {
          key: "hpsa-not-designated",
          color: HPSA_NOT_DESIGNATED_COLOR,
          label: "Not designated",
        },
        {
          key: "hpsa-designated-no-score",
          color: HPSA_DESIGNATED_NO_SCORE_COLOR,
          label: "Designated (score unavailable)",
        },
      ];
    }
    if (isSviDataSource) {
      return sviBins.map((bin) => ({
        key: `svi-bin-${bin.key}`,
        colorIndex: bin.colorIndex,
        label: `${bin.label}: ${bin.rangeLabel}`,
      }));
    }
    if (isUsdaDataSource) {
      if (isUsdaHeatMode) {
        return [];
      }
      const bins = Array.isArray(usdaLegend?.bins) ? usdaLegend.bins : [];
      if (bins.length > 0) {
        return bins.map((bin, index) => ({
          key: `${bin?.min}-${bin?.max}-${index}`,
          colorIndex: Number.isFinite(Number(bin?.colorIndex))
            ? Number(bin.colorIndex)
            : index,
          label: String(bin?.label ?? formatRange(bin?.min, bin?.max)),
        }));
      }

      return breaks.slice(0, -1).map((start, index) => {
        const end = breaks[index + 1];
        return {
          key: `${start}-${end}-${index}`,
          colorIndex: index,
          label: formatRange(start, end),
        };
      });
    }
    if (isFemaDataSource) {
      const categories = Array.isArray(femaLegend?.categories) ? femaLegend.categories : [];
      if (categories.length > 0) {
        return categories.map((category, index) => {
          const categoryLabel = normalizeFemaRatingLabel(category?.label ?? category?.value) || "No data";
          const categoryCount = Number(category?.count);
          return {
            key: `fema-category-${categoryLabel}-${index}`,
            color: FEMA_RATING_COLORS[categoryLabel] ?? COLORS[index] ?? COLORS[COLORS.length - 1],
            label: categoryLabel,
            subLabel: Number.isFinite(categoryCount)
              ? `n=${categoryCount.toLocaleString("en-US")}`
              : null,
          };
        });
      }

      const bins = Array.isArray(femaLegend?.bins) ? femaLegend.bins : [];
      if (bins.length > 0) {
        return bins.map((bin, index) => ({
          key: `fema-bin-${bin?.min}-${bin?.max}-${index}`,
          colorIndex: index,
          label: String(bin?.label ?? formatRange(bin?.min, bin?.max)),
        }));
      }

      return breaks.slice(0, -1).map((start, index) => {
        const end = breaks[index + 1];
        return {
          key: `fema-fallback-${start}-${end}-${index}`,
          colorIndex: index,
          label: formatRange(start, end),
        };
      });
    }
    if (isAcsDataSource) {
      const bins = Array.isArray(acsLegend?.bins) ? acsLegend.bins : [];
      return bins.map((bin, index) => ({
        key: `${bin?.min}-${bin?.max}-${index}`,
        colorIndex: Number.isFinite(Number(bin?.colorIndex))
          ? Number(bin.colorIndex)
          : index,
        label: String(bin?.label ?? formatRange(bin?.min, bin?.max)),
      }));
    }
    if (isCmsDataSource) {
      return breaks.slice(0, -1).map((start, index) => {
        const end = breaks[index + 1];
        return {
          key: `${start}-${end}-${index}`,
          colorIndex: index,
          label: formatCmsRange(start, end, cmsUnitType),
        };
      });
    }
    if (isCdcDataSource) {
      const bins = Array.isArray(cdcLegend?.bins) ? cdcLegend.bins : [];
      if (bins.length > 0) {
        return bins.map((bin, index) => ({
          key: `cdc-bin-${bin?.min}-${bin?.max}-${index}`,
          colorIndex: Number.isFinite(Number(bin?.colorIndex))
            ? Number(bin.colorIndex)
            : index,
          label: String(bin?.label ?? formatRange(bin?.min, bin?.max)),
        }));
      }
      return breaks.slice(0, -1).map((start, index) => {
        const end = breaks[index + 1];
        return {
          key: `cdc-fallback-${start}-${end}-${index}`,
          colorIndex: index,
          label: formatRange(start, end),
        };
      });
    }

    return breaks.slice(0, -1).map((start, index) => {
      const end = breaks[index + 1];
      return {
        key: `${start}-${end}-${index}`,
        colorIndex: index,
        label: formatRange(start, end),
      };
    });
  }, [
    acsLegend,
    breaks,
    cdcLegend,
    cmsUnitType,
    femaLegend,
    hpsaTierRanges,
    isAcsDataSource,
    isCdcDataSource,
    isCmsDataSource,
    isFemaDataSource,
    isHpsaDataSource,
    isSviDataSource,
    isUsdaDataSource,
    isUsdaHeatMode,
    sviBins,
    usdaLegend,
  ]);

  const compactOverlayLayout = viewportWidth <= 1200;
  const mapViewportHeight = Math.max(420, viewportHeight - HEADER_HEIGHT);
  const profilePanelWidth = profilePanelOpen
    ? Math.min(460, Math.round(viewportWidth * 0.92))
    : 0;
  const rightOverlayInset = compactOverlayLayout
    ? 16
    : 16 + (profilePanelWidth > 0 ? profilePanelWidth + 12 : 0);
  const legendTopOffset = compactOverlayLayout
    ? 16 + measurePanelHeight + 12
    : 16;
  const legendMaxHeight = Math.max(180, mapViewportHeight - (legendTopOffset + 16));
  const usdaLegendLabel = getUsdaPlainLabel(
    selectedMeasureId,
    firstDefined(
      usdaLegend?.label,
      selectedMeasure?.name,
      selectedMeasureId,
      "USDA Food Environment"
    )
  );
  const usdaLegendDescription = truncateText(
    getUsdaPlainDescription(
      selectedMeasureId,
      firstDefined(
        usdaLegend?.description,
        selectedMeasure?.description,
        selectedMeasure?.usda_description_raw,
        selectedMeasure?.usda_notes,
        ""
      )
    ),
    170
  );
  const usdaLegendAggText = usdaRenderLevel === "state"
    ? "Value = USDA Food Environment state-level indicator."
    : "Value = USDA Food Environment county-level indicator.";
  const femaLegendLabel = getFemaMeasureLabel(selectedMeasure, selectedMeasureId);
  const femaLegendDescription = truncateText(
    String(firstDefined(femaLegend?.description, selectedMeasure?.description, "")).trim(),
    180
  );
  const femaLegendNote = truncateText(
    String(firstDefined(femaLegend?.note, femaCatalogMeta?.notes, "")).trim(),
    220
  );
  const femaLegendLevelText = tractsActive ? "Census tract level" : "County level";
  const usdaHeatPoints = Array.isArray(usdaHeatLayer?.points) ? usdaHeatLayer.points : [];
  const usdaHeatAgg = String(usdaHeatLayer?.agg ?? "median").toLowerCase();
  const usdaHeatUnitType = usdaHeatAgg === "pct_flagged"
    ? "percent"
    : inferTooltipUnitType({
      source: DATA_SOURCES.USDA_FOOD_ENV,
      measureId: selectedMeasureId,
      measureLabel: usdaLegendLabel,
    });
  const usdaHeatRenderModel = useMemo(
    () => buildUsdaHeatRenderModel(usdaHeatPoints, usdaHeatAgg),
    [usdaHeatAgg, usdaHeatPoints]
  );
  const usdaHeatLatLngs = usdaHeatRenderModel.heatLatLngs;
  const usdaHeatHoverCandidates = usdaHeatRenderModel.hoverPoints;
  const usdaHeatStats = usdaHeatRenderModel.stats ?? {};
  const selectedBaseMap = useMemo(
    () => BASE_MAP_OPTIONS.find((option) => option.id === selectedBaseMapId) ?? BASE_MAP_OPTIONS[0],
    [selectedBaseMapId]
  );
  const usdaHeatStyle = getHeatStyle(mapZoom);
  const usdaHeatLayerOptions = {
    minOpacity: 0.20,
    maxZoom: 9,
    max: 1.0,
    radius: usdaHeatStyle.radius,
    blur: usdaHeatStyle.blur,
    gradient: USDA_HEAT_LAYER_GRADIENT,
  };
  const usdaHeatHoverValueText = usdaHeatHoverPoint
    ? formatTooltipValue(usdaHeatHoverPoint.value, usdaHeatUnitType)
    : "No data";
  const usdaHeatHoverDisplayValue = usdaHeatHoverValueText === "No data"
    ? usdaHeatHoverValueText
    : `~${usdaHeatHoverValueText}`;
  const usdaHeatHoverTractCount = Number.isFinite(Number(usdaHeatHoverPoint?.n))
    ? Number(usdaHeatHoverPoint.n)
    : 0;
  const showUsdaHeatDebug = Boolean(import.meta.env.DEV && isUsdaDataSource && isUsdaHeatMode);
  const showUsdaMapDebugToggle = Boolean(import.meta.env.DEV && isUsdaDataSource && !isUsdaHeatMode);
  const legendTitle = isHpsaDataSource
    ? `Healthcare Access — ${hpsaDomainLabel}`
    : isCdcDataSource
      ? "CDC Funding"
    : isUsdaDataSource
      ? "USDA Food Environment"
    : isFemaDataSource
      ? "FEMA National Risk Index"
    : isSviDataSource
      ? (selectedMeasureDisplayName || selectedMeasureId)
      : isCmsDataSource
        ? (selectedMeasureDisplayName || selectedMeasureId)
      : `${formatDataValueTypeLabel(selectedType)} \u2013 ${
        tractsActive ? "Census Tract Level" : "County Level"
      }`;
  const legendSubtitle = isHpsaDataSource
    ? "County-only HPSA choropleth"
    : isCdcDataSource
      ? `${cdcBasis === "prime" ? "Prime Awards" : "Subawards"} • ${cdcGeography === "state" ? "State" : "County"}`
    : isUsdaDataSource
      ? `${usdaLegendLabel} (${usdaRenderLevel === "state" ? "State-level" : "County-level"})`
    : isFemaDataSource
      ? `${femaLegendLabel} (${femaLegendLevelText})`
    : isSviDataSource
      ? "Levels of Vulnerability"
      : isCmsDataSource
        ? `County-level • Medicare Fee-for-Service • ${selectedYear ?? "N/A"} • ${selectedCmsAgeLabel}`
      : null;
  const floatingPanelStyle = {
    background: "#ffffff",
    border: "1px solid #E3E8ED",
    borderRadius: 10,
    boxShadow: "0 6px 20px rgba(15, 45, 70, 0.12)",
  };
  const controlSelectStyle = {
    width: "100%",
    minWidth: 0,
    padding: "7px 9px",
    borderRadius: 6,
    border: "1px solid #C4D2E0",
    background: "#ffffff",
    color: "#0F2D46",
    fontSize: 12,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  };
  const panelToggleButtonStyle = {
    position: "absolute",
    top: 8,
    right: 8,
    width: 24,
    height: 24,
    borderRadius: 6,
    border: "1px solid #C4D2E0",
    background: "#ffffff",
    color: "#2C5F8A",
    fontWeight: 700,
    cursor: "pointer",
    lineHeight: "20px",
    textAlign: "center",
    padding: 0,
  };

  return (
    <div className="app">
      <Header />
      <div
        className="app-content"
        style={{ width: "100vw", height: mapViewportHeight }}
      >
        <div className="chip-brand-line">
          <span>Community Health Intelligence Platform (CHIP)</span>
          <span>Local Data. Strategic Insight.</span>
        </div>
        <div
          ref={measurePanelRef}
          className="measure-controls-panel"
          style={{
            ...floatingPanelStyle,
            position: "absolute",
            top: 16,
            left: 16,
            right: compactOverlayLayout ? 16 : "auto",
            width: compactOverlayLayout ? "auto" : "min(460px, calc(100vw - 32px))",
            padding: "12px 14px",
            fontSize: 12,
            maxWidth: "min(560px, calc(100vw - 32px))",
            display: "grid",
            gap: 10,
            zIndex: 2200,
          }}
        >
        <button
          type="button"
          aria-label={isMeasurePanelMinimized ? "Expand measure controls" : "Minimize measure controls"}
          onClick={() => setIsMeasurePanelMinimized((current) => !current)}
          style={panelToggleButtonStyle}
        >
          {isMeasurePanelMinimized ? "+" : "\u2212"}
        </button>
        <div style={{ fontWeight: 700, fontSize: 13, paddingRight: 30, color: "#0F2D46" }}>
          Measure controls {isCountyLoading || isTractLoading || isUsdaHeatLoading ? "- Loading..." : ""}
        </div>
        {!isMeasurePanelMinimized ? (
          <>
            {error ? <div style={{ color: "#b91c1c", fontWeight: 600 }}>{error}</div> : null}
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontWeight: 600 }}>Data source</span>
              <select
                value={selectedDataSource}
                onChange={(event) => {
                  const nextSource = event.target.value;
                  setSelectedDataSource(nextSource);
                  setSelectedMeasureId("");
                  if (nextSource === DATA_SOURCES.USDA_FOOD_ENV) {
                    setUsdaIncludeArchive(false);
                    setUsdaShowStateMeasures(false);
                    setUsdaMeasureSearch("");
                    setUsdaMeasurePickerOpen(false);
                  }
                  if (nextSource === DATA_SOURCES.FEMA_NRI) {
                    setFemaMeasureSearch("");
                    setFemaMeasurePickerOpen(false);
                  }
                  if (nextSource === DATA_SOURCES.CDC_FUNDING) {
                    setCdcBasis("prime");
                    setCdcGeography("county");
                    setCdcAssistanceType("");
                    setCdcFiscalYear("");
                    setCdcAwardingOffice("");
                    setCdcFundingOffice("");
                    setCdcCenter("");
                    setCdcStateFilter("");
                  }
                  if (nextSource === DATA_SOURCES.PLACES) {
                    setPlacesMeasureSearch("");
                    setPlacesMeasurePickerOpen(false);
                  }
                }}
                style={controlSelectStyle}
              >
                <option value={DATA_SOURCES.PLACES}>PLACES (modeled health estimates)</option>
                <option value={DATA_SOURCES.CMS}>CMS (Medicare Fee-for-Service)</option>
                <option value={DATA_SOURCES.CDC_FUNDING}>CDC Funding</option>
                <option value={DATA_SOURCES.USDA_FOOD_ENV}>USDA Food Environment</option>
                <option value={DATA_SOURCES.FEMA_NRI}>FEMA National Risk Index</option>
                <option value={DATA_SOURCES.ACS_NMF}>ACS Non-medical factors</option>
                <option value={DATA_SOURCES.SVI}>Social Vulnerability Index</option>
                <option value={DATA_SOURCES.HPSA}>HRSA HPSA</option>
              </select>
            </label>
            {isHpsaDataSource ? (
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontWeight: 600 }}>HPSA domain</span>
                <select
                  value={selectedHpsaDomain}
                  onChange={(event) => setSelectedHpsaDomain(event.target.value)}
                  style={controlSelectStyle}
                >
                  {HPSA_DOMAIN_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <span style={{ color: "#475569", fontSize: 11 }}>
                  County-only quartile tiers by designated-county score distribution.
                </span>
                {hpsaChoroplethError ? (
                  <span style={{ color: "#b91c1c", fontSize: 11 }}>{hpsaChoroplethError}</span>
                ) : null}
              </label>
            ) : (
              <>
            {isUsdaDataSource ? (
              <div ref={usdaMeasureSelectorRef} style={{ display: "grid", gap: 6 }}>
                <span style={{ fontWeight: 600 }}>Measure</span>
                <UsdaMeasureSelector
                  selectedMeasureId={selectedMeasureId}
                  selectedMeasure={selectedMeasure}
                  isOpen={usdaMeasurePickerOpen}
                  onToggleOpen={() => setUsdaMeasurePickerOpen((value) => !value)}
                  onClose={() => setUsdaMeasurePickerOpen(false)}
                  searchValue={usdaMeasureSearch}
                  onSearchChange={setUsdaMeasureSearch}
                  includeArchive={usdaIncludeArchive}
                  onToggleIncludeArchive={setUsdaIncludeArchive}
                  showStateMeasures={usdaShowStateMeasures}
                  onToggleShowStateMeasures={setUsdaShowStateMeasures}
                  recentMeasures={usdaRecentMeasures}
                  recommendedMeasures={usdaRecommendedMeasures}
                  commonMeasures={usdaCommonMeasures}
                  categoryGroups={usdaCategoryGroups}
                  archiveMeasures={usdaArchiveMeasures}
                  stateMeasures={usdaStateMeasures}
                  onSelectMeasure={(measureId) => {
                    setSelectedMeasureId(measureId);
                    setUsdaMeasurePickerOpen(false);
                  }}
                />
              </div>
            ) : isFemaDataSource ? (
              <div ref={femaMeasureSelectorRef} style={{ display: "grid", gap: 6 }}>
                <span style={{ fontWeight: 600 }}>Measure</span>
                <FemaMeasureSelector
                  selectedMeasureId={selectedMeasureId}
                  selectedMeasure={selectedMeasure}
                  isOpen={femaMeasurePickerOpen}
                  onToggleOpen={() => setFemaMeasurePickerOpen((value) => !value)}
                  onClose={() => setFemaMeasurePickerOpen(false)}
                  searchValue={femaMeasureSearch}
                  onSearchChange={setFemaMeasureSearch}
                  groupedMeasures={femaGroupedMeasures}
                  totalVisibleMeasures={femaVisibleMeasures.length}
                  onSelectMeasure={(measureId) => {
                    setSelectedMeasureId(measureId);
                    setFemaMeasurePickerOpen(false);
                  }}
                />
              </div>
            ) : isPlacesDataSource ? (
              <div ref={placesMeasureSelectorRef} style={{ display: "grid", gap: 6 }}>
                <span style={{ fontWeight: 600 }}>Measure</span>
                <PlacesMeasureSelector
                  selectedMeasureId={selectedMeasureId}
                  selectedMeasure={selectedMeasure}
                  isOpen={placesMeasurePickerOpen}
                  onToggleOpen={() => setPlacesMeasurePickerOpen((value) => !value)}
                  onClose={() => setPlacesMeasurePickerOpen(false)}
                  searchValue={placesMeasureSearch}
                  onSearchChange={setPlacesMeasureSearch}
                  categoryGroups={placesMeasureGroups}
                  totalVisibleMeasures={placesVisibleMeasures.length}
                  onSelectMeasure={(measureId) => {
                    setSelectedMeasureId(measureId);
                    setPlacesMeasurePickerOpen(false);
                  }}
                />
              </div>
            ) : (
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontWeight: 600 }}>Measure</span>
                <select
                  value={selectedMeasureId}
                  onChange={(event) => setSelectedMeasureId(event.target.value)}
                  style={controlSelectStyle}
                >
                  {measures.length === 0 ? (
                    <option value={selectedMeasureId}>Loading measures...</option>
                  ) : isSviDataSource ? (
                    sviMeasureGroups.map((group) => (
                      <optgroup key={group.id} label={group.label}>
                        {group.options.map((option) => {
                          const normalizedId = String(option.measure_id).trim().toUpperCase();
                          const measureMeta = sviMeasureById.get(normalizedId);
                          const isAvailable = Boolean(
                            measureMeta && measureMeta.svi_available !== false
                          );
                          const optionLabel = isAvailable
                            ? option.label
                            : `${option.label} (unavailable)`;
                          return (
                            <option
                              key={normalizedId}
                              value={normalizedId}
                              disabled={!isAvailable}
                            >
                              {optionLabel}
                            </option>
                          );
                        })}
                      </optgroup>
                    ))
                  ) : isCmsDataSource ? (
                    measures.map((measure) => (
                      <option key={measure.measure_id} value={measure.measure_id}>
                        {getMeasureDisplayName(measure)}
                      </option>
                    ))
                  ) : (
                    measures.map((measure) => {
                      const label = getMeasureDisplayName(measure);
                      const optionLabel = `${measure.measure_id}${label ? ` - ${label}` : ""}`;
                      return (
                        <option key={measure.measure_id} value={measure.measure_id}>
                          {optionLabel}
                        </option>
                      );
                    })
                  )}
                </select>
              </label>
            )}
            {isCdcDataSource ? (
              <>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontWeight: 600 }}>Funding basis</span>
                  <select
                    value={cdcBasis}
                    onChange={(event) => {
                      const nextBasis = String(event.target.value ?? "prime");
                      setCdcBasis(nextBasis);
                      setCdcAssistanceType("");
                      const defaultMetric = CDC_DEFAULT_METRIC_BY_BASIS[nextBasis] ?? "total_funding";
                      setSelectedMeasureId(defaultMetric);
                    }}
                    style={controlSelectStyle}
                  >
                    {CDC_BASIS_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontWeight: 600 }}>Geography</span>
                  <select
                    value={cdcGeography}
                    onChange={(event) => setCdcGeography(String(event.target.value ?? "county"))}
                    style={controlSelectStyle}
                  >
                    {CDC_GEOGRAPHY_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                {cdcBasis === "prime" ? (
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontWeight: 600 }}>Assistance type</span>
                    <select
                      value={cdcAssistanceType}
                      onChange={(event) => setCdcAssistanceType(String(event.target.value ?? ""))}
                      style={controlSelectStyle}
                    >
                      <option value="">All assistance types</option>
                      {(cdcFilterOptions.assistance_types ?? []).map((value) => (
                        <option key={`cdc-assistance-${value}`} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontWeight: 600 }}>Fiscal year</span>
                  <select
                    value={cdcFiscalYear}
                    onChange={(event) => setCdcFiscalYear(String(event.target.value ?? ""))}
                    style={controlSelectStyle}
                  >
                    <option value="">All fiscal years</option>
                    {(cdcFilterOptions.fiscal_years ?? []).map((value) => (
                      <option key={`cdc-fy-${value}`} value={String(value)}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontWeight: 600 }}>CDC center / subagency</span>
                  <select
                    value={cdcCenter}
                    onChange={(event) => setCdcCenter(String(event.target.value ?? ""))}
                    style={controlSelectStyle}
                  >
                    <option value="">All centers / subagencies</option>
                    {(cdcFilterOptions.centers ?? []).map((value) => (
                      <option key={`cdc-center-${value}`} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontWeight: 600 }}>Awarding office</span>
                  <select
                    value={cdcAwardingOffice}
                    onChange={(event) => setCdcAwardingOffice(String(event.target.value ?? ""))}
                    style={controlSelectStyle}
                  >
                    <option value="">All awarding offices</option>
                    {(cdcFilterOptions.awarding_offices ?? []).map((value) => (
                      <option key={`cdc-awarding-office-${value}`} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontWeight: 600 }}>Funding office</span>
                  <select
                    value={cdcFundingOffice}
                    onChange={(event) => setCdcFundingOffice(String(event.target.value ?? ""))}
                    style={controlSelectStyle}
                  >
                    <option value="">All funding offices</option>
                    {(cdcFilterOptions.funding_offices ?? []).map((value) => (
                      <option key={`cdc-funding-office-${value}`} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontWeight: 600 }}>State filter</span>
                  <select
                    value={cdcStateFilter}
                    onChange={(event) => setCdcStateFilter(String(event.target.value ?? "").toUpperCase())}
                    style={controlSelectStyle}
                  >
                    <option value="">All states</option>
                    {(cdcFilterOptions.states ?? []).map((entry) => {
                      const code = String(entry?.code ?? "").trim().toUpperCase();
                      const name = String(entry?.name ?? code).trim();
                      if (!code) return null;
                      return (
                        <option key={`cdc-state-${code}`} value={code}>
                          {code} - {name}
                        </option>
                      );
                    })}
                  </select>
                </label>
              </>
            ) : null}
            {isSviDataSource ? (
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontWeight: 600 }}>Year</span>
                <select
                  value={selectedSviYear ?? ""}
                  onChange={(event) => {
                    const nextYear = Number(event.target.value);
                    if (Number.isFinite(nextYear)) {
                      setSelectedSviYear(nextYear);
                    }
                  }}
                  disabled={isSviYearsLoading || sviYears.length === 0}
                  style={controlSelectStyle}
                >
                  {isSviYearsLoading && sviYears.length === 0 ? (
                    <option value="">Loading years...</option>
                  ) : (
                    sviYears.map((year) => (
                      <option key={year} value={year}>
                        {year}
                      </option>
                    ))
                  )}
                </select>
                {sviYearsError ? (
                  <span style={{ color: "#b91c1c", fontSize: 11 }}>{sviYearsError}</span>
                ) : null}
              </label>
            ) : (
	            isUsdaDataSource ? (
	              <div style={{ display: "grid", gap: 4, color: "#475569" }}>
	                <div style={{ fontWeight: 600, color: "#0F2D46" }}>Food Environment</div>
	                <div>USDA Food Environment Atlas (July 2025).</div>
	                <div style={{ fontSize: 11 }}>
	                  Category: {String(selectedMeasure?.category ?? "Other")}
	                </div>
	                <div style={{ fontSize: 11 }}>
	                  Recommended set: {Array.isArray(usdaVariableMeta?.recommended) ? usdaVariableMeta.recommended.length : 0}
	                </div>
	                <div style={{ marginTop: 2 }}>
	                  <span
	                    style={{
	                      display: "inline-flex",
	                      alignItems: "center",
	                      padding: "2px 8px",
	                      borderRadius: 999,
	                      border: "1px solid #bfdbfe",
	                      background: "#eff6ff",
	                      color: "#1d4ed8",
	                      fontSize: 11,
	                      fontWeight: 600,
	                    }}
	                  >
	                    {usdaRenderLevel === "state" ? "State-level" : "County-level"}
	                  </span>
	                </div>
                  {showUsdaMapDebugToggle ? (
                    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
                      <input
                        type="checkbox"
                        checked={usdaShowMapDiagnostics}
                        onChange={(event) => setUsdaShowMapDiagnostics(Boolean(event.target.checked))}
                      />
                      Show map diagnostics
                    </label>
                  ) : null}
                  {showUsdaMapDebugToggle && usdaShowMapDiagnostics && usdaMapDiagnostics ? (
                    <div style={{ fontSize: 11, color: "#334155" }}>
                      zoom={usdaMapDiagnostics.zoom}
                      {" • "}
                      level={usdaMapDiagnostics.level}
                      {" • "}
                      tolerance={Number(usdaMapDiagnostics.simplifyToleranceDegrees).toFixed(3)}°
                      {" • "}
                      precision={usdaMapDiagnostics.geojsonPrecision}
                    </div>
                  ) : null}
	              </div>
	            ) : isFemaDataSource ? (
	              <div style={{ display: "grid", gap: 4, color: "#475569" }}>
	                <div style={{ fontWeight: 600, color: "#0F2D46" }}>FEMA Risk Index</div>
	                <div>
	                  {String(femaCatalogMeta?.dataset_name ?? "FEMA National Risk Index")}
	                  {femaCatalogMeta?.dataset_vintage ? ` (${femaCatalogMeta.dataset_vintage})` : ""}
	                </div>
	                <div style={{ fontSize: 11 }}>
	                  Group: {String(selectedMeasure?.fema_group ?? selectedMeasure?.category ?? "Other")}
	                </div>
	                <div style={{ fontSize: 11 }}>
	                  Subgroup: {String(selectedMeasure?.fema_subgroup ?? "General")}
	                </div>
	                <div style={{ marginTop: 2 }}>
	                  <span
	                    style={{
	                      display: "inline-flex",
	                      alignItems: "center",
	                      padding: "2px 8px",
	                      borderRadius: 999,
	                      border: "1px solid #bfdbfe",
	                      background: "#eff6ff",
	                      color: "#1d4ed8",
	                      fontSize: 11,
	                      fontWeight: 600,
	                    }}
	                  >
	                    {tractsActive ? "Census tract level" : "County level"}
	                  </span>
	                </div>
	              </div>
	            ) : isCdcDataSource ? (
	              <div style={{ display: "grid", gap: 4, color: "#475569" }}>
	                <div style={{ fontWeight: 600, color: "#0F2D46" }}>CDC Funding</div>
	                <div>
	                  {cdcBasis === "prime" ? "Prime Awards" : "Subawards"} • {cdcGeography === "state" ? "State totals" : "County totals"}
	                </div>
	                <div style={{ fontSize: 11 }}>
	                  Prime awards and subawards are shown separately. Subawards are downstream portions of prime awards and are not added to prime totals in this view.
	                </div>
	                <div style={{ fontSize: 11 }}>
	                  Records without county FIPS remain searchable but are excluded from county choropleth totals.
	                </div>
	              </div>
	            ) : (
	              <label style={{ display: "grid", gap: 6 }}>
	                <span style={{ fontWeight: 600 }}>{isAcsDataSource ? "Year window" : "Year"}</span>
	                <select
	                  value={isAcsDataSource ? (selectedYearWindow ?? "") : (selectedYear ?? "")}
	                  onChange={(event) => {
	                    if (isAcsDataSource) {
	                      const nextYearWindow = String(event.target.value ?? "").trim();
	                      setSelectedYearWindow(nextYearWindow || null);
	                    } else {
	                      setSelectedYear(Number(event.target.value));
	                    }
	                  }}
	                  disabled={
	                    isAcsDataSource
	                      ? acsYearWindows.length === 0
	                      : (isYearsLoading || years.length === 0)
	                  }
	                  style={controlSelectStyle}
	                >
	                  {isAcsDataSource ? (
	                    acsYearWindows.length === 0 ? (
	                      <option value="">Loading year windows...</option>
	                    ) : (
	                      acsYearWindows.map((yearWindow) => (
	                        <option key={yearWindow} value={yearWindow}>
	                          {formatYearWindowDisplay(yearWindow)}
	                        </option>
	                      ))
	                    )
	                  ) : isYearsLoading && years.length === 0 ? (
	                    <option value="">Loading years...</option>
	                  ) : (
	                    years.map((year) => (
	                      <option key={year} value={year}>
	                        {year}
	                      </option>
	                    ))
	                  )}
	                </select>
	                {!isAcsDataSource && yearsError ? (
	                  <span style={{ color: "#b91c1c", fontSize: 11 }}>{yearsError}</span>
	                ) : null}
	              </label>
	            )
	            )}
	            {isCmsDataSource ? (
	              <label style={{ display: "grid", gap: 6 }}>
	                <span style={{ fontWeight: 600 }}>Age group</span>
	                <select
	                  value={selectedCmsAgeGroup}
	                  onChange={(event) => setSelectedCmsAgeGroup(event.target.value)}
	                  style={controlSelectStyle}
	                >
	                  {CMS_AGE_OPTIONS.map((option) => (
	                    <option key={option.value} value={option.value}>
	                      {option.label}
	                    </option>
	                  ))}
	                </select>
	              </label>
	            ) : null}
	            {!isSviDataSource ? (
	              isCmsDataSource ? (
	                <div style={{ display: "grid", gap: 4 }}>
	                  <div style={{ fontWeight: 600 }}>Data type</div>
	                  <div>Medicare Fee-for-Service reported value</div>
	                  <div style={{ color: "#64748b", fontSize: 11 }}>
	                    County-level only (no tracts).
	                  </div>
	                </div>
	              ) : isUsdaDataSource ? (
	                <div style={{ display: "grid", gap: 4 }}>
	                  <div style={{ fontWeight: 600 }}>Data type</div>
	                  <div>USDA Food Environment indicator value</div>
	                  <div style={{ color: "#64748b", fontSize: 11 }}>
	                    Values are selected from USDA variable metadata.
	                  </div>
	                </div>
	              ) : isFemaDataSource ? (
	                <div style={{ display: "grid", gap: 4 }}>
	                  <div style={{ fontWeight: 600 }}>Data type</div>
	                  <div>FEMA National Risk Index indicator value</div>
	                  <div style={{ color: "#64748b", fontSize: 11 }}>
	                    Includes scores, ratings, expected annual loss, and hazard-specific indicators.
	                  </div>
	                </div>
	              ) : isCdcDataSource ? (
	                <div style={{ display: "grid", gap: 6 }}>
	                  <div style={{ fontWeight: 600 }}>Search awards/subawards</div>
	                  <input
	                    type="text"
	                    value={cdcSearchQuery}
	                    onChange={(event) => setCdcSearchQuery(event.target.value)}
	                    placeholder="Search FAIN, recipient, office, description..."
	                    style={{
	                      width: "100%",
	                      minWidth: 0,
	                      padding: "7px 9px",
	                      borderRadius: 6,
	                      border: "1px solid #C4D2E0",
	                      background: "#ffffff",
	                      color: "#0F2D46",
	                      fontSize: 12,
	                    }}
	                  />
	                  <div style={{ color: "#64748b", fontSize: 11 }}>
	                    Type at least 2 characters to search. Results include both Prime Awards and Subawards.
	                  </div>
	                </div>
	              ) : (
	                <label style={{ display: "grid", gap: 6 }}>
	                  <span style={{ fontWeight: 600 }}>Data value type</span>
	                  <select
	                    value={selectedType}
	                    onChange={(event) => setSelectedType(event.target.value)}
	                    disabled={isAcsDataSource && acsDataValueTypeIds.length === 0}
	                    style={controlSelectStyle}
	                  >
	                    {isAcsDataSource ? (
	                      acsDataValueTypeIds.length === 0 ? (
	                        <option value="">Loading types...</option>
	                      ) : (
	                        acsDataValueTypeIds.map((typeId) => (
	                          <option key={typeId} value={typeId}>
	                            {formatDataValueTypeLabel(typeId)}
	                          </option>
	                        ))
	                      )
	                    ) : (
	                      <>
	                        <option value="CrdPrv">Crude Prevalence</option>
	                        <option value="AgeAdjPrv">Age-Adjusted Prevalence</option>
	                      </>
	                    )}
	                  </select>
	                </label>
	              )
	            ) : null}
            {measures.length === 0 ? null : (
              <div style={{ color: "#475569" }}>
                {selectedMeasureDisplayName}
              </div>
            )}
              </>
            )}
          </>
        ) : null}
      </div>

        <div className="map-wrapper" style={{ height: "100%", width: "100%", background: "#F4F6F8" }}>
          <MapContainer
            center={DEFAULT_CENTER}
            zoom={DEFAULT_ZOOM}
            style={{ height: "100%", width: "100%" }}
          >
          <TileLayer
            key={selectedBaseMap.id}
            attribution={selectedBaseMap.attribution}
            url={selectedBaseMap.url}
            maxZoom={selectedBaseMap.maxZoom}
          />

          <MapViewportWatcher
            onMapReady={(map) => {
              mapRef.current = map;
            }}
            onViewportChange={(zoom, bounds) => {
              setMapZoom(zoom);
              
              const bboxString = boundsToPaddedBbox(bounds, zoom);
              const previousZoom = previousZoomRef.current;
              const crossedCountyReloadZoom =
                previousZoom > COUNTY_RELOAD_ZOOM && zoom <= COUNTY_RELOAD_ZOOM && zoom < previousZoom;
              previousZoomRef.current = zoom;
              if (crossedCountyReloadZoom) {
                setCountyGeojson(null);
                setCountyReloadNonce((value) => value + 1);
                setBbox(bboxString);
              }
              
              // Debounce bbox updates to prevent excessive fetches
              if (viewportDebounceRef.current) {
                clearTimeout(viewportDebounceRef.current);
              }
              
              viewportDebounceRef.current = setTimeout(() => {
                setBbox(bboxString);
              }, VIEWPORT_DEBOUNCE_MS);
            }}
          />
          <MapToolbar
            defaultCenter={DEFAULT_CENTER}
            defaultZoom={DEFAULT_ZOOM}
            baseMapOptions={BASE_MAP_OPTIONS}
            selectedBaseMapId={selectedBaseMapId}
            onBaseMapChange={setSelectedBaseMapId}
            compactLayout={compactOverlayLayout}
            rightInset={rightOverlayInset}
            hasSelectedLocation={Boolean(selectedLocationId)}
            onZoomToSelected={handleZoomToSelected}
            onAnalyzeSelectedArea={handleAnalyzeSelectedArea}
            zoomToSelectedLabel={zoomToSelectedLabel}
            zoomToSelectedRef={zoomToSelectedButtonRef}
            profileGenerating={profileGenerating || analyzeGenerating || assistantLoading}
            profileTarget={selectedProfileTarget}
            onOpenProfile={handleOpenSelectedProfile}
          />
          <SearchBar
            apiBase={API_BASE}
            onCountySelected={handleCountySearchSelection}
            compactLayout={compactOverlayLayout}
            rightInset={rightOverlayInset}
          />

          {isUsdaHeatMode ? (
            <>
              <UsdaHeatHoverWatcher
                enabled={isUsdaHeatMode}
                points={usdaHeatHoverCandidates}
                onHover={setUsdaHeatHoverPoint}
              />
              {usdaHeatLatLngs.length > 0 ? (
                <Pane name="usda-heat-surface" style={{ zIndex: 650 }}>
                  <UsdaHeatLayer
                    points={usdaHeatLatLngs}
                    options={usdaHeatLayerOptions}
                    pane="usda-heat-surface"
                  />
                </Pane>
              ) : null}
              {usdaHeatHoverPoint ? (
                <Pane name="usda-heat-hover" style={{ zIndex: 700 }}>
                  <CircleMarker
                    center={[usdaHeatHoverPoint.lat, usdaHeatHoverPoint.lon]}
                    radius={1}
                    pathOptions={{
                      opacity: 0,
                      fillOpacity: 0,
                      weight: 0,
                    }}
                    interactive={false}
                    pane="usda-heat-hover"
                  >
                    <Tooltip direction="top" opacity={0.95} permanent>
                      <div>{`${usdaLegendLabel}: ${usdaHeatHoverDisplayValue}`}</div>
                      <div style={{ color: "#475569" }}>
                        Aggregated from {usdaHeatHoverTractCount} tracts
                      </div>
                    </Tooltip>
                  </CircleMarker>
                </Pane>
              ) : null}
            </>
          ) : null}

          {activeGeojson ? (
            <GeoJSON
              key={`${selectedDataSource}-${tractsActive ? "tracts" : "counties"}-${selectedTemporalValue}-${selectedMeasureId}-${selectedType}-${bbox ?? "no-bbox"}-${tractsActive ? "tract" : `county-${countyReloadNonce}`}`}
              ref={geoJsonRef}
              data={activeGeojson}
              style={choroplethStyle}
              onEachFeature={handleEachFeature}
            />
          ) : null}

          {tractsActive && !isUsdaDataSource && countyBoundaryOverlay ? (
            <Pane name="county-boundary-overlay" style={{ zIndex: 640 }}>
              <GeoJSON
                key="outline"
                data={countyBoundaryOverlay}
                style={countyBoundaryLineStyle}
                interactive={false}
                pane="county-boundary-overlay"
              />
            </Pane>
          ) : null}

          {!tractsActive && !isUsdaDataSource && stateBoundaryOverlay ? (
            <Pane name="state-boundary-overlay" style={{ zIndex: 640 }}>
              <GeoJSON
                key="state-outline"
                data={stateBoundaryOverlay}
                style={stateBoundaryLineStyle}
                interactive={false}
                pane="state-boundary-overlay"
              />
            </Pane>
          ) : null}
        </MapContainer>
      </div>

      {isCountyLoading || isTractLoading || isUsdaHeatLoading || isHpsaChoroplethLoading ? (
        <div
          style={{
            position: "absolute",
            top: 24,
            right: rightOverlayInset + 8,
            background: "#ffffff",
            color: "#0F2D46",
            border: "1px solid #E3E8ED",
            padding: "10px 16px",
            borderRadius: 999,
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: 0.2,
            boxShadow: "0 6px 20px rgba(15, 45, 70, 0.12)",
            zIndex: 2100,
          }}
        >
          Loading...
        </div>
      ) : null}

      <div
        className="legend-panel"
        style={{
          ...floatingPanelStyle,
          position: "absolute",
          top: legendTopOffset,
          left: compactOverlayLayout ? 16 : "auto",
          right: rightOverlayInset,
          padding: "12px 14px",
          fontSize: 12,
          width: compactOverlayLayout ? "auto" : "min(320px, calc(100vw - 32px))",
          maxWidth: "min(520px, calc(100vw - 32px))",
          maxHeight: legendMaxHeight,
          overflowY: "auto",
          zIndex: 2100,
        }}
      >
        <button
          type="button"
          aria-label={isLegendPanelMinimized ? "Expand legend" : "Minimize legend"}
          onClick={() => setIsLegendPanelMinimized((current) => !current)}
          style={panelToggleButtonStyle}
        >
          {isLegendPanelMinimized ? "+" : "\u2212"}
        </button>
        <div style={{ marginBottom: 8, paddingRight: 30, color: "#0F2D46" }}>
          <div style={{ fontWeight: 700 }}>
            {legendTitle}
          </div>
          {legendSubtitle ? (
            <div style={{ fontSize: 11, color: "#475569", marginTop: 2 }}>
              {legendSubtitle}
            </div>
          ) : null}
        </div>
        {!isLegendPanelMinimized ? (
          <>
        <div style={{ display: "grid", gap: 6 }}>
          {isUsdaDataSource && isUsdaHeatMode ? (
            <div style={{ display: "grid", gap: 6 }}>
              <div
                style={{
                  height: 10,
                  borderRadius: 999,
                  background: USDA_HEAT_RAMP_CSS,
                  border: "1px solid #C4D2E0",
                }}
              />
              <div style={{ display: "flex", justifyContent: "space-between", color: "#475569", fontSize: 11 }}>
                <span>Lower (p10)</span>
                <span>Higher (p90)</span>
              </div>
              <div style={{ color: "#475569" }}>
                This heat map shows where tract values are higher or lower in the current view. Zoom in for tract-level boundaries.
              </div>
              <div style={{ color: "#475569" }}>
                Colors are scaled to the current view to avoid distortion from outliers.
              </div>
              {showUsdaHeatDebug ? (
                <div style={{ color: "#64748b", fontSize: 11 }}>
                  points={usdaHeatStats?.pointCount ?? 0}
                  {Number.isFinite(usdaHeatStats?.p10) ? ` • p10=${Number(usdaHeatStats.p10).toFixed(3)}` : ""}
                  {Number.isFinite(usdaHeatStats?.p90) ? ` • p90=${Number(usdaHeatStats.p90).toFixed(3)}` : ""}
                  {Number.isFinite(usdaHeatStats?.minIntensity) ? ` • intensity min=${Number(usdaHeatStats.minIntensity).toFixed(3)}` : ""}
                  {Number.isFinite(usdaHeatStats?.maxIntensity) ? ` • max=${Number(usdaHeatStats.maxIntensity).toFixed(3)}` : ""}
                </div>
              ) : null}
            </div>
          ) : legendRows.length > 0
            ? legendRows.map((row) => {
                const color = row.color ?? COLORS[row.colorIndex] ?? COLORS[COLORS.length - 1];
                return (
                  <div
                    key={row.key}
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <span
                      style={{
                        width: 12,
                        height: 12,
                        background: color,
                        borderRadius: 2,
                        border: "1px solid #C4D2E0",
                      }}
                    />
                    <span>
                      <div>{row.label}</div>
                      {row.subLabel ? (
                        <div style={{ color: "#64748b", fontSize: 11 }}>{row.subLabel}</div>
                      ) : null}
                    </span>
                  </div>
                );
              })
            : isCountyLoading
              || isTractLoading
              || isUsdaHeatLoading
              || isHpsaChoroplethLoading
              || (isAcsDataSource && isLegendLoading)
              || (isCdcDataSource && isCdcLegendLoading)
              || (isUsdaDataSource && isUsdaLegendLoading)
              || (isFemaDataSource && isFemaLegendLoading)
              ? "Loading..."
              : "Legend unavailable."}
	          {!isHpsaDataSource && !(isUsdaDataSource && isUsdaHeatMode) ? (
	            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                style={{
                  width: 12,
                  height: 12,
                  background: NO_DATA_COLOR,
                  borderRadius: 2,
                  border: "1px solid #C4D2E0",
                }}
              />
	              <span>{isCmsDataSource ? "Not shown" : "No data"}</span>
	            </div>
	          ) : null}
          {isAcsDataSource && acsLegend ? (
            <div style={{ color: "#64748b" }}>
              n={acsLegend.n ?? 0}, no data={acsLegend.noDataCount ?? 0}
            </div>
          ) : null}
          {isCdcDataSource && cdcLegend ? (
            <div style={{ color: "#64748b" }}>
              n={cdcLegend.n ?? 0}, no data={cdcLegend.noDataCount ?? 0}
            </div>
          ) : null}
          {isUsdaDataSource && usdaLegend ? (
            <div style={{ color: "#64748b" }}>
              n={usdaLegend.n ?? 0}, no data={usdaLegend.noDataCount ?? 0}
            </div>
          ) : null}
          {isFemaDataSource && femaLegend ? (
            <div style={{ color: "#64748b" }}>
              n={femaLegend.n ?? 0}, no data={femaLegend.noDataCount ?? 0}
            </div>
          ) : null}
          {isUsdaDataSource && isUsdaHeatMode && usdaHeatLayer ? (
            <div style={{ color: "#64748b" }}>
              cells={Array.isArray(usdaHeatLayer?.points) ? usdaHeatLayer.points.length : 0}
            </div>
          ) : null}
          {isUsdaDataSource && usdaLegendDescription ? (
            <div style={{ color: "#475569" }}>{usdaLegendDescription}</div>
          ) : null}
          {isUsdaDataSource && !isUsdaHeatMode ? (
            <div style={{ color: "#475569" }}>{usdaLegendAggText}</div>
          ) : null}
          {isUsdaDataSource && usdaMapMessage ? (
            <div style={{ color: "#475569" }}>{usdaMapMessage}</div>
          ) : null}
          {isCdcDataSource && cdcMapMessage ? (
            <div style={{ color: "#475569" }}>{cdcMapMessage}</div>
          ) : null}
          {isCdcDataSource ? (
            <div style={{ color: "#475569", borderTop: "1px solid #e2e8f0", paddingTop: 8 }}>
              Prime awards and subawards are shown separately. Subawards are downstream portions of prime awards and are not added to prime totals in this view.
            </div>
          ) : null}
          {isFemaDataSource && femaLegendDescription ? (
            <div style={{ color: "#475569" }}>{femaLegendDescription}</div>
          ) : null}
          {isFemaDataSource && femaLegendNote ? (
            <div style={{ color: "#475569" }}>{femaLegendNote}</div>
          ) : null}
          {isFemaDataSource && femaMapMessage ? (
            <div style={{ color: "#475569" }}>{femaMapMessage}</div>
          ) : null}
	          {isHpsaDataSource && hpsaQuartiles ? (
	            <div style={{ color: "#64748b" }}>
	              designated counties n={hpsaQuartiles.n_counties ?? 0}
	              {hpsaQuartiles.as_of_date ? `, as-of ${hpsaQuartiles.as_of_date}` : ""}
	            </div>
	          ) : null}
	          {isCmsDataSource ? (
	            <div
	              style={{
	                marginTop: 6,
	                paddingTop: 8,
	                borderTop: "1px solid #e2e8f0",
	                display: "grid",
	                gap: 8,
	                color: "#334155",
	              }}
	            >
	              <div style={{ display: "grid", gap: 2 }}>
	                <div style={{ fontWeight: 700 }}>What this means</div>
	                <div>
	                  These values describe people enrolled in traditional Medicare
	                  (fee-for-service). They do not include Medicare Advantage enrollees
	                  and do not represent all residents.
	                </div>
	              </div>
	              <div style={{ display: "grid", gap: 2 }}>
	                <div style={{ fontWeight: 700 }}>Why this may differ from PLACES</div>
	                <div>
	                  PLACES estimates reflect all adults aged 18+. CMS reflects Medicare
	                  fee-for-service beneficiaries (mostly age 65+).
	                </div>
	              </div>
	            </div>
	          ) : null}
	        </div>
        {selectedFeature && !isHpsaDataSource ? (
          <>
            <hr />
            <div className="legend-details">
	              {isCmsDataSource ? (
	                <>
	                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>
	                    In {cmsCountyStateLine}:
	                  </div>
	                  {cmsValueNumeric == null ? (
	                    <p>Data not shown for this county (suppressed or unavailable).</p>
	                  ) : (
	                    <>
	                      <p>
	                        In <strong>{yearValue ?? selectedYear ?? "N/A"}</strong>, Medicare
	                        fee-for-service beneficiaries had{" "}
	                        <strong>{formatCmsValue(cmsValueNumeric, cmsUnitType)}</strong>{" "}
	                        ({cmsUnitLabel}).
	                      </p>
	                      <p>This reflects traditional Medicare (not Medicare Advantage).</p>
	                    </>
	                  )}
	                </>
	              ) : isCdcDataSource ? (
	                <>
	                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>
	                    {cdcGeoLevel === "state" ? "State" : "County"} • {cdcLocationLine}
	                  </div>
	                  <p>
	                    <strong>{selectedMeasureDisplayName}</strong>: <strong>{cdcMetricValueText}</strong>.
	                  </p>
	                  <p>Award count: <strong>{cdcAwardCountText}</strong>.</p>
	                  <p>{cdcSummaryNote}</p>
	                  {isCdcTopLoading ? (
	                    <div style={{ color: "#64748b" }}>Loading top awards...</div>
	                  ) : cdcTopError ? (
	                    <div style={{ color: "#b91c1c" }}>{cdcTopError}</div>
	                  ) : (
	                    <div style={{ display: "grid", gap: 4 }}>
	                      <div style={{ fontWeight: 600 }}>Top 5 {cdcBasis === "prime" ? "awards" : "subawards"}</div>
	                      {cdcTopRows.length === 0 ? (
	                        <div style={{ color: "#64748b" }}>No records for this geography under current filters.</div>
	                      ) : (
	                        cdcTopRows.map((row) => (
	                          <div key={`cdc-top-${row.record_id}`} style={{ display: "grid", gap: 2 }}>
	                            <div style={{ fontWeight: 600 }}>
	                              {String(row?.entity_name ?? "Unknown recipient")}
	                            </div>
	                            <div style={{ color: "#475569", fontSize: 11 }}>
	                              {row?.record_type === "subaward" ? "Subaward" : "Prime award"} • FAIN {String(row?.fain ?? "N/A")}
	                            </div>
	                          </div>
	                        ))
	                      )}
	                      {cdcTopNote ? (
	                        <div style={{ color: "#64748b", fontSize: 11 }}>{cdcTopNote}</div>
	                      ) : null}
	                    </div>
	                  )}
	                </>
	              ) : isUsdaDataSource ? (
	                <>
	                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>
	                    {usdaGeoLevel === "state" ? "State" : "County"} • {usdaLocationLine}
	                  </div>
	                  <p>
	                    USDA Food Environment: <strong>{usdaLabel}</strong> = <strong>{usdaValueText}</strong>.
	                  </p>
	                  {usdaLegendDescription ? (
	                    <p>{usdaLegendDescription}</p>
	                  ) : null}
	                </>
              ) : isFemaDataSource ? (
                <>
                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>
                    {femaLevel === "tract" ? "Census tract" : "County"} • {femaLocationLine}
                  </div>
                  <p>
                    <strong>{femaMeasureLabel}</strong>: <strong>{femaValueText}</strong>.
                  </p>
                  {femaRatingText && String(selectedMeasure?.fema_value_type ?? "").trim().toLowerCase() !== "rating" ? (
                    <p>Composite risk rating: <strong>{femaRatingText}</strong>.</p>
                  ) : null}
                  {femaHazardName ? (
                    <p>Hazard: <strong>{femaHazardName}</strong>.</p>
                  ) : null}
                  {femaMeasureDescription ? (
                    <p>{femaMeasureDescription}</p>
                  ) : null}
                  <p style={{ color: "#475569" }}>
                    FEMA NRI supports planning and broad comparison, and is not a substitute for local engineering-grade risk assessment.
                  </p>
                </>
	              ) : isAcsDataSource ? (
	                <p>
	                  In <strong>{acsAreaLabel}</strong>,{" "}
                  <strong>{measureNameValue}</strong> is{" "}
                  <strong>{fmtPercent(acsValue)}</strong>
                  {acsMoe == null ? "" : ` (MOE \u00b1${fmt1(acsMoe)})`} for{" "}
                  <strong>{formatYearWindowDisplay(yearValue)}</strong>.
                  {` Population: ${fmtPop(populationValue)}.`}
                </p>
              ) : isSviDataSource ? (
                <>
                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>
                    {sviAreaTitle}
                  </div>
                  <p>
                    {yearValue ?? selectedSviYear} National <strong>{sviMeasureName}</strong> SVI Rank:{" "}
                    <strong>{sviRankValueText}</strong>
                  </p>
                  <SviRankBar value={sviValueNumeric} />
                  <p>
                    Possible ranks range from 0 (lowest vulnerability) to 1 (highest
                    vulnerability).
                  </p>
                  {sviValueNumeric == null ? (
                    <p>No rank is available for this geography.</p>
                  ) : (
                    <p>
                      A rank of <strong>{sviRankValueText}</strong> indicates a{" "}
                      <strong>{sviLevelText}</strong> level of vulnerability.
                    </p>
                  )}
                  <p>
                    <a
                      href="#"
                      onClick={(event) => event.preventDefault()}
                    >
                      View County Map Series
                    </a>
                  </p>
                  {isSviThemeMeasure && sviThemeLabel ? (
                    <p>
                      Theme: <strong>{sviThemeLabel}</strong>
                    </p>
                  ) : null}
                </>
              ) : (
                <>
                  <p>
                    In <strong>{selectedAreaLabel}</strong>, the estimated prevalence of{" "}
                    <strong>{measureNameValue}</strong> among adults aged 18 years and older
                    (%) was <strong>{fmt1(crudeValue)}</strong> with 95% CI (
                    <strong>{ciText(crudeLow, crudeHigh)}</strong>), and the age-adjusted
                    prevalence (%) was <strong>{fmt1(ageAdjustedValue)}</strong> (
                    <strong>{ciText(ageAdjustedLow, ageAdjustedHigh)}</strong>) in{" "}
                    <strong>{yearValue ?? "N/A"}</strong>.
                  </p>
                  <p>
                    According to the Census <strong>{yearValue ?? "N/A"}</strong> population
                    estimates, <strong>{fmtPop(populationValue)}</strong> adults live in{" "}
                    <strong>{selectedAreaLabel}</strong>.
                  </p>
                  <p>
                    For more demographic, social, and economic data, visit{" "}
                    <a href={censusProfileHref} target="_blank" rel="noreferrer">
                      Census County Profile
                    </a>
                    .
                  </p>
                </>
              )}
            </div>
          </>
        ) : null}

        {isCdcDataSource ? (
          <>
            <hr />
            <div style={{ display: "grid", gap: 8 }}>
              <div style={{ fontWeight: 700 }}>CDC Search Results</div>
              {isCdcSearchLoading ? (
                <div style={{ color: "#64748b" }}>Searching...</div>
              ) : cdcSearchError ? (
                <div style={{ color: "#b91c1c" }}>{cdcSearchError}</div>
              ) : cdcSearchResults.length === 0 ? (
                <div style={{ color: "#64748b" }}>
                  {String(cdcSearchQuery ?? "").trim().length < 2
                    ? "Enter at least 2 characters to search."
                    : "No matches under current filters."}
                </div>
              ) : (
                <div style={{ display: "grid", gap: 8 }}>
                  <div style={{ color: "#64748b", fontSize: 11 }}>
                    Showing {cdcSearchResults.length} of {cdcSearchTotal.toLocaleString("en-US")} matches.
                  </div>
                  {cdcSearchResults.map((row) => {
                    const amountValue = toFiniteNumericValue(row?.amount);
                    const amountText = amountValue == null
                      ? "No amount"
                      : `$${amountValue.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
                    const sourceBadge = row?.record_type === "subaward" ? "Subaward" : "Prime Award";
                    const stateCode = String(row?.state_code ?? "").trim();
                    const countyName = String(row?.county_name ?? "").trim();
                    const placeLine = countyName
                      ? (stateCode ? `${countyName}, ${stateCode}` : countyName)
                      : (stateCode || "No mapped geography");
                    const latestDate = String(row?.latest_action_date ?? "").trim() || "No date";
                    const descriptionText = truncateText(String(row?.description ?? "").trim(), 160);
                    return (
                      <button
                        key={`cdc-search-${row.record_type}-${row.record_id}`}
                        type="button"
                        onClick={() => handleCdcResultSelect(row)}
                        style={{
                          textAlign: "left",
                          border: "1px solid #dbe7f0",
                          borderRadius: 8,
                          padding: "8px 10px",
                          background: "#ffffff",
                          cursor: "pointer",
                          display: "grid",
                          gap: 4,
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              borderRadius: 999,
                              padding: "1px 8px",
                              fontSize: 10,
                              fontWeight: 700,
                              color: "#1e3a8a",
                              background: "#eff6ff",
                              border: "1px solid #bfdbfe",
                            }}
                          >
                            {sourceBadge}
                          </span>
                          <span style={{ fontWeight: 700 }}>{String(row?.entity_name ?? "Unknown entity")}</span>
                        </div>
                        <div style={{ color: "#475569", fontSize: 11 }}>
                          FAIN: {String(row?.fain ?? "N/A")}
                          {row?.assistance_type_description ? ` • ${row.assistance_type_description}` : ""}
                        </div>
                        <div style={{ color: "#334155", fontSize: 11 }}>
                          {amountText} • {latestDate} • {placeLine}
                        </div>
                        {descriptionText ? (
                          <div style={{ color: "#475569", fontSize: 11 }}>{descriptionText}</div>
                        ) : null}
                        {row?.usaspending_permalink ? (
                          <a
                            href={row.usaspending_permalink}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(event) => event.stopPropagation()}
                            style={{ fontSize: 11 }}
                          >
                            View on USAspending
                          </a>
                        ) : null}
                      </button>
                    );
                  })}
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <button
                      type="button"
                      disabled={cdcSearchPage <= 1 || isCdcSearchLoading}
                      onClick={() => setCdcSearchPage((page) => Math.max(1, page - 1))}
                      className="chip-secondary-btn"
                    >
                      Prev
                    </button>
                    <div style={{ color: "#64748b", fontSize: 11, alignSelf: "center" }}>
                      Page {cdcSearchPage}
                    </div>
                    <button
                      type="button"
                      disabled={isCdcSearchLoading || (cdcSearchPage * 20 >= cdcSearchTotal)}
                      onClick={() => setCdcSearchPage((page) => page + 1)}
                      className="chip-secondary-btn"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}

              {cdcSelectedResult ? (
                <div style={{ borderTop: "1px solid #e2e8f0", paddingTop: 8, display: "grid", gap: 6 }}>
                  <div style={{ fontWeight: 700 }}>Selected record details</div>
                  {isCdcDetailLoading ? (
                    <div style={{ color: "#64748b" }}>Loading detail...</div>
                  ) : cdcDetailError ? (
                    <div style={{ color: "#b91c1c" }}>{cdcDetailError}</div>
                  ) : cdcDetailRecord ? (
                    <div style={{ display: "grid", gap: 4, color: "#334155" }}>
                      <div>
                        <strong>Type:</strong> {cdcDetailRecord.record_type === "subaward" ? "Subaward" : "Prime Award"}
                      </div>
                      <div>
                        <strong>FAIN:</strong> {String(cdcDetailRecord.fain ?? cdcDetailRecord.prime_award_fain ?? "N/A")}
                      </div>
                      <div>
                        <strong>Recipient:</strong> {String(cdcDetailRecord.recipient_name ?? cdcDetailRecord.subawardee_name ?? "Unknown")}
                      </div>
                      <div>
                        <strong>Latest action date:</strong>{" "}
                        {String(
                          cdcDetailRecord.award_latest_action_date
                          ?? cdcDetailRecord.subaward_action_date
                          ?? "N/A"
                        )}
                      </div>
                      <div>
                        <strong>Amount:</strong>{" "}
                        {(() => {
                          const detailAmount = toFiniteNumericValue(
                            cdcDetailRecord.total_funding_amount ?? cdcDetailRecord.subaward_amount
                          );
                          if (detailAmount == null) return "N/A";
                          return `$${detailAmount.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
                        })()}
                      </div>
                      {cdcDetailRecord.usaspending_permalink ? (
                        <a href={cdcDetailRecord.usaspending_permalink} target="_blank" rel="noreferrer">
                          Open USAspending record
                        </a>
                      ) : null}
                    </div>
                  ) : (
                    <div style={{ color: "#64748b" }}>No detail available for this record.</div>
                  )}
                </div>
              ) : null}
            </div>
          </>
        ) : null}

        <div
          style={{
            marginTop: 12,
            paddingTop: 10,
            borderTop: "1px solid #e2e8f0",
            display: "grid",
            gap: 6,
          }}
        >
          {selectedProps ? (
            <>
              {isHpsaDataSource ? (
                <>
                  {selectedGeoLevel !== "county" ? (
                    <div style={{ color: "#64748b" }}>Select a county to view HPSA details.</div>
                  ) : (
                    <div style={{ display: "grid", gap: 10 }}>
                      <div style={{ fontWeight: 700, fontSize: 14 }}>
                        Healthcare Access — {hpsaDomainLabel}
                      </div>
                      <div style={{ color: "#475569" }}>{hpsaCountyStateLine}</div>

                      {isHpsaDomainDetailsLoading ? (
                        <div style={{ color: "#64748b" }}>Loading county details...</div>
                      ) : hpsaDomainDetailsError ? (
                        <div style={{ color: "#b91c1c" }}>{hpsaDomainDetailsError}</div>
                      ) : (
                        <>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                            {hpsaSeverityBadgeLabel ? (
                              <span
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  padding: "2px 10px",
                                  borderRadius: 999,
                                  background: hpsaSeverityBadgeStyle?.background ?? "#B8C2CC",
                                  border: `1px solid ${hpsaSeverityBadgeStyle?.border ?? "#94A3B8"}`,
                                  fontWeight: 700,
                                  color: hpsaSeverityBadgeStyle?.color ?? "#0F172A",
                                  fontSize: 11,
                                }}
                              >
                                {hpsaSeverityBadgeLabel}
                              </span>
                            ) : null}
                            <span style={{ fontWeight: 700 }}>
                              {hpsaSeverityLine}
                            </span>
                          </div>
                          <div style={{ color: "#475569" }}>
                            Federally designated HPSA: {hpsaIsDesignated ? "Yes" : "No"}
                            {!hpsaIsDesignated ? " (Not designated)" : ""}
                          </div>
                          {hpsaIsDesignated ? (
                            <div style={{ color: "#475569" }}>HPSA score: {hpsaSelectedScoreText}</div>
                          ) : null}

                          {hpsaIsDesignated ? (
                            <div style={{ display: "grid", gap: 4 }}>
                              <div style={{ fontWeight: 600 }}>What this means</div>
                              <ul style={{ margin: 0, paddingLeft: 18, color: "#334155" }}>
                                {hpsaWhatThisMeansLines.map((line) => (
                                  <li key={line}>{line}</li>
                                ))}
                              </ul>
                            </div>
                          ) : (
                            <div style={{ color: "#334155" }}>{hpsaWhatThisMeansLines[0]}</div>
                          )}

                          {hpsaHasProviderSection ? (
                            <div style={{ display: "grid", gap: 4 }}>
                              <div style={{ fontWeight: 600 }}>Provider availability</div>
                              {hpsaDomainDetails?.hpsa_formal_ratio ? (
                                <div>
                                  Population-to-provider ratio: {hpsaProviderRatioText}
                                </div>
                              ) : null}
                              {hpsaDomainDetails?.provider_ratio_goal ? (
                                <div>
                                  Federal goal: {hpsaProviderGoalText}
                                </div>
                              ) : null}
                              {toFiniteNumericValue(hpsaDomainDetails?.fte) != null ? (
                                <div>Provider FTE: {hpsaSelectedFteText}</div>
                              ) : null}
                              <div style={{ color: "#64748b" }}>
                                A higher ratio generally means fewer providers relative to the population.
                              </div>
                            </div>
                          ) : null}

                          {hpsaHasPopulationSection ? (
                            <div style={{ display: "grid", gap: 4 }}>
                              <div style={{ fontWeight: 600 }}>Population impact</div>
                              <div>Population covered: {hpsaPopulationCoveredText}</div>
                              <div>Coverage: {hpsaCoveragePercentText} of county population</div>
                              {hpsaCoverageInterpretationLine ? (
                                <div style={{ color: "#64748b" }}>{hpsaCoverageInterpretationLine}</div>
                              ) : null}
                            </div>
                          ) : null}

                          <div style={{ display: "grid", gap: 4, color: "#64748b", fontSize: 11 }}>
                            <div style={{ fontWeight: 600, color: "#475569" }}>How severity is defined</div>
                            <div>Quartiles among designated counties (n={hpsaQuartiles?.n_counties ?? 0}).</div>
                            {hpsaTierRanges.map((tierRange) => (
                              <div key={`hpsa-tier-definition-${tierRange.tier}`}>
                                {tierRange.tierMeta}: {tierRange.rangeLabel}
                              </div>
                            ))}
                            <div>As of: {hpsaAsOfText ? String(hpsaAsOfText) : "Unknown"}</div>
                          </div>

                          <div style={{ color: "#64748b", fontSize: 11 }}>
                            Data Notes: how these values are calculated
                          </div>
                          <details>
                            <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                              Data Notes
                            </summary>
                            <div style={{ marginTop: 4, color: "#334155", display: "grid", gap: 4 }}>
                              <div>Source: {hpsaDataNoteSource}</div>
                              <div>As-of date: {hpsaAsOfText ? String(hpsaAsOfText) : "Unknown"}</div>
                              <div>Denominator type: {hpsaDenominatorTypeText}</div>
                              <div>Denominator value: {hpsaDenominatorValueText}</div>
                              <div>Denominator source: {hpsaDenominatorSourceText}</div>
                              <div>Calculation: {hpsaDataNoteCalculation}</div>
                              <div>{hpsaDataNoteCaveat}</div>
                            </div>
                          </details>
                        </>
                      )}
                    </div>
                  )}
                </>
              ) : null}
              {selectedGeoLevel === "county" && !isHpsaDataSource && !isCmsDataSource ? (
                <div
                  style={{
                    marginTop: 6,
                    paddingTop: 8,
                    borderTop: "1px solid #e2e8f0",
                    display: "grid",
                    gap: 4,
                  }}
                >
                  <div style={{ fontWeight: 600 }}>HPSA county coverage</div>
                  {isHpsaLoading ? (
                    <div style={{ color: "#64748b" }}>Loading HPSA summary...</div>
                  ) : hpsaError ? (
                    <div style={{ color: "#b91c1c" }}>{hpsaError}</div>
                  ) : hpsaSummary ? (
                    <>
                      <div>Primary Care coverage: {hpsaPcCoverageText}</div>
                      <div>Mental Health coverage: {hpsaMhCoverageText}</div>
                      <div>Dental Health coverage: {hpsaDhCoverageText}</div>
                      <details>
                        <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                          Data Notes
                        </summary>
                        <div style={{ marginTop: 4, color: "#334155", display: "grid", gap: 4 }}>
                          <div>Source: {hpsaDataNoteSource}</div>
                          <div>As-of date: {hasText(hpsaDataNoteAsOf) ? String(hpsaDataNoteAsOf) : "Unknown"}</div>
                          <div>
                            Denominator: {hpsaDenominatorTypeText} ({hpsaDenominatorValueText})
                          </div>
                          <div>
                            Population covered aggregation:{" "}
                            {hpsaAggregationMethodText} (conservative)
                          </div>
                          <div>{hpsaDataNoteCaveat}</div>
                        </div>
                      </details>
                    </>
                  ) : (
                    <div style={{ color: "#64748b" }}>No HPSA summary available for this county.</div>
                  )}
                </div>
              ) : null}
              {historySupported ? (
                <button
                  type="button"
                  onClick={handleToggleHistoryClick}
                  className="chip-secondary-btn"
                  style={{ marginTop: 4, width: "fit-content" }}
                >
                  {historyOpen ? "Hide history" : "Show history"}
                </button>
              ) : null}

              {historySupported && historyOpen ? (
                <div
                  style={{
                    marginTop: 6,
                    paddingTop: 8,
                    borderTop: "1px solid #e2e8f0",
                    display: "grid",
                    gap: 4,
                  }}
                >
                  <div style={{ fontWeight: 600 }}>
                    {tractsActive ? "Tract" : "County"} history
                  </div>
                  <div>
                    Measure:{" "}
                    {historyMeta?.measure ??
                      selectedMeasure?.measure ??
                      selectedMeasureId}
                  </div>
                  <div>
                    Data value type: {formatDataValueTypeLabel(
                      historyMeta?.data_value_type ?? selectedType
                    )}
                  </div>
                  {isHistoryLoading ? (
                    <div style={{ color: "#64748b" }}>Loading history...</div>
                  ) : null}
                  {historyError ? (
                    <div style={{ color: "#b91c1c" }}>{historyError}</div>
                  ) : null}
                  {!isHistoryLoading && !historyError ? (
                    <>
                      <MiniHistoryChart
                        series={historySeries}
                        startYear={HISTORY_START_YEAR}
                        endYear={HISTORY_END_YEAR}
                        yLabel="Value"
                      />
                      <div style={{ fontSize: 11, color: "#64748b" }}>
                        {historySeries.map((point) => (
                          <span
                            key={`history-summary-${point.year}`}
                            style={{ marginRight: 8, display: "inline-block" }}
                          >
                            {point.year}: {formatValue(point.value)}
                          </span>
                        ))}
                      </div>
                    </>
                  ) : null}
                </div>
              ) : null}
            </>
          ) : (
            <div style={{ color: "#64748b" }}>Click a {currentLayerLabel}.</div>
          )}
        </div>
          </>
        ) : null}
      </div>

      <AskMapChat
        assistantInput={assistantInput}
        assistantMessages={assistantMessages}
        assistantLoading={assistantLoading}
        scrollSignal={assistantScrollSignal}
        openSignal={assistantOpenSignal}
        compactLayout={compactOverlayLayout}
        onAssistantInputChange={setAssistantInput}
        onAssistantSubmit={handleAssistantSubmit}
        onOpenProfile={openProfilePanel}
      />

      <FullProfilePanel
        apiBase={API_BASE}
        profileId={activeProfileId}
        open={profilePanelOpen}
        onClose={() => setProfilePanelOpen(false)}
      />
      </div>
    </div>
  );
}
