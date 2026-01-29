import ChoroplethLayer from "./ChoroplethLayer";

export default function StatesChoropleth({
  params,
  enabled,
  onHover,
  onSelect,
  onBreaks,
}) {
  return (
    <ChoroplethLayer
      url="http://localhost:8000/geojson/states"
      params={params}
      idProp="state_fips"
      nameProp="name"
      enabled={enabled}
      onHover={onHover}
      onSelect={onSelect}
      onBreaks={onBreaks}
    />
  );
}
