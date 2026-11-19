import { useEffect, useMemo, useState } from "react";
import SiteHeader from "../components/SiteHeader";
import Footer from "../components/Footer";
import { fiscalYears, stateSummary, stateGrants, grantsCsvUrl } from "../api/stateFunding";
import "./CdcStateFundingProfile.css";

const DEFAULTS = { funding_type: "all", award_type: "all", account: "", recipient_type: "all", q: "", sort: "amount", dir: "desc", page: "1", page_size: "25" };
const NAME_SOURCES = { grants_gov_nofo_title: "NOFO title (Grants.gov)", cdc_funding_profiles_nofo_title: "NOFO title (CDC Funding Profiles)", taggs_award_title: "Project title (TAGGS)", assistance_listing_title: "Assistance listing", award_description: "Award description" };
const amount = (value) => `${Number(value) < 0 ? "−" : "+"}$${Math.abs(Number(value || 0)).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function readParams() {
  const incoming = new URLSearchParams(window.location.search);
  const next = { ...DEFAULTS };
  for (const key of ["fy", ...Object.keys(DEFAULTS)]) if (incoming.has(key)) next[key] = incoming.get(key);
  return next;
}

export default function CdcStateFundingProfile({ stateCode }) {
  const code = String(stateCode || "").toUpperCase();
  const [params, setParams] = useState(readParams);
  const [search, setSearch] = useState(params.q);
  const [years, setYears] = useState(null);
  const [summary, setSummary] = useState(null);
  const [grants, setGrants] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [showTable, setShowTable] = useState(false);
  const [expanded, setExpanded] = useState({});

  useEffect(() => { const onPop = () => { const p = readParams(); setParams(p); setSearch(p.q); }; window.addEventListener("popstate", onPop); return () => window.removeEventListener("popstate", onPop); }, []);
  useEffect(() => { const timer = setTimeout(() => { if (search !== params.q) update({ q: search, page: "1" }); }, 300); return () => clearTimeout(timer); }, [search]); // Debounced search shares the URL.
  function update(changes) {
    setParams((current) => {
      const next = { ...current, ...changes };
      const url = new URL(window.location.href);
      url.search = "";
      for (const [key, value] of Object.entries(next)) if (value && (key === "fy" || value !== DEFAULTS[key])) url.searchParams.set(key, value);
      window.history.pushState({}, "", url);
      return next;
    });
  }
  useEffect(() => {
    const controller = new AbortController();
    fiscalYears(controller.signal).then(setYears).catch((e) => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [retry]);
  const fy = params.fy || years?.default;
  const base = useMemo(() => ({ fy, funding_type: params.funding_type, award_type: params.award_type, account: params.account, recipient_type: params.recipient_type }), [fy, params.funding_type, params.award_type, params.account, params.recipient_type]);
  const listParams = useMemo(() => ({ ...base, q: params.q, sort: params.sort, dir: params.dir, page: params.page, page_size: params.page_size }), [base, params.q, params.sort, params.dir, params.page, params.page_size]);
  useEffect(() => {
    if (!fy) return undefined;
    const controller = new AbortController();
    setLoading(true); setError("");
    Promise.all([stateSummary(code, base, controller.signal), stateGrants(code, listParams, controller.signal)])
      .then(([s, g]) => { setSummary(s); setGrants(g); document.title = `CDC funding to recipients in ${s.state.name} | CHIP`; })
      .catch((e) => { if (e.name !== "AbortError") setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [code, fy, base, listParams, retry]);
  const accounts = summary?.by_account || [];
  const maxAbs = Math.max(1, ...accounts.flatMap((a) => [Math.abs(a.regular), Math.abs(a.supplemental)]));
  const active = Object.entries(params).filter(([key, value]) => ["funding_type", "award_type", "account", "recipient_type"].includes(key) && value && value !== DEFAULTS[key]);
  const totalPages = Math.max(1, Math.ceil((grants?.total_rows || 0) / Number(params.page_size)));
  const sort = (key) => update({ sort: key, dir: params.sort === key && params.dir === "desc" ? "asc" : "desc", page: "1" });
  return <div className="sf-page"><SiteHeader /><main id="main" className="sf-main">
    <a href="/cdc-funding">← CDC funding overview</a>
    <header className="sf-hero"><p className="sf-eyebrow">USAspending · CDC · File C</p><h1>CDC funding to recipients in {summary?.state.name || code}</h1>
      <div className="sf-controls"><label>Fiscal year <select value={fy || ""} onChange={(e) => update({ fy: e.target.value, page: "1" })}>{years?.fiscal_years?.map((year) => <option key={year} value={year}>FY{year}</option>)}</select></label><span>{summary?.period || (fy ? `FY${fy}` : "")}</span></div>
    </header>
    {error && <div role="alert" className="sf-message">{error} <button onClick={() => setRetry((n) => n + 1)}>Retry</button></div>}
    {loading && <p role="status" className="sf-message">Loading funding data…</p>}
    {!loading && !error && summary && grants && <>
      <section className="sf-kpis" aria-label="Funding totals">{[["Total obligations", summary.totals.total, true], ["Regular", summary.totals.regular, true], ["Supplemental/emergency", summary.totals.supplemental, true], ["Grants", summary.totals.grant_count ?? summary.totals.award_count, false], ["Recipients", summary.totals.recipient_count, false]].map(([label, value, currency]) => <div className="sf-kpi" key={label}><span>{label}</span><strong>{currency ? amount(value) : Number(value).toLocaleString()}</strong></div>)}</section>
      <section className="sf-panel" aria-labelledby="sf-filters"><h2 id="sf-filters">Filters</h2><div className="sf-filter-grid">
        <label>Funding type<select value={params.funding_type} onChange={(e) => update({ funding_type: e.target.value, page: "1" })}><option value="all">All funding</option><option value="regular">Regular</option><option value="supplemental">Supplemental/emergency</option></select></label>
        <label>Award type<select value={params.award_type} onChange={(e) => update({ award_type: e.target.value, page: "1" })}><option value="all">All awards</option><option value="grant">Grants</option><option value="contract">Contracts</option></select></label>
        <label>Federal account<select value={params.account} onChange={(e) => update({ account: e.target.value, page: "1" })}><option value="">All accounts</option>{summary.accounts_available.map((a) => <option key={a.symbol} value={a.symbol}>{a.symbol} · {a.name}</option>)}</select></label>
        <label>Recipient type<select value={params.recipient_type} onChange={(e) => update({ recipient_type: e.target.value, page: "1" })}><option value="all">All recipients</option><option value="state_government">State government</option></select></label>
      </div><div className="sf-chips">{active.map(([key, value]) => <button key={key} onClick={() => update({ [key]: DEFAULTS[key], page: "1" })}>{key.replaceAll("_", " ")}: {value} ×</button>)}<button onClick={() => update({ funding_type: "all", award_type: "all", account: "", recipient_type: "all", page: "1" })}>Clear filters</button></div></section>
      <section className="sf-panel"><div className="sf-heading"><h2>Funding by federal account</h2><button onClick={() => setShowTable((v) => !v)}>{showTable ? "Show as chart" : "Show as table"}</button></div>
        {accounts.length === 0 && <p>No funding matches these filters.</p>}
        {showTable ? <div className="sf-scroll"><table><thead><tr><th>Account</th><th>Regular</th><th>Supplemental</th><th>Total</th></tr></thead><tbody>{accounts.map((a) => <tr key={a.symbol}><th>{a.symbol} · {a.name}</th><td>{amount(a.regular)}</td><td>{amount(a.supplemental)}</td><td>{amount(a.total)}</td></tr>)}</tbody></table></div> : <div className="sf-bars">{accounts.map((a) => <div className="sf-account" key={a.symbol}><h3>{a.symbol} · {a.name}</h3>{[["Regular", a.regular, "regular"], ["Supplemental", a.supplemental, "supplemental"]].map(([label, value, kind]) => <div className="sf-bar-row" key={kind}><span>{label}</span><div className="sf-track"><i className="sf-zero"/><i className={`sf-bar ${kind} ${value < 0 ? "negative" : ""}`} style={{ width: `${Math.abs(value) / maxAbs * 48}%` }} /></div><strong>{amount(value)}</strong></div>)}</div>)}</div>}
        <p className="sf-source">{summary.citation}</p></section>
      <section className="sf-panel"><div className="sf-heading"><h2>Grants</h2><a href={grantsCsvUrl(code, { ...listParams, page: undefined, page_size: undefined })} download>Download CSV</a></div>
        <label className="sf-search">Search grants <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, FAIN, NOFO, description" /></label>
        <p>{grants.total_rows.toLocaleString()} awards · {amount(grants.sum_total)} matching search</p>
        {grants.rows.length === 0 ? <p>No awards match this search and filters.</p> : <div className="sf-scroll"><table><thead><tr><th><button onClick={() => sort("name")}>Grant ↕</button></th><th><button onClick={() => sort("recipient")}>Recipient ↕</button></th><th>NOFO number</th><th>Federal account(s)</th><th>Regular</th><th>Supplemental</th><th><button onClick={() => sort("amount")}>Total ↕</button></th></tr></thead><tbody>{grants.rows.map((row) => <tr key={row.award_unique_key} id={`award-${row.award_unique_key}`} data-award-key={row.award_unique_key}><td><button className="sf-expand" aria-expanded={!!expanded[row.award_unique_key]} onClick={() => setExpanded((current) => ({ ...current, [row.award_unique_key]: !current[row.award_unique_key] }))}>{row.grant_name}</button><small>{NAME_SOURCES[row.name_source] || row.name_source}</small>{row.project_title && row.project_title !== row.grant_name && <small>{row.project_title}</small>}{expanded[row.award_unique_key] && <div className="sf-details"><p>{row.description || "No description available."}</p><p>Assistance listing: {row.cfda_number || "—"} {row.cfda_title || ""}</p><p>Award ID: {row.award_id}</p>{row.usaspending_url && <a href={row.usaspending_url} target="_blank" rel="noreferrer">View on USAspending</a>}</div>}</td><td>{row.recipient_name}{row.is_state_government === true && <small>State government</small>}</td><td>{row.fon || "—"}</td><td>{row.accounts.map((a) => a.symbol).join("; ")}</td><td>{amount(row.regular)}</td><td>{amount(row.supplemental)}</td><td>{amount(row.total)}</td></tr>)}</tbody></table></div>}
        <div className="sf-pager"><label>Rows per page <select value={params.page_size} onChange={(e) => update({ page_size: e.target.value, page: "1" })}>{[25, 50, 100].map((size) => <option key={size}>{size}</option>)}</select></label><button disabled={Number(params.page) <= 1} onClick={() => update({ page: String(Number(params.page) - 1) })}>Previous</button><span>Page {params.page} of {totalPages}</span><button disabled={Number(params.page) >= totalPages} onClick={() => update({ page: String(Number(params.page) + 1) })}>Next</button></div><p className="sf-source">{grants.citation}</p></section>
      <section className="sf-panel sf-about"><h2>About these numbers</h2><p>Amounts are CDC award obligations in USAspending File C for the selected fiscal year. They are assigned to the recipient state recorded in the source. Regular and supplemental amounts come from File C disaster emergency fund codes. Negative amounts reflect reductions to earlier obligations. Award names may come from a NOFO title, TAGGS project title, assistance listing, or award description. Recipients and awards are counted after the selected filters. Subawards are not added to these totals.</p></section>
    </>}
  </main><Footer /></div>;
}
