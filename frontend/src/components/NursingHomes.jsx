import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { CircleMarker, Marker, Pane, useMap } from "react-leaflet";
import { API_BASE } from "../config/apiBase";

const PANE = "chip-cms-nursing-homes";
const PAGE_SIZE = 50;
const FILTERS = ["provider_type", "ownership", "overall"];
const cache = new Map();

async function get(path, signal) {
  if (cache.has(path)) return cache.get(path);
  const response = await fetch(API_BASE + "/area/nursing-homes/" + path, { signal });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Nursing home request failed (" + response.status + ")");
  }
  const data = await response.json();
  if (!path.startsWith("catalog")) {
    cache.set(path, data);
    if (cache.size > 150) cache.delete(cache.keys().next().value);
  }
  return data;
}

function stored() { try { return JSON.parse(sessionStorage.getItem("chip.cmsNursingHomes.v1") || "null"); } catch { return null; } }
function save(value) { try { sessionStorage.setItem("chip.cmsNursingHomes.v1", JSON.stringify(value)); } catch { /* unavailable */ } }
function defaults(catalog) {
  return Object.fromEntries(catalog.filters.map((group) => [group.name, group.values.filter((v) => v.default).map((v) => v.code).sort()]));
}
function query(releaseId, bbox, filters, extra = {}) {
  const params = new URLSearchParams({ release_id: releaseId, bbox, ...extra });
  FILTERS.forEach((name) => { if (filters?.[name]) params.set(name, [...filters[name]].sort().join(",")); });
  return params;
}
function sameFilters(a, b) {
  return FILTERS.every((name) => [...(a?.[name] || [])].sort().join(",") === [...(b?.[name] || [])].sort().join(","));
}
function groups(points) {
  const found = new Map();
  points.forEach((point) => found.set(point.location_key, [...(found.get(point.location_key) || []), point]));
  return [...found.values()];
}

