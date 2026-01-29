import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GeoJSON } from "react-leaflet";

const COLORS = ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"];
const NO_DATA_COLOR = "#e2e8f0";
const HOVER_STYLE = {
  color: "#0f172a",
  weight: 2,
  fillOpacity: 0.85,
};

function getFillColor(value, breaks) {
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

export default function ChoroplethLayer({
  url,
  params,
  idProp,
  nameProp,
  zoomMin,
  zoomMax,
  enabled = true,
  onHover,
  onSelect,
  onBreaks,
}) {
  const [geojson, setGeojson] = useState(null);
  const [breaks, setBreaks] = useState([]);
  const abortRef = useRef(null);
  const layerRef = useRef(null);

  const isVisible = useMemo(() => {
    if (zoomMin != null && zoomMax != null) {
      return enabled && zoomMin <= zoomMax;
    }
    return enabled;
  }, [enabled, zoomMin, zoomMax]);

  const baseStyle = useCallback(
    (feature) => {
      const value = feature?.properties?.value ?? null;
      return {
        fill: true,
        fillColor: getFillColor(value, breaks),
        fillOpacity: 0.6,
        color: "#334155",
        weight: 1,
      };
    },
    [breaks]
  );

  const handleEachFeature = useCallback(
    (feature, layer) => {
      const label =
        feature?.properties?.[nameProp] ??
        feature?.properties?.[idProp] ??
        "Feature";
      layer.bindTooltip(String(label), { sticky: true });

      layer.on({
        mouseover: () => {
          layer.setStyle({ ...baseStyle(feature), ...HOVER_STYLE });
          if (layer.bringToFront) {
            layer.bringToFront();
          }
          onHover?.(feature.properties ?? null);
        },
        mouseout: () => {
          layer.setStyle(baseStyle(feature));
          onHover?.(null);
        },
        click: () => {
          onSelect?.(feature.properties ?? null);
        },
      });
    },
    [baseStyle, idProp, nameProp, onHover, onSelect]
  );

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;

    const requestUrl = new URL(url);
    Object.entries(params ?? {}).forEach(([key, value]) => {
      if (value != null) {
        requestUrl.searchParams.set(key, String(value));
      }
    });

    fetch(requestUrl, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.text();
          throw new Error(
            `GeoJSON request failed (${response.status}): ${body || "No body"}`
          );
        }
        return response.json();
      })
      .then((json) => {
        const incomingGeojson = json.geojson ?? json;
        setGeojson(incomingGeojson);
        const incomingBreaks = json.breaks ?? [];
        setBreaks(incomingBreaks);
        onBreaks?.(incomingBreaks);
      })
      .catch((error) => {
        if (error.name === "AbortError") {
          return;
        }
        console.error(error);
      });

    return () => {
      controller.abort();
    };
  }, [enabled, params, url, onBreaks]);

  useEffect(() => {
    if (layerRef.current) {
      layerRef.current.setStyle(baseStyle);
    }
  }, [baseStyle, geojson]);

  if (!isVisible || !geojson) {
    return null;
  }

  return (
    <GeoJSON
      data={geojson}
      style={baseStyle}
      onEachFeature={handleEachFeature}
      ref={layerRef}
    />
  );
}
