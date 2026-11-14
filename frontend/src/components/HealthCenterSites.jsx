import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { CircleMarker, Marker, Pane, useMap } from "react-leaflet";
import { API_BASE } from "../config/apiBase";

// Optional HRSA health center site overlay. Its release, filters, requests, and cache are independent
// of the area layer: switching area measure or dataset never changes the site release, and vice versa.

export const SITES_PANE = "chip-health-center-sites";
export const SITE_PAGE_SIZE = 50;
const STORAGE_KEY = "chip.healthCenterSites.v1";
const FILTER_NAMES = ["program", "site_type", "location_type", "setting"];
const CACHE_LIMIT = 150;
const cache = new Map();
export const PROGRAM_COLORS = { fqhc: "#0b6e69", look_alike: "#9a4f00" };

function cacheGet(key) { return cache.get(key); }
function cacheSet(key, value) {
  cache.set(key, value);
  if (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value);
}
export function clearSiteCache() { cache.clear(); }

async function getSites(path, signal) {
  const cached = cacheGet(path);
  if (cached) return cached;
  const response = await fetch(`${API_BASE}/area/sites/${path}`, { signal });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body.detail || `Health center site request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  const data = await response.json();
  // Catalog responses change when a pointer moves; only release-pinned responses are cached.
  if (!path.startsWith("catalog")) cacheSet(path, data);
  return data;
}

export function defaultFilters(catalog) {
  return Object.fromEntries((catalog?.filters || []).map((group) => [group.name, group.values.filter((v) => v.default).map((v) => v.code).sort()]));
}

export function siteQuery({ releaseId, bbox, zoom, filters, limit, offset }) {
  const params = new URLSearchParams({ release_id: releaseId, bbox });
  if (zoom != null) params.set("zoom", String(zoom));
  FILTER_NAMES.forEach((name) => { if (filters?.[name]) params.set(name, [...filters[name]].sort().join(",")); });
  if (limit != null) params.set("limit", String(limit));
  if (offset != null) params.set("offset", String(offset));
  return params;
}

export function groupColocated(points) {
  const groups = new Map();
  points.forEach((point) => {
    const list = groups.get(point.location_key) || [];
    list.push(point);
    groups.set(point.location_key, list);
  });
  return [...groups.values()];
}

function readStored() {
  try { return JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || "null"); } catch { return null; }
}
function writeStored(value) {
  try { window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

function sameFilters(a, b) {
  return FILTER_NAMES.every((name) => [...(a?.[name] || [])].sort().join(",") === [...(b?.[name] || [])].sort().join(","));
}

export function useHealthCenterSites({ bbox, zoom }) {
  const stored = useMemo(readStored, []);
  const [enabled, setEnabled] = useState(Boolean(stored?.enabled));
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState("");
  const [filters, setFilters] = useState(null);
  const [page, setPage] = useState(0);
  const [view, setView] = useState({ key: null, map: null, table: null, error: "" });
  const [selection, setSelection] = useState(null); // {type:'site', siteId} | {type:'group', sites}
  const [detail, setDetail] = useState({ siteId: null, data: null, error: "" });
  const requestId = useRef(0);
  const detailRequest = useRef(0);
  const zoomLevel = Math.max(0, Math.floor(zoom ?? 0));
  const releaseId = catalog?.active_release_id || null;

  useEffect(() => {
    if (!enabled || catalog) return undefined;
    const controller = new AbortController();
    getSites("catalog", controller.signal).then((data) => {
      setCatalog(data);
      const defaults = defaultFilters(data);
      const valid = stored?.filters && FILTER_NAMES.every((name) => Array.isArray(stored.filters[name]) && stored.filters[name].length
        && stored.filters[name].every((code) => data.filters?.find((g) => g.name === name)?.values.some((v) => v.code === code)));
      setFilters(valid ? stored.filters : defaults);
    }).catch((err) => { if (err.name !== "AbortError") setCatalogError(err.message); });
    return () => controller.abort();
  }, [enabled, catalog, stored]);

  useEffect(() => { writeStored({ enabled, filters }); }, [enabled, filters]);
  useEffect(() => { setPage(0); }, [bbox, zoomLevel, filters, releaseId]);

  const requestKey = enabled && releaseId && bbox && filters
    ? `${siteQuery({ releaseId, bbox, zoom: zoomLevel, filters })}|${page}` : null;

  useEffect(() => {
    if (!requestKey) return undefined;
    const controller = new AbortController();
    const id = ++requestId.current;
    const mapPath = `map?${siteQuery({ releaseId, bbox, zoom: zoomLevel, filters })}`;
    const tablePath = `table?${siteQuery({ releaseId, bbox, filters, limit: SITE_PAGE_SIZE, offset: page * SITE_PAGE_SIZE })}`;
    setView((current) => ({ ...current, error: "" }));
    Promise.all([getSites(mapPath, controller.signal), getSites(tablePath, controller.signal)]).then(([map, table]) => {
      if (id !== requestId.current) return; // a newer viewport, filter, or release request superseded this one
      if (map.release_id !== releaseId || table.release_id !== releaseId || !sameFilters(map.filters, filters)
          || !sameFilters(table.filters, filters) || map.bbox !== bbox || table.bbox !== bbox) {
        throw new Error("Site response did not match the requested release, viewport, or filters");
      }
      if (map.total !== table.total) throw new Error("Site map and table totals differ; retry");
      setView({ key: requestKey, map, table, error: "" });
    }).catch((err) => {
      if (err.name !== "AbortError" && id === requestId.current) setView({ key: null, map: null, table: null, error: err.message });
    });
    return () => controller.abort();
  }, [requestKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const openSite = useCallback((siteId) => {
    if (!releaseId) return;
    setSelection({ type: "site", siteId });
    const id = ++detailRequest.current;
    setDetail({ siteId, data: null, error: "" });
    getSites(`detail?${new URLSearchParams({ release_id: releaseId, site_id: siteId })}`).then((data) => {
      if (id === detailRequest.current && data.release_id === releaseId) setDetail({ siteId, data, error: "" });
    }).catch((err) => { if (id === detailRequest.current) setDetail({ siteId, data: null, error: err.message }); });
  }, [releaseId]);
  const openGroup = useCallback((sites) => { detailRequest.current += 1; setSelection({ type: "group", sites }); setDetail({ siteId: null, data: null, error: "" }); }, []);
  const closeSelection = useCallback(() => { detailRequest.current += 1; setSelection(null); setDetail({ siteId: null, data: null, error: "" }); }, []);
  const toggleFilter = useCallback((name, code) => {
    setFilters((current) => {
      const values = new Set(current?.[name] || []);
      if (values.has(code)) values.delete(code); else values.add(code);
      if (!values.size) return current; // at least one value per group stays selected
      return { ...current, [name]: [...values].sort() };
    });
  }, []);
  const resetFilters = useCallback(() => setFilters(defaultFilters(catalog)), [catalog]);

  const ready = Boolean(requestKey && view.key === requestKey);
  return { enabled, setEnabled, catalog, catalogError, releaseId, filters, toggleFilter, resetFilters,
    page, setPage, ready, map: ready ? view.map : null, table: ready ? view.table : null, error: view.error,
    selection, detail, openSite, openGroup, closeSelection };
}

function clusterIcon(count) {
  const size = count >= 1000 ? 46 : count >= 100 ? 38 : count >= 10 ? 32 : 26;
  return L.divIcon({ className: "chip-site-cluster", iconSize: [size, size],
    html: `<span>${count.toLocaleString("en-US")}</span>` });
}
function groupIcon(count) {
  return L.divIcon({ className: "chip-site-colocated", iconSize: [24, 24], html: `<span>${count}</span>` });
}
function stop(event) {
  if (event?.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
}

export function HealthCenterSiteLayer({ sites }) {
  const map = useMap();
  if (!sites.enabled || !sites.map) return null;
  const data = sites.map;
  return <Pane name={SITES_PANE} style={{ zIndex: 640 }}>
    {data.mode === "clusters" ? data.clusters.map((cluster) => <Marker key={cluster.id} pane={SITES_PANE}
      position={[cluster.lat, cluster.lon]} icon={clusterIcon(cluster.count)} keyboard={false}
      title={`${cluster.count.toLocaleString("en-US")} health center sites grouped for display (not a service area). Select to zoom in.`}
      eventHandlers={{ click: (event) => {
        stop(event);
        const [west, south, east, north] = cluster.bounds;
        if (west === east && south === north) map.setView([south, west], Math.min(map.getZoom() + 3, 18));
        else map.fitBounds([[south, west], [north, east]], { padding: [40, 40], maxZoom: 18 });
      } }} />)
      : groupColocated(data.points).map((group) => group.length > 1
        ? <Marker key={group[0].location_key} pane={SITES_PANE} position={[group[0].lat, group[0].lon]} icon={groupIcon(group.length)}
          keyboard={false} title={`${group.length} distinct sites share this published location`}
          eventHandlers={{ click: (event) => { stop(event); sites.openGroup(group); } }} />
        : <CircleMarker key={group[0].site_id} pane={SITES_PANE} center={[group[0].lat, group[0].lon]} radius={6}
          bubblingMouseEvents={false}
          pathOptions={{ color: "#ffffff", weight: 1.5, fillColor: PROGRAM_COLORS[group[0].program] || "#333", fillOpacity: 0.95 }}
          eventHandlers={{ click: (event) => { stop(event); sites.openSite(group[0].site_id); } }} />)}
  </Pane>;
}

function SiteDetail({ sites, headingRef }) {
  const { selection, detail } = sites;
  if (!selection) return null;
  if (selection.type === "group") {
    return <div className="chip-sites-detail" role="region" aria-labelledby="chip-site-detail-heading">
      <h3 id="chip-site-detail-heading" tabIndex={-1} ref={headingRef}>{selection.sites.length} sites at one published location</h3>
      <p>These are distinct HRSA sites with identical published coordinates. They are not merged.</p>
      <ul>{selection.sites.map((item) => <li key={item.site_id}>
        <button type="button" onClick={() => sites.openSite(item.site_id)}>{item.site_name}</button> <span>({item.site_type_label})</span>
      </li>)}</ul>
      <button type="button" onClick={sites.closeSelection}>Close</button>
    </div>;
  }
  const data = detail.data;
  const a = data?.attributes || {};
  return <div className="chip-sites-detail" role="region" aria-labelledby="chip-site-detail-heading" aria-busy={!data && !detail.error}>
    <h3 id="chip-site-detail-heading" tabIndex={-1} ref={headingRef}>{data ? a.site_name : "Loading site…"}</h3>
    {detail.error && <p role="alert">{detail.error}</p>}
    {data && <dl>
      <dt>Organization (awardee or look-alike)</dt><dd>{a.organization_name} · {a.health_center_number}</dd>
      <dt>Program</dt><dd>{data.program_label}</dd>
      <dt>Site type</dt><dd>{data.site_type_label}</dd>
      <dt>Location type</dt><dd>{data.location_type_label}</dd>
      <dt>Setting</dt><dd>{data.setting_label}</dd>
      <dt>Address</dt><dd>{[a.site_address, a.site_city, a.site_state, a.site_postal_code].filter(Boolean).join(", ") || "Not published"}</dd>
      <dt>County (HRSA)</dt><dd>{a.county_name || "—"}{a.county_fips ? ` (${a.county_fips})` : ""}</dd>
      <dt>Phone</dt><dd>{a.site_phone || "Not published"}</dd>
      <dt>Website</dt><dd>{a.site_website ? <a href={/^https?:\/\//i.test(a.site_website) ? a.site_website : `https://${a.site_website}`} target="_blank" rel="noreferrer noopener">{a.site_website}</a> : "Not published"}</dd>
      <dt>Operating hours per week</dt><dd>{a.operating_hours_per_week || "Not published"}{a.operating_schedule && a.operating_schedule !== "Unknown" ? ` · ${a.operating_schedule}` : ""}{a.operating_calendar && a.operating_calendar !== "Unknown" ? ` · ${a.operating_calendar}` : ""}</dd>
      <dt>Operator</dt><dd>{a.operator_type || "—"}</dd>
      <dt>HRSA site ID</dt><dd>{data.site_id}</dd>
      <dt>Published location</dt><dd>{data.location.published_y}, {data.location.published_x} ({data.location.crs}){data.location.sites_at_location > 1 ? ` · ${data.location.sites_at_location} sites share this location` : ""}{data.location.boundary_check === "outside_chip_boundary_layer" ? " · not cross-checked (area outside CHIP county boundaries)" : ""}</dd>
    </dl>}
    {data && <p>{data.services_note} HRSA snapshot {data.snapshot_date}.</p>}
    <button type="button" onClick={sites.closeSelection}>Close</button>
  </div>;
}

