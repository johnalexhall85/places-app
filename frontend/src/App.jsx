import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, useMapEvents } from "react-leaflet";
import CountiesChoropleth from "./layers/CountiesChoropleth";
import StatesChoropleth from "./layers/StatesChoropleth";

const COLORS = ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"];
const NO_DATA_COLOR = "#e2e8f0";
const ZOOM_THRESHOLD = 6;

function formatRange(min, max) {
  return `${min} – ${max}`;
}

export default function App() {
  const [measures, setMeasures] = useState([]);
  const [selectedMeasureId, setSelectedMeasureId] = useState("CASTHMA");
  const [selectedYear, setSelectedYear] = useState(2023);
  const [selectedType, setSelectedType] = useState("CrdPrv");
  const [selectedProps, setSelectedProps] = useState(null);
  const [hoveredProps, setHoveredProps] = useState(null);
  const [legendBreaks, setLegendBreaks] = useState([]);
  const [zoom, setZoom] = useState(4);
  const [error, setError] = useState(null);

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
    setSelectedProps(null);
    setHoveredProps(null);
    setLegendBreaks([]);
    setError(null);
  }, [selectedMeasureId, selectedYear, selectedType]);

  const breaks = useMemo(() => legendBreaks ?? [], [legendBreaks]);
  const selectedMeasure = measures.find(
    (measure) => measure.measure_id === selectedMeasureId
  );
  const isLoading = false;

  const params = useMemo(
    () => ({
      measure_id: selectedMeasureId,
      year: selectedYear,
      data_value_type_id: selectedType,
    }),
    [selectedMeasureId, selectedYear, selectedType]
  );

  function MapEvents() {
    useMapEvents({
      zoomend(event) {
        setZoom(event.target.getZoom());
      },
    });
    return null;
  }

  const showingCounties = zoom >= ZOOM_THRESHOLD;

  return (
    <div
      className="app"
      style={{ position: "relative", height: "100vh", width: "100vw" }}
    >
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
          zIndex: 2000,
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
      <div className="map-wrapper" style={{ height: "100%", width: "100%" }}>
        <MapContainer center={[39.5, -98.35]} zoom={4} style={{ height: "100%" }}>
          <MapEvents />
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <StatesChoropleth
            params={params}
            enabled={!showingCounties}
            onHover={(props) => setHoveredProps(props)}
            onSelect={(props) => setSelectedProps(props)}
            onBreaks={(incomingBreaks) => {
              if (!showingCounties) {
                setLegendBreaks(incomingBreaks);
              }
            }}
          />
          <CountiesChoropleth
            params={params}
            enabled={showingCounties}
            onHover={(props) => setHoveredProps(props)}
            onSelect={(props) => setSelectedProps(props)}
            onBreaks={(incomingBreaks) => {
              if (showingCounties) {
                setLegendBreaks(incomingBreaks);
              }
            }}
          />
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
            zIndex: 2100,
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
          zIndex: 2000,
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
          <div style={{ fontWeight: 600 }}>
            Hovered {showingCounties ? "county" : "state"}
          </div>
          {hoveredProps ? (
            <>
              <div>
                {hoveredProps.name ??
                  hoveredProps.state_desc ??
                  hoveredProps.state_abbr ??
                  "Unknown"}
              </div>
              <div>Value: {hoveredProps.value ?? "No data"}</div>
            </>
          ) : (
            <div style={{ color: "#64748b" }}>Hover an area.</div>
          )}
          <div style={{ fontWeight: 600 }}>
            Selected {showingCounties ? "county" : "state"}
          </div>
          {selectedProps ? (
            <>
              <div>
                {selectedProps.name ??
                  selectedProps.state_desc ??
                  selectedProps.state_abbr ??
                  "Unknown"}
              </div>
              <div>Value: {selectedProps.value ?? "No data"}</div>
              <div>Year: {selectedYear}</div>
              <div>Measure: {selectedMeasureId}</div>
              <div>Data value type: {selectedType}</div>
            </>
          ) : (
            <div style={{ color: "#64748b" }}>Click an area.</div>
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
