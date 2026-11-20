import { Fragment, useEffect, useMemo, useState } from "react";
import SiteHeader from "../components/SiteHeader";
import Footer from "../components/Footer";
import { grantHistory, grantAward, grantHistoryCsvUrl } from "../api/stateFunding";
import "./CdcStateFundingProfile.css";
import "./CdcGrantHistory.css";

const money = (value) => value == null ? "—" :
  `${Number(value) < 0 ? "−" : ""}$${Math.round(Math.abs(Number(value))).toLocaleString("en-US")}`;
const sourceLabel = {
  grants_gov_nofo_title: "NOFO title (Grants.gov)",
  cdc_funding_profiles_nofo_title: "NOFO title (CDC Funding Profiles)",
  fon: "Funding opportunity number",
};
const recipientSourceLabel = {
  taggs_recipient_class: "HHS TAGGS recipient class",
  usaspending_business_types: "USAspending business types",
};
const districtSourceLabel = {
  usaspending_current: "USAspending, current district",
  usaspending_original: "USAspending, district at award",
  taggs: "HHS TAGGS",
};
const abstractSourceLabel = { taggs: "HHS TAGGS", usaspending: "USAspending" };
const titleCase = (value) => value && value === value.toUpperCase()
  ? value.toLowerCase().replace(/\b[a-z]/g, (letter) => letter.toUpperCase()) : value;
const initial = () => {
  const p = new URLSearchParams(window.location.search);
  return { q: p.get("q") || "", past: p.get("past") !== "0", sort: p.get("sort") || "state_total",
    dir: p.get("dir") || "desc", open: p.get("open") || "" };
};

function HistoryBars({ rows, latest, table = false }) {
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.total)));
  const diverging = rows.some((row) => row.total < 0);
  return <div className={`gh-bars ${diverging ? "gh-diverging" : "gh-positive-only"}`}>
    {rows.map((row) => <div className="gh-bar-row" key={row.fiscal_year}>
      <span>FY{row.fiscal_year}{row.fiscal_year === latest && " · latest"}</span>
      <div className="gh-track" aria-hidden="true"><i className="gh-zero" />
        <i className={`gh-bar ${row.total < 0 ? "negative" : ""}`}
          style={{ width: `${Math.abs(row.total) / max * (diverging ? 48 : 100)}%` }} /></div>
      <strong>{money(row.total)}</strong>
    </div>)}
    {table && <div className="sf-scroll"><table>
      <thead><tr><th>Fiscal year</th><th>Regular</th><th>Supplemental</th><th>Total</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.fiscal_year}>
        <th>FY{row.fiscal_year}</th><td>{money(row.regular)}</td>
        <td>{money(row.supplemental)}</td><td>{money(row.total)}</td>
      </tr>)}</tbody>
    </table></div>}
  </div>;
}

