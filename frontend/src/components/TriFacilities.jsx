import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { CircleMarker, Marker, Pane, useMap } from "react-leaflet";
import { API_BASE } from "../config/apiBase";
import { groupColocated } from "./HealthCenterSites";

// Optional EPA TRI reporting-facility overlay. Its release, filters, requests, and cache are independent
// of the area layer and of the HRSA site overlay; both overlays can be shown at the same time.

export const TRI_PANE = "chip-tri-facilities";
export const TRI_PAGE_SIZE = 50;
export const TRI_CHEMICAL_PAGE_SIZE = 20;
export const TRI_DETAIL_CHEMICAL_PAGE_SIZE = 50;
export const TRI_COLOR = "#6b3fa0";
const STORAGE_KEY = "chip.triFacilities.v1";
const CACHE_LIMIT = 150;
const cache = new Map();

function cacheSet(key, value) {
  cache.set(key, value);
  if (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value);
}
export function clearTriCache() { cache.clear(); }

async function getTri(path, signal) {
  const cached = cache.get(path);
  if (cached) return cached;
  const response = await fetch(`${API_BASE}/area/tri/${path}`, { signal });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body.detail || `TRI facility request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  const data = await response.json();
  // Catalog responses change when the pointer moves; only release-pinned responses are cached.
  if (!path.startsWith("catalog")) cacheSet(path, data);
  return data;
}

export function allSectors(catalog) {
  return (catalog?.sectors || []).map((s) => s.code).sort();
}

export function triQuery({ releaseId, bbox, zoom, filters, limit, offset }) {
  const params = new URLSearchParams({ release_id: releaseId, bbox });
  if (zoom != null) params.set("zoom", String(zoom));
  if (filters?.sector) params.set("sector", [...filters.sector].sort().join(","));
  if (filters?.chemical?.id) params.set("chemical", filters.chemical.id);
  if (limit != null) params.set("limit", String(limit));
  if (offset != null) params.set("offset", String(offset));
  return params;
}

export function chemicalLabel(chemical) {
  if (!chemical) return "";
  return `${(chemical.names || []).join(" / ")}${chemical.cas_number && chemical.cas_number !== chemical.chemical_id ? ` (CAS ${chemical.cas_number})` : ""}`;
}

function readStored() {
  try { return JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || "null"); } catch { return null; }
}
function writeStored(value) {
  try { window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

function sameFilters(response, filters) {
  return [...(response?.sector || [])].sort().join(",") === [...(filters?.sector || [])].sort().join(",")
    && (response?.chemical || null) === (filters?.chemical?.id || null);
}

export function useTriFacilities({ bbox, zoom }) {
  const stored = useMemo(readStored, []);
  const [enabled, setEnabled] = useState(Boolean(stored?.enabled));
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState("");
  const [filters, setFilters] = useState(null); // {sector: [codes], chemical: null | {id, label}}
  const [page, setPage] = useState(0);
  const [view, setView] = useState({ key: null, map: null, table: null, error: "" });
  const [selection, setSelection] = useState(null); // {type:'facility', facilityId} | {type:'group', facilities}
  const [detail, setDetail] = useState({ facilityId: null, offset: 0, data: null, error: "" });
  const requestId = useRef(0);
  const detailRequest = useRef(0);
  const zoomLevel = Math.max(0, Math.floor(zoom ?? 0));
  const releaseId = catalog?.active_release_id || null;

  useEffect(() => {
    if (!enabled || catalog) return undefined;
    const controller = new AbortController();
    getTri("catalog", controller.signal).then((data) => {
      setCatalog(data);
      const codes = allSectors(data);
      const storedSectors = stored?.filters?.sector;
      const validSectors = Array.isArray(storedSectors) && storedSectors.length && storedSectors.every((c) => codes.includes(c));
      // A stored chemical is only reused for the same release; it is revalidated by the API on every request.
      const chemical = stored?.releaseId === data.active_release_id && stored?.filters?.chemical?.id ? stored.filters.chemical : null;
      setFilters({ sector: validSectors ? storedSectors : codes, chemical });
    }).catch((err) => { if (err.name !== "AbortError") setCatalogError(err.message); });
    return () => controller.abort();
  }, [enabled, catalog, stored]);

  useEffect(() => { writeStored({ enabled, filters, releaseId }); }, [enabled, filters, releaseId]);
  useEffect(() => { setPage(0); }, [bbox, zoomLevel, filters, releaseId]);

  const requestKey = enabled && releaseId && bbox && filters
    ? `${triQuery({ releaseId, bbox, zoom: zoomLevel, filters })}|${page}` : null;

  useEffect(() => {
    if (!requestKey) return undefined;
    const controller = new AbortController();
    const id = ++requestId.current;
    const mapPath = `map?${triQuery({ releaseId, bbox, zoom: zoomLevel, filters })}`;
    const tablePath = `table?${triQuery({ releaseId, bbox, filters, limit: TRI_PAGE_SIZE, offset: page * TRI_PAGE_SIZE })}`;
    setView((current) => ({ ...current, error: "" }));
    Promise.all([getTri(mapPath, controller.signal), getTri(tablePath, controller.signal)]).then(([map, table]) => {
      if (id !== requestId.current) return; // a newer viewport, filter, or release request superseded this one
      if (map.release_id !== releaseId || table.release_id !== releaseId || !sameFilters(map.filters, filters)
          || !sameFilters(table.filters, filters) || map.bbox !== bbox || table.bbox !== bbox) {
        throw new Error("TRI response did not match the requested release, viewport, or filters");
      }
      if (map.total !== table.total) throw new Error("TRI map and table totals differ; retry");
      setView({ key: requestKey, map, table, error: "" });
    }).catch((err) => {
      if (err.name !== "AbortError" && id === requestId.current) setView({ key: null, map: null, table: null, error: err.message });
    });
    return () => controller.abort();
  }, [requestKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const openFacility = useCallback((facilityId, offset = 0) => {
    if (!releaseId) return;
    setSelection({ type: "facility", facilityId });
    const id = ++detailRequest.current;
    setDetail((current) => ({ facilityId, offset, data: current.facilityId === facilityId ? current.data : null, error: "" }));
    const query = new URLSearchParams({ release_id: releaseId, facility_id: facilityId,
      chemical_limit: String(TRI_DETAIL_CHEMICAL_PAGE_SIZE), chemical_offset: String(offset) });
    getTri(`detail?${query}`).then((data) => {
      if (id === detailRequest.current && data.release_id === releaseId && data.facility_id === facilityId) {
        setDetail({ facilityId, offset, data, error: "" });
      }
    }).catch((err) => { if (id === detailRequest.current) setDetail({ facilityId, offset, data: null, error: err.message }); });
  }, [releaseId]);
  const openGroup = useCallback((facilities) => {
    detailRequest.current += 1;
    setSelection({ type: "group", facilities });
    setDetail({ facilityId: null, offset: 0, data: null, error: "" });
  }, []);
  const closeSelection = useCallback(() => {
    detailRequest.current += 1;
    setSelection(null);
    setDetail({ facilityId: null, offset: 0, data: null, error: "" });
  }, []);
  const toggleSector = useCallback((code) => {
    setFilters((current) => {
      const values = new Set(current?.sector || []);
      if (values.has(code)) values.delete(code); else values.add(code);
      if (!values.size) return current; // at least one sector stays selected
      return { ...current, sector: [...values].sort() };
    });
  }, []);
  const setAllSectors = useCallback(() => setFilters((current) => ({ ...current, sector: allSectors(catalog) })), [catalog]);
  const setChemical = useCallback((chemical) => setFilters((current) => ({ ...current, chemical })), []);

  const ready = Boolean(requestKey && view.key === requestKey);
  return { enabled, setEnabled, catalog, catalogError, releaseId, filters, toggleSector, setAllSectors, setChemical,
    page, setPage, ready, map: ready ? view.map : null, table: ready ? view.table : null, error: view.error,
    selection, detail, openFacility, openGroup, closeSelection };
}

/** Paginated, searchable TRI chemical list for the active release. */
export function useTriChemicalSearch(releaseId, active) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState({ key: null, data: null, error: "" });
  const requestId = useRef(0);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);
  useEffect(() => { setOffset(0); }, [debounced, releaseId]);
  const key = active && releaseId ? `chemicals?${new URLSearchParams({ release_id: releaseId, q: debounced,
    limit: String(TRI_CHEMICAL_PAGE_SIZE), offset: String(offset) })}` : null;
  useEffect(() => {
    if (!key) return undefined;
    const controller = new AbortController();
    const id = ++requestId.current;
    getTri(key, controller.signal).then((data) => {
      if (id === requestId.current && data.release_id === releaseId) setResult({ key, data, error: "" });
    }).catch((err) => { if (err.name !== "AbortError" && id === requestId.current) setResult({ key: null, data: null, error: err.message }); });
    return () => controller.abort();
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return { query, setQuery, offset, setOffset, data: result.key === key ? result.data : null, error: result.error,
    loading: Boolean(key) && result.key !== key && !result.error };
}

function clusterIcon(count) {
  const size = count >= 1000 ? 46 : count >= 100 ? 38 : count >= 10 ? 32 : 26;
  return L.divIcon({ className: "chip-tri-cluster", iconSize: [size, size], html: `<span>${count.toLocaleString("en-US")}</span>` });
}
function groupIcon(count) {
  return L.divIcon({ className: "chip-tri-colocated", iconSize: [24, 24], html: `<span>${count}</span>` });
}
function stop(event) {
  if (event?.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
}

export function TriFacilityLayer({ tri }) {
  const map = useMap();
  if (!tri.enabled || !tri.map) return null;
  const data = tri.map;
  const groups = data.mode === "points"
    ? groupColocated(data.points.map((p) => ({ ...p, site_id: p.facility_id }))) : [];
  return <Pane name={TRI_PANE} style={{ zIndex: 645 }}>
    {data.mode === "clusters" ? data.clusters.map((cluster) => <Marker key={cluster.id} pane={TRI_PANE}
      position={[cluster.lat, cluster.lon]} icon={clusterIcon(cluster.count)} keyboard={false}
      title={`${cluster.count.toLocaleString("en-US")} TRI reporting facilities grouped for display (not an exposure zone). Select to zoom in.`}
      eventHandlers={{ click: (event) => {
        stop(event);
        const [west, south, east, north] = cluster.bounds;
        if (west === east && south === north) map.setView([south, west], Math.min(map.getZoom() + 3, 18));
        else map.fitBounds([[south, west], [north, east]], { padding: [40, 40], maxZoom: 18 });
      } }} />)
      : groups.map((group) => group.length > 1
        ? <Marker key={`tri:${group[0].location_key}`} pane={TRI_PANE} position={[group[0].lat, group[0].lon]} icon={groupIcon(group.length)}
          keyboard={false} title={`${group.length} distinct TRI facilities share this published location`}
          eventHandlers={{ click: (event) => { stop(event); tri.openGroup(group); } }} />
        : <CircleMarker key={group[0].facility_id} pane={TRI_PANE} center={[group[0].lat, group[0].lon]} radius={5}
          bubblingMouseEvents={false}
          pathOptions={{ color: "#ffffff", weight: 1.5, fillColor: TRI_COLOR, fillOpacity: 0.95 }}
          eventHandlers={{ click: (event) => { stop(event); tri.openFacility(group[0].facility_id); } }} />)}
  </Pane>;
}

function FacilityDetail({ tri, headingRef }) {
  const { selection, detail } = tri;
  if (!selection) return null;
  if (selection.type === "group") {
    return <div className="chip-sites-detail" role="region" aria-labelledby="chip-tri-detail-heading">
      <h3 id="chip-tri-detail-heading" tabIndex={-1} ref={headingRef}>{selection.facilities.length} TRI facilities at one published location</h3>
      <p>These are distinct TRI facility IDs with identical published coordinates. They are not merged.</p>
      <ul>{selection.facilities.map((item) => <li key={item.facility_id}>
        <button type="button" onClick={() => tri.openFacility(item.facility_id)}>{item.facility_name}</button> <span>({item.facility_id})</span>
      </li>)}</ul>
      <button type="button" onClick={tri.closeSelection}>Close</button>
    </div>;
  }
  const data = detail.data;
  const address = data ? [data.address.street_address, data.address.city, data.address.state, data.address.zip].filter(Boolean).join(", ") : "";
  return <div className="chip-sites-detail" role="region" aria-labelledby="chip-tri-detail-heading" aria-busy={!data && !detail.error}>
    <h3 id="chip-tri-detail-heading" tabIndex={-1} ref={headingRef}>{data ? data.facility_name : "Loading facility…"}</h3>
    {detail.error && <p role="alert">{detail.error}</p>}
    {data && <>
      <dl>
        <dt>TRI facility ID</dt><dd>{data.facility_id}</dd>
        <dt>Reporting year</dt><dd>{data.reporting_year} · EPA file processed as of {data.processed_as_of}</dd>
        <dt>Address (as reported)</dt><dd>{address || "Not published"}{data.address.county ? ` · ${data.address.county} County (as reported)` : ""}</dd>
        <dt>Industry sector(s)</dt><dd>{data.sectors.map((s) => `${s.label} (${s.code})`).join("; ")}</dd>
        <dt>Primary NAICS on forms</dt><dd>{data.naics_codes.join(", ") || "—"}</dd>
        <dt>Forms filed</dt><dd>{data.forms.total} ({data.forms.form_r} Form R, {data.forms.form_a} Form A)</dd>
        {data.parent_company && <><dt>Parent company (as reported)</dt><dd>{data.parent_company}</dd></>}
        {data.federal_facility === "YES" && <><dt>Federal facility</dt><dd>Yes</dd></>}
        {data.tribe && <><dt>Tribal land</dt><dd>{data.tribe}</dd></>}
        <dt>Published location</dt><dd>{data.location.published_latitude}, {data.location.published_longitude} (datum not published; drawn as {data.location.crs})
          {data.location.facilities_at_location > 1 ? ` · ${data.location.facilities_at_location} facilities share this location` : ""}
          {data.location.boundary_check === "outside_published_state" ? " · point lies outside the reported state (kept as published)" : ""}
          {data.location.boundary_check === "outside_chip_boundary_layer" ? " · outside CHIP county boundaries" : ""}</dd>
        {data.location.derived_county_geoid && <><dt>County containing the point (CHIP 2024 boundaries)</dt><dd>{data.location.derived_county_name} ({data.location.derived_county_geoid})</dd></>}
      </dl>
      <p><strong>Chemicals reported for {data.reporting_year}</strong> ({data.chemical_total}). Reported does not mean released.</p>
      <ul className="chip-tri-chemicals">{data.chemicals.map((c) => <li key={c.chemical_id}>
        {c.names.join(" / ")}{c.cas_number && c.cas_number !== c.chemical_id ? ` · CAS ${c.cas_number}` : ""} · {c.form_types.map((t) => t === "A" ? "Form A" : "Form R").join(" and ")}{c.forms > 1 ? ` (${c.forms} forms)` : ""}
        {c.generic_identity_note && <span className="pilot-sites-count"> — {c.generic_identity_note}</span>}
      </li>)}</ul>
      {data.chemical_total > TRI_DETAIL_CHEMICAL_PAGE_SIZE && <nav aria-label="Facility chemical pages">
        <button type="button" disabled={detail.offset === 0} onClick={() => tri.openFacility(data.facility_id, Math.max(0, detail.offset - TRI_DETAIL_CHEMICAL_PAGE_SIZE))}>Previous</button>
        {" "}Chemicals {detail.offset + 1}–{Math.min(detail.offset + TRI_DETAIL_CHEMICAL_PAGE_SIZE, data.chemical_total)} of {data.chemical_total}{" "}
        <button type="button" disabled={detail.offset + TRI_DETAIL_CHEMICAL_PAGE_SIZE >= data.chemical_total} onClick={() => tri.openFacility(data.facility_id, detail.offset + TRI_DETAIL_CHEMICAL_PAGE_SIZE)}>Next</button>
      </nav>}
      <p>{data.quantities_note} {data.reporting_note}</p>
      <p><a href={data.epa_link.url} target="_blank" rel="noreferrer noopener">{data.epa_link.label}</a></p>
    </>}
    <button type="button" onClick={tri.closeSelection}>Close</button>
  </div>;
}

function ChemicalFilter({ tri }) {
  const [open, setOpen] = useState(false);
  const search = useTriChemicalSearch(tri.releaseId, open);
  const selected = tri.filters?.chemical;
  return <div className="chip-tri-chemical-filter">
    <p><strong>Reported chemical:</strong> {selected ? selected.label : "Any chemical"}{" "}
      {selected && <button type="button" onClick={() => tri.setChemical(null)}>Clear chemical</button>}</p>
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Choose a chemical</summary>
      <label>Search by name, CAS number, or TRI chemical ID <input type="search" value={search.query}
        onChange={(event) => search.setQuery(event.target.value)} /></label>
      {search.error && <p role="alert">{search.error}</p>}
      {search.loading && <p role="status">Loading chemicals…</p>}
      {search.data && <>
        <p role="status">{search.data.total.toLocaleString("en-US")} chemicals{search.data.q ? ` match “${search.data.q}”` : ""}.</p>
        <ul className="chip-tri-chemical-list">{search.data.rows.map((c) => <li key={c.chemical_id}>
          <button type="button" aria-pressed={selected?.id === c.chemical_id}
            onClick={() => tri.setChemical({ id: c.chemical_id, label: chemicalLabel(c) })}>{chemicalLabel(c)}</button>
          {" "}<span className="pilot-sites-count">({c.mapped_facilities.toLocaleString("en-US")} mapped facilities)</span>
        </li>)}</ul>
        <nav aria-label="Chemical list pages">
          <button type="button" disabled={search.offset === 0} onClick={() => search.setOffset(Math.max(0, search.offset - TRI_CHEMICAL_PAGE_SIZE))}>Previous</button>
          {" "}Page {Math.floor(search.offset / TRI_CHEMICAL_PAGE_SIZE) + 1} of {Math.max(1, Math.ceil(search.data.total / TRI_CHEMICAL_PAGE_SIZE))}{" "}
          <button type="button" disabled={search.offset + TRI_CHEMICAL_PAGE_SIZE >= search.data.total} onClick={() => search.setOffset(search.offset + TRI_CHEMICAL_PAGE_SIZE)}>Next</button>
        </nav>
      </>}
    </details>
  </div>;
}

export function TriFacilityPanel({ tri }) {
  const [open, setOpen] = useState(() => typeof window === "undefined" || window.innerWidth > 700);
  const headingRef = useRef(null);
  const { catalog, filters, map, table, ready } = tri;
  useEffect(() => { if (tri.selection) headingRef.current?.focus(); }, [tri.selection, tri.detail.data]);
  const counts = catalog?.counts || {};
  const notMapped = Object.values(counts.not_mapped_by_reason || {}).reduce((sum, n) => sum + n, 0);
  const allSelected = catalog && filters && filters.sector.length === allSectors(catalog).length;
  return <section className={`pilot-panel pilot-sites pilot-tri ${tri.enabled && open ? "is-open" : ""}`} aria-label="TRI reporting facilities overlay">
    <div className="pilot-sites-head">
      <label><input type="checkbox" checked={tri.enabled} onChange={(event) => tri.setEnabled(event.target.checked)} /> Show TRI reporting facilities</label>
      {tri.enabled && <button type="button" className="pilot-sites-collapse" aria-expanded={open} onClick={() => setOpen((v) => !v)}>{open ? "Hide panel" : "Show panel"}</button>}
    </div>
    {tri.enabled && open && <div className="pilot-sites-body">
      {tri.catalogError && <p role="alert">{tri.catalogError}</p>}
      {!catalog && !tri.catalogError && <p role="status">Loading TRI catalog…</p>}
      {catalog && !tri.releaseId && <p role="status">No TRI facility release is published yet.</p>}
      {catalog && tri.releaseId && <>
        <p className="pilot-metadata">EPA Toxics Release Inventory, reporting year {catalog.reporting_year} · basic data file processed as of {catalog.processed_as_of} · TRI release {tri.releaseId.slice(0, 8)} · independent of the area layer and health center sites.</p>
        <p className="pilot-metadata">{(counts.mapped_facilities ?? 0).toLocaleString("en-US")} of {(counts.facilities ?? 0).toLocaleString("en-US")} reporting facilities are mapped ({(counts.source_reports ?? 0).toLocaleString("en-US")} chemical forms){notMapped ? `; ${notMapped.toLocaleString("en-US")} have no usable published location and are not drawn` : ""}.</p>
        <ul className="pilot-limitations" aria-label="How to read TRI facilities">{catalog.interpretation.map((item) => <li key={item}>{item}</li>)}</ul>
        <ul className="pilot-swatches" aria-label="TRI symbols">
          <li><i className="chip-swatch-dot" style={{ background: TRI_COLOR }} />TRI reporting facility</li>
          <li><i className="chip-swatch-colocated chip-tri-swatch-colocated" />Several facilities at one published location</li>
          <li><i className="chip-swatch-cluster chip-tri-swatch-cluster" />Cluster: display grouping, not an exposure zone</li>
        </ul>
        <ChemicalFilter tri={tri} />
        <details className="pilot-sites-filters">
          <summary>Industry sectors{allSelected ? " (all)" : ` (${filters?.sector.length ?? 0} selected)`}</summary>
          <fieldset>
            <legend>TRI industry sector on the facility's forms</legend>
            {catalog.sectors.map((s) => <label key={s.code}>
              <input type="checkbox" checked={Boolean(filters?.sector.includes(s.code))} onChange={() => tri.toggleSector(s.code)} /> {s.label} <span className="pilot-sites-count">({s.mapped_facilities.toLocaleString("en-US")})</span>
            </label>)}
          </fieldset>
          <button type="button" onClick={tri.setAllSectors}>Select all sectors</button>
        </details>
        <details><summary>Data limits</summary>
          <ul className="pilot-limitations">{catalog.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        </details>
        {tri.error && <p role="alert">{tri.error}</p>}
        {!ready && !tri.error && <p role="status">Loading TRI facilities in view…</p>}
        {ready && map && <p role="status">{map.total.toLocaleString("en-US")} TRI facilities in view under these filters{map.mode === "clusters" ? `, shown as ${map.clusters.length.toLocaleString("en-US")} clusters. ${map.message}` : "."}</p>}
        <FacilityDetail tri={tri} headingRef={headingRef} />
        {ready && table && <>
          <div className="pilot-table-scroll"><table>
            <caption>TRI reporting facilities in view (same filters and viewport as the map), reporting year {table.reporting_year}</caption>
            <thead><tr><th scope="col">Facility</th><th scope="col">City, state</th><th scope="col">Sector(s)</th><th scope="col">Chemicals</th><th scope="col"><span className="visually-hidden">Details</span></th></tr></thead>
            <tbody>{table.rows.map((row) => <tr key={row.facility_id}>
              <th scope="row">{row.facility_name}</th><td>{[row.city, row.state].filter(Boolean).join(", ")}</td>
              <td>{row.sectors.map((s) => s.label).join("; ")}</td><td>{row.chemical_count}</td>
              <td><button type="button" onClick={() => tri.openFacility(row.facility_id)} aria-label={`Details for ${row.facility_name}`}>Details</button></td>
            </tr>)}</tbody>
          </table></div>
          <nav aria-label="TRI facility table pages"><button type="button" disabled={tri.page === 0} onClick={() => tri.setPage(tri.page - 1)}>Previous</button> Page {tri.page + 1} of {Math.max(1, Math.ceil(table.total / TRI_PAGE_SIZE))} <button type="button" disabled={(tri.page + 1) * TRI_PAGE_SIZE >= table.total} onClick={() => tri.setPage(tri.page + 1)}>Next</button></nav>
        </>}
        <p className="pilot-metadata">Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">EPA TRI basic data files</a>. {catalog.usage_terms}</p>
      </>}
    </div>}
  </section>;
}
