import { useEffect, useMemo, useState } from "react";
import Header from "../components/Header";
import { API_BASE } from "../config/apiBase";
import {
  fetchCdcFundingProfileCategories,
  fetchCdcFundingProfileDetails,
  fetchCdcFundingProfileSubcategories,
  fetchCdcFundingProfileSummary,
} from "../api/cdcFunding";
import "./CdcStateFundingProfile.css";

const DETAILS_PAGE_SIZE = 25;

function parseBooleanParam(params, key, defaultValue = false) {
  const token = params.get(key);
  if (token == null) return defaultValue;
  return String(token).trim().toLowerCase() === "true";
}

function parseQueryParams() {
  const search = typeof window !== "undefined" ? window.location.search : "";
  const params = new URLSearchParams(search);
  return {
    basis: String(params.get("basis") ?? "prime").trim().toLowerCase() || "prime",
    fy: Number.isFinite(Number(params.get("fy"))) ? Number(params.get("fy")) : null,
    fundingGeographyMode: String(params.get("funding_geography_mode") ?? "recipient_location").trim() || "recipient_location",
    appropriationType: String(params.get("appropriation_type") ?? "all").trim() || "all",
    assistanceType: String(params.get("assistance_type") ?? "").trim() || null,
    awardingOffice: String(params.get("awarding_office") ?? "").trim() || null,
    fundingOffice: String(params.get("funding_office") ?? "").trim() || null,
    center: String(params.get("center") ?? "").trim() || null,
    metric: String(params.get("metric") ?? "").trim() || null,
    displayMode: String(params.get("display_mode") ?? "").trim() || null,
    normalized: parseBooleanParam(params, "normalized", false),
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

function clampText(value, max = 84) {
  const text = String(value ?? "").trim();
  if (!text) return "Not available";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 3)}...`;
}

function SortHeader({ label, sortKey, activeSort, activeDir, onChange }) {
  const isActive = activeSort === sortKey;
  const direction = isActive ? activeDir : null;
  const suffix = direction === "asc" ? "^" : direction === "desc" ? "v" : "";
  return (
    <button
      type="button"
      className="cdc-profile-table-sort"
      onClick={() => onChange(sortKey)}
      title={`Sort by ${label}`}
    >
      {label} {suffix}
    </button>
  );
}

function SectionTitle({ title, subtitle }) {
  return (
    <div className="cdc-profile-section-title">
      <h2>{title}</h2>
      {subtitle ? <p>{subtitle}</p> : null}
    </div>
  );
}

export default function CdcStateFundingProfile({ stateCode }) {
  const query = useMemo(() => parseQueryParams(), []);
  const normalizedStateCode = String(stateCode ?? "").trim().toUpperCase();
  const hasState = /^[A-Z]{2}$/.test(normalizedStateCode);
  const [summary, setSummary] = useState(null);
  const [categories, setCategories] = useState(null);
  const [subcategories, setSubcategories] = useState(null);
  const [details, setDetails] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isDetailsLoading, setIsDetailsLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailsPage, setDetailsPage] = useState(1);
  const [detailsSortBy, setDetailsSortBy] = useState("amount");
  const [detailsSortDir, setDetailsSortDir] = useState("desc");
  const [detailsQuery, setDetailsQuery] = useState("");

  useEffect(() => {
    if (!hasState) {
      setError("A valid 2-letter state code is required in the route.");
      setIsLoading(false);
      return;
    }

    const controller = new AbortController();
    setIsLoading(true);
    setError("");

    const sharedParams = {
      apiBase: API_BASE,
      state: normalizedStateCode,
      basis: query.basis,
      funding_geography_mode: query.fundingGeographyMode,
      appropriation_type: query.appropriationType,
      normalize: query.normalized,
      assistance_type: query.assistanceType,
      fy: query.fy,
      awarding_office: query.awardingOffice,
      funding_office: query.fundingOffice,
      center: query.center,
      signal: controller.signal,
    };

    Promise.all([
      fetchCdcFundingProfileSummary(sharedParams),
      fetchCdcFundingProfileCategories(sharedParams),
      fetchCdcFundingProfileSubcategories(sharedParams),
    ])
      .then(([summaryPayload, categoriesPayload, subcategoriesPayload]) => {
        if (controller.signal.aborted) return;
        setSummary(summaryPayload);
        setCategories(categoriesPayload);
        setSubcategories(subcategoriesPayload);
      })
      .catch((fetchError) => {
        if (controller.signal.aborted) return;
        setError(fetchError?.message ?? "Failed to load CDC state funding profile.");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setIsLoading(false);
      });

    return () => controller.abort();
  }, [
    hasState,
    normalizedStateCode,
    query.appropriationType,
    query.assistanceType,
    query.awardingOffice,
    query.basis,
    query.center,
    query.fundingGeographyMode,
    query.fundingOffice,
    query.fy,
    query.normalized,
  ]);

  useEffect(() => {
    if (!hasState) return;
    const controller = new AbortController();
    setIsDetailsLoading(true);

    fetchCdcFundingProfileDetails({
      apiBase: API_BASE,
      state: normalizedStateCode,
      basis: query.basis,
      funding_geography_mode: query.fundingGeographyMode,
      appropriation_type: query.appropriationType,
      normalize: query.normalized,
      assistance_type: query.assistanceType,
      fy: query.fy,
      awarding_office: query.awardingOffice,
      funding_office: query.fundingOffice,
      center: query.center,
      q: detailsQuery,
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
        setError(detailsError?.message ?? "Failed to load CDC funding detail rows.");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setIsDetailsLoading(false);
      });

    return () => controller.abort();
  }, [
    detailsPage,
    detailsQuery,
    detailsSortBy,
    detailsSortDir,
    hasState,
    normalizedStateCode,
    query.appropriationType,
    query.assistanceType,
    query.awardingOffice,
    query.basis,
    query.center,
    query.fundingGeographyMode,
    query.fundingOffice,
    query.fy,
    query.normalized,
  ]);

  const detailRows = Array.isArray(details?.rows) ? details.rows : [];
  const detailTotalRows = Number(details?.total_rows ?? 0);
  const detailTotalPages = Math.max(1, Math.ceil(detailTotalRows / DETAILS_PAGE_SIZE));
  const categoryRows = Array.isArray(categories?.rows) ? categories.rows : [];
  const subcategoryRows = Array.isArray(subcategories?.rows) ? subcategories.rows : [];
  const stateName = summary?.state_name ?? normalizedStateCode;
  const totalFunding = summary?.total_funding;
  const dataModeLabel = summary?.data_mode_label ?? (query.normalized ? "Normalized data" : "Raw obligations");
  const isNormalizedMode = summary?.normalization_applied ?? query.normalized;
  const normalizationNotice = (
    summary?.normalization_requested &&
    !summary?.normalization_applied &&
    summary?.normalization_note
  )
    ? summary.normalization_note
    : "";
  const groupedSubcategories = useMemo(() => {
    const grouped = new Map();
    subcategoryRows.forEach((row) => {
      const category = String(row?.category ?? "Unclassified").trim() || "Unclassified";
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

  const summaryCards = [
    {
      label: "Total funding",
      value: formatCurrency(totalFunding),
      note: summary?.funding_per_capita != null ? `${formatCurrency(summary.funding_per_capita)} per person` : null,
    },
    {
      label: query.basis === "subaward" ? "Awards represented" : "Awards",
      value: formatCount(summary?.award_count),
      note: detailTotalRows > 0 ? `${formatCount(detailTotalRows)} detail rows` : null,
    },
    {
      label: "Categories",
      value: formatCount(summary?.category_count),
      note: categoryRows.length > 0 ? `${formatCount(categoryRows.length)} visible groups` : null,
    },
    {
      label: "Population estimate",
      value: summary?.population != null ? formatCount(summary.population) : "Not available",
      note: summary?.population_source || null,
    },
  ];

  const filterChips = [
    summary?.timeframe_label || "All available years",
    query.basis === "subaward" ? "Basis: Subawards" : "Basis: Prime awards",
    query.fundingGeographyMode === "statewide_allocation"
      ? "County mode: Estimated statewide allocation"
      : "Geography: Recipient location",
    summary?.appropriation_type_label ? `Funding: ${summary.appropriation_type_label}` : null,
    query.assistanceType ? `Assistance type: ${query.assistanceType}` : null,
    query.center ? `Center: ${query.center}` : null,
    query.awardingOffice ? `Awarding office: ${query.awardingOffice}` : null,
    query.fundingOffice ? `Funding office: ${query.fundingOffice}` : null,
    query.metric ? `Map metric: ${query.metric}` : null,
  ].filter(Boolean);

  const handleSortChange = (nextSortBy) => {
    setDetailsPage(1);
    setDetailsSortDir((currentDir) => {
      if (detailsSortBy !== nextSortBy) return "desc";
      return currentDir === "desc" ? "asc" : "desc";
    });
    setDetailsSortBy(nextSortBy);
  };

  return (
    <div className="cdc-profile-page">
      <Header />
      <main className="cdc-profile-main">
        <header className="cdc-profile-hero">
          <div className="cdc-profile-hero-copy">
            <div className="cdc-profile-kicker">CHIP report</div>
            <div className="cdc-profile-mode-row">
              <span
                className={`cdc-profile-mode-badge ${isNormalizedMode ? "is-normalized" : "is-raw"}`}
                data-testid="cdc-profile-mode-badge"
              >
                {dataModeLabel}
              </span>
            </div>
            <h1>CDC State Funding Profile</h1>
            <p className="cdc-profile-subtitle">
              {stateName} funding obligations summarized from CHIP's CDC funding pipeline in a state report format modeled after CDC grants profiles.
            </p>
            {normalizationNotice ? (
              <p className="cdc-profile-mode-note">{normalizationNotice}</p>
            ) : null}
            <div className="cdc-profile-hero-amount">{formatCurrency(totalFunding)}</div>
            <div className="cdc-profile-hero-label">
              Total obligated funding for {stateName}
            </div>
            <div className="cdc-profile-chip-row">
              <span className="cdc-profile-chip">{stateName}</span>
              {filterChips.map((chip) => (
                <span className="cdc-profile-chip" key={chip}>{chip}</span>
              ))}
            </div>
          </div>
          <aside className="cdc-profile-hero-actions">
            <button type="button" className="chip-secondary-btn" onClick={() => window.print()}>
              Print / Save PDF
            </button>
            <button type="button" className="chip-secondary-btn" disabled title="Export placeholder">
              Export report
            </button>
            <a className="chip-primary-btn cdc-profile-link-btn" href="/">
              Back to Map
            </a>
          </aside>
        </header>

        {isLoading ? <div className="cdc-profile-status">Loading CDC state funding profile...</div> : null}
        {error ? <div className="cdc-profile-status cdc-profile-status-error">{error}</div> : null}

        {!isLoading && !error ? (
          <>
            <section className="cdc-profile-section">
              <SectionTitle
                title="Summary Cards"
                subtitle="High-level state indicators for the active CDC funding filters."
              />
              <div className="cdc-profile-card-grid">
                {summaryCards.map((card) => (
                  <article className="cdc-profile-card" key={card.label}>
                    <div className="cdc-profile-card-label">{card.label}</div>
                    <div className="cdc-profile-card-value">{card.value}</div>
                    {card.note ? <div className="cdc-profile-card-note">{card.note}</div> : null}
                  </article>
                ))}
              </div>
            </section>

            <section className="cdc-profile-section">
              <SectionTitle
                title="Category Summary"
                subtitle="Category totals are CHIP-derived rollups from available CDC center and assistance metadata."
              />
              <div className="cdc-profile-table-wrap">
                <table className="cdc-profile-table">
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th>Obligated amount</th>
                      <th>Percent of total</th>
                      <th>Awards</th>
                    </tr>
                  </thead>
                  <tbody>
                    {categoryRows.map((row) => (
                      <tr key={`cdc-category-${row.category}`}>
                        <td title={row.category}>{clampText(row.category, 84)}</td>
                        <td>{formatCurrency(row.amount)}</td>
                        <td>{formatPercent(row.share_pct)}</td>
                        <td>{formatCount(row.award_count)}</td>
                      </tr>
                    ))}
                    {categoryRows.length === 0 ? (
                      <tr>
                        <td colSpan={4}>No category totals matched the current state filters.</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="cdc-profile-section">
              <SectionTitle
                title="Category + Sub-Category Breakdown"
                subtitle="Grouped rollups help mirror the CDC profile structure while staying tied to CHIP's CDC metadata."
              />
              <div className="cdc-profile-accordion-list">
                {groupedSubcategories.map((group) => (
                  <details key={`cdc-subcategory-${group.category}`} className="cdc-profile-accordion" open>
                    <summary>
                      <span>{group.category}</span>
                      <span>{formatCurrency(group.total)}</span>
                    </summary>
                    <div className="cdc-profile-table-wrap">
                      <table className="cdc-profile-table">
                        <thead>
                          <tr>
                            <th>Sub-category</th>
                            <th>Amount</th>
                            <th>Share of total</th>
                            <th>Share within category</th>
                            <th>Awards</th>
                          </tr>
                        </thead>
                        <tbody>
                          {group.rows.map((row) => (
                            <tr key={`cdc-subcategory-row-${group.category}-${row.subcategory}`}>
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
                {groupedSubcategories.length === 0 ? (
                  <div className="cdc-profile-muted">No sub-category breakdown matched the current state filters.</div>
                ) : null}
              </div>
            </section>

            <section className="cdc-profile-section">
              <SectionTitle
                title="Detailed Awards"
                subtitle="Searchable, sortable award rows for the selected state profile context."
              />
              <div className="cdc-profile-detail-tools">
                <label className="cdc-profile-search">
                  <span>Search detail rows</span>
                  <input
                    type="search"
                    value={detailsQuery}
                    onChange={(event) => {
                      setDetailsPage(1);
                      setDetailsQuery(String(event.target.value ?? ""));
                    }}
                    placeholder="Filter by category, title, grantee, city, county, or FAIN"
                  />
                </label>
                <div className="cdc-profile-muted">
                  {formatCount(detailTotalRows)} rows
                </div>
              </div>
              <div className="cdc-profile-table-wrap">
                <table className="cdc-profile-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th><SortHeader label="Category" sortKey="category" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th><SortHeader label="Sub-category" sortKey="subcategory" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th><SortHeader label="Project title" sortKey="project_title" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th><SortHeader label="Grantee name" sortKey="grantee_name" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th><SortHeader label="City" sortKey="city" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th><SortHeader label="County" sortKey="county" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                      <th><SortHeader label="Amount" sortKey="amount" activeSort={detailsSortBy} activeDir={detailsSortDir} onChange={handleSortChange} /></th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailRows.map((row) => (
                      <tr key={`cdc-detail-${row.record_id}-${row.line_number}`}>
                        <td>{row.line_number}</td>
                        <td title={row.category}>{clampText(row.category, 40)}</td>
                        <td title={row.subcategory}>{clampText(row.subcategory, 48)}</td>
                        <td title={row.project_title}>
                          <div>{clampText(row.project_title, 72)}</div>
                          <div className="cdc-profile-cell-meta">
                            {row.fain || "No FAIN"} | {formatDate(row.latest_action_date)}
                          </div>
                        </td>
                        <td title={row.grantee_name}>{clampText(row.grantee_name, 42)}</td>
                        <td>{row.city || "Not available"}</td>
                        <td>{row.county || "Not available"}</td>
                        <td>{formatCurrency(row.amount)}</td>
                      </tr>
                    ))}
                    {detailRows.length === 0 ? (
                      <tr>
                        <td colSpan={8}>No detail rows matched the current state filters.</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
              {isDetailsLoading ? <div className="cdc-profile-muted">Loading detail rows...</div> : null}
              <div className="cdc-profile-inline-actions">
                <button
                  type="button"
                  className="chip-secondary-btn"
                  disabled={detailsPage <= 1 || isDetailsLoading}
                  onClick={() => setDetailsPage((current) => Math.max(1, current - 1))}
                >
                  Prev
                </button>
                <span className="cdc-profile-muted">Page {detailsPage} of {detailTotalPages}</span>
                <button
                  type="button"
                  className="chip-secondary-btn"
                  disabled={detailsPage >= detailTotalPages || isDetailsLoading}
                  onClick={() => setDetailsPage((current) => Math.min(detailTotalPages, current + 1))}
                >
                  Next
                </button>
              </div>
            </section>

            <section className="cdc-profile-section">
              <SectionTitle
                title="Methodology / Notes"
                subtitle="Plain-language guidance for interpreting this CHIP CDC funding profile."
              />
              <ul className="cdc-profile-list">
                {(Array.isArray(summary?.methodology_notes) ? summary.methodology_notes : []).map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
              {summary?.grouping ? (
                <div className="cdc-profile-note-block">
                  <div><strong>{summary.grouping.category_label}:</strong> {summary.grouping.category_method}</div>
                  <div><strong>{summary.grouping.subcategory_label}:</strong> {summary.grouping.subcategory_method}</div>
                </div>
              ) : null}
              {query.displayMode ? (
                <p className="cdc-profile-muted">Launch context display mode: {query.displayMode}.</p>
              ) : null}
            </section>
          </>
        ) : null}
      </main>
    </div>
  );
}