function AwardDetail({ nofo, awardKey, onClose }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [abstractOpen, setAbstractOpen] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    grantAward(nofo, awardKey, controller.signal).then(setDetail).catch((e) => {
      if (e.name !== "AbortError") setError(e.message);
    });
    return () => controller.abort();
  }, [nofo, awardKey]);
  if (error) return <div className="gh-detail" role="alert">{error} <button onClick={onClose}>Close</button></div>;
  if (!detail) return <div className="gh-detail" role="status">Loading award details…</div>;
  const address = detail.address || {};
  const abstract = detail.abstract || "No abstract available.";
  const addressText = [titleCase(address.line1), titleCase(address.city), address.state,
    address.zip, titleCase(address.county)].filter(Boolean).join(", ") || "Not stated";
  const districtSource = districtSourceLabel[detail.congressional_district_source];
  const recipientSource = recipientSourceLabel[detail.recipient_type_source];
  const abstractSource = abstractSourceLabel[detail.abstract_source];
  return <div className="gh-detail">
    <button onClick={onClose}>Close details</button>
    <h4>Recipient and award details</h4>
    <p>{detail.recipient_name}</p>
    <dl className="gh-definition-list">
      <div><dt>UEI</dt><dd>{detail.recipient_uei || "Not stated"}</dd></div>
      <div><dt>Address</dt><dd>{addressText}</dd></div>
      <div><dt>Congressional district</dt><dd>{detail.congressional_district || "Not stated"}
        {districtSource && <small>{districtSource}</small>}</dd></div>
      <div><dt>Recipient type</dt><dd>{detail.recipient_type || "Not stated"}
        {recipientSource && <small>{recipientSource}</small>}</dd></div>
      <div><dt>Organization type</dt><dd>{detail.organization_type || "Not stated"}</dd></div>
      <div><dt>Business types</dt><dd>{(detail.business_types || []).map(titleCase).join("; ") || "Not stated"}</dd></div>
      <div><dt>Metro status</dt><dd>{detail.metro_status || "Not stated"}</dd></div>
      <div><dt>Award ID</dt><dd>{detail.award_id || "Not stated"}
        {detail.usaspending_url && <small><a href={detail.usaspending_url}
          target="_blank" rel="noreferrer">View on USAspending</a></small>}</dd></div>
      <div><dt>Assistance listing</dt><dd>{detail.cfda?.number || "—"} {detail.cfda?.title || ""}</dd></div>
      <div><dt>Funding office</dt><dd>{detail.funding_office || "Not stated"}</dd></div>
      <div><dt>Period of performance</dt><dd>{detail.period_of_performance?.start || "—"} to
        {` ${detail.period_of_performance?.end || "—"}`}</dd></div>
    </dl>
    <h4>Project abstract</h4>
    <p>{detail.project_title || "Project title not stated"}</p>
    <p>{abstractOpen || abstract.length <= 600 ? abstract : `${abstract.slice(0, 600)}…`}</p>
    {abstractSource && <small>Abstract source: {abstractSource}</small>}
    {abstract.length > 600 && <button onClick={() => setAbstractOpen(!abstractOpen)}>
      {abstractOpen ? "Show less" : "Read full abstract"}</button>}
    <h4>Funding history under this grant</h4>
    <HistoryBars rows={detail.history} latest={detail.last_fy} table />
    <p>FY2021–FY2026 award total: <strong>{money(detail.all_years_total)}</strong></p>
    <h4>Latest-year budget categories</h4>
    <ul>{detail.categories.map((c) => <li key={c.code}>{c.name}: {money(c.total)}
      <small> {c.accounts.map((a) => `${a.symbol} ${money(a.total)}`).join("; ")}</small>
    </li>)}</ul>
    <div data-subawards-for={awardKey}>
      <h4>Sub-awards</h4>
      {detail.subawards ? <p>{detail.subawards.subawardee_count} sub-awardees ·
        {` ${detail.subawards.action_count}`} actions · {money(detail.subawards.reported_amount)} reported</p>
        : <p>No sub-award profile available.</p>}
      <p>Sub-award amounts are reported by prime recipients and are not additional federal funding.</p>
    </div>
  </div>;
}

