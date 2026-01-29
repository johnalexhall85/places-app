import { useCallback, useEffect, useMemo, useRef } from "react";
import { GeoJSON } from "react-leaflet";

const HOVER_STYLE = {
  color: "#0f172a",
  weight: 3,
  fillOpacity: 0.9,
};

export default function StateLayer({
  data,
  breaks,
  selectedStateAbbr,
  getColor,
  onHover,
  onSelect,
}) {
  const layerRef = useRef(null);

  const baseStyle = useCallback(
    (feature) => {
      const value = feature?.properties?.data_value ?? null;
      const fillColor = getColor(value, breaks);
      const isSelected = feature?.properties?.state_abbr === selectedStateAbbr;
      return {
        fill: true,
        fillColor,
        fillOpacity: 0.7,
        color: isSelected ? "#111827" : "#64748b",
        weight: isSelected ? 3 : 1,
      };
    },
    [breaks, getColor, selectedStateAbbr]
  );

  const handleEachFeature = useCallback(
    (feature, layer) => {
      const tooltipLabel =
        feature?.properties?.state_desc ??
        feature?.properties?.state_abbr ??
        "State";
      layer.bindTooltip(tooltipLabel, { sticky: true });

      layer.on({
        mouseover: (event) => {
          const target = event?.target;
          if (target) {
            target.setStyle({ ...baseStyle(feature), ...HOVER_STYLE });
            if (target.bringToFront) {
              target.bringToFront();
            }
          }
          onHover?.(feature.properties ?? null);
        },
        mouseout: (event) => {
          const target = event?.target;
          if (target && layerRef.current) {
            layerRef.current.resetStyle(target);
          }
          onHover?.(null);
        },
        click: () => {
          onSelect?.(feature.properties ?? null);
        },
      });
    },
    [baseStyle, onHover, onSelect]
  );

  const memoizedData = useMemo(() => data, [data]);

  useEffect(() => {
    if (layerRef.current) {
      layerRef.current.setStyle(baseStyle);
    }
  }, [baseStyle, memoizedData]);

  if (!memoizedData) {
    return null;
  }

  return (
    <GeoJSON
      data={memoizedData}
      style={baseStyle}
      onEachFeature={handleEachFeature}
      ref={layerRef}
    />
  );
}
