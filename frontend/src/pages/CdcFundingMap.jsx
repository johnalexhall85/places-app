import { useEffect, useMemo, useState } from "react";
import { geoAlbersUsa, geoCentroid, geoMercator, geoPath } from "d3-geo";
import SiteHeader from "../components/SiteHeader";
import Footer from "../components/Footer";
import { fiscalYears, fundingMap, fundingMapShapes, stateSummary } from "../api/stateFunding";
import "./CdcFundingMap.css";

const TILE_CODES = ["DC", "PR", "GU", "VI", "AS", "MP", "FM", "MH", "PW"];
const TILE_NAMES = {
  DC: "District of Columbia", PR: "Puerto Rico", GU: "Guam",
  VI: "U.S. Virgin Islands", AS: "American Samoa", MP: "Northern Mariana Islands",
  FM: "Federated States of Micronesia", MH: "Marshall Islands", PW: "Palau",
};
const BLUE = ["#dcecf6", "#a9d4ed", "#75b9de", "#0277bd", "#003f61"];
const ORANGE = ["#f0b97d", "#e89555", "#bb5d2c"];
const EMPTY = "#e3e7e9";
const PR_INSET = { x: 834, y: 440, width: 124, height: 106, centerX: 895, centerY: 481 };
const amount = (value) => `${Number(value) < 0 ? "−" : ""}$${Math.round(Math.abs(Number(value || 0)))
  .toLocaleString("en-US")}`;
