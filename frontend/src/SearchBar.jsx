import { useCallback, useEffect, useRef, useState } from "react";
import { useMap } from "react-leaflet";

const SEARCH_DEBOUNCE_MS = 300;
const SUGGESTION_LIMIT = 5;
const COUNTY_SELECTION_ZOOM = 9;
const GEO_SELECTION_ZOOM = 13;

function toCountySuggestion(item) {
  return {
    id: `county-${item.county_fips}`,
    type: "county",
    label: `${item.name}, ${item.state_abbr}`,
    subtitle: `County - ${item.county_fips}`,
    county_fips: item.county_fips,
    bbox: item.bbox,
    centroid: item.centroid,
  };
}

function toGeoSuggestion(item) {
  const lat = Number(item.lat);
  const lon = Number(item.lon);
  return {
    id: `geo-${item.place_id ?? item.display_name}`,
    type: "geo",
    label: item.display_name,
    subtitle: "Address/place",
    lat: Number.isFinite(lat) ? lat : null,
    lon: Number.isFinite(lon) ? lon : null,
    boundingbox: Array.isArray(item.boundingbox) ? item.boundingbox : null,
  };
}

async function fetchCountySuggestions(apiBase, query, signal) {
  const url = new URL(`${apiBase}/search/counties`);
  url.searchParams.set("q", query);
  url.searchParams.set("limit", String(SUGGESTION_LIMIT));

  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`County search failed (${response.status}).`);
  }
  const data = await response.json();
  if (!Array.isArray(data)) return [];
  return data.map(toCountySuggestion);
}

