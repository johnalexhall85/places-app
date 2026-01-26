import { useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, TileLayer, Tooltip } from "react-leaflet";

const LEGEND_URL =
  "http://localhost:8000/legend?measure_id=CASTHMA&year=2023&data_value_type_id=CrdPrv&bins=5";
const GEOJSON_URL =
  "http://localhost:8000/counties/geojson?measure_id=CASTHMA&year=2023&data_value_type_id=CrdPrv&limit=10000";

const COLORS = ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"];
const NO_DATA_COLOR = "#9ca3af";

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
  const [legend, setLegend] = useState(null);
  const [geojson, setGeojson] = useState(null);

  useEffect(() => {
    let isMounted = true;

    const fetchLegend = fetch(LEGEND_URL).then((response) => response.json());
    const fetchGeojson = fetch(GEOJSON_URL).then((response) => response.json());

    Promise.all([fetchLegend, fetchGeojson])
      .then(([legendData, geojsonData]) => {
        if (!isMounted) return;
        setLegend(legendData);
        setGeojson(geojsonData);
      })
      .catch((error) => {
        console.error("Failed to load map data (possible CORS issue):", error);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const breaks = useMemo(() => legend?.breaks ?? [], [legend]);
  const features = geojson?.features ?? [];

  return (
    <div className="app">
      <div className="map-wrapper">
        <MapContainer center={[39.5, -98.35]} zoom={4} style={{ height: "100%" }}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {features.map((feature) => {
            const { geometry, properties } = feature;
            if (!geometry || geometry.type !== "Point") return null;

            const [lon, lat] = geometry.coordinates;
            const value = properties?.data_value ?? null;
            const color = getColor(value, breaks);

            return (
              <CircleMarker
                key={properties?.geoid ?? `${lat}-${lon}`}
                center={[lat, lon]}
                radius={4}
                pathOptions={{
                  color,
                  fillColor: color,
                  fillOpacity: 0.8,
                  weight: 1,
                }}
              >
                <Tooltip direction="top" offset={[0, -4]}>
                  <div>
                    <strong>
                      {properties?.county_name ?? "Unknown County"},{" "}
                      {properties?.state_abbr ?? ""}
                    </strong>
                    <div>Value: {value ?? "No data"}</div>
                  </div>
                </Tooltip>
              </CircleMarker>
            );
          })}
        </MapContainer>
      </div>

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
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Legend (CrdPrv)</div>
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
            : "Loading..."}
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
        measure_id=CASTHMA · year=2023 · data_value_type_id=CrdPrv · bins=5
      </div>
    </div>
  );
}