export function useNursingHomes({ bbox, zoom }) {
  const initial = useMemo(stored, []);
  const [enabled, setEnabled] = useState(Boolean(initial?.enabled));
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState("");
  const [filters, setFilters] = useState(null);
  const [debouncedFilters, setDebouncedFilters] = useState(null);
  const [page, setPage] = useState(0);
  const [view, setView] = useState({ key: null, map: null, table: null, error: "" });
  const [selection, setSelection] = useState(null);
  const [detail, setDetail] = useState({ data: null, error: "" });
  const requestId = useRef(0);
  const detailId = useRef(0);
  const releaseId = catalog?.active_release_id || null;
  const zoomLevel = Math.max(0, Math.floor(zoom ?? 0));

  useEffect(() => {
    if (!enabled || catalog) return undefined;
    const controller = new AbortController();
    get("catalog", controller.signal).then((data) => {
      setCatalog(data);
      const valid = initial?.filters && FILTERS.every((name) => Array.isArray(initial.filters[name])
        && initial.filters[name].length && initial.filters[name].every((code) =>
          data.filters?.find((group) => group.name === name)?.values.some((value) => value.code === code)));
      setFilters(valid ? initial.filters : defaults(data));
    }).catch((error) => { if (error.name !== "AbortError") setCatalogError(error.message); });
    return () => controller.abort();
  }, [enabled, catalog, initial]);
  useEffect(() => { save({ enabled, filters }); }, [enabled, filters]);
  useEffect(() => { setPage(0); detailId.current += 1; setSelection(null); setDetail({ data: null, error: "" }); }, [bbox, filters, releaseId]);
  useEffect(() => {
    if (!filters) return undefined;
    const timer = setTimeout(() => setDebouncedFilters(filters), 400);
    return () => clearTimeout(timer);
  }, [filters]);

  const requestKey = enabled && releaseId && bbox && debouncedFilters
    ? String(query(releaseId, bbox, debouncedFilters, { zoom: zoomLevel })) + "|" + page : null;
  useEffect(() => {
    if (!requestKey) return undefined;
    const controller = new AbortController();
    const id = ++requestId.current;
    const mapPath = "map?" + query(releaseId, bbox, debouncedFilters, { zoom: zoomLevel });
    const tablePath = "table?" + query(releaseId, bbox, debouncedFilters, { limit: PAGE_SIZE, offset: page * PAGE_SIZE });
    Promise.all([get(mapPath, controller.signal), get(tablePath, controller.signal)]).then(([map, table]) => {
      if (id !== requestId.current) return;
      if (map.release_id !== releaseId || table.release_id !== releaseId || map.bbox !== bbox || table.bbox !== bbox
          || !sameFilters(map.filters, debouncedFilters) || !sameFilters(table.filters, debouncedFilters) || map.total !== table.total)
        throw new Error("Nursing home map and table responses differ from the requested selection");
      setView({ key: requestKey, map, table, error: "" });
    }).catch((error) => {
      if (error.name !== "AbortError" && id === requestId.current)
        setView({ key: null, map: null, table: null, error: error.message });
    });
    return () => controller.abort();
  }, [requestKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const openFacility = useCallback((ccn) => {
    if (!releaseId || !bbox || !filters) return;
    setSelection({ type: "facility", ccn });
    const id = ++detailId.current;
    setDetail({ data: null, error: "" });
    const params = query(releaseId, bbox, filters, { ccn });
    get("detail?" + params).then((data) => {
      if (id === detailId.current && data.release_id === releaseId && data.bbox === bbox && sameFilters(data.filters, filters))
        setDetail({ data, error: "" });
    }).catch((error) => { if (id === detailId.current) setDetail({ data: null, error: error.message }); });
  }, [releaseId, bbox, filters]);
  const openGroup = useCallback((facilities) => { detailId.current += 1; setSelection({ type: "group", facilities }); }, []);
  const closeSelection = useCallback(() => { detailId.current += 1; setSelection(null); setDetail({ data: null, error: "" }); }, []);
  const toggleFilter = useCallback((name, code) => setFilters((current) => {
    const values = new Set(current?.[name] || []);
    if (values.has(code)) values.delete(code); else values.add(code);
    return values.size ? { ...current, [name]: [...values].sort() } : current;
  }), []);
  const resetFilters = useCallback(() => setFilters(defaults(catalog)), [catalog]);
  const ready = Boolean(requestKey && view.key === requestKey && sameFilters(filters, debouncedFilters));
  return { enabled, setEnabled, catalog, catalogError, releaseId, filters, toggleFilter, resetFilters,
    page, setPage, ready, map: ready ? view.map : null, table: ready ? view.table : null, error: view.error,
    selection, detail, openFacility, openGroup, closeSelection };
}

function markerIcon(count, kind) {
  const size = kind === "cluster" ? count >= 1000 ? 46 : count >= 100 ? 38 : 30 : 26;
  return L.divIcon({ className: "chip-cms-" + kind, iconSize: [size, size], html: "<span>" + count.toLocaleString("en-US") + "</span>" });
}
function stop(event) { if (event?.originalEvent) L.DomEvent.stopPropagation(event.originalEvent); }

export function NursingHomeLayer({ homes }) {
  const map = useMap();
  if (!homes.enabled || !homes.map) return null;
  return <Pane name={PANE} style={{ zIndex: 650 }}>
    {homes.map.mode === "clusters" ? homes.map.clusters.map((cluster) => <Marker key={cluster.id} pane={PANE}
      position={[cluster.lat, cluster.lon]} icon={markerIcon(cluster.count, "cluster")} keyboard={false}
      title={cluster.count + " nursing homes grouped for display. Select to zoom in."}
      eventHandlers={{ click: (event) => {
        stop(event);
        const [west, south, east, north] = cluster.bounds;
        if (west === east && south === north) map.setView([south, west], Math.min(map.getZoom() + 3, 18));
        else map.fitBounds([[south, west], [north, east]], { padding: [40, 40], maxZoom: 18 });
      } }} />) : groups(homes.map.points).map((group) => group.length > 1
      ? <Marker key={group[0].location_key} pane={PANE} position={[group[0].lat, group[0].lon]}
          icon={markerIcon(group.length, "colocated")} keyboard={false}
          title={group.length + " distinct nursing homes share this published location"}
          eventHandlers={{ click: (event) => { stop(event); homes.openGroup(group); } }} />
      : <CircleMarker key={group[0].ccn} pane={PANE} center={[group[0].lat, group[0].lon]} radius={6}
          bubblingMouseEvents={false} pathOptions={{ color: "#fff", weight: 1.5, fillColor: "#1c5da6", fillOpacity: 0.95 }}
          eventHandlers={{ click: (event) => { stop(event); homes.openFacility(group[0].ccn); } }} />)}
  </Pane>;
}

export function StarRating({ value, footnote }) {
  const label = value == null ? "Unrated" : value + " of 5 stars";
  return <span>{value == null ? "Unrated" : <><span aria-hidden="true">{"★".repeat(value)}{"☆".repeat(5 - value)}</span> <span className="visually-hidden">{label}</span></>}
    {footnote?.code && <span> · CMS footnote {footnote.code}: {footnote.explanation}</span>}</span>;
}

function FacilityDetail({ homes, headingRef }) {
  const { selection, detail } = homes;
  if (!selection) return null;
  if (selection.type === "group") return <div className="chip-sites-detail" role="region" aria-labelledby="chip-cms-detail-heading">
    <h3 id="chip-cms-detail-heading" tabIndex={-1} ref={headingRef}>{selection.facilities.length} distinct nursing homes at one published location</h3>
    <ul>{selection.facilities.map((item) => <li key={item.ccn}><button type="button" onClick={() => homes.openFacility(item.ccn)}>{item.provider_name} ({item.ccn})</button></li>)}</ul>
    <button type="button" onClick={homes.closeSelection}>Close</button>
  </div>;
  const data = detail.data;
  const ratings = data && [["Overall", data.overall_rating, data.rating_footnotes.overall],
    ["Health inspection", data.health_inspection_rating, data.rating_footnotes.health_inspection],
    ["Staffing", data.staffing_rating, data.rating_footnotes.staffing],
    ["Quality measure", data.quality_measure_rating, data.rating_footnotes.quality_measure]];
  return <div className="chip-sites-detail" role="region" aria-labelledby="chip-cms-detail-heading" aria-busy={!data && !detail.error}>
    <h3 id="chip-cms-detail-heading" tabIndex={-1} ref={headingRef}>{data ? data.provider_name : "Loading nursing home…"}</h3>
    {detail.error && <p role="alert">{detail.error}</p>}
    {data && <><dl>
      <dt>CMS Certification Number</dt><dd>{data.ccn}</dd>
      <dt>Address</dt><dd>{[data.address, data.city, data.state, data.zip_code].filter(Boolean).join(", ")}</dd>
      <dt>County as published</dt><dd>{data.county_name || "Not published"}</dd>
      <dt>Provider type</dt><dd>{data.provider_type}</dd>
      <dt>Ownership type</dt><dd>{data.ownership_type}</dd>
      <dt>Certified beds</dt><dd>{data.certified_beds ?? "Not published"} {data.certified_beds != null && "federally certified beds; not vacancies"}</dd>
      {ratings.map(([label, value, footnote]) => <div key={label}><dt>{label} rating</dt><dd><StarRating value={value} footnote={footnote} /></dd></div>)}
      <dt>CMS processing date</dt><dd>{data.processing_date}</dd>
      <dt>Published coordinates</dt><dd>{data.location.source_latitude}, {data.location.source_longitude} (EPSG:4326){data.location.facilities_at_location > 1 ? " · " + data.location.facilities_at_location + " distinct facilities here" : ""}</dd>
    </dl><p>{data.period_note}</p><p><a href={data.care_compare_url} target="_blank" rel="noreferrer noopener">View this facility on Medicare Care Compare</a></p></>}
    <button type="button" onClick={homes.closeSelection}>Close</button>
  </div>;
}

export function NursingHomePanel({ homes }) {
  const [open, setOpen] = useState(() => typeof window === "undefined" || window.innerWidth > 700);
  const headingRef = useRef(null);
  useEffect(() => { if (homes.selection) headingRef.current?.focus(); }, [homes.selection, homes.detail.data]);
  const { catalog, filters, map, table, ready } = homes;
  const counts = catalog?.counts || {};
  return <section className={"pilot-panel pilot-sites pilot-cms-homes " + (homes.enabled && open ? "is-open" : "")} aria-label="CMS nursing homes overlay">
    <div className="pilot-sites-head"><label><input type="checkbox" checked={homes.enabled} onChange={(event) => homes.setEnabled(event.target.checked)} /> Show CMS nursing homes</label>
      {homes.enabled && <button type="button" className="pilot-sites-collapse" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? "Hide panel" : "Show panel"}</button>}</div>
    {homes.enabled && open && <div className="pilot-sites-body">
      {homes.catalogError && <p role="alert">{homes.catalogError}</p>}
      {!catalog && !homes.catalogError && <p role="status">Loading CMS nursing home catalog…</p>}
      {catalog && !homes.releaseId && <p role="status">No CMS nursing home release is published.</p>}
      {catalog && homes.releaseId && <>
        <p className="pilot-metadata">CMS Provider Information · released {catalog.released_date} · processed {catalog.processing_date} · independent facility release {homes.releaseId.slice(0, 8)}.</p>
        <p className="pilot-metadata">{counts.mapped?.toLocaleString("en-US")} of {counts.source?.toLocaleString("en-US")} published facilities mapped; {counts.excluded?.toLocaleString("en-US")} ZIP based locations excluded. {counts.unrated_overall?.toLocaleString("en-US")} have no overall rating.</p>
        <p>CMS stars describe published measures, not a guarantee of individual care or a live assessment. Certified beds are not vacant beds.</p>
        <ul className="pilot-swatches" aria-label="Nursing home symbols"><li>Blue circle: one nursing home</li><li>Blue numbered square: distinct colocated homes</li><li>Blue cluster: display grouping; zoom in for individual homes</li></ul>
        <details className="pilot-sites-filters"><summary>Filters</summary>{catalog.filters.map((group) => <fieldset key={group.name}><legend>{group.label}</legend>
          {group.values.map((value) => <label key={value.code}><input type="checkbox" checked={Boolean(filters?.[group.name]?.includes(value.code))}
            onChange={() => homes.toggleFilter(group.name, value.code)} /> {value.label}</label>)}</fieldset>)}
          <button type="button" onClick={homes.resetFilters}>Reset filters</button></details>
        <details><summary>Source and interpretation limits</summary><ul className="pilot-limitations">{catalog.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
          <p><a href={catalog.dictionary_url} target="_blank" rel="noreferrer noopener">CMS data dictionary and footnotes</a></p></details>
        {homes.error && <p role="alert">{homes.error}</p>}
        {!ready && !homes.error && <p role="status">Loading nursing homes in view…</p>}
        {ready && map && <p role="status">{map.total.toLocaleString("en-US")} nursing homes in view{map.mode === "clusters" ? ", displayed as " + map.clusters.length + " clusters. Zoom in for points." : "."}</p>}
        <FacilityDetail homes={homes} headingRef={headingRef} />
        {ready && table && <><div className="pilot-table-scroll"><table><caption>CMS nursing homes in view; same release and filters as map; CMS processing date {table.processing_date}</caption>
          <thead><tr><th scope="col">Facility</th><th scope="col">City, state</th><th scope="col">Provider type</th><th scope="col">Ownership</th><th scope="col">Certified beds</th><th scope="col">Overall</th><th scope="col">Health inspection</th><th scope="col">Staffing</th><th scope="col">Quality measure</th><th scope="col">Details</th></tr></thead>
          <tbody>{table.rows.map((row) => <tr key={row.ccn}><th scope="row">{row.provider_name}<br />{row.ccn}</th><td>{row.city}, {row.state}</td><td>{row.provider_type}</td><td>{row.ownership_type}</td><td>{row.certified_beds ?? "Not published"}</td>
            {[[row.overall_rating, row.rating_footnotes.overall], [row.health_inspection_rating, row.rating_footnotes.health_inspection], [row.staffing_rating, row.rating_footnotes.staffing], [row.quality_measure_rating, row.rating_footnotes.quality_measure]].map(([value, footnote], index) => <td key={index}><StarRating value={value} footnote={footnote} /></td>)}
            <td><button type="button" onClick={() => homes.openFacility(row.ccn)} aria-label={"Details for " + row.provider_name}>Details</button></td></tr>)}</tbody>
        </table></div><nav aria-label="Nursing home table pages"><button type="button" disabled={homes.page===0} onClick={() => homes.setPage(homes.page-1)}>Previous</button> Page {homes.page+1} of {Math.max(1,Math.ceil(table.total/PAGE_SIZE))} <button type="button" disabled={(homes.page+1)*PAGE_SIZE>=table.total} onClick={() => homes.setPage(homes.page+1)}>Next</button></nav></>}
        <p className="pilot-metadata">Source: <a href={catalog.source_url} target="_blank" rel="noreferrer noopener">CMS Provider Data Catalog</a>.</p>
      </>}
    </div>}
  </section>;
}