async function fetchGeoSuggestions(query, signal) {
  const url = new URL("https://nominatim.openstreetmap.org/search");
  url.searchParams.set("format", "jsonv2");
  url.searchParams.set("limit", String(SUGGESTION_LIMIT));
  url.searchParams.set("addressdetails", "1");
  url.searchParams.set("countrycodes", "us");
  url.searchParams.set("q", query);

  const response = await fetch(url, {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Geocoder search failed (${response.status}).`);
  }
  const data = await response.json();
  if (!Array.isArray(data)) return [];
  return data.map(toGeoSuggestion);
}

function parseBoundingBox(bounds) {
  if (!Array.isArray(bounds) || bounds.length !== 4) {
    return null;
  }

  const south = Number(bounds[0]);
  const north = Number(bounds[1]);
  const west = Number(bounds[2]);
  const east = Number(bounds[3]);

  if (
    !Number.isFinite(south)
    || !Number.isFinite(north)
    || !Number.isFinite(west)
    || !Number.isFinite(east)
  ) {
    return null;
  }
  if (south >= north || west >= east) {
    return null;
  }

  return { south, north, west, east };
}

function getCenterFromBounds(bounds) {
  if (!bounds) return null;
  return {
    lat: (bounds.south + bounds.north) / 2,
    lon: (bounds.west + bounds.east) / 2,
  };
}

export default function SearchBar({
  apiBase,
  onCountySelected,
  compactLayout = false,
  rightInset = 16,
}) {
  const map = useMap();
  const rootRef = useRef(null);
  const cacheRef = useRef(new Map());
  const abortRef = useRef(null);
  const requestIdRef = useRef(0);
  const toastTimerRef = useRef(null);

  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);

  const showToast = useCallback((message) => {
    setToastMessage(message);
    if (toastTimerRef.current) {
      clearTimeout(toastTimerRef.current);
    }
    toastTimerRef.current = setTimeout(() => {
      setToastMessage(null);
    }, 3500);
  }, []);

  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
      if (toastTimerRef.current) {
        clearTimeout(toastTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const handleDocumentMouseDown = (event) => {
      if (!rootRef.current || rootRef.current.contains(event.target)) {
        return;
      }
      setIsOpen(false);
    };

    document.addEventListener("mousedown", handleDocumentMouseDown);
    return () => {
      document.removeEventListener("mousedown", handleDocumentMouseDown);
    };
  }, []);

  const loadSuggestions = useCallback(
    async (rawQuery, options = {}) => {
      const { openDropdown = true } = options;
      const normalizedQuery = rawQuery.trim().toLowerCase();
      if (!normalizedQuery) {
        setSuggestions([]);
        setIsOpen(false);
        setIsLoading(false);
        return [];
      }

      const cached = cacheRef.current.get(normalizedQuery);
      if (cached) {
        setSuggestions(cached);
        setIsLoading(false);
        if (openDropdown) {
          setIsOpen(true);
        }
        return cached;
      }

      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      setIsLoading(true);

      try {
        const [countyResult, geoResult] = await Promise.allSettled([
          fetchCountySuggestions(apiBase, rawQuery, controller.signal),
          fetchGeoSuggestions(rawQuery, controller.signal),
        ]);

        if (requestIdRef.current !== requestId) {
          return [];
        }

        const countySuggestions = countyResult.status === "fulfilled"
          ? countyResult.value
          : [];
        const geoSuggestions = geoResult.status === "fulfilled"
          ? geoResult.value
          : [];

        if (
          countyResult.status === "rejected"
          && geoResult.status === "rejected"
        ) {
          throw new Error("Search services are unavailable right now.");
        }

        const combined = [...countySuggestions, ...geoSuggestions].slice(
          0,
          SUGGESTION_LIMIT
        );
        cacheRef.current.set(normalizedQuery, combined);
        setSuggestions(combined);
        if (openDropdown) {
          setIsOpen(true);
        }
        return combined;
      } catch (error) {
        if (controller.signal.aborted) {
          return [];
        }
        setSuggestions([]);
        if (openDropdown) {
          setIsOpen(true);
        }
        showToast(error.message ?? "Failed to search.");
        return [];
      } finally {
        if (requestIdRef.current === requestId) {
          setIsLoading(false);
        }
      }
    },
    [apiBase, showToast]
  );

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      if (abortRef.current) {
        abortRef.current.abort();
      }
      setSuggestions([]);
      setIsOpen(false);
      setIsLoading(false);
      return;
    }

    const timer = setTimeout(() => {
      loadSuggestions(trimmed, { openDropdown: true }).catch(() => {
        // Errors are already handled inside loadSuggestions.
      });
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
    };
  }, [query, loadSuggestions]);

  const selectSuggestion = useCallback(
    (suggestion) => {
      if (!suggestion) return;

      setQuery(suggestion.label);
      setIsOpen(false);

      if (suggestion.type === "county") {
        let countyCenter = null;
        if (suggestion.centroid) {
          countyCenter = {
            lat: suggestion.centroid.lat,
            lon: suggestion.centroid.lon,
          };
        } else if (suggestion.bbox) {
          countyCenter = {
            lat: (suggestion.bbox.min_lat + suggestion.bbox.max_lat) / 2,
            lon: (suggestion.bbox.min_lon + suggestion.bbox.max_lon) / 2,
          };
        }
        if (countyCenter) {
          map.setView([countyCenter.lat, countyCenter.lon], COUNTY_SELECTION_ZOOM);
        }
        if (onCountySelected) {
          onCountySelected(suggestion.county_fips);
        }
        return;
      }

      const bbox = parseBoundingBox(suggestion.boundingbox);
      if (Number.isFinite(suggestion.lat) && Number.isFinite(suggestion.lon)) {
        map.setView([suggestion.lat, suggestion.lon], GEO_SELECTION_ZOOM);
      } else if (bbox) {
        const center = getCenterFromBounds(bbox);
        if (center) {
          map.setView([center.lat, center.lon], GEO_SELECTION_ZOOM);
        }
      } else {
        showToast("Selected location has no coordinates.");
      }
    },
    [map, onCountySelected, showToast]
  );

  const handleSubmit = useCallback(
    async (event) => {
      event.preventDefault();
      const trimmed = query.trim();
      if (!trimmed) {
        setIsOpen(false);
        return;
      }

      const immediateSuggestion = isOpen && suggestions.length > 0 ? suggestions[0] : null;
      if (immediateSuggestion) {
        selectSuggestion(immediateSuggestion);
        return;
      }

      const fetchedSuggestions = await loadSuggestions(trimmed, {
        openDropdown: false,
      });
      if (fetchedSuggestions.length > 0) {
        selectSuggestion(fetchedSuggestions[0]);
      } else {
        showToast("No matches found.");
      }
    },
    [isOpen, loadSuggestions, query, selectSuggestion, showToast, suggestions]
  );

  const handleClear = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    requestIdRef.current += 1;
    setQuery("");
    setSuggestions([]);
    setIsOpen(false);
    setIsLoading(false);
  }, []);

  const showEmptyState = isOpen && !isLoading && query.trim().length > 0 && suggestions.length === 0;

  return (
    <div
      ref={rootRef}
      style={{
        position: "absolute",
        left: compactLayout ? 16 : 392,
        right: compactLayout ? 16 : rightInset,
        bottom: 16,
        width: "auto",
        zIndex: 2000,
      }}
    >
      {toastMessage ? (
        <div
          style={{
            position: "absolute",
            left: "50%",
            bottom: 74,
            transform: "translateX(-50%)",
            background: "rgba(127, 29, 29, 0.96)",
            color: "white",
            borderRadius: 8,
            fontSize: 12,
            fontWeight: 600,
            padding: "8px 12px",
            boxShadow: "0 6px 16px rgba(15, 23, 42, 0.32)",
            maxWidth: "90%",
            textAlign: "center",
            whiteSpace: "nowrap",
          }}
        >
          {toastMessage}
        </div>
      ) : null}

      {isOpen ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 58,
            background: "white",
            borderRadius: 10,
            border: "1px solid #E3E8ED",
            boxShadow: "0 6px 20px rgba(15, 45, 70, 0.12)",
            overflow: "hidden",
          }}
        >
          {isLoading ? (
            <div
              style={{
                padding: "12px 14px",
                display: "flex",
                alignItems: "center",
                gap: 10,
                color: "#334155",
                fontSize: 13,
              }}
            >
              <span className="search-spinner" />
              Loading suggestions...
            </div>
          ) : null}

          {!isLoading
            ? suggestions.map((suggestion) => (
              <button
                key={suggestion.id}
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => selectSuggestion(suggestion)}
                className="chip-search-suggestion"
                style={{
                  width: "100%",
                  padding: "10px 14px",
                  textAlign: "left",
                  border: "none",
                  borderBottom: "1px solid #e2e8f0",
                  cursor: "pointer",
                  display: "grid",
                  gap: 2,
                }}
              >
                <span style={{ fontSize: 13, color: "#0f172a" }}>
                  {suggestion.label}
                </span>
                <span style={{ fontSize: 11, color: "#475569" }}>
                  {suggestion.subtitle}
                </span>
              </button>
            ))
            : null}

          {showEmptyState ? (
            <div
              style={{
                padding: "12px 14px",
                color: "#64748b",
                fontSize: 13,
              }}
            >
              No suggestions found.
            </div>
          ) : null}
        </div>
      ) : null}

      <form
        onSubmit={handleSubmit}
        className="chip-search-form"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto auto",
          alignItems: "center",
          gap: 8,
          padding: 8,
          borderRadius: 10,
          border: "1px solid #E3E8ED",
          background: "#ffffff",
          boxShadow: "0 6px 20px rgba(15, 45, 70, 0.12)",
        }}
      >
        <input
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => {
            if (query.trim().length > 0) {
              setIsOpen(true);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setIsOpen(false);
              return;
            }
            if (event.key === "Enter" && isOpen && suggestions.length > 0) {
              event.preventDefault();
              selectSuggestion(suggestions[0]);
            }
          }}
          placeholder="Search address, ZIP, or county (e.g., Fulton County, GA)"
          aria-label="Search address, ZIP, or county"
          style={{
            width: "100%",
            border: "none",
            outline: "none",
            background: "transparent",
            padding: "10px 10px",
            fontSize: 14,
            color: "#0f172a",
          }}
        />

        {query ? (
          <button
            type="button"
            onClick={handleClear}
            aria-label="Clear search"
            style={{
              border: "none",
              background: "rgba(44, 95, 138, 0.12)",
              color: "#2C5F8A",
              width: 28,
              height: 28,
              borderRadius: 999,
              cursor: "pointer",
              fontSize: 14,
              fontWeight: 700,
              lineHeight: "28px",
              padding: 0,
            }}
          >
            x
          </button>
        ) : (
          <span style={{ width: 28, height: 28 }} />
        )}

        <button
          type="submit"
          className="chip-primary-btn"
          style={{
            borderRadius: 8,
            padding: "8px 12px",
            fontSize: 13,
            fontWeight: 600,
            minWidth: 72,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
          }}
        >
          {isLoading ? (
            <span
              className="search-spinner"
              style={{
                borderColor: "rgba(255, 255, 255, 0.45)",
                borderTopColor: "#ffffff",
              }}
            />
          ) : null}
          Search
        </button>
      </form>
    </div>
  );
}
