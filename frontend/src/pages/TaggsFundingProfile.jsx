import { useEffect, useMemo, useState } from "react";
import Header from "../components/Header";
import { API_BASE } from "../config/apiBase";
import {
  buildTaggsDetailsExportUrl,
  fetchTaggsFundingProfileCanBreakdown,
  fetchTaggsFundingProfileCategories,
  fetchTaggsFundingProfileCounties,
  fetchTaggsFundingProfileDetails,
  fetchTaggsFundingProfileRecipients,
  fetchTaggsFundingProfileSubcategories,
  fetchTaggsFundingProfileSummary,
} from "../api/taggs";
import "./TaggsFundingProfile.css";

const DETAILS_PAGE_SIZE = 25;

function parseQueryParams() {
  const search = typeof window !== "undefined" ? window.location.search : "";
  const params = new URLSearchParams(search);
  return {
    state: String(params.get("state") ?? "").trim().toUpperCase(),
    fy: Number.isFinite(Number(params.get("fy"))) ? Number(params.get("fy")) : null,
    programOffice: String(params.get("program_office") ?? "").trim() || null,
    aln: String(params.get("aln") ?? "").trim() || null,
    canCode: String(params.get("can_code") ?? "").trim() || null,
    fundingStream: String(params.get("funding_stream") ?? "").trim() || null,
    domesticOnly: String(params.get("domestic_only") ?? "true").trim().toLowerCase() !== "false",
    metric: String(params.get("metric") ?? "").trim() || null,
  };
}