export default function CdcGrantHistory({ nofo }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [retry, setRetry] = useState(0);
  const [view, setView] = useState(initial);
  const [openState, setOpenState] = useState(null);
  const [showTable, setShowTable] = useState(false);
  const [showAllStates, setShowAllStates] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    grantHistory(nofo, controller.signal).then((result) => {
      setData(result);
      document.title = `${result.nofo.grant_name} | CHIP`;
      if (nofo !== result.nofo.fon_display) {
        const url = new URL(window.location.href);
        url.pathname = `/cdc-funding/grant/${encodeURIComponent(result.nofo.fon_display)}`;
        window.history.replaceState({}, "", url);
      }
    }).catch((e) => {
      if (e.name !== "AbortError") { setError(e.message); setSuggestions(e.suggestions || []); }
    });
    return () => controller.abort();
  }, [nofo, retry]);
  useEffect(() => {
    const onPop = () => setView(initial());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  function update(changes) {
    setView((current) => {
      const next = { ...current, ...changes };
      const url = new URL(window.location.href);
      url.search = "";
      if (next.q) url.searchParams.set("q", next.q);
      url.searchParams.set("past", next.past ? "1" : "0");
      url.searchParams.set("sort", next.sort);
      url.searchParams.set("dir", next.dir);
      if (next.open) url.searchParams.set("open", next.open);
      window.history.pushState({}, "", url);
      return next;
    });
  }
  const groups = useMemo(() => {
    if (!data) return [];
    const terms = view.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const all = data.by_state.map((state) => {
      const awards = data.awards.filter((a) => a.state === state.state);
      const visible = awards.filter((a) => (view.past || a.is_current) && terms.every((term) =>
        [a.recipient_name, a.project_title, a.award_id, a.recipient_uei, a.city, a.recipient_type]
          .some((field) => String(field || "").toLowerCase().includes(term))));
      const sorted = [...visible].sort((a, b) => {
        if (a.is_current !== b.is_current) return a.is_current ? -1 : 1;
        const field = view.sort === "recipient" ? "recipient_name" :
          view.sort === "recipient_type" ? "recipient_type" : null;
        const comparison = field ? String(a[field]).localeCompare(String(b[field])) :
          (a.latest_fy_amount?.total || 0) - (b.latest_fy_amount?.total || 0);
        return (view.dir === "asc" ? 1 : -1) * comparison || a.recipient_name.localeCompare(b.recipient_name);
      });
      return { state, awards: sorted, total: awards.length };
    }).filter((group) => group.awards.length);
    if (view.sort === "state_name") all.sort((a, b) =>
      (view.dir === "asc" ? 1 : -1) * a.state.name.localeCompare(b.state.name));
    if (view.sort === "state_total") all.sort((a, b) =>
      (view.dir === "asc" ? 1 : -1) * ((a.state.latest_fy_total || 0) - (b.state.latest_fy_total || 0)));
    return all;
  }, [data, view]);
  const variants = data?.nofo.fon_variants.filter((value) => value !== data.nofo.fon_display) || [];
  return <div className="sf-page gh-page"><SiteHeader /><main id="main" className="sf-main">
    <a href="/cdc-funding">← CDC funding overview</a>
    {error && <div className="sf-message" role="alert"><p>{error}</p>
      {suggestions.map((s) => <a key={s} href={`/cdc-funding/grant/${encodeURIComponent(s)}`}>{s}</a>)}
      <button onClick={() => setRetry((n) => n + 1)}>Retry</button></div>}
    {!data && !error && <div className="sf-message" role="status">Loading grant history…</div>}
    {data && <>
      <section className="sf-hero"><span className="sf-eyebrow">CDC funding · Grant history</span>
        <h1>{data.nofo.grant_name}</h1><small>{sourceLabel[data.nofo.name_source]}</small>
        <p><strong>{data.nofo.fon_display}</strong>
          {variants.length > 0 && ` · Also recorded as ${variants.join(", ")}`}</p>
        <p>Assistance listings: {data.nofo.cfda.map((c) => `${c.number} ${c.title || ""}`).join("; ") || "—"}</p>
        <p>Awarding offices: {data.nofo.awarding_offices.join("; ") || "—"}</p>
        <p>Period of performance: {data.nofo.period_of_performance.start_min || "—"} to
          {` ${data.nofo.period_of_performance.end_max || "—"}`}</p>
        <p>Budget categories: {data.nofo.categories.map((c) => c.name).join("; ") || "—"}</p>
        {data.latest_fy < Math.max(...data.fiscal_years) && <p>FY{data.latest_fy} is the last fiscal year with obligations.</p>}
        {data.latest_fy_note && <p>{data.latest_fy_note}</p>}
        <div className="sf-kpis">
          <div className="sf-kpi"><span>FY{data.latest_fy} obligations</span>
            <strong>{money(data.totals.latest_fy.total)}</strong>
            <small>Regular {money(data.totals.latest_fy.regular)} · Supplemental
              {` ${money(data.totals.latest_fy.supplemental)}`}</small></div>
          <div className="sf-kpi"><span>FY2021–FY2026 total</span>
            <strong>{money(data.totals.all_years.total)}</strong></div>
          <div className="sf-kpi"><span>Recipients in FY{data.latest_fy}</span>
            <strong>{data.totals.latest_fy.recipient_count}</strong></div>
          <div className="sf-kpi"><span>States and territories in FY{data.latest_fy}</span>
            <strong>{data.totals.latest_fy.state_count}</strong></div>
        </div>
      </section>
      <section className="sf-panel"><div className="sf-heading"><h2>Funding by fiscal year</h2>
        <button onClick={() => setShowTable(!showTable)}>{showTable ? "Hide table" : "Show as table"}</button></div>
        <HistoryBars rows={data.by_fiscal_year} latest={data.latest_fy} table={showTable} />
        <p className="sf-source">{data.citation}</p></section>
      <section className="sf-panel"><h2>By state, FY{data.latest_fy}</h2>
        <div className="gh-states">{(showAllStates ? data.by_state : data.by_state.slice(0, 10))
          .map((s) => <div key={s.state}>
          <a href={`#state-${s.state}`}>{s.name}</a>
          {s.state !== "__" && <a className="gh-state-link" href={`/cdc-funding/state/${s.state}?fy=${data.latest_fy}&award_type=grant&q=${encodeURIComponent(data.nofo.fon_display)}`}>State funding page</a>}
          <strong>{money(s.latest_fy_total)}</strong><span>{s.current_count} current</span>
        </div>)}</div>
        {data.by_state.length > 10 && <button onClick={() => setShowAllStates(!showAllStates)}>
          {showAllStates ? "Show top 10 states" : `Show all ${data.by_state.length} states`}
        </button>}</section>
      <section className="sf-panel"><h2>Recipients</h2>
        <div className="gh-controls"><label>Search recipients
          <input value={view.q} onChange={(e) => update({ q: e.target.value })} /></label>
          <label><input type="checkbox" checked={view.past}
            onChange={(e) => update({ past: e.target.checked })} /> Show past recipients</label>
          <label>Sort by <select value={view.sort} onChange={(e) => update({ sort: e.target.value })}>
            <option value="state_total">State total</option><option value="state_name">State name</option>
            <option value="recipient">Recipient</option><option value="recipient_type">Recipient type</option>
            <option value="amount">FY{data.latest_fy} amount</option>
          </select></label>
          <label>Direction <select value={view.dir} onChange={(e) => update({ dir: e.target.value })}>
            <option value="desc">Descending</option><option value="asc">Ascending</option>
          </select></label></div>
        {groups.length === 0 && <p>No recipients match these filters.</p>}
        {groups.map(({ state, awards, total }) => <section id={`state-${state.state}`} className="gh-group" key={state.state}>
          <h3>{state.name} · {money(state.latest_fy_total)}
            <small>{state.current_count} current · {state.past_count} past
              {view.q && ` · ${awards.length} of ${total} shown`}</small></h3>
          <div className="sf-scroll gh-awards-scroll"><table><thead><tr><th>Recipient</th><th>Recipient type</th>
            <th>Project title</th><th>FY{data.latest_fy} obligations</th></tr></thead>
            <tbody>{awards.map((a) => {
              const expanded = view.open === a.award_unique_key && (!openState || openState === a.state);
              return <Fragment key={`${a.state}-${a.award_unique_key}`}><tr>
              <td><button className="sf-expand"
                aria-expanded={expanded}
                onClick={() => {
                  setOpenState(a.state);
                  update({ open: view.open === a.award_unique_key && openState === a.state
                    ? "" : a.award_unique_key });
                }}>
                {a.recipient_name}</button>{a.split_state && <small>Split across states</small>}
                <small>{a.award_id}</small></td>
              <td>{a.recipient_type}</td><td>{a.project_title || "—"}</td>
              <td className="gh-amount">{money(a.latest_fy_amount?.total)}
                {!a.is_current && <small>Last funded FY{a.last_fy}</small>}</td>
            </tr>
              {expanded && <tr className="gh-detail-row"><td colSpan={4}>
                <AwardDetail nofo={data.nofo.fon_display} awardKey={a.award_unique_key}
                  onClose={() => update({ open: "" })} />
              </td></tr>}</Fragment>;
            })}</tbody></table></div></section>)}
        <a href={grantHistoryCsvUrl(data.nofo.fon_display)}>Download CSV</a>
        <p className="sf-source">{data.citation}</p></section>
      <section className="sf-panel sf-about"><h2>About these numbers</h2>
        {data.notes.map((note) => <p key={note}>{note}</p>)}
        <p>Other federal awards held by these recipients are not shown here; the CHIP recipient profile report lists them.</p>
      </section>
    </>}
  </main><Footer /></div>;
}
