import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  GeoJSON,
  MapContainer,
  Pane,
  TileLayer,
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

const API_BASE = "http://localhost:8000";
const DATA_SOURCES = {
  PLACES: "places",
  ACS_NMF: "acs_nmf",
  SVI: "svi",
  HPSA: "hpsa",
  CMS: "cms",
};
const DEFAULT_SVI_YEAR = 2022;
const SVI_FALLBACK_YEARS = [2022, 2020, 2018];
const HEADER_HEIGHT = 56;
const DEFAULT_CENTER = [39.5, -98.35];
const DEFAULT_ZOOM = 4;
const TRACT_ZOOM = 10;
const COUNTY_RELOAD_ZOOM = 8;
const BBOX_PRECISION = 4;
const BIN_COUNT = 5;
const COLORS = ["#F2FBFB", "#AADDDD", "#7FCACB", "#42A6A8", "#0F2D46"];
const NO_DATA_COLOR = "#DDE5EB";
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
const VIEWPORT_DEBOUNCE_MS = 200;
const HISTORY_START_YEAR = 2018;
const HISTORY_END_YEAR = 2023;
const ASSISTANT_POST_CONTEXT_ACTION_DELAY_MS = 200;
const ASSISTANT_STREAM_CHUNK_CHARS = 4;
const ASSISTANT_STREAM_INTERVAL_MS = 18;
const ANALYSIS_PROMPT_PATTERN = /\b(analy[sz]e|analysis|full profile|profile)\b/i;

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
  return properties.locationid ?? properties.location_id ?? properties.geoid ?? "Unknown";
}