function toFinite(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatCurrency(value) {
  const numeric = toFinite(value);
  if (numeric == null) return "Not available";
  return numeric.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

function formatCount(value) {
  const numeric = toFinite(value);
  if (numeric == null) return "Not available";
  return Math.round(numeric).toLocaleString("en-US");
}

function formatPercent(value, digits = 1) {
  const numeric = toFinite(value);
  if (numeric == null) return "Not available";
  return `${numeric.toFixed(digits)}%`;
}

function formatDate(value) {
  if (!value) return "Not available";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return String(value);
  return parsed.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function clampText(value, max = 72) {
  const text = String(value ?? "").trim();
  if (!text) return "Not available";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function mappingStatusText(status) {
  return String(status ?? "").trim().toLowerCase() === "mapped"
    ? "Mapped"
    : "Unresolved";
}

function SortHeader({ label, sortKey, activeSort, activeDir, onChange }) {
  const isActive = activeSort === sortKey;
  const direction = isActive ? activeDir : null;
  const suffix = direction === "asc" ? "↑" : direction === "desc" ? "↓" : "";
  return (
    <button
      type="button"
      className="taggs-table-sort"
      onClick={() => onChange(sortKey)}
      title={`Sort by ${label}`}
    >
      {label} {suffix}
    </button>
  );
}

function SectionTitle({ title, subtitle }) {
  return (
    <div className="taggs-section-title">
      <h2>{title}</h2>
      {subtitle ? <p>{subtitle}</p> : null}
    </div>
  );
}

function CategoryBarChart({ rows }) {
  const topRows = Array.isArray(rows) ? rows.slice(0, 10) : [];
  const maxValue = topRows.length > 0 ? Math.max(...topRows.map((row) => Number(row?.amount ?? 0))) : 0;
  return (
    <div className="taggs-bar-chart">
      {topRows.map((row) => {
        const amount = Number(row?.amount ?? 0);
        const width = maxValue > 0 ? (amount / maxValue) * 100 : 0;
        return (
          <div key={`cat-bar-${row.category}`} className="taggs-bar-row">
            <div className="taggs-bar-label" title={row.category}>{clampText(row.category, 52)}</div>
            <div className="taggs-bar-track">
              <div className="taggs-bar-fill" style={{ width: `${width}%` }} />
            </div>
            <div className="taggs-bar-value">{formatCurrency(amount)}</div>
          </div>
        );
      })}
    </div>
  );
}

export default function TaggsFundingProfile() {
  const query = useMemo(() => parseQueryParams(), []);
  const [summary, setSummary] = useState(null);
  const [categories, setCategories] = useState(null);
  const [subcategories, setSubcategories] = useState(null);
  const [canBreakdown, setCanBreakdown] = useState(null);
  const [recipients, setRecipients] = useState(null);
  const [counties, setCounties] = useState(null);
  const [details, setDetails] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isDetailsLoading, setIsDetailsLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailsPage, setDetailsPage] = useState(1);
  const [detailsSortBy, setDetailsSortBy] = useState("amount");
  const [detailsSortDir, setDetailsSortDir] = useState("desc");
  const [showAllRecipients, setShowAllRecipients] = useState(false);

  const hasState = query.state.length === 2;

  useEffect(() => {
    if (!hasState) {
      setError("A valid 2-letter state code is required in the query string.");
      setIsLoading(false);
      return;
    }

    const controller = new AbortController();
    setIsLoading(true);
    setError("");

    const sharedParams = {
      apiBase: API_BASE,
      state: query.state,
      fy: query.fy,
      program_office: query.programOffice,
      aln: query.aln,
      can_code: query.canCode,
      funding_stream: query.fundingStream,
      domestic_only: query.domesticOnly,
      signal: controller.signal,
    };

    Promise.all([
      fetchTaggsFundingProfileSummary(sharedParams),
      fetchTaggsFundingProfileCategories(sharedParams),
      fetchTaggsFundingProfileSubcategories(sharedParams),
      fetchTaggsFundingProfileCanBreakdown(sharedParams),
      fetchTaggsFundingProfileRecipients({
        ...sharedParams,
        page: 1,
        page_size: showAllRecipients ? 200 : 20,
      }),
      fetchTaggsFundingProfileCounties({
        ...sharedParams,
        limit: 400,
      }),
    ])
      .then(([
        summaryPayload,
        categoriesPayload,
        subcategoriesPayload,
        canBreakdownPayload,
        recipientsPayload,
        countiesPayload,
      ]) => {
        if (controller.signal.aborted) return;
        setSummary(summaryPayload);
        setCategories(categoriesPayload);
        setSubcategories(subcategoriesPayload);
        setCanBreakdown(canBreakdownPayload);
        setRecipients(recipientsPayload);
        setCounties(countiesPayload);
      })
      .catch((fetchError) => {
        if (controller.signal.aborted) return;
        setError(fetchError?.message ?? "Failed to load TAGGS funding profile.");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setIsLoading(false);
      });

    return () => controller.abort();
  }, [
    hasState,
    query.aln,
    query.canCode,
    query.domesticOnly,
    query.fundingStream,
    query.fy,
    query.programOffice,
    query.state,
    showAllRecipients,
  ]);

  useEffect(() => {
    if (!hasState) return;
    const controller = new AbortController();
    setIsDetailsLoading(true);

    fetchTaggsFundingProfileDetails({
      apiBase: API_BASE,
      state: query.state,
      fy: query.fy,
      program_office: query.programOffice,
      aln: query.aln,
      can_code: query.canCode,
      funding_stream: query.fundingStream,
      domestic_only: query.domesticOnly,
      page: detailsPage,
      page_size: DETAILS_PAGE_SIZE,
      sort_by: detailsSortBy,
      sort_dir: detailsSortDir,
      signal: controller.signal,
    })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setDetails(payload);
      })
      .catch((detailsError) => {
        if (controller.signal.aborted) return;
        setError(detailsError?.message ?? "Failed to load TAGGS detail rows.");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setIsDetailsLoading(false);
      });

    return () => controller.abort();
  }, [
    detailsPage,
    detailsSortBy,
    detailsSortDir,
    hasState,
    query.aln,
    query.canCode,
    query.domesticOnly,
    query.fundingStream,
    query.fy,
    query.programOffice,
    query.state,
  ]);

  const stateName = summary?.state_name ?? query.state;
  const fiscalYear = summary?.fiscal_year ?? query.fy ?? "N/A";
  const detailRows = Array.isArray(details?.rows) ? details.rows : [];
  const detailTotalRows = Number(details?.total_rows ?? 0);
  const detailTotalPages = Math.max(1, Math.ceil(detailTotalRows / DETAILS_PAGE_SIZE));
  const categoryRows = Array.isArray(categories?.rows) ? categories.rows : [];
  const subcategoryRows = Array.isArray(subcategories?.rows) ? subcategories.rows : [];
  const canRows = Array.isArray(canBreakdown?.rows) ? canBreakdown.rows : [];
  const recipientRows = Array.isArray(recipients?.rows) ? recipients.rows : [];
  const countyRows = Array.isArray(counties?.rows) ? counties.rows : [];
  const exportUrl = buildTaggsDetailsExportUrl({
    apiBase: API_BASE,
    state: query.state,
    fy: fiscalYear,
    program_office: query.programOffice,
    aln: query.aln,
    can_code: query.canCode,
    funding_stream: query.fundingStream,
    domestic_only: query.domesticOnly,
    sort_by: detailsSortBy,
    sort_dir: detailsSortDir,
  });

  const validation = summary?.validation ?? null;
  const validationRows = [
    { label: "Summary total = category total", left: validation?.summary_total, right: validation?.category_total },
    { label: "Summary total = sub-category total", left: validation?.summary_total, right: validation?.subcategory_total },
    { label: "Summary total = detail total", left: validation?.summary_total, right: validation?.detail_total },
    {
      label: "Summary total = county total (including undefined)",
      left: validation?.summary_total,
      right: validation?.county_total_including_undefined,
    },
    { label: "Summary total = CAN breakdown total", left: validation?.summary_total, right: validation?.can_breakdown_total },
  ];

  const summaryCards = [
    { label: "Total funding", value: formatCurrency(summary?.total_funding) },
    { label: "Awards", value: formatCount(summary?.award_count) },
    { label: "Funding per capita", value: formatCurrency(summary?.funding_per_capita) },
    { label: "Unique recipients", value: formatCount(summary?.recipient_count) },
    { label: "Counties represented", value: formatCount(summary?.county_count) },
    {
      label: "Top category",
      value: summary?.top_category?.name || "Not available",
      note: summary?.top_category?.amount != null ? formatCurrency(summary.top_category.amount) : null,
    },
    {
      label: "Top recipient",
      value: summary?.top_recipient?.name || "Not available",
      note: summary?.top_recipient?.amount != null ? formatCurrency(summary.top_recipient.amount) : null,
    },
  ];

  const groupedSubcategories = useMemo(() => {
    const grouped = new Map();
    subcategoryRows.forEach((row) => {
      const category = String(row?.category ?? "Unspecified Category");
      if (!grouped.has(category)) {
        grouped.set(category, []);
      }
      grouped.get(category).push(row);
    });
    return Array.from(grouped.entries()).map(([category, rows]) => ({
      category,
      rows,
      total: rows.reduce((sum, row) => sum + Number(row?.amount ?? 0), 0),
    }));
  }, [subcategoryRows]);

  const handleSortChange = (nextSortBy) => {
    setDetailsPage(1);
    setDetailsSortDir((currentDir) => {
      if (detailsSortBy !== nextSortBy) return "desc";
      return currentDir === "desc" ? "asc" : "desc";
    });
    setDetailsSortBy(nextSortBy);
  };

  return (
    <div className="taggs-profile-page">
      <Header />
      <main className="taggs-profile-main">
        <header className="taggs-profile-header">
          <div>
            <h1>{`Fiscal Year ${fiscalYear} TAGGS Funding Profile for ${stateName}`}</h1>
            <p>
              State funding profile generated from CHIP TAGGS ingestion with CDC-profile-assisted CAN mapping, deterministic fallback inference, and a transparent domestic reporting filter.
            </p>
            <div className="taggs-header-chips">
              <span className="taggs-chip">FY {fiscalYear}</span>
              <span className="taggs-chip">State {query.state}</span>
              <span className="taggs-chip">Scope {query.domesticOnly ? "Domestic" : "All rows"}</span>
              {query.fundingStream ? <span className="taggs-chip">Stream {query.fundingStream}</span> : null}
              {query.canCode ? <span className="taggs-chip">Raw CAN {query.canCode}</span> : null}
              <span className="taggs-chip">Data source: HHS TAGGS</span>
              <span className="taggs-chip">Last refreshed: {formatDate(summary?.last_refreshed_at)}</span>
            </div>
          </div>
          <div className="taggs-header-actions">
            <button type="button" className="chip-secondary-btn" onClick={() => window.print()}>
              Print / Save PDF
            </button>
            <a className="chip-primary-btn taggs-link-btn" href={exportUrl}>
              Download Detail CSV
            </a>
            <a className="chip-secondary-btn taggs-link-btn" href="/">
              Back to Map
            </a>
          </div>
        </header>

        {isLoading ? <div className="taggs-status">Loading TAGGS funding profile...</div> : null}
        {error ? <div className="taggs-status taggs-status-error">{error}</div> : null}

        {!isLoading && !error ? (
          <>
            <section className="taggs-section">
              <SectionTitle title="Executive Summary" subtitle="Deterministic highlights from the filtered TAGGS aggregate results." />
              <ul className="taggs-list">
                {(Array.isArray(summary?.executive_summary) ? summary.executive_summary : []).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              {summary?.mapping_notice ? <p className="taggs-muted">{summary.mapping_notice}</p> : null}
            </section>

            <section className="taggs-section">
              <SectionTitle title="Top-Level Summary Cards" subtitle="Key statewide indicators for this TAGGS query context." />
              <div className="taggs-cards-grid">
                {summaryCards.map((card) => (
                  <article key={card.label} className="taggs-card">
                    <div className="taggs-card-label">{card.label}</div>
                    <div className="taggs-card-value">{card.value}</div>
                    {card.note ? <div className="taggs-card-note">{card.note}</div> : null}
                  </article>
                ))}
              </div>
            </section>

            <section className="taggs-section">
              <SectionTitle
                title="Category Totals"
                subtitle="Category = effective CAN category from manual, profile-assisted, or fallback mapping; unresolved CANs remain unclassified."
              />
              <div className="taggs-grid-2">
                <div className="taggs-table-wrap">
                  <table className="taggs-table">
                    <thead>
                      <tr>
                        <th>Category</th>
                        <th>Funding amount</th>
                        <th>Share of state total</th>
                        <th>Awards</th>
                      </tr>
                    </thead>
                    <tbody>
                      {categoryRows.map((row) => (
                        <tr key={`cat-row-${row.category}`}>
                          <td title={row.category}>{clampText(row.category, 80)}</td>
                          <td>{formatCurrency(row.amount)}</td>
                          <td>{formatPercent(row.share_pct)}</td>
                          <td>{formatCount(row.award_count)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <article className="taggs-card">
                  <h3>Top categories by funding</h3>
                  <CategoryBarChart rows={categoryRows} />
                </article>
              </div>
            </section>

            <section className="taggs-section">
              <SectionTitle
                title="Category + Sub-Category Totals"
                subtitle="Sub-category = effective CAN sub-category from manual, profile-assisted, or fallback mapping; unresolved CANs remain unclassified."
              />
              <div className="taggs-accordion-list">
                {groupedSubcategories.map((group) => (
                  <details key={`subcat-group-${group.category}`} className="taggs-accordion" open>
                    <summary>
                      <span title={group.category}>{clampText(group.category, 90)}</span>
                      <span>{formatCurrency(group.total)}</span>
                    </summary>
                    <div className="taggs-table-wrap">
                      <table className="taggs-table">
                        <thead>
                          <tr>
                            <th>Sub-category</th>
                            <th>Funding amount</th>
                            <th>Share of state total</th>
                            <th>Share within category</th>
                            <th>Awards</th>
                          </tr>
                        </thead>
                        <tbody>
                          {group.rows.map((row) => (
                            <tr key={`subcat-${group.category}-${row.subcategory}`}>
                              <td title={row.subcategory}>{clampText(row.subcategory, 96)}</td>
                              <td>{formatCurrency(row.amount)}</td>
                              <td>{formatPercent(row.share_total_pct)}</td>
                              <td>{formatPercent(row.share_category_pct)}</td>
                              <td>{formatCount(row.award_count)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                ))}
              </div>
            </section>

            <section className="taggs-section">
              <SectionTitle
                title="Funding Stream / CAN Mapping Breakdown"
                subtitle="Interpreted funding stream or program label shown first; raw TAGGS CAN preserved as secondary audit metadata."
              />
              <div className="taggs-table-wrap">
                <table className="taggs-table">
                  <thead>
                    <tr>
                      <th>Interpreted label</th>
                      <th>Funding stream</th>
                      <th>Mapping status</th>
                      <th>Appropriation type</th>
                      <th>Raw CAN</th>
                      <th>Funding amount</th>
                      <th>Share of total</th>
                      <th>Share of stream</th>
                      <th>Awards</th>
                      <th>Recipients</th>
                    </tr>
                  </thead>
                  <tbody>
                    {canRows.map((row) => (
                      <tr key={`can-row-${row.funding_stream}-${row.raw_can_code || row.can_code}`}>
                        <td title={row.display_label}>{clampText(row.display_label || "Unknown / Unclassified", 80)}</td>
                        <td>{row.funding_stream || "Not available"}</td>
                        <td>{mappingStatusText(row.mapping_status)}</td>
                        <td>{row.appropriation_type}</td>
                        <td>{row.raw_can_code || row.can_code || "Not available"}</td>
                        <td>{formatCurrency(row.amount)}</td>
                        <td>{formatPercent(row.share_total_pct)}</td>
                        <td>{formatPercent(row.share_stream_pct)}</td>
                        <td>{formatCount(row.award_count)}</td>
                        <td>{formatCount(row.unique_recipient_count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="taggs-section">
              <SectionTitle title="Top Recipients" subtitle="Recipient totals, city/county context, and share of state funding." />
              <div className="taggs-table-wrap">
                <table className="taggs-table">
                  <thead>
                    <tr>
                      <th>Recipient</th>
                      <th>City</th>
                      <th>County</th>
                      <th>Total funding</th>
                      <th>Share of state total</th>
                      <th>Awards</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recipientRows.map((row) => (
                      <tr key={`recipient-${row.recipient_name}`}>
                        <td title={row.recipient_name}>{clampText(row.recipient_name, 72)}</td>
                        <td>{row.city || "Not available"}</td>
                        <td>{row.county || "Not available"}</td>
                        <td>{formatCurrency(row.total_funding)}</td>
                        <td>{formatPercent(row.share_pct)}</td>
                        <td>{formatCount(row.award_count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {Number(recipients?.total_rows ?? 0) > 20 ? (
                <div className="taggs-inline-actions">
                  <button
                    type="button"
                    className="chip-secondary-btn"
                    onClick={() => setShowAllRecipients((current) => !current)}
                  >
                    {showAllRecipients ? "Show top 20" : "View all recipients (up to 200)"}
                  </button>
                </div>
              ) : null}
            </section>

            <section className="taggs-section">
              <SectionTitle title="County Distribution" subtitle="Includes the explicit undefined county bucket preserved from TAGGS location fields." />
              <div className="taggs-table-wrap">
                <table className="taggs-table">
                  <thead>
                    <tr>
                      <th>County</th>
                      <th>Total funding</th>
                      <th>Share of state total</th>
                      <th>Awards</th>
                    </tr>
                  </thead>
                  <tbody>
                    {countyRows.map((row) => (
                      <tr key={`county-${row.county}`}>
                        <td>{row.county}</td>
                        <td>{formatCurrency(row.total_funding)}</td>
                        <td>{formatPercent(row.share_pct)}</td>
                        <td>{formatCount(row.award_count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="taggs-muted">
                Undefined county amount: {formatCurrency(counties?.undefined_county_amount)}.
              </p>
            </section>

            <section className="taggs-section">
              <SectionTitle
                title="Detailed Grants Table"
                subtitle="Award-level rows show interpreted CAN label first, with the raw TAGGS CAN retained for auditability."
              />
              <div className="taggs-table-wrap">
                <table className="taggs-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th><SortHeader label="Category" sortKey="category" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th><SortHeader label="Sub-category" sortKey="subcategory" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th><SortHeader label="Award title" sortKey="award_title" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th><SortHeader label="Recipient" sortKey="recipient_name" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th>City</th>
                      <th>County</th>
                      <th><SortHeader label="Award #" sortKey="award_number" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th><SortHeader label="ALN" sortKey="aln" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th>Interpreted label</th>
                      <th><SortHeader label="Funding stream" sortKey="funding_stream" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th>Mapping status</th>
                      <th><SortHeader label="Raw CAN" sortKey="can_code" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th>Issue FY</th>
                      <th><SortHeader label="Amount" sortKey="amount" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailRows.map((row) => (
                      <tr key={`detail-${row.line_number}-${row.award_number}-${row.can_code}`}>
                        <td>{row.line_number}</td>
                        <td title={row.category}>{clampText(row.category, 44)}</td>
                        <td title={row.subcategory}>{clampText(row.subcategory, 56)}</td>
                        <td title={row.award_title}>{clampText(row.award_title, 64)}</td>
                        <td title={row.recipient_name}>{clampText(row.recipient_name, 48)}</td>
                        <td>{row.city || "Not available"}</td>
                        <td>{row.county || "Not available"}</td>
                        <td>{row.award_number || "Not available"}</td>
                        <td>{row.aln || "Not available"}</td>
                        <td title={row.display_label}>{clampText(row.display_label || "Unknown / Unclassified", 52)}</td>
                        <td>{row.funding_stream || "Not available"}</td>
                        <td>{mappingStatusText(row.mapping_status)}</td>
                        <td>{row.raw_can_code || row.can_code || "Not available"}</td>
                        <td>{row.issue_fiscal_year || "Not available"}</td>
                        <td>{formatCurrency(row.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {isDetailsLoading ? <div className="taggs-muted">Loading detail rows...</div> : null}
              <div className="taggs-inline-actions">
                <button
                  type="button"
                  className="chip-secondary-btn"
                  disabled={detailsPage <= 1 || isDetailsLoading}
                  onClick={() => setDetailsPage((current) => Math.max(1, current - 1))}
                >
                  Prev
                </button>
                <span className="taggs-muted">Page {detailsPage} of {detailTotalPages}</span>
                <button
                  type="button"
                  className="chip-secondary-btn"
                  disabled={detailsPage >= detailTotalPages || isDetailsLoading}
                  onClick={() => setDetailsPage((current) => Math.min(detailTotalPages, current + 1))}
                >
                  Next
                </button>
                <span className="taggs-muted">{formatCount(detailTotalRows)} total rows</span>
              </div>
            </section>

            <section className="taggs-section">
              <SectionTitle title="Methodology / Notes" subtitle="Transparent calculation, grouping, and validation notes for this TAGGS report." />
              <ul className="taggs-list">
                {(Array.isArray(summary?.methodology_notes) ? summary.methodology_notes : []).map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
              {summary?.mapping_metadata ? (
                <div className="taggs-muted" style={{ display: "grid", gap: 4 }}>
                  <div>
                    CAN mapping version: {summary.mapping_metadata.can_mapping_version || "Not available"}.
                  </div>
                  <div>
                    Methodology version: {summary.mapping_metadata.methodology_version || "Not available"}.
                  </div>
                  <div>
                    Selected CANs in this view: {formatCount(summary.mapping_metadata.can_count)} total,{" "}
                    {formatCount(summary.mapping_metadata.mapped_can_count)} interpreted,{" "}
                    {formatCount(summary.mapping_metadata.profile_assisted_can_count)} profile-assisted,{" "}
                    {formatCount(summary.mapping_metadata.fallback_inferred_can_count)} fallback-inferred,{" "}
                    {formatCount(summary.mapping_metadata.unresolved_can_count)} unresolved.
                  </div>
                </div>
              ) : null}
              <div className="taggs-table-wrap">
                <table className="taggs-table">
                  <thead>
                    <tr>
                      <th>Validation check</th>
                      <th>Left value</th>
                      <th>Right value</th>
                      <th>Difference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {validationRows.map((row) => {
                      const left = toFinite(row.left) ?? 0;
                      const right = toFinite(row.right) ?? 0;
                      const diff = left - right;
                      return (
                        <tr key={row.label}>
                          <td>{row.label}</td>
                          <td>{formatCurrency(left)}</td>
                          <td>{formatCurrency(right)}</td>
                          <td>{formatCurrency(diff)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="taggs-muted">
                Population source for per-capita calculations: {summary?.population_source || "Not available"}.
              </p>
              {query.metric ? (
                <p className="taggs-muted">Map metric context from launch route: {query.metric}.</p>
              ) : null}
            </section>
          </>
        ) : null}
      </main>
    </div>
  );
}
