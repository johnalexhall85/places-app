import { useEffect, useMemo, useState } from "react";
import Header from "../components/Header";
import { API_BASE } from "../config/apiBase";
import {
  fetchCdcFundingProfileCategories,
  fetchCdcFundingProfileSubcategories,
  fetchCdcFundingProfileSummary,
} from "../api/cdcFunding";
import "./CdcStateFundingProfile.css";

function parseQueryParams() {
  const search = typeof window !== "undefined" ? window.location.search : "";
  const params = new URLSearchParams(search);
  return {
    fiscalYear: Number.isFinite(Number(params.get("fiscal_year") ?? params.get("fy")))
      ? Number(params.get("fiscal_year") ?? params.get("fy"))
      : null,
    metric: String(params.get("metric") ?? "total_funding").trim() || "total_funding",
    fundingType: String(params.get("funding_type") ?? "total_cdc_funding").trim() || "total_cdc_funding",
    cdcCenter: String(params.get("cdc_center") ?? "").trim() || null,
    programArea: String(params.get("program_area") ?? "").trim() || null,
    mechanism: String(params.get("mechanism") ?? "").trim() || null,
    recipientType: String(params.get("recipient_type") ?? "").trim() || null,
    timeAggregation: String(params.get("time_aggregation") ?? "").trim() || null,
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

function clampText(value, max = 84) {
  const text = String(value ?? "").trim();
  if (!text) return "Not available";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 3)}...`;
}

function formatMetricValue(metric, value) {
  const numeric = toFinite(value);
  if (numeric == null) return "Not available";
  if (metric === "share_national") {
    return `${numeric.toFixed(2)}%`;
  }
  return formatCurrency(numeric);
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
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

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
      fiscal_year: query.fiscalYear,
      metric: query.metric,
      funding_type: query.fundingType,
      cdc_center: query.cdcCenter,
      program_area: query.programArea,
      mechanism: query.mechanism,
      recipient_type: query.recipientType,
      time_aggregation: query.timeAggregation,
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
    query.cdcCenter,
    query.fiscalYear,
    query.fundingType,
    query.mechanism,
    query.metric,
    query.programArea,
    query.recipientType,
    query.timeAggregation,
  ]);

  const categoryRows = Array.isArray(categories?.rows) ? categories.rows : [];
  const subcategoryRows = Array.isArray(subcategories?.rows) ? subcategories.rows : [];
  const stateName = summary?.state_name ?? normalizedStateCode;
  const filterContext = summary?.filter_context ?? {};
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
      value: formatCurrency(summary?.total_funding),
      note: summary?.timeframe_label ?? "Current filter context",
    },
    {
      label: summary?.selected_metric_label ?? "Selected metric",
      value: formatMetricValue(summary?.selected_metric, summary?.selected_metric_value),
      note: filterContext?.legend_title ?? null,
    },
    {
      label: "Awards represented",
      value: formatCount(summary?.award_count),
      note: summary?.contract_award_count ? `${formatCount(summary.contract_award_count)} contract awards` : null,
    },
    {
      label: "Population estimate",
      value: formatCount(summary?.population),
      note: summary?.funding_per_capita != null
        ? `${formatCurrency(summary.funding_per_capita)} per person`
        : null,
    },
  ];

  const filterChips = [
    summary?.timeframe_label,
    filterContext?.funding_type_label,
    filterContext?.cdc_center_label,
    filterContext?.mechanism_label,
    filterContext?.recipient_type_label,
    filterContext?.time_aggregation_label,
  ].filter(Boolean);

  const methodologyNotes = Array.isArray(summary?.methodology_notes)
    ? summary.methodology_notes.filter(Boolean)
    : [];

  return (
    <div className="cdc-profile-page">
      <Header />
      <main className="cdc-profile-main">
        <header className="cdc-profile-hero">
          <div className="cdc-profile-hero-copy">
            <div className="cdc-profile-kicker">CHIP funding intelligence</div>
            <div className="cdc-profile-mode-row">
              <span className="cdc-profile-mode-badge is-raw" data-testid="cdc-profile-mode-badge">
                CHIP funding model
              </span>
            </div>
            <h1>CDC State Funding Profile</h1>
            <p className="cdc-profile-subtitle">
              {stateName} funding summarized from CHIP&apos;s unified CDC funding model, with USAspending as the transactional backbone and TAGGS used for CDC program-area enrichment.
            </p>
            <div className="cdc-profile-hero-amount">{formatCurrency(summary?.total_funding)}</div>
            <div className="cdc-profile-hero-label">
              {summary?.legend_title ?? "Filtered CDC funding total"}
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
                subtitle="State totals and comparisons are aligned to the same filter context as the map."
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
                title="Program Area Summary"
                subtitle="Program areas are derived from TAGGS ALN-linked classification first, with CDC metadata fallback when enrichment is unavailable."
              />
              <div className="cdc-profile-table-wrap">
                <table className="cdc-profile-table">
                  <thead>
                    <tr>
                      <th>Program area</th>
                      <th>Funding</th>
                      <th>Share of state total</th>
                      <th>Awards</th>
                      <th>Programs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {categoryRows.map((row) => (
                      <tr key={`cdc-category-${row.category_value ?? row.category}`}>
                        <td title={row.category}>{clampText(row.category, 84)}</td>
                        <td>{formatCurrency(row.amount)}</td>
                        <td>{formatPercent(row.share_pct)}</td>
                        <td>{formatCount(row.award_count)}</td>
                        <td>{formatCount(row.subcategory_count)}</td>
                      </tr>
                    ))}
                    {categoryRows.length === 0 ? (
                      <tr>
                        <td colSpan={5}>No program areas matched the current state filters.</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="cdc-profile-section">
              <SectionTitle
                title="Program Breakdown"
                subtitle="Program rows show the enriched program-level view that sits under each CHIP funding program area."
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
                            <th>Program</th>
                            <th>Funding</th>
                            <th>Share of state total</th>
                            <th>Share of program area</th>
                            <th>Awards</th>
                          </tr>
                        </thead>
                        <tbody>
                          {group.rows.map((row) => (
                            <tr key={`cdc-subcategory-row-${group.category}-${row.subcategory}`}>
                              <td title={row.subcategory}>{clampText(row.subcategory, 108)}</td>
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
                  <div className="cdc-profile-muted">No program breakdown matched the current state filters.</div>
                ) : null}
              </div>
            </section>

            <section className="cdc-profile-section">
              <SectionTitle
                title="Method Notes"
                subtitle="How the unified CDC funding map combines USAspending and TAGGS."
              />
              <div className="cdc-profile-note-block">
                <div>
                  USAspending supplies award, subaward, and contract transactions. TAGGS contributes ALN-linked CDC center and program-area enrichment so the funding map behaves like an intelligence layer instead of a raw transaction dump.
                </div>
                {summary?.grouping?.category_method ? (
                  <div>{summary.grouping.category_method}</div>
                ) : null}
                {summary?.grouping?.subcategory_method ? (
                  <div>{summary.grouping.subcategory_method}</div>
                ) : null}
              </div>
              {methodologyNotes.length > 0 ? (
                <ul className="cdc-profile-list">
                  {methodologyNotes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              ) : null}
            </section>
          </>
        ) : null}
      </main>
    </div>
  );
}