export function HealthCenterSitePanel({ sites }) {
  // Narrow screens start with only the toggle row visible; the panel can be expanded.
  const [open, setOpen] = useState(() => typeof window === "undefined" || window.innerWidth > 700);
  const headingRef = useRef(null);
  const { catalog, filters, map, table, ready } = sites;
  useEffect(() => { if (sites.selection) headingRef.current?.focus(); }, [sites.selection, sites.detail.data]);
  const counts = catalog?.counts || {};
  const notMapped = Object.values(counts.not_mapped_by_reason || {}).reduce((sum, n) => sum + n, 0);
  return <section className={`pilot-panel pilot-sites ${sites.enabled && open ? "is-open" : ""}`} aria-label="Health center sites overlay">
    <div className="pilot-sites-head">
      <label><input type="checkbox" checked={sites.enabled} onChange={(event) => sites.setEnabled(event.target.checked)} /> Show HRSA health center sites</label>
      {sites.enabled && <button type="button" className="pilot-sites-collapse" aria-expanded={open} onClick={() => setOpen((v) => !v)}>{open ? "Hide panel" : "Show panel"}</button>}
    </div>
    {sites.enabled && open && <div className="pilot-sites-body">
      {sites.catalogError && <p role="alert">{sites.catalogError}</p>}
      {!catalog && !sites.catalogError && <p role="status">Loading site catalog…</p>}
      {catalog && !sites.releaseId && <p role="status">No health center site release is published yet.</p>}
      {catalog && sites.releaseId && <>
        <p className="pilot-metadata">HRSA Health Center Service Delivery and Look-Alike Sites · snapshot {catalog.snapshot_date} (current directory, not an annual period) · site release {sites.releaseId.slice(0, 8)} · independent of the area layer.</p>
        <p className="pilot-metadata">{(counts.mapped_eligible_sites ?? 0).toLocaleString("en-US")} of {(counts.source_sites ?? 0).toLocaleString("en-US")} listed sites are mapped; {notMapped.toLocaleString("en-US")} are listed without a mappable exact location (suppressed, not published, or approximate) and are not drawn.</p>
        <ul className="pilot-swatches" aria-label="Site symbols">
          <li><i className="chip-swatch-dot" style={{ background: PROGRAM_COLORS.fqhc }} />Health Center Program awardee site</li>
          <li><i className="chip-swatch-dot" style={{ background: PROGRAM_COLORS.look_alike }} />Look-alike site</li>
          <li><i className="chip-swatch-colocated" />Several sites at one published location</li>
          <li><i className="chip-swatch-cluster" />Cluster: display grouping, not a service area</li>
        </ul>
        <details className="pilot-sites-filters">
          <summary>Filters</summary>
          {catalog.filters.map((group) => <fieldset key={group.name}>
            <legend>{group.label}</legend>
            {group.values.map((value) => <label key={value.code}>
              <input type="checkbox" checked={Boolean(filters?.[group.name]?.includes(value.code))}
                onChange={() => sites.toggleFilter(group.name, value.code)} /> {value.label} <span className="pilot-sites-count">({value.mapped_sites.toLocaleString("en-US")})</span>
            </label>)}
          </fieldset>)}
          <button type="button" onClick={sites.resetFilters}>Reset to service-delivery defaults</button>
        </details>
        <details><summary>Location limits and interpretation</summary>
          <ul className="pilot-limitations">{catalog.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        </details>
        {sites.error && <p role="alert">{sites.error}</p>}
        {!ready && !sites.error && <p role="status">Loading sites in view…</p>}
        {ready && map && <p role="status">{map.total.toLocaleString("en-US")} sites in view under these filters{map.mode === "clusters" ? `, shown as ${map.clusters.length.toLocaleString("en-US")} clusters. ${map.message}` : "."}</p>}
        <SiteDetail sites={sites} headingRef={headingRef} />
        {ready && table && <>
          <div className="pilot-table-scroll"><table>
            <caption>Health center sites in view (same filters and viewport as the map), snapshot {table.snapshot_date}</caption>
            <thead><tr><th scope="col">Site</th><th scope="col">Organization</th><th scope="col">City, state</th><th scope="col">Site type</th><th scope="col"><span className="visually-hidden">Details</span></th></tr></thead>
            <tbody>{table.rows.map((row) => <tr key={row.site_id}>
              <th scope="row">{row.site_name}</th><td>{row.organization_name}</td><td>{[row.city, row.state].filter(Boolean).join(", ")}</td><td>{row.site_type_label}</td>
              <td><button type="button" onClick={() => sites.openSite(row.site_id)} aria-label={`Details for ${row.site_name}`}>Details</button></td>
            </tr>)}</tbody>
          </table></div>
          <nav aria-label="Health center site table pages"><button type="button" disabled={sites.page === 0} onClick={() => sites.setPage(sites.page - 1)}>Previous</button> Page {sites.page + 1} of {Math.max(1, Math.ceil(table.total / SITE_PAGE_SIZE))} <button type="button" disabled={(sites.page + 1) * SITE_PAGE_SIZE >= table.total} onClick={() => sites.setPage(sites.page + 1)}>Next</button></nav>
        </>}
        <p className="pilot-metadata">Source: <a href={catalog.source_url} target="_blank" rel="noreferrer">HRSA data downloads</a>. {catalog.usage_terms}</p>
      </>}
    </div>}
  </section>;
}
