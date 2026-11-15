import { useEffect, useMemo, useState } from "react";
import { GeoJSON, MapContainer } from "react-leaflet";
import { API_BASE } from "../config/apiBase";
import { formatIndicatorValue } from "./CommunityPages";
import { BLUES } from "../branding/mapColors";

const STATUS_COLORS = {
  suppressed: "#b9a7b1",
  missing: "#d4dce1",
  not_published: "#d4dce1",
  not_applicable: "#dfd4e5",
  open_ended: "#d1bbdf",
};

export function tractColor(value, status, low, high) {
  if (STATUS_COLORS[status]) return STATUS_COLORS[status];
  if (value == null) return "#d4dce1";
  if (high <= low) return BLUES[2];
  const index = Math.min(BLUES.length - 1, Math.floor((value - low) / (high - low) * BLUES.length));
  return BLUES[Math.max(0, index)];
}

export default function TractPatternMap({ area, row }) {
  const [mapData, setMapData] = useState(null);
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    const controller = new AbortController();
    setMapData(null);
    setStatus("loading");
    async function load() {
      try {
        const tractResponse = await fetch(`${API_BASE}/community/county/${area.geoid}/tracts?product=${encodeURIComponent(row.product)}&measure_id=${encodeURIComponent(row.measure_id)}`, { signal: controller.signal });
        if (!tractResponse.ok) throw new Error("Tract values are unavailable for this measure.");
        const tractData = await tractResponse.json();
        if (!tractData.values.length) { setStatus("empty"); return; }
        const params = new URLSearchParams({
          dataset_id: row.dataset_id, release_id: row.release_id, measure_id: row.measure_id,
          period: row.period, population: row.population, value_type: row.value_type,
          geography: "tract", bbox: area.bbox.join(","), simplify: "0.002",
        });
        const response = await fetch(`${API_BASE}/area/map?${params}`, { signal: controller.signal });
        if (!response.ok) throw new Error(response.status === 413 ? "This county is too large for one map request. Open the full map." : "Tract map is unavailable right now.");
        const data = await response.json();
        if (data.release_id !== row.release_id || data.measure_id !== row.measure_id || data.geography !== "tract") {
          throw new Error("Tract map selection did not match the published release.");
        }
        const features = data.features.filter((feature) => feature.properties.geography_id?.startsWith(area.geoid));
        setMapData({ ...data, features });
        setStatus(features.length ? "ready" : "empty");
      } catch (error) {
        if (error.name !== "AbortError") setStatus(error.message);
      }
    }
    load();
    return () => controller.abort();
  }, [area, row]);

  const values = useMemo(() => (mapData?.features || []).map((feature) => feature.properties.value).filter((value) => value != null), [mapData]);
  const low = values.length ? Math.min(...values) : 0;
  const high = values.length ? Math.max(...values) : 0;
  const [west, south, east, north] = area.bbox;

  if (status === "loading") return <p className="community-message" role="status">Loading published tract patterns…</p>;
  if (status === "empty") return <p className="community-message">No tract values are published in the active release for this measure and county.</p>;
  if (status !== "ready") return <p className="community-message" role="alert">{status}</p>;
  return <div className="community-tract-block">
    <div className="community-tract-map" role="img" aria-label={`${row.label} by published census tract in ${area.name} County`}>
      <MapContainer key={`${area.geoid}:${row.release_id}:${row.measure_id}`} bounds={[[south, west], [north, east]]} zoomControl={true} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
        <GeoJSON data={mapData} style={(feature) => ({
          color: "#657a86", weight: 0.8, fillOpacity: 0.88,
          fillColor: tractColor(feature.properties.value, feature.properties.status, low, high),
        })} onEachFeature={(feature, layer) => {
          const label = document.createElement("div");
          label.textContent = `Tract ${feature.properties.geography_id}: ${formatIndicatorValue({ ...row, value: feature.properties.value, status: feature.properties.status, status_text: feature.properties.status })}. Source: ${row.source.publisher}, ${row.period}, release ${row.source_release_id}.`;
          layer.bindTooltip(label);
        }} />
      </MapContainer>
    </div>
    <div className="community-tract-legend">
      <span><i className="community-legend-gradient" /> Lower to higher published values within this county</span>
      <span><i className="community-legend-status" /> Missing or not published</span>
      <span><i className="community-legend-suppressed" /> Suppressed or open-ended (see tooltip)</span>
    </div>
    <p className="community-source">Source: {row.source.publisher} · {row.source.product_name} · {row.period} · {row.source_release_id}. Population: {row.population}. Boundary: {mapData.boundary_vintage}. Tracts are shown individually; no county value is calculated from them.</p>
  </div>;
}