function getFeatureLocationId(properties) {
  if (!properties) return null;
  const locationId = properties.locationid ?? properties.location_id ?? properties.geoid ?? null;
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

function getMeasureDisplayName(measure) {
  if (!measure) return "";
  return measure.name ?? measure.measure ?? measure.short_question_text ?? measure.measure_id ?? "";
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

function MapToolbar({
  defaultCenter,
  defaultZoom,
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
  const [isLegendLoading, setIsLegendLoading] = useState(false);
  const [hpsaChoropleth, setHpsaChoropleth] = useState(null);
  const [isHpsaChoroplethLoading, setIsHpsaChoroplethLoading] = useState(false);
  const [hpsaChoroplethError, setHpsaChoroplethError] = useState(null);

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
        : "places";
  const historySupported = selectedDataSource === DATA_SOURCES.PLACES;
  const tractsActive = !isHpsaDataSource && !isCmsDataSource && mapZoom >= TRACT_ZOOM;
  const activeGeography = tractsActive ? "tract" : "county";
  const acsGeography = isAcsDataSource && tractsActive ? "tract" : "county";
  const selectedTemporalValue = isHpsaDataSource
    ? selectedHpsaDomain
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
  const selectedMeasure = measures.find(
    (measure) => measure.measure_id === selectedMeasureId
  );
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
  const placesMeasureGroups = useMemo(() => {
    if (!isPlacesDataSource) return [];
    const grouped = new Map();
    for (const measure of measures ?? []) {
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
        measures: [...groupMeasures].sort((left, right) => {
          const leftLabel = getMeasureDisplayName(left);
          const rightLabel = getMeasureDisplayName(right);
          return String(leftLabel).localeCompare(String(rightLabel));
        }),
      }));
  }, [isPlacesDataSource, measures]);
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
    if (isAcsDataSource || isSviDataSource || isHpsaDataSource || isCmsDataSource) return;
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
    selectedMeasureId,
    selectedType,
    selectedYear,
  ]);

  const activeGeojson = tractsActive ? tractGeojson : countyGeojson;
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
  const sviBins = useMemo(() => getSviBins(), []);

  const breaks = useMemo(() => {
    if (isSviDataSource) {
      return [];
    }
    if (isCmsDataSource) {
      return cmsBreaks;
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
  }, [acsLegend, cmsBreaks, computedBreaks, isAcsDataSource, isCmsDataSource, isSviDataSource, tractsActive]);
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
        : DATA_SOURCES.PLACES;
    const cachedMeasures = measuresCacheRef.current.get(sourceKey);
    let endpoint = "/measures";
    if (source === DATA_SOURCES.ACS_NMF) {
      endpoint = acsGeography === "tract" ? "/acs-nmf/tracts/measures" : "/acs-nmf/measures";
    } else if (source === DATA_SOURCES.SVI) {
      endpoint = `/svi/measures?geography_level=${activeGeography}&year=${selectedSviYear}`;
    }

    const applyMeasureDefaults = (nextMeasures) => {
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
        const list = Array.isArray(data) ? data : [];
        let sorted = [];
        if (source === DATA_SOURCES.CMS) {
          sorted = buildCmsCuratedMeasures(list);
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
        measuresCacheRef.current.set(sourceKey, taggedMeasures);
        setMeasures(taggedMeasures);
        applyMeasureDefaults(taggedMeasures);
      })
      .catch((errorResponse) => {
        if (!isMounted) return;
        if (source === DATA_SOURCES.CMS) {
          const fallbackCmsMeasures = tagMeasuresForSource(buildCmsCuratedMeasures([]), source);
          measuresCacheRef.current.set(sourceKey, fallbackCmsMeasures);
          setMeasures(fallbackCmsMeasures);
          applyMeasureDefaults(fallbackCmsMeasures);
        }
        setError(errorResponse.message ?? "Failed to load measures.");
      });

    return () => {
      isMounted = false;
    };
  }, [acsGeography, activeGeography, selectedDataSource, selectedSviYear]);

  useEffect(() => {
    if (selectedDataSource === DATA_SOURCES.HPSA) {
      setIsYearsLoading(false);
      setYearsError(null);
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
      isAcsMeasureSelected,
      loadCmsSelectionData,
      syncHpsaMetadataFromCountyPayload,
      selectedHpsaDomain,
      selectedCmsAgeLevel,
      selectedMeasureId,
      selectedSviYear,
      selectedYear,
      selectedYearWindow,
      selectedType,
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
      isAcsMeasureSelected,
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
    // Clear currently-displayed geojson so the map updates for the new measure
    setCountyGeojson(null);
    setTractGeojson(null);
    setCountyBoundaryOverlay(null);
    setStateBoundaryOverlay(null);
    setAcsLegend(null);
    setHpsaChoropleth(null);
    setHpsaChoroplethError(null);
    setIsHpsaChoroplethLoading(false);
    setHistoryOpen(false);
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
      // Fetch tracts + county boundary overlay
      
      // Tracts
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
        
        // Check cache first
        const cachedTractData = getCached(tractKey);
        if (cachedTractData) {
          setTractGeojson(cachedTractData);
          // Background refresh
          fetchWithDedupe(tractKey, async () => {
            try {
              const data = await fetchTractsForBbox(bbox);
              if (latestTractReqRef.current === tractReqId) {
                setCached(tractKey, data);
                setTractGeojson(data);
              }
            } catch (err) {
              if (latestTractReqRef.current === tractReqId) {
                if (isAbortLikeError(err)) {
                  return;
                }
                console.error("Tract background refresh failed:", err);
              }
            }
          }).catch(() => {
            // Ignore errors in background refresh
          });
        } else {
          // No cache, do a for-real fetch (with loading state)
          setIsTractLoading(true);
          
          fetchWithDedupe(tractKey, async () => {
            try {
              const data = await fetchTractsForBbox(bbox);
              if (latestTractReqRef.current === tractReqId) {
                setCached(tractKey, data);
                setTractGeojson(data);
                setError(null);
              }
            } catch (err) {
              if (latestTractReqRef.current === tractReqId) {
                if (isAbortLikeError(err)) {
                  return;
                }
                console.error(err);
                setError(err.message ?? "Failed to load tract map data.");
              }
            } finally {
              if (latestTractReqRef.current === tractReqId) {
                setIsTractLoading(false);
              }
            }
          }).catch(() => {
            // Ignore
          });
        }
      }
      
      // County boundary overlay
      {
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
    syncHpsaMetadataFromCountyPayload,
    isAcsMeasureSelected,
    selectedMeasureId,
    selectedTemporalValue,
    selectedType,
    selectedYear,
    setCached,
    tractsActive,
  ]);

  const choroplethStyle = useCallback(
    (feature) => {
      const value = getValueFromProperties(feature?.properties);
      let fillColor = getColor(value, breaks);
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
      }
      return {
        color: tractsActive ? "#334155" : "#555",
        weight: tractsActive ? 0.6 : 1,
        fillColor,
        fillOpacity: isHpsaDataSource ? 0.78 : 0.72,
      };
    },
    [breaks, isHpsaDataSource, isSviDataSource, sviBins, tractsActive]
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
    layer.setStyle({ color: "orange", weight: 2.5 });
  }, []);

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
      if (!featureProps || tractsActive) {
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

      if (isCmsDataSource) {
        const cmsUnitType = getCmsUnitType(selectedMeasure);
        const cmsValueText = Boolean(featureProps?.cms_is_suppressed)
          ? "Not shown"
          : formatCmsValue(featureProps?.cms_value, cmsUnitType, { includeUnits: true });
        const cmsYearText = String(featureProps?.year ?? selectedYear ?? "").trim() || "N/A";
        return `${countyLine}<br/>${cmsValueText}<br/>Medicare Fee-for-Service • ${cmsYearText}`;
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
      isCmsDataSource,
      isHpsaDataSource,
      isSviDataSource,
      selectedHpsaDomain,
      selectedMeasure,
      selectedMeasureId,
      selectedSviYear,
      selectedType,
      selectedYear,
      selectedYearWindow,
      tractsActive,
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
          layer.setStyle({ weight: tractsActive ? 1.2 : 2, color: "#0f172a" });
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
    [applySelectedStyle, buildCountyHoverTooltipHtml, handleFeatureClick, tractsActive]
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

  const currentLayerLabel = tractsActive ? "tract" : "county";
  const zoomToSelectedLabel = tractsActive
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
  const selectedGeoLevel = String(
    firstDefined(selectedFeatureProps?.geo_level, tractsActive ? "tract" : "county")
  ).toLowerCase() === "tract"
    ? "tract"
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
    : isSviDataSource
      ? getSviLabel(selectedMeasureId)
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
    selectedFeatureProps?.locationid
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
          : parseYearFromToken(selectedYear);
    const resolvedYear = defaultYear ?? 0;
    const resolvedMeasureId = isAcsDataSource
      ? (selectedMeasureId || "ACS")
      : isSviDataSource
        ? (selectedMeasureId || "RPL_THEMES")
        : isHpsaDataSource
          ? "HPSA"
          : (selectedMeasureId || "PLACES");
    const resolvedType = isAcsDataSource
      ? (selectedType || "Percent")
      : isSviDataSource
        ? "Rank"
        : isHpsaDataSource
          ? (selectedHpsaDomain || "pc")
          : isCmsDataSource
            ? selectedCmsAgeLevel
          : (selectedType || "CrdPrv");

    return {
      measure_id: resolvedMeasureId,
      year: resolvedYear,
      data_value_type_id: resolvedType,
      zoom: mapZoom,
      bbox,
      active_layer: tractsActive ? "tract" : "county",
    };
  }, [
    bbox,
    isAcsDataSource,
    isCmsDataSource,
    isHpsaDataSource,
    isSviDataSource,
    mapZoom,
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
	    isHpsaDataSource,
	    isSviDataSource,
	    mapZoom,
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

    const targetZoom = tractsActive ? 10.0 : 9.0;
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
    selectedLocationId,
    selectedProps,
    selectActiveFeatureByLocationId,
    tractsActive,
  ]);

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
    cmsUnitType,
    hpsaTierRanges,
    isAcsDataSource,
    isCmsDataSource,
    isHpsaDataSource,
    isSviDataSource,
    sviBins,
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
  const legendTitle = isHpsaDataSource
    ? `Healthcare Access — ${hpsaDomainLabel}`
    : isSviDataSource
      ? (selectedMeasureDisplayName || selectedMeasureId)
      : isCmsDataSource
        ? (selectedMeasureDisplayName || selectedMeasureId)
      : `${formatDataValueTypeLabel(selectedType)} \u2013 ${
        tractsActive ? "Census Tract Level" : "County Level"
      }`;
  const legendSubtitle = isHpsaDataSource
    ? "County-only HPSA choropleth"
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
          Measure controls {isCountyLoading || isTractLoading ? "- Loading..." : ""}
        </div>
        {!isMeasurePanelMinimized ? (
          <>
            {error ? <div style={{ color: "#b91c1c", fontWeight: 600 }}>{error}</div> : null}
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontWeight: 600 }}>Data source</span>
              <select
                value={selectedDataSource}
                onChange={(event) => {
                  setSelectedDataSource(event.target.value);
                  setSelectedMeasureId("");
                }}
                style={controlSelectStyle}
              >
                <option value={DATA_SOURCES.PLACES}>PLACES (modeled health estimates)</option>
                <option value={DATA_SOURCES.CMS}>CMS (Medicare Fee-for-Service)</option>
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
                ) : isPlacesDataSource ? (
                  placesMeasureGroups.map((group) => (
                    <optgroup key={`places-${group.category}`} label={group.category}>
                      {group.measures.map((measure) => {
                        const label = getMeasureDisplayName(measure);
                        const optionLabel = `${measure.measure_id}${label ? ` - ${label}` : ""}`;
                        return (
                          <option key={measure.measure_id} value={measure.measure_id}>
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
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
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

          {activeGeojson ? (
            <GeoJSON
              key={`${selectedDataSource}-${tractsActive ? "tracts" : "counties"}-${selectedTemporalValue}-${selectedMeasureId}-${selectedType}-${bbox ?? "no-bbox"}-${tractsActive ? "tract" : `county-${countyReloadNonce}`}`}
              ref={geoJsonRef}
              data={activeGeojson}
              style={choroplethStyle}
              onEachFeature={handleEachFeature}
            />
          ) : null}

          {tractsActive && countyBoundaryOverlay ? (
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

          {!tractsActive && stateBoundaryOverlay ? (
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

      {isCountyLoading || isTractLoading || isHpsaChoroplethLoading ? (
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
          {legendRows.length > 0
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
              || isHpsaChoroplethLoading
              || (isAcsDataSource && isLegendLoading)
              ? "Loading..."
              : "Legend unavailable."}
	          {!isHpsaDataSource ? (
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
