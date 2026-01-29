import ChoroplethLayer from "./ChoroplethLayer";

export default function CountiesChoropleth({
  params,
  enabled,
  onHover,
  onSelect,
  onBreaks,
}) {
  return (
    <ChoroplethLayer
      url="http://localhost:8000/geojson/counties"
      params={params}
      idProp="county_fips"
      nameProp="name"
      enabled={enabled}
      onHover={onHover}
      onSelect={onSelect}
      onBreaks={onBreaks}
    />
  );
}