const exact = (value) => `${Number(value) < 0 ? "−" : ""}$${Math.abs(Number(value || 0))
  .toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const compact = (value) => {
  const absolute = Math.abs(Number(value || 0));
  const sign = Number(value) < 0 ? "−" : "";
  if (absolute >= 1e9) return `${sign}$${(absolute / 1e9).toFixed(1)} billion`;
  if (absolute >= 1e6) return `${sign}$${(absolute / 1e6).toFixed(1)} million`;
  if (absolute >= 1e3) return `${sign}$${(absolute / 1e3).toFixed(1)} thousand`;
  return `${sign}$${absolute.toFixed(1)}`;
};
const grantLabel = (count) => `${Number(count).toLocaleString("en-US")} ${count === 1 ? "grant" : "grants"}`;

function initialParams() {
  const search = new URLSearchParams(window.location.search);
  return {
    fy: search.get("fy") || "",
    funding_type: ["all", "regular", "supplemental"].includes(search.get("funding_type"))
      ? search.get("funding_type") : "all",
    category: search.get("category") || "",
    state: search.get("state") || "",
    deobligations: search.get("deobligations") === "exclude" ? "exclude" : "include",
  };
}

function classes(values, colors) {
  const sorted = [...values].sort((a, b) => a - b);
  const count = Math.min(colors.length, sorted.length);
  const quantiles = Array.from({ length: count }, (_, index) => ({
    min: sorted[Math.floor(index * sorted.length / count)],
    max: sorted[Math.floor((index + 1) * sorted.length / count) - 1],
    color: colors[Math.floor(index * colors.length / count)],
  }));
  return quantiles.reduce((merged, current) => {
    const previous = merged.at(-1);
    if (previous && compact(previous.max) === compact(current.min)) {
      previous.max = current.max;
      previous.color = current.color;
    } else {
      merged.push({ ...current });
    }
    return merged;
  }, []);
}

const legendRange = (start, end) => compact(start) === compact(end)
  ? compact(start) : `${compact(start)} to ${compact(end)}`;

export default function CdcFundingMap() {
  const [params, setParams] = useState(initialParams);
  const [years, setYears] = useState(null);
  const [shapes, setShapes] = useState(null);
  const [data, setData] = useState(null);
  const [summary, setSummary] = useState(null);
  const [tooltip, setTooltip] = useState(null);
  const [tableSort, setTableSort] = useState("name");
  const [error, setError] = useState("");

  useEffect(() => {
    const onPop = () => setParams(initialParams());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    const onEscape = (event) => {
      if (event.key === "Escape" && params.state) update({ state: "" });
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [params]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([fiscalYears(controller.signal), fundingMapShapes(controller.signal)])
      .then(([yearData, shapeData]) => {
        setYears(yearData);
        setShapes(shapeData.states);
        setParams((current) => ({ ...current, fy: current.fy || String(yearData.default || "") }));
      })
      .catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!params.fy) return undefined;
    const controller = new AbortController();
    setError("");
    setData(null);
    fundingMap({
      fy: params.fy, funding_type: params.funding_type, category: params.category,
      deobligations: params.deobligations,
    }, controller.signal)
      .then(setData)
      .catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [params.fy, params.funding_type, params.category, params.deobligations]);

  useEffect(() => {
    if (!params.state || !data || params.category) {
      setSummary(null);
      return undefined;
    }
    const controller = new AbortController();
    setSummary(null);
    stateSummary(params.state, {
      fy: params.fy, funding_type: params.funding_type, award_type: "grant",
      deobligations: params.deobligations,
    }, controller.signal)
      .then(setSummary)
      .catch(() => { if (!controller.signal.aborted) setSummary(null); });
    return () => controller.abort();
  }, [params.state, params.fy, params.funding_type, params.category, params.deobligations, data]);

  const update = (changes) => {
    const next = { ...params, ...changes };
    const query = new URLSearchParams({
      fy: next.fy, funding_type: next.funding_type, category: next.category, state: next.state,
    });
    if (next.deobligations === "exclude") query.set("deobligations", "exclude");
    window.history.pushState({}, "", `${window.location.pathname}?${query}`);
    setParams(next);
    setTooltip(null);
  };

  const rows = useMemo(() => {
    if (!data || !shapes) return [];
    const byCode = Object.fromEntries(data.states.map((state) => [state.code, state]));
    return [...new Set([...Object.keys(shapes), ...Object.keys(TILE_NAMES), ...Object.keys(byCode)])]
      .map((code) => byCode[code] || {
        code, fips: shapes[code]?.fips || null,
        name: shapes[code]?.name || TILE_NAMES[code] || code,
        total: 0, regular: 0, supplemental: 0, award_count: 0, recipient_count: 0,
        indicators_geoid: null, has_shape: !!shapes[code], no_grants: true,
      });
  }, [data, shapes]);
  const byCode = useMemo(() => Object.fromEntries(rows.map((row) => [row.code, row])), [rows]);
  const tileCodes = TILE_CODES.filter((code) => code === "DC" || code === "PR"
    || data?.states.some((row) => row.code === code && row.has_shape === false));
  const positive = useMemo(() => classes(rows.filter((row) => !row.no_grants && row.total > 0)
    .map((row) => row.total), BLUE), [rows]);
  const negative = useMemo(() => classes(rows.filter((row) => !row.no_grants && row.total < 0)
    .map((row) => Math.abs(row.total)), ORANGE), [rows]);
  const fill = (row) => {
    if (!row || row.no_grants || row.total === 0) return EMPTY;
    const scale = row.total < 0 ? negative : positive;
    const value = Math.abs(row.total);
    return scale.find((item) => value >= item.min && value <= item.max)?.color || EMPTY;
  };
  const geometries = useMemo(() => {
    if (!shapes) return [];
    const entries = Object.entries(shapes).map(([code, shape]) => ({
      code, feature: { type: "Feature", properties: { code }, geometry: shape.geometry },
    }));
    const mainland = entries.filter(({ code }) => code !== "PR");
    const projection = geoAlbersUsa().fitSize([960, 540], {
      type: "FeatureCollection", features: mainland.map(({ feature }) => feature),
    });
    const path = geoPath(projection);
    const puertoRico = entries.find(({ code }) => code === "PR");
    const prPath = puertoRico && geoPath(geoMercator()
      .scale(projection.scale())
      .center(geoCentroid(puertoRico.feature))
      .translate([PR_INSET.centerX, PR_INSET.centerY]))(puertoRico.feature);
    return entries.map(({ code, feature }) => ({
      code, path: code === "PR" ? prPath : path(feature),
    })).filter(({ path: shapePath }) => shapePath);
  }, [shapes]);

  const openTooltip = (event, row) => {
    if (event.pointerType === "touch") return;
    const box = event.currentTarget.closest(".cfm-map-frame").getBoundingClientRect();
    const element = event.currentTarget.getBoundingClientRect();
    setTooltip({ row, x: element.left + element.width / 2 - box.left, y: element.top - box.top });
  };
  const open = (code) => update({ state: code });
  const selected = byCode[params.state];
  const categoryLabel = data?.categories_available.find((item) => item.code === params.category)?.name
    || "All categories";
  const fundingLabel = { all: "All funding", regular: "Regular", supplemental: "Supplemental" }[params.funding_type];
  const profileQuery = new URLSearchParams({
    fy: params.fy, funding_type: params.funding_type, category: params.category, award_type: "grant",
  });
  const tableRows = [...rows].sort((left, right) => tableSort === "amount"
    ? right.total - left.total || left.name.localeCompare(right.name)
    : left.name.localeCompare(right.name));
  const categories = summary?.by_category?.slice().sort((left, right) =>
    Math.abs(right.total) - Math.abs(left.total)).slice(0, 5) || [];

  return (
    <div className="cfm-page">
      <SiteHeader />
      <main id="main" className="cfm-main">
        <a href="/cdc-funding">← CDC funding overview</a>
        <header className="cfm-hero">
          <p className="cfm-eyebrow">CDC funding · National map</p>
          <h1>CDC grants to recipients by state</h1>
          <p>
            {data?.period || (params.fy ? `FY${params.fy}` : "Loading fiscal years…")}
            {params.deobligations === "exclude" && " · Deobligations excluded"}
          </p>
        </header>
        {error && <p role="alert" className="cfm-card">{error}</p>}
        <section className="cfm-controls cfm-card" aria-label="Map filters">
          <label>Fiscal year
            <select value={params.fy} onChange={(event) => update({ fy: event.target.value, category: "", state: "" })}>
              {years?.fiscal_years.map((year) => <option key={year} value={year}>FY{year}</option>)}
            </select>
          </label>
          <label>Budget category
            <select value={params.category} onChange={(event) => update({ category: event.target.value, state: "" })}>
              <option value="">All categories</option>
              {data?.categories_available.map((category) =>
                <option key={category.code} value={category.code}>{category.name}</option>)}
            </select>
          </label>
          <label>Funding type
            <select value={params.funding_type}
              onChange={(event) => update({ funding_type: event.target.value, state: "" })}>
              <option value="all">All funding</option>
              <option value="regular">Regular</option>
              <option value="supplemental">Supplemental</option>
            </select>
          </label>
          <label className="cfm-checkbox">
            <input type="checkbox" checked={params.deobligations === "exclude"}
              onChange={(event) => update({
                deobligations: event.target.checked ? "exclude" : "include",
              })} />
            Exclude deobligations
          </label>
        </section>
        {!data && !error && <p role="status" className="cfm-card">Loading map data…</p>}
        {data && shapes && <>
          <div className="cfm-content">
            <section className="cfm-card cfm-map-section" aria-label="State funding map">
              <div className="cfm-map-frame">
                <svg viewBox="0 0 960 550" role="img" aria-label="CDC grant amounts by recipient state">
                  {shapes.PR && <rect className="cfm-inset-frame" x={PR_INSET.x} y={PR_INSET.y}
                    width={PR_INSET.width} height={PR_INSET.height} />}
                  {geometries.map(({ code, path }) => {
                    const row = byCode[code];
                    return (
                      <path key={code} d={path} fill={fill(row)} className="cfm-state"
                        tabIndex={0} role="button"
                        aria-label={`${row.name}: ${row.no_grants ? "No grants" : amount(row.total)}`}
                        onPointerEnter={(event) => openTooltip(event, row)}
                        onPointerLeave={() => setTooltip(null)}
                        onFocus={(event) => openTooltip(event, row)}
                        onBlur={() => setTooltip(null)}
                        onClick={() => open(code)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            open(code);
                          }
                        }}
                      />
                    );
                  })}
                  {shapes.PR && <text x="846" y="529" className="cfm-inset-label">Puerto Rico</text>}
                </svg>
                {tooltip && <div role="tooltip" className="cfm-tooltip"
                  style={{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }}>
                  <strong>{tooltip.row.name}</strong>
                  <span>{tooltip.row.no_grants ? "No grants" : amount(tooltip.row.total)}</span>
                  <span>{grantLabel(tooltip.row.award_count)}</span>
                </div>}
              </div>
              <div className="cfm-tiles" aria-label="District and territory tiles">
                {tileCodes.map((code) => {
                  const row = byCode[code];
                  return <button key={code} className="cfm-tile" style={{ borderColor: fill(row) }}
                    onClick={() => open(code)}>
                    <strong>{code}</strong><span>{row?.name || TILE_NAMES[code]}</span>
                    <span>{row?.no_grants ? "No grants" : amount(row?.total)}</span>
                  </button>;
                })}
              </div>
              <div className="cfm-legend" aria-label="Map legend">
                {negative.length > 0 && <span className="cfm-legend-title">Net reduction</span>}
                {negative.map((item, index) => <span key={`negative-${index}`}>
                  <i style={{ background: item.color }} />{legendRange(-item.max, -item.min)}
                </span>)}
                <span><i style={{ background: EMPTY }} />Zero / No grants</span>
                {positive.map((item, index) => <span key={`positive-${index}`}>
                  <i style={{ background: item.color }} />{legendRange(item.min, item.max)}
                </span>)}
              </div>
            </section>
            {selected && <aside className="cfm-card cfm-detail" aria-label="Selected state">
              <button className="cfm-close" onClick={() => update({ state: "" })}
                aria-label="Close state details">×</button>
              <h2>{selected.name}</h2>
              <p>FY{params.fy} · {categoryLabel} · {fundingLabel}</p>
              <dl>
                {[['Total', selected.total, true], ['Regular', selected.regular, true],
                  ['Supplemental', selected.supplemental, true], ['Grants', selected.award_count, false],
                  ['Recipients', selected.recipient_count, false]].map(([label, value, currency]) =>
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{currency ? amount(value) : Number(value).toLocaleString()}</dd>
                  </div>)}
              </dl>
              {!params.category && categories.length > 0 && <section>
                <h3>Largest budget categories</h3>
                <ul>{categories.map((category) => <li key={category.code}>
                  <span>{category.name}</span><strong>{amount(category.total)}</strong>
                </li>)}</ul>
              </section>}
              <div className="cfm-detail-links">
                {selected.indicators_geoid && <a href={`/community/state/${selected.indicators_geoid}`}>
                  State indicators</a>}
                <a href={`/cdc-funding/state/${selected.code}?${profileQuery}`}>State funding profile</a>
              </div>
              {params.deobligations === "exclude" && <p>
                The state funding profile shows net amounts, including deobligations.
              </p>}
            </aside>}
          </div>
          <section className="cfm-card cfm-notes">
            <div className="cfm-kpi"><span>National total</span>
              <strong title={exact(data.national.total)}>{compact(data.national.total)}</strong>
              <span className="cfm-sr-only">Exact amount: {exact(data.national.total)}</span>
            </div>
            <p>{grantLabel(data.national.award_count)} nationwide</p>
            <p>
              {amount(data.unattributed.total)} in {grantLabel(data.unattributed.award_count)} has no recipient
              state and is not mapped.
            </p>
            {data.notes.map((note) => <p key={note}>{note}</p>)}
            <p className="cfm-source">{data.citation}</p>
          </section>
          <details className="cfm-card cfm-table-section">
            <summary>Table of states</summary>
            <div className="cfm-table-wrap">
              <table><thead><tr>
                <th><button onClick={() => setTableSort("name")}>State ↕</button></th>
                <th><button onClick={() => setTableSort("amount")}>Amount ↕</button></th>
                <th>Grants</th>
              </tr></thead><tbody>
                {tableRows.map((row) => <tr key={row.code}>
                  <th><button onClick={() => open(row.code)}>{row.name}</button></th>
                  <td>{row.no_grants ? "No grants" : amount(row.total)}</td>
                  <td>{row.award_count.toLocaleString("en-US")}</td>
                </tr>)}
              </tbody></table>
            </div>
          </details>
        </>}
      </main>
      <Footer />
    </div>
  );
}
