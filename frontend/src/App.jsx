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

const API_BASE = "http://localhost:8000";
const DEFAULT_CENTER = [39.5, -98.35];
const DEFAULT_ZOOM = 4;
const TRACT_ZOOM = 10;
const COUNTY_RELOAD_ZOOM = 8;
const BBOX_PRECISION = 4;
const BIN_COUNT = 5;
const COLORS = ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"];
const NO_DATA_COLOR = "#eee";
const STATE_BORDER_COLOR = "#4c1d95";
const FALLBACK_YEARS = [2023];
const CACHE_TTL_MS = 10 * 60 * 1000; // 10 minutes
const VIEWPORT_DEBOUNCE_MS = 200;
const HISTORY_START_YEAR = 2018;
const HISTORY_END_YEAR = 2023;
const ASSISTANT_POST_CONTEXT_ACTION_DELAY_MS = 200;
const ASSISTANT_STREAM_CHUNK_CHARS = 4;
const ASSISTANT_STREAM_INTERVAL_MS = 18;

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

function MapToolbar({ defaultCenter, defaultZoom }) {
  const map = useMap();

  return (
    <div
      style={{
        position: "absolute",
        top: 16,
        left: 16,
        zIndex: 2200,
        display: "grid",
        gap: 8,
      }}
    >
      <button
        type="button"
        onClick={() => map.setView(defaultCenter, defaultZoom)}
        style={{
          padding: "8px 10px",
          borderRadius: 8,
          border: "1px solid #cbd5e1",
          background: "white",
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        Home
      </button>
      <button
        type="button"
        onClick={() => map.zoomIn()}
        style={{
          padding: "8px 10px",
          borderRadius: 8,
          border: "1px solid #cbd5e1",
          background: "white",
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        Zoom In
      </button>
      <button
        type="button"
        onClick={() => map.zoomOut()}
        style={{
          padding: "8px 10px",
          borderRadius: 8,
          border: "1px solid #cbd5e1",
          background: "white",
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        Zoom Out
      </button>
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

  const [measures, setMeasures] = useState([]);
  const [selectedMeasureId, setSelectedMeasureId] = useState("CASTHMA");
  const [years, setYears] = useState([]);
  const [selectedYear, setSelectedYear] = useState(null);
  const [selectedType, setSelectedType] = useState("CrdPrv");
  const [isYearsLoading, setIsYearsLoading] = useState(true);
  const [yearsError, setYearsError] = useState(null);

  const [mapZoom, setMapZoom] = useState(DEFAULT_ZOOM);
  const [bbox, setBbox] = useState(null);

  const [countyGeojson, setCountyGeojson] = useState(null);
  const [tractGeojson, setTractGeojson] = useState(null);
  const [countyBoundaryOverlay, setCountyBoundaryOverlay] = useState(null);
  const [stateBoundaryOverlay, setStateBoundaryOverlay] = useState(null);

  const [selectedProps, setSelectedProps] = useState(null);
  const [hoveredProps, setHoveredProps] = useState(null);
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

  const geoJsonRef = useRef(null);
  const selectedLayerRef = useRef(null);
  const zoomToSelectedButtonRef = useRef(null);
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

  const tractsActive = mapZoom >= TRACT_ZOOM;
  const selectedMeasure = measures.find(
    (measure) => measure.measure_id === selectedMeasureId
  );

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

  const breaks = useMemo(() => {
    return computeBreaks(
      activeFeatures.map((feature) => getValueFromProperties(feature.properties))
    );
  }, [activeFeatures]);

  useEffect(() => {
    let isMounted = true;

    fetch(`${API_BASE}/measures`)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Failed to load measures.");
        }
        return response.json();
      })
      .then((data) => {
        if (!isMounted) return;
        const byId = new Map();
        for (const measure of data) {
          if (!byId.has(measure.measure_id)) {
            byId.set(measure.measure_id, measure);
          }
        }
        const sorted = Array.from(byId.values()).sort((a, b) => {
          const labelA = (a.measure ?? a.short_question_text ?? "").toLowerCase();
          const labelB = (b.measure ?? b.short_question_text ?? "").toLowerCase();
          return labelA.localeCompare(labelB);
        });
        setMeasures(sorted);
      })
      .catch((errorResponse) => {
        if (!isMounted) return;
        setError(errorResponse.message ?? "Failed to load measures.");
      });

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    let isMounted = true;
    setIsYearsLoading(true);
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
  }, [tractsActive]);

  const fetchCountyChoropleth = useCallback(
    async (bboxValue) => {
      const url = new URL(`${API_BASE}/counties/boundaries/geojson/estimates`);
      url.searchParams.set("measure_id", selectedMeasureId);
      url.searchParams.set("year", String(selectedYear));
      url.searchParams.set("data_value_type_id", selectedType);
      url.searchParams.set("bbox", bboxValue);

      // Abort previous request if any
      if (countyAbortRef.current) {
        countyAbortRef.current.abort();
      }
      const controller = new AbortController();
      countyAbortRef.current = controller;

      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) {
        const body = await parseErrorBody(response);
        throw new Error(`County request failed (${response.status}): ${body}`);
      }
      return response.json();
    },
    [selectedMeasureId, selectedYear, selectedType]
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

  const fetchTractsForBbox = useCallback(
    async (bboxValue) => {
      if (!bboxValue) {
        throw new Error("bbox is required for tract requests.");
      }

      // Abort previous request if any
      if (tractAbortRef.current) {
        tractAbortRef.current.abort();
      }
      const controller = new AbortController();
      tractAbortRef.current = controller;

      const url = new URL(`${API_BASE}/geojson/tracts`);
      url.searchParams.set("year", String(selectedYear));
      url.searchParams.set("measure_id", selectedMeasureId);
      url.searchParams.set("data_value_type_id", selectedType);
      url.searchParams.set("bbox", bboxValue);

      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) {
        const body = await parseErrorBody(response);
        throw new Error(`Tract request failed (${response.status}): ${body}`);
      }
      return response.json();
    },
    [selectedMeasureId, selectedYear, selectedType]
  );

  // Clear cache when measure/year/type changes
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
    // Keep selection across measure/year/type changes; only clear transient hover state.
    setHoveredProps(null);
    if (pendingCountySelectionTimerRef.current) {
      clearTimeout(pendingCountySelectionTimerRef.current);
      pendingCountySelectionTimerRef.current = null;
    }
    pendingCountySelectionRef.current = null;
  }, [selectedMeasureId, selectedYear, selectedType]);

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
    if (!bbox || selectedYear == null || mapZoom !== TRACT_ZOOM - 1) {
      return;
    }

    const key = makeCacheKey("tracts", selectedYear, selectedMeasureId, selectedType, bbox);
    
    fetchWithDedupe(key, async () => {
      try {
        const data = await fetchTractsForBbox(bbox);
        setCached(key, data);
      } catch (prefetchError) {
        console.warn("Tract prefetch failed:", prefetchError);
      }
    }).catch(() => {
      // Silently ignore prefetch errors
    });
  }, [bbox, mapZoom, selectedMeasureId, selectedYear, selectedType, fetchTractsForBbox, fetchWithDedupe, setCached]);

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
          console.error("State boundary fetch failed:", err);
        }
      }
    }).catch(() => {
      // Ignore
    });
  }, [tractsActive, fetchStateBoundaryOverlay, getCached, setCached, fetchWithDedupe]);

  // Main data-fetching effect with caching, deduping, and stale-while-revalidate
  useEffect(() => {
    if (!bbox || selectedYear == null) {
      return;
    }

    if (tractsActive) {
      // Fetch tracts + county boundary overlay
      
      // Tracts
      {
        const tractReqId = latestTractReqRef.current + 1;
        latestTractReqRef.current = tractReqId;
        
        const tractKey = makeCacheKey("tracts", selectedYear, selectedMeasureId, selectedType, bbox);
        
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
        
        const outlineKey = makeCacheKey("countyOutline", selectedYear, selectedMeasureId, selectedType, bbox);
        
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
        "counties",
        selectedYear,
        selectedMeasureId,
        selectedType,
        bbox
      )}|reload:${countyReloadNonce}`;
      
      // Check cache first
      const cachedCountyData = getCached(countyKey);
      if (cachedCountyData) {
        setCountyGeojson(cachedCountyData);
        setCountyBoundaryOverlay(null);
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
  }, [bbox, tractsActive, selectedMeasureId, selectedYear, selectedType, countyReloadNonce, fetchCountyChoropleth, fetchCountyBoundaryOverlay, fetchTractsForBbox, getCached, setCached, fetchWithDedupe]);

  const choroplethStyle = useCallback(
    (feature) => {
      const value = getValueFromProperties(feature?.properties);
      const fillColor = getColor(value, breaks);
      return {
        color: tractsActive ? "#334155" : "#555",
        weight: tractsActive ? 0.6 : 1,
        fillColor,
        fillOpacity: 0.72,
      };
    },
    [breaks, tractsActive]
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
      const shouldOpenHistory = options.openHistory !== false;
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
      }
      applySelectedStyle(layer);
    },
    [applySelectedStyle]
  );

  const handleEachFeature = useCallback(
    (feature, layer) => {
      layer.on("click", () => {
        handleFeatureClick(feature, layer, { openHistory: true });
      });
      layer.on("mouseover", () => {
        setHoveredProps(feature.properties);
        if (selectedLayerRef.current !== layer) {
          layer.setStyle({ weight: tractsActive ? 1.2 : 2, color: "#0f172a" });
        }
      });
      layer.on("mouseout", () => {
        setHoveredProps(null);
        if (selectedLayerRef.current === layer) {
          applySelectedStyle(layer);
        } else if (geoJsonRef.current) {
          geoJsonRef.current.resetStyle(layer);
        }
      });
    },
    [handleFeatureClick, applySelectedStyle, tractsActive]
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
      selectCountyFeatureByFips(countyFips, { openHistory: true });
      if (pendingCountySelectionTimerRef.current) {
        clearTimeout(pendingCountySelectionTimerRef.current);
      }
      pendingCountySelectionTimerRef.current = setTimeout(() => {
        pendingCountySelectionRef.current = null;
        pendingCountySelectionTimerRef.current = null;
        pendingAssistantCountyZoomRef.current = false;
      }, 10000);
    },
    [selectCountyFeatureByFips]
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
      if (!trimmedInput || selectedYear == null) return;

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
              measure_id: selectedMeasureId,
              year: selectedYear,
              data_value_type_id: selectedType,
              zoom: mapZoom,
              bbox,
              active_layer: tractsActive ? "tract" : "county",
            },
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

        const answerMarkdown = typeof resp?.answer_markdown === "string"
          ? resp.answer_markdown
          : "";
        await streamAssistantAnswer(answerMarkdown);
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
      assistantLoading,
      bbox,
      cancelAssistantStream,
      executeAssistantActions,
      mapZoom,
      selectedMeasureId,
      selectedType,
      selectedYear,
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
    if (selectCountyFeatureByFips(pendingCountyFips, { openHistory: true })) {
      pendingCountySelectionRef.current = null;
      if (pendingCountySelectionTimerRef.current) {
        clearTimeout(pendingCountySelectionTimerRef.current);
        pendingCountySelectionTimerRef.current = null;
      }
    }
  }, [activeGeojson, tractsActive, selectCountyFeatureByFips]);

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
        if (controller.signal.aborted) return;
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
    getCached,
    setCached,
  ]);

  const currentLayerLabel = tractsActive ? "tract" : "county";
  const zoomToSelectedLabel = tractsActive
    ? "Zoom to Selected Census Tract"
    : "Zoom to Selected County";
  const selectedFeature = selectedProps ? { properties: selectedProps } : null;
  const selectedFeatureProps = selectedFeature?.properties ?? null;
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
  const measureNameValue = normalizeMeasureName(
    firstDefined(
      selectedFeatureProps?.measure_name,
      selectedFeatureProps?.short_question_text,
      selectedMeasure?.short_question_text,
      selectedMeasure?.measure
    )
  );
  const yearValue = firstDefined(selectedFeatureProps?.year, selectedYear);
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
  const censusProfileHref = hasText(selectedLocationIdForLink)
    ? `https://data.census.gov/profile/${String(selectedLocationIdForLink).trim()}`
    : hasText(selectedLocationNameForLink)
      ? `https://data.census.gov/profile/${encodeURIComponent(
        String(selectedLocationNameForLink).trim()
      )}`
      : "https://data.census.gov/";

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

  return (
    <div
      className="app"
      style={{ position: "relative", height: "100vh", width: "100vw" }}
    >
      <div
        style={{
          position: "absolute",
          top: 16,
          left: 150,
          background: "white",
          padding: "12px 14px",
          borderRadius: 8,
          boxShadow: "0 4px 12px rgba(15, 23, 42, 0.15)",
          fontSize: 12,
          minWidth: 260,
          display: "grid",
          gap: 10,
          zIndex: 2000,
        }}
      >
          <div style={{ fontWeight: 600, fontSize: 13 }}>
            Measure controls {isCountyLoading || isTractLoading ? "- Loading..." : ""}
          </div>
          {error ? <div style={{ color: "#b91c1c", fontWeight: 600 }}>{error}</div> : null}
        <label style={{ display: "grid", gap: 6 }}>
          <span style={{ fontWeight: 600 }}>Measure</span>
          <select
            value={selectedMeasureId}
            onChange={(event) => setSelectedMeasureId(event.target.value)}
            style={{ padding: "6px 8px", borderRadius: 6 }}
          >
            {measures.length === 0 ? (
              <option value={selectedMeasureId}>Loading measures...</option>
            ) : (
              measures.map((measure) => {
                const label = measure.measure ?? measure.short_question_text ?? "";
                return (
                  <option key={measure.measure_id} value={measure.measure_id}>
                    {measure.measure_id}
                    {label ? ` - ${label}` : ""}
                  </option>
                );
              })
            )}
          </select>
        </label>
        <label style={{ display: "grid", gap: 6 }}>
          <span style={{ fontWeight: 600 }}>Year</span>
          <select
            value={selectedYear ?? ""}
            onChange={(event) => setSelectedYear(Number(event.target.value))}
            disabled={isYearsLoading || years.length === 0}
            style={{ padding: "6px 8px", borderRadius: 6 }}
          >
            {isYearsLoading && years.length === 0 ? (
              <option value="">Loading years...</option>
            ) : (
              years.map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))
            )}
          </select>
          {yearsError ? (
            <span style={{ color: "#b91c1c", fontSize: 11 }}>{yearsError}</span>
          ) : null}
        </label>
        <label style={{ display: "grid", gap: 6 }}>
          <span style={{ fontWeight: 600 }}>Data value type</span>
          <select
            value={selectedType}
            onChange={(event) => setSelectedType(event.target.value)}
            style={{ padding: "6px 8px", borderRadius: 6 }}
          >
            <option value="CrdPrv">Crude prevalence (CrdPrv)</option>
            <option value="AgeAdjPrv">Age-adjusted prevalence (AgeAdjPrv)</option>
          </select>
        </label>
        {measures.length === 0 ? null : (
          <div style={{ color: "#475569" }}>
            {selectedMeasure?.measure ?? selectedMeasure?.short_question_text ?? ""}
          </div>
        )}
      </div>

      <div className="map-wrapper" style={{ height: "100%", width: "100%" }}>
          <MapContainer
            center={DEFAULT_CENTER}
            zoom={DEFAULT_ZOOM}
            style={{ height: "100%" }}
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
          <MapToolbar defaultCenter={DEFAULT_CENTER} defaultZoom={DEFAULT_ZOOM} />
          <SearchBar
            apiBase={API_BASE}
            onCountySelected={handleCountySearchSelection}
          />

          {activeGeojson ? (
            <GeoJSON
              key={`${tractsActive ? "tracts" : "counties"}-${selectedYear}-${selectedMeasureId}-${selectedType}-${bbox ?? "no-bbox"}-${tractsActive ? "tract" : `county-${countyReloadNonce}`}`}
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

      {isCountyLoading || isTractLoading ? (
        <div
          style={{
            position: "absolute",
            top: 24,
            right: 24,
            background: "rgba(15, 23, 42, 0.85)",
            color: "white",
            padding: "10px 16px",
            borderRadius: 999,
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: 0.2,
            zIndex: 2100,
          }}
        >
          Loading...
        </div>
      ) : null}

      <div
        style={{
          position: "absolute",
          top: 16,
          right: 16,
          background: "white",
          padding: "12px 14px",
          borderRadius: 8,
          boxShadow: "0 4px 12px rgba(15, 23, 42, 0.15)",
          fontSize: 12,
          minWidth: 210,
          maxHeight: "calc(100vh - 32px)",
          overflowY: "auto",
          zIndex: 2000,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 8 }}>
          Legend ({selectedType}) - {tractsActive ? "Tracts" : "Counties"}
        </div>
        <div style={{ display: "grid", gap: 6 }}>
          {breaks.length > 1
            ? breaks.slice(0, -1).map((start, index) => {
                const end = breaks[index + 1];
                const color = COLORS[index] ?? COLORS[COLORS.length - 1];
                return (
                  <div
                    key={`${start}-${end}`}
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <span
                      style={{
                        width: 12,
                        height: 12,
                        background: color,
                        borderRadius: 2,
                        border: "1px solid #cbd5f5",
                      }}
                    />
                    <span>{formatRange(start, end)}</span>
                  </div>
                );
              })
            : isCountyLoading || isTractLoading
              ? "Loading..."
              : "Legend unavailable."}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span
              style={{
                width: 12,
                height: 12,
                background: NO_DATA_COLOR,
                borderRadius: 2,
                border: "1px solid #cbd5f5",
              }}
            />
            <span>No data</span>
          </div>
        </div>
        {selectedFeature ? (
          <>
            <hr />
            <div className="legend-details">
              <p>
                In this <strong>{selectedGeoLevel}</strong>, the estimated prevalence of{" "}
                <strong>{measureNameValue}</strong> among adults aged 18 years and older
                (%) was <strong>{fmt1(crudeValue)}</strong> with 95% CI (
                <strong>{ciText(crudeLow, crudeHigh)}</strong>), and the age-adjusted
                prevalence (%) was <strong>{fmt1(ageAdjustedValue)}</strong> (
                <strong>{ciText(ageAdjustedLow, ageAdjustedHigh)}</strong>) in{" "}
                <strong>{yearValue ?? "N/A"}</strong>.
              </p>
              <p>
                According to the Census <strong>{yearValue ?? "N/A"}</strong> population
                estimates, <strong>{fmtPop(populationValue)}</strong> adults live in this{" "}
                <strong>{selectedGeoLevel}</strong>.
              </p>
              <p>
                For more demographic, social, and economic data, visit{" "}
                <a href={censusProfileHref} target="_blank" rel="noreferrer">
                  Census County Profile
                </a>
                .
              </p>
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
          <div style={{ fontWeight: 600 }}>Hovered {currentLayerLabel}</div>
          {hoveredProps ? (
            <>
              <div>
                {tractsActive ? getFeatureId(hoveredProps) : getCountyName(hoveredProps)}
              </div>
              <div>State: {hoveredProps.state_abbr ?? "N/A"}</div>
              <div>
                Value: {getValueFromProperties(hoveredProps) ?? "No data"}
              </div>
            </>
          ) : (
            <div style={{ color: "#64748b" }}>Hover a {currentLayerLabel}.</div>
          )}

          <div style={{ fontWeight: 600 }}>Selected {currentLayerLabel}</div>
          {selectedProps ? (
            <>
              <div>
                {tractsActive ? getFeatureId(selectedProps) : getCountyName(selectedProps)}
              </div>
              <div>State: {selectedProps.state_abbr ?? "N/A"}</div>
              <div>
                Value: {getValueFromProperties(selectedProps) ?? "No data"}
              </div>
              <div>Year: {selectedProps.year ?? selectedYear}</div>
              <div>Measure: {selectedProps.measure_id ?? selectedMeasureId}</div>
              <div>
                Data value type: {selectedProps.data_value_type_id ?? selectedType}
              </div>
              <button
                type="button"
                ref={zoomToSelectedButtonRef}
                onClick={handleZoomToSelected}
                style={{
                  marginTop: 4,
                  width: "fit-content",
                  padding: "6px 10px",
                  borderRadius: 6,
                  border: "1px solid #1d4ed8",
                  background: "#eff6ff",
                  color: "#1e40af",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {zoomToSelectedLabel}
              </button>
              <button
                type="button"
                onClick={handleToggleHistoryClick}
                style={{
                  marginTop: 4,
                  width: "fit-content",
                  padding: "6px 10px",
                  borderRadius: 6,
                  border: "1px solid #cbd5e1",
                  background: "#f8fafc",
                  color: "#0f172a",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {historyOpen ? "Hide history" : "Show history"}
              </button>

              {historyOpen ? (
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
                    Data value type: {historyMeta?.data_value_type ?? selectedType}
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
      </div>

      <AskMapChat
        assistantInput={assistantInput}
        assistantMessages={assistantMessages}
        assistantLoading={assistantLoading}
        scrollSignal={assistantScrollSignal}
        onAssistantInputChange={setAssistantInput}
        onAssistantSubmit={handleAssistantSubmit}
      />

      <div
        style={{
          position: "absolute",
          right: 16,
          bottom: 16,
          background: "white",
          padding: "10px 12px",
          borderRadius: 8,
          boxShadow: "0 4px 12px rgba(15, 23, 42, 0.12)",
          fontSize: 12,
          zIndex: 2000,
        }}
      >
        layer={tractsActive ? "tracts + county-lines" : "counties"} - zoom={mapZoom.toFixed(2)} -
        measure_id={selectedMeasureId} - year={selectedYear} - data_value_type_id={selectedType} -
        tract_zoom={TRACT_ZOOM} - highlight_level={highlightedLevel ?? "none"} -
        highlight_geoid={highlightedGeoid ?? "none"}
      </div>
    </div>
  );
}
