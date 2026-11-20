import { useEffect, useMemo, useState } from "react";
import SiteHeader from "../components/SiteHeader";
import Footer from "../components/Footer";
import { fiscalYears, stateSummary, stateGrants, grantsCsvUrl } from "../api/stateFunding";
import "./CdcStateFundingProfile.css";

const DEFAULTS = {
  funding_type: "all", award_type: "grant", category: "", recipient_type: "all",
  q: "", sort: "amount", dir: "desc", page: "1", page_size: "25",
};
const NAME_SOURCES = {
  grants_gov_nofo_title: "NOFO title (Grants.gov)",
  cdc_funding_profiles_nofo_title: "NOFO title (CDC Funding Profiles)",
  taggs_award_title: "Project title (TAGGS)",
  assistance_listing_title: "Assistance listing",
  award_description: "Award description",
};
const integer = (value) => Math.round(Math.abs(Number(value || 0))).toLocaleString("en-US");
const amount = (value) => `${Number(value) < 0 ? "−" : ""}$${integer(value)}`;
const compactAmount = (value) => {
  const absolute = Math.abs(Number(value || 0));
  const sign = Number(value) < 0 ? "−" : "";
  if (absolute >= 1e9) return `${sign}$${(absolute / 1e9).toFixed(1)} billion`;
  if (absolute >= 1e6) return `${sign}$${(absolute / 1e6).toFixed(1)} million`;
  if (absolute >= 1e3) return `${sign}$${(absolute / 1e3).toFixed(1)} thousand`;
  return `${sign}$${absolute.toFixed(1)}`;
};
const exactAmount = (value) => `${Number(value) < 0 ? "−" : ""}$${Math.abs(Number(value || 0))
  .toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function readParams() {
  const incoming = new URLSearchParams(window.location.search);
  const next = { ...DEFAULTS };
  for (const key of ["fy", ...Object.keys(DEFAULTS)]) {
    if (incoming.has(key)) next[key] = incoming.get(key);
  }
  return next;
}

function Dollars({ value, compact = false }) {
  return <span className="sf-amount" title={exactAmount(value)}>
    {compact ? compactAmount(value) : amount(value)}
    {compact && <span className="sf-sr-only"> Exact amount: {exactAmount(value)}</span>}
  </span>;
}

function FundingBars({ categories, maxAbs }) {
  return <div className="sf-bars">
    {categories.map((category) => <div className="sf-category" key={category.code}>
      <h3>{category.name}</h3>
      {category.accounts.length === 1 && <small className="sf-single-account"
        title={category.accounts[0].name}>
        Federal account {category.accounts[0].symbol}
      </small>}
      {category.basis === "outside_operating_plan" &&
        <small>Outside CDC&apos;s operating plan</small>}
      {[["Regular", category.regular, "regular"],
        ["Supplemental", category.supplemental, "supplemental"]]
        .filter(([, value]) => Number(value) !== 0)
        .map(([label, value, kind]) =>
        <div className="sf-bar-row" key={kind}>
          <span>{label}</span>
          <div className="sf-track" aria-hidden="true">
            <i className="sf-zero" />
            <i className={`sf-bar ${kind} ${value < 0 ? "negative" : ""}`}
              style={{ width: `${Math.abs(value) / maxAbs * 48}%` }} />
          </div>
          <strong><Dollars value={value} /></strong>
        </div>)}
      {category.accounts.length >= 2 && <details className="sf-category-details">
        <summary>Federal accounts ({category.accounts.length})</summary>
        <div className="sf-scroll">
          <table>
            <thead><tr><th>Federal account</th><th>Regular</th><th>Supplemental</th><th>Total</th></tr></thead>
            <tbody>{category.accounts.map((account) => <tr key={account.symbol}>
              <th>{account.symbol} · {account.name}</th>
              <td><Dollars value={account.regular} /></td>
              <td><Dollars value={account.supplemental} /></td>
              <td><Dollars value={account.total} /></td>
            </tr>)}</tbody>
          </table>
        </div>
      </details>}
    </div>)}
  </div>;
}

function CategoryTable({ categories }) {
  return <div className="sf-scroll"><table>
    <thead><tr><th>Budget category</th><th>Regular</th><th>Supplemental</th><th>Total</th></tr></thead>
    <tbody>{categories.map((category) => <tr key={category.code}>
      <th>
        <details>
          <summary>{category.name}</summary>
          {category.basis === "outside_operating_plan" &&
            <small>Outside CDC&apos;s operating plan</small>}
          <ul>{category.accounts.map((account) => <li key={account.symbol}>
            {account.symbol} · {account.name}: <Dollars value={account.total} />
          </li>)}</ul>
        </details>
      </th>
      <td><Dollars value={category.regular} /></td>
      <td><Dollars value={category.supplemental} /></td>
      <td><Dollars value={category.total} /></td>
    </tr>)}</tbody>
  </table></div>;
}

function GrantsTable({ rows, expanded, setExpanded, sort }) {
  return <div className="sf-scroll"><table>
    <thead><tr>
      <th><button onClick={() => sort("name")}>Grant ↕</button></th>
      <th><button onClick={() => sort("recipient")}>Recipient ↕</button></th>
      <th>NOFO number</th>
      <th><button onClick={() => sort("category")}>Budget category ↕</button></th>
      <th>Regular</th><th>Supplemental</th>
      <th><button onClick={() => sort("amount")}>Total ↕</button></th>
    </tr></thead>
    <tbody>{rows.map((row) => <tr key={row.award_unique_key}
      id={`award-${row.award_unique_key}`} data-award-key={row.award_unique_key}>
      <td>
        <button className="sf-expand" aria-label={`Expand details for ${row.grant_name}`}
          aria-expanded={!!expanded[row.award_unique_key]}
          onClick={() => setExpanded((current) => ({
            ...current, [row.award_unique_key]: !current[row.award_unique_key],
          }))}>{row.fon ? "▸" : row.grant_name}</button>
        {row.fon && <a className="sf-grant-link" href={`/cdc-funding/grant/${encodeURIComponent(row.fon)}`}>
          {row.grant_name}</a>}
        <small>{NAME_SOURCES[row.name_source] || row.name_source}</small>
        {row.project_title && row.project_title !== row.grant_name && <small>{row.project_title}</small>}
        {expanded[row.award_unique_key] && <div className="sf-details">
          <p>{row.description || "No description available."}</p>
          <p>Assistance listing: {row.cfda_number || "—"} {row.cfda_title || ""}</p>
          <p>Award ID: {row.award_id}</p>
          {row.fon && <p><a href={`/cdc-funding/grant/${encodeURIComponent(row.fon)}`}>
            Grant history</a></p>}
          <p>Federal accounts: {row.accounts.map((account) =>
            `${account.symbol} · ${account.name}`).join("; ") || "—"}</p>
          {row.usaspending_url && <a href={row.usaspending_url}
            target="_blank" rel="noreferrer">View on USAspending</a>}
        </div>}
      </td>
      <td>{row.recipient_name}{row.is_state_government === true && <small>State government</small>}</td>
      <td className="sf-nowrap">{row.fon || "—"}</td>
      <td>{row.categories.map((category) => category.name).join("; ")}</td>
      <td><Dollars value={row.regular} /></td>
      <td><Dollars value={row.supplemental} /></td>
      <td><Dollars value={row.total} /></td>
    </tr>)}</tbody>
  </table></div>;
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

  function update(changes) {
    setParams((current) => {
      const next = { ...current, ...changes };
      const url = new URL(window.location.href);
      url.search = "";
      for (const [key, value] of Object.entries(next)) {
        if (value && (key === "fy" || value !== DEFAULTS[key])) url.searchParams.set(key, value);
      }
      window.history.pushState({}, "", url);
      return next;
    });
  }

  useEffect(() => {
    const onPop = () => {
      const p = readParams();
      setParams(p);
      setSearch(p.q);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => {
      if (search !== params.q) update({ q: search, page: "1" });
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);
  useEffect(() => {
    const controller = new AbortController();
    fiscalYears(controller.signal).then(setYears).catch((e) => {
      if (e.name !== "AbortError") setError(e.message);
    });
    return () => controller.abort();
  }, [retry]);

  const fy = params.fy || years?.default;
  const base = useMemo(() => ({
    fy, funding_type: params.funding_type, award_type: params.award_type,
    category: params.category, recipient_type: params.recipient_type,
  }), [fy, params.funding_type, params.award_type, params.category, params.recipient_type]);
  const listParams = useMemo(() => ({
    ...base, q: params.q, sort: params.sort, dir: params.dir,
    page: params.page, page_size: params.page_size,
  }), [base, params.q, params.sort, params.dir, params.page, params.page_size]);
  useEffect(() => {
    if (!fy) return undefined;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    Promise.all([stateSummary(code, base, controller.signal),
      stateGrants(code, listParams, controller.signal)])
      .then(([s, g]) => {
        setSummary(s);
        setGrants(g);
        const noun = params.award_type === "grant" ? "grants" : "funding";
        document.title = `CDC ${noun} to recipients in ${s.state.name} | CHIP`;
      })
      .catch((e) => { if (e.name !== "AbortError") setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [code, fy, base, listParams, retry]);

  const categories = (summary?.by_category || [])
    .filter((category) => category.regular !== 0 || category.supplemental !== 0);
  const maxAbs = Math.max(1, ...categories.flatMap((category) =>
    [Math.abs(category.regular), Math.abs(category.supplemental)]));
  const active = Object.entries(params).filter(([key, value]) =>
    ["funding_type", "award_type", "category", "recipient_type"].includes(key)
    && value && value !== DEFAULTS[key]);
  const totalPages = Math.max(1, Math.ceil((grants?.total_rows || 0) / Number(params.page_size)));
  const sort = (key) => update({
    sort: key, dir: params.sort === key && params.dir === "desc" ? "asc" : "desc", page: "1",
  });
  const title = `CDC ${params.award_type === "grant" ? "grants" : "funding"} to recipients in ${summary?.state.name || code}`;

  return <div className="sf-page">
    <SiteHeader />
    <main id="main" className="sf-main">
      <a href="/cdc-funding">← CDC funding overview</a>
      <a href="/cdc-funding/map">National map</a>
      <header className="sf-hero">
        <p className="sf-eyebrow">CDC funding · State profile</p>
        <h1>{title}</h1>
        <div className="sf-controls">
          <label>Fiscal year <select value={fy || ""}
            onChange={(e) => update({ fy: e.target.value, page: "1" })}>
            {years?.fiscal_years?.map((year) => <option key={year} value={year}>FY{year}</option>)}
          </select></label>
          <span>{summary?.period || (fy ? `FY${fy}` : "")}</span>
        </div>
      </header>
      {error && <div role="alert" className="sf-message">{error}{" "}
        <button onClick={() => setRetry((n) => n + 1)}>Retry</button></div>}
      {loading && <p role="status" className="sf-message">Loading funding data…</p>}
      {!loading && !error && summary && grants && <>
        <section className="sf-kpis" aria-label="Funding totals">
          {[["Total obligations", summary.totals.total, true],
            ["Regular", summary.totals.regular, true],
            ["Supplemental (emergency)", summary.totals.supplemental, true],
            ["Grants", summary.totals.grant_count ?? summary.totals.award_count, false],
            ["Recipients", summary.totals.recipient_count, false]].map(([label, value, currency]) =>
            <div className="sf-kpi" key={label}>
              <span>{label}</span>
              <strong>{currency ? <Dollars value={value} compact /> : Number(value).toLocaleString()}</strong>
            </div>)}
        </section>
        <section className="sf-panel" aria-labelledby="sf-filters">
          <h2 id="sf-filters">Filters</h2>
          <div className="sf-filter-grid">
            <label>Funding type<select value={params.funding_type}
              onChange={(e) => update({ funding_type: e.target.value, page: "1" })}>
              <option value="all">All funding</option><option value="regular">Regular</option>
              <option value="supplemental">Supplemental/emergency</option>
            </select></label>
            <label>Award type<select value={params.award_type}
              onChange={(e) => update({ award_type: e.target.value, page: "1" })}>
              <option value="grant">Grants</option><option value="all">All awards</option>
              <option value="contract">Contracts</option>
            </select></label>
            <label>Budget category<select value={params.category}
              onChange={(e) => update({ category: e.target.value, page: "1" })}>
              <option value="">All categories</option>
              {summary.categories_available.map((category) =>
                <option key={category.code} value={category.code}>{category.name}</option>)}
            </select></label>
            <label>Recipient type<select value={params.recipient_type}
              onChange={(e) => update({ recipient_type: e.target.value, page: "1" })}>
              <option value="all">All recipients</option>
              <option value="state_government">State government</option>
            </select></label>
          </div>
          <div className="sf-chips">
            {active.map(([key, value]) => <button key={key}
              onClick={() => update({ [key]: DEFAULTS[key], page: "1" })}>
              {key.replaceAll("_", " ")}: {value} ×
            </button>)}
            <button onClick={() => update({
              funding_type: "all", award_type: "grant", category: "",
              recipient_type: "all", page: "1",
            })}>Clear filters</button>
          </div>
        </section>
        {params.award_type !== "grant" && <p className="sf-message">
          Contracts are counted in the state where the contractor is located.
          Vaccines for Children purchases, for example, appear in the vaccine manufacturers&apos; states.
        </p>}
        <section className="sf-panel">
          <div className="sf-heading"><h2>Funding by budget category</h2>
            <button onClick={() => setShowTable((value) => !value)}>
              {showTable ? "Show as chart" : "Show as table"}
            </button>
          </div>
          {categories.length === 0 && <p>No funding matches these filters.</p>}
          {showTable ? <CategoryTable categories={categories} />
            : <FundingBars categories={categories} maxAbs={maxAbs} />}
          <p className="sf-source">{summary.citation}</p>
        </section>
        <section className="sf-panel">
          <div className="sf-heading"><h2>Grants</h2>
            <a href={grantsCsvUrl(code, { ...listParams, page: undefined, page_size: undefined })}
              download>Download CSV</a>
          </div>
          <label className="sf-search">Search grants <input type="search" value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Name, category, FAIN, NOFO, description" /></label>
          <p>{grants.total_rows.toLocaleString()} awards · <Dollars value={grants.sum_total} /> matching search</p>
          {grants.rows.length === 0 ? <p>No awards match this search and filters.</p>
            : <GrantsTable rows={grants.rows} expanded={expanded}
              setExpanded={setExpanded} sort={sort} />}
          <div className="sf-pager">
            <label>Rows per page <select value={params.page_size}
              onChange={(e) => update({ page_size: e.target.value, page: "1" })}>
              {[25, 50, 100].map((size) => <option key={size}>{size}</option>)}
            </select></label>
            <button disabled={Number(params.page) <= 1}
              onClick={() => update({ page: String(Number(params.page) - 1) })}>Previous</button>
            <span>Page {params.page} of {totalPages}</span>
            <button disabled={Number(params.page) >= totalPages}
              onClick={() => update({ page: String(Number(params.page) + 1) })}>Next</button>
          </div>
          <p className="sf-source">{grants.citation}</p>
        </section>
        <section className="sf-panel sf-about"><h2>About these numbers</h2>
          <p>Amounts are CDC award obligations in USAspending File C for the selected fiscal year.
            They are assigned to the recipient state recorded in the source. Regular and supplemental
            amounts come from File C disaster emergency fund codes. Negative amounts reflect reductions
            to earlier obligations. Award names may come from a NOFO title, TAGGS project title,
            assistance listing, or award description. Recipients and awards are counted after the
            selected filters. Subawards are not added to these totals.</p>
          <p>Budget categories follow the top-level lines of CDC&apos;s FY 2026 Operating Plan.
            Each federal account belongs to one category; amounts are not split. Some money, such as
            Vaccines for Children (paid from Medicaid) and HHS emergency funds, is outside CDC&apos;s
            operating plan and is labelled that way.</p>
        </section>
      </>}
    </main>
    <Footer />
  </div>;
}
