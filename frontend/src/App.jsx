import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GeoJSON, MapContainer, TileLayer } from "react-leaflet";

const COLORS = ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"];
const NO_DATA_COLOR = "#eee";

function getColor(value, breaks) {
  if (value == null || !Array.isArray(breaks) || breaks.length < 2) {
    return NO_DATA_COLOR;
  }

  const numericValue = Number(value);
  if (Number.isNaN(numericValue)) {
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
  return `${min} – ${max}`;
}

export default function App() {
  const [measures, setMeasures] = useState([]);
  const [selectedMeasureId, setSelectedMeasureId] = useState("CASTHMA");
  const [selectedYear, setSelectedYear] = useState(2023);
  const [selectedType, setSelectedType] = useState("CrdPrv");
  const [legend, setLegend] = useState(null);
  const [geojson, setGeojson] = useState(null);
  const [selectedLocationId, setSelectedLocationId] = useState(null);
  const [selectedProps, setSelectedProps] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const geoJsonRef = useRef(null);
  const selectedLocationIdRef = useRef(null);
  const styleFeatureRef = useRef(null);

  const yearOptions = useMemo(() => {
    // TODO: Derive years from backend data when available.
    return [2023];
  }, []);

  useEffect(() => {
    let isMounted = true;

    fetch("http://localhost:8000/measures")
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
        const deduped = Array.from(byId.values());
        const sorted = deduped.sort((a, b) => {
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
    setIsLoading(true);
    setError(null);
    setSelectedLocationId(null);
    setSelectedProps(null);

    const legendUrl = new URL("http://localhost:8000/legend");
    legendUrl.searchParams.set("measure_id", selectedMeasureId);
    legendUrl.searchParams.set("year", String(selectedYear));
    legendUrl.searchParams.set("data_value_type_id", selectedType);
    legendUrl.searchParams.set("bins", "5");

    const geojsonUrl = new URL(
      "http://localhost:8000/counties/boundaries/geojson/estimates"
    );
    geojsonUrl.searchParams.set("measure_id", selectedMeasureId);
    geojsonUrl.searchParams.set("year", String(selectedYear));
    geojsonUrl.searchParams.set("data_value_type_id", selectedType);

    const fetchLegend = fetch(legendUrl).then(async (response) => {
      if (!response.ok) {
        const body = await response.text();
        throw new Error(
          `Legend request failed (${response.status}): ${body || "No body"}`
        );
      }
      return response.json();
    });
    const fetchGeojson = fetch(geojsonUrl).then(async (response) => {
      if (!response.ok) {
        const body = await response.text();
        throw new Error(
          `Map request failed (${response.status}): ${body || "No body"}`
        );
      }
      return response.json();
    });

    Promise.all([fetchLegend, fetchGeojson])
      .then(([legendData, geojsonData]) => {
        if (!isMounted) return;
        setLegend(legendData);
        setGeojson(geojsonData);
      })
      .catch((errorResponse) => {
        if (!isMounted) return;
        console.error(errorResponse);
        setError(
          errorResponse.message ??
            "Failed to load map data (possible CORS issue)."
        );
      })
      .finally(() => {
        if (!isMounted) return;
        setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [selectedMeasureId, selectedYear, selectedType]);

  useEffect(() => {
    selectedLocationIdRef.current = selectedLocationId;
  }, [selectedLocationId]);

  const breaks = useMemo(() => legend?.breaks ?? [], [legend]);
  const features = geojson?.features ?? [];
  const selectedMeasure = measures.find(
    (measure) => measure.measure_id === selectedMeasureId
  );
  const styleFeature = useCallback(
    (feature) => {
      const value = feature?.properties?.data_value ?? null;
      const fillColor = getColor(value, legend?.breaks ?? []);
      const isSelected =
        feature?.properties?.location_id === selectedLocationId;

      return {
        color: isSelected ? "#000" : "#555",
        weight: isSelected ? 3 : 1,
        fillColor,
        fillOpacity: 0.7,
      };
    },
    [legend?.breaks, selectedLocationId]
  );
  const geoJsonKey = `${selectedMeasureId}-${selectedYear}-${selectedType}`;

  useEffect(() => {
    styleFeatureRef.current = styleFeature;
  }, [styleFeature]);

  const handleEachFeature = useCallback((feature, layer) => {
    layer.on("click", () => {
      setSelectedLocationId(feature.properties.location_id);
      setSelectedProps(feature.properties);
    });
    layer.on("mouseover", () => {
      if (feature.properties.location_id !== selectedLocationIdRef.current) {
        layer.setStyle({ weight: 2, color: "#000" });
      }
    });
    layer.on("mouseout", () => {
      if (styleFeatureRef.current) {
        layer.setStyle(styleFeatureRef.current(feature));
      }
    });
  }, []);

  useEffect(() => {
    if (geoJsonRef.current) {
      geoJsonRef.current.setStyle(styleFeature);
    }
  }, [styleFeature]);

  useEffect(() => {
    const gj = geoJsonRef.current;
    if (!gj) return;
    gj.eachLayer((layer) => {
      if (layer?.feature) layer.setStyle(styleFeature(layer.feature));
    });
  }, [geojson, legend, selectedLocationId, styleFeature]);

  return (
    <div className="app">
      <div
        style={{
          position: "absolute",
          top: 16,
          left: 16,
          background: "white",
          padding: "12px 14px",
          borderRadius: 8,
          boxShadow: "0 4px 12px rgba(15, 23, 42, 0.15)",
          fontSize: 12,
          minWidth: 240,
          display: "grid",
          gap: 10,
          zIndex: 1000,
        }}
      >
        <div style={{ fontWeight: 600, fontSize: 13 }}>
          Measure controls {isLoading ? "· Loading…" : ""}
        </div>
        {error ? (
          <div style={{ color: "#b91c1c", fontWeight: 600 }}>{error}</div>
        ) : null}
        <label style={{ display: "grid", gap: 6 }}>
          <span style={{ fontWeight: 600 }}>Measure</span>
          <select
            value={selectedMeasureId}
            onChange={(event) => setSelectedMeasureId(event.target.value)}
            style={{ padding: "6px 8px", borderRadius: 6 }}
          >
            {measures.length === 0 ? (
              <option value={selectedMeasureId}>Loading measures…</option>
            ) : (
              measures.map((measure) => {
                const label = measure.measure ?? measure.short_question_text ?? "";
                return (
                  <option key={measure.measure_id} value={measure.measure_id}>
                    {measure.measure_id}
                    {label ? ` — ${label}` : ""}
                  </option>
                );
              })
            )}
          </select>
        </label>
        <label style={{ display: "grid", gap: 6 }}>
          <span style={{ fontWeight: 600 }}>Year</span>
          <select
            value={selectedYear}
            onChange={(event) => setSelectedYear(Number(event.target.value))}
            style={{ padding: "6px 8px", borderRadius: 6 }}
          >
            {yearOptions.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
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
      <div className="map-wrapper">
        <MapContainer center={[39.5, -98.35]} zoom={4} style={{ height: "100%" }}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {geojson ? (
            <GeoJSON
              key={geoJsonKey}
              ref={geoJsonRef}
              data={geojson}
              style={styleFeature}
              onEachFeature={handleEachFeature}
            />
          ) : null}
        </MapContainer>
      </div>
      {isLoading ? (
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
            zIndex: 1100,
          }}
        >
          Loading…
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
          minWidth: 180,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 8 }}>
          Legend ({selectedType})
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
            : isLoading
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
        <div
          style={{
            marginTop: 12,
            paddingTop: 10,
            borderTop: "1px solid #e2e8f0",
            display: "grid",
            gap: 6,
          }}
        >
          <div style={{ fontWeight: 600 }}>Selected county</div>
          {selectedProps ? (
            <>
              <div>
                {selectedProps.name ??
                  selectedProps.county_name ??
                  "Unknown County"}
                {", "}
                {selectedProps.state_abbr ?? selectedProps.state_desc ?? ""}
              </div>
              <div>Value: {selectedProps.data_value ?? "No data"}</div>
              <div>Year: {selectedProps.year ?? selectedYear}</div>
              <div>Measure: {selectedProps.measure_id ?? selectedMeasureId}</div>
              <div>
                Data value type:{" "}
                {selectedProps.data_value_type ??
                  selectedProps.data_value_type_id ??
                  selectedType}
              </div>
            </>
          ) : (
            <div style={{ color: "#64748b" }}>Click a county.</div>
          )}
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: 16,
          bottom: 16,
          background: "white",
          padding: "10px 12px",
          borderRadius: 8,
          boxShadow: "0 4px 12px rgba(15, 23, 42, 0.12)",
          fontSize: 12,
        }}
      >
        measure_id={selectedMeasureId} · year={selectedYear} ·
        data_value_type_id={selectedType} · bins=5
      </div>
    </div>
  );
}
