import { useEffect, useMemo, useState } from "react";
import Footer from "../components/Footer";
import Header from "../components/Header";
import { API_BASE } from "../config/apiBase";
import {
  fetchCdcFundingProfileDetails,
  fetchCdcFundingProfileOverview,
} from "../api/cdcFunding";
import {
  CDC_DEFAULT_FUNDING_MODE,
  getCdcFundingModeLabel,
  isChipAccountClassificationCdcFundingMode,
  isNormalizedCdcFundingMode,
  normalizeCdcFundingMode,
} from "../utils/cdcFundingMode";
import "./CdcStateFundingProfile.css";

function parseBooleanParam(params, key) {
  const raw = String(params.get(key) ?? "").trim().toLowerCase();
  if (!raw) return null;
  if (raw === "true") return true;
  if (raw === "false") return false;
  return null;
}

function parseQueryParams() {
  const search = typeof window !== "undefined" ? window.location.search : "";
  const params = new URLSearchParams(search);
  const fiscalYearToken = params.get("fy") ?? params.get("fiscal_year");
  const fundingModeToken = params.get("mode") ?? params.get("funding_mode");
  return {
    fiscalYear: Number.isFinite(Number(fiscalYearToken))
      ? Number(fiscalYearToken)
      : null,
    metric: String(params.get("metric") ?? "total_funding").trim() || "total_funding",
    fundingType: String(params.get("funding_type") ?? "total_cdc_funding").trim() || "total_cdc_funding",
    fundingMode: normalizeCdcFundingMode(fundingModeToken ?? CDC_DEFAULT_FUNDING_MODE),
    cdcCenter: String(params.get("cdc_center") ?? "").trim() || null,
    programArea: String(params.get("program_area") ?? "").trim() || null,
    mechanism: String(params.get("mechanism") ?? "").trim() || null,
    recipientType: String(params.get("recipient_type") ?? "").trim() || null,
    timeAggregation: String(params.get("time_aggregation") ?? "").trim() || null,
    includeMandatory: parseBooleanParam(params, "include_mandatory"),
    includeEmergency: parseBooleanParam(params, "include_emergency"),
    includeSupplemental: parseBooleanParam(params, "include_supplemental"),
    includePphf: parseBooleanParam(params, "include_pphf"),
    includeTransfers: parseBooleanParam(params, "include_transfers"),
    includePendingReview: parseBooleanParam(params, "include_pending_review"),
    reviewMode: String(params.get("review_mode") ?? "").trim() || null,
    fundingScopePreset: String(params.get("funding_scope_preset") ?? "").trim() || null,
    awardType: String(params.get("award_type") ?? "").trim() || null,
    emergencySupplementalScope: String(params.get("emergency_supplemental_scope") ?? "").trim() || null,
    reviewStatus: String(params.get("review_status") ?? "").trim() || null,
    transfersScope: String(params.get("transfers_scope") ?? "").trim() || null,
    dataSourceScope: String(params.get("data_source_scope") ?? "").trim() || null,
  };
}

function toFinite(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function firstDefined(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined) {
      return value;
    }
  }
  return null;
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

function formatDate(value) {
  const text = String(value ?? "").trim();
  if (!text) return "Not available";
  return text.slice(0, 10);
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
  const [isLoadingOverview, setIsLoadingOverview] = useState(true);
  const [overviewError, setOverviewError] = useState("");
  const [details, setDetails] = useState(null);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);
  const [detailsError, setDetailsError] = useState("");
  const [detailSearchInput, setDetailSearchInput] = useState("");
  const [detailQuery, setDetailQuery] = useState("");
  const [detailPage, setDetailPage] = useState(1);
  const [detailPageSize, setDetailPageSize] = useState(25);
  const [detailSortBy, setDetailSortBy] = useState("amount");
  const [detailSortDir, setDetailSortDir] = useState("desc");

  useEffect(() => {
    setDetailSearchInput("");
    setDetailQuery("");
    setDetailPage(1);
    setDetailPageSize(25);
    setDetailSortBy("amount");
    setDetailSortDir("desc");
  }, [
    normalizedStateCode,
    query.fiscalYear,
    query.fundingMode,
    query.fundingType,
    query.includeMandatory,
    query.includeEmergency,
    query.includeSupplemental,
    query.includePphf,
    query.includeTransfers,
    query.includePendingReview,
    query.reviewMode,
    query.fundingScopePreset,
    query.awardType,
    query.emergencySupplementalScope,
    query.reviewStatus,
    query.transfersScope,
    query.dataSourceScope,
  ]);

  useEffect(() => {
    if (!hasState) {
      setOverviewError("A valid 2-letter state code is required in the route.");
      setIsLoadingOverview(false);
      return;
    }

    const controller = new AbortController();
    setIsLoadingOverview(true);
    setOverviewError("");

    fetchCdcFundingProfileOverview({
      apiBase: API_BASE,
      state: normalizedStateCode,
      fiscal_year: query.fiscalYear,
      metric: query.metric,
      funding_type: query.fundingType,
      funding_mode: query.fundingMode,
      cdc_center: query.cdcCenter,
      program_area: query.programArea,
      mechanism: query.mechanism,
      recipient_type: query.recipientType,
      time_aggregation: query.timeAggregation,
      include_mandatory: query.includeMandatory,
      include_emergency: query.includeEmergency,
      include_supplemental: query.includeSupplemental,
      include_pphf: query.includePphf,
      include_transfers: query.includeTransfers,
      include_pending_review: query.includePendingReview,
      review_mode: query.reviewMode,
      funding_scope_preset: query.fundingScopePreset,
      award_type: query.awardType,
      emergency_supplemental_scope: query.emergencySupplementalScope,
      review_status: query.reviewStatus,
      transfers_scope: query.transfersScope,
      data_source_scope: query.dataSourceScope,
      signal: controller.signal,
    })
      .then((overviewPayload) => {
        if (controller.signal.aborted) return;
        setSummary(overviewPayload?.summary ?? null);
        setCategories(overviewPayload?.categories ?? null);
        setSubcategories(overviewPayload?.subcategories ?? null);
      })
      .catch((fetchError) => {
        if (controller.signal.aborted) return;
        setOverviewError(fetchError?.message ?? "Failed to load CDC state funding profile.");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setIsLoadingOverview(false);
      });

    return () => controller.abort();
  }, [
    hasState,
    normalizedStateCode,
    query.cdcCenter,
    query.fiscalYear,
    query.fundingType,
    query.fundingMode,
    query.mechanism,
    query.metric,
    query.programArea,
    query.recipientType,
    query.timeAggregation,
    query.includeMandatory,
    query.includeEmergency,
    query.includeSupplemental,
    query.includePphf,
    query.includeTransfers,
    query.includePendingReview,
    query.reviewMode,
    query.fundingScopePreset,
    query.awardType,
    query.emergencySupplementalScope,
    query.reviewStatus,
    query.transfersScope,
    query.dataSourceScope,
  ]);

  useEffect(() => {
    if (!hasState) {
      setDetailsError("A valid 2-letter state code is required in the route.");
      setIsLoadingDetails(false);
      return;
    }

    const controller = new AbortController();
    setIsLoadingDetails(true);
    setDetailsError("");

    fetchCdcFundingProfileDetails({
      apiBase: API_BASE,
      state: normalizedStateCode,
      fiscal_year: query.fiscalYear,
      funding_type: query.fundingType,
      funding_mode: query.fundingMode,
      include_mandatory: query.includeMandatory,
      include_emergency: query.includeEmergency,
      include_supplemental: query.includeSupplemental,
      include_pphf: query.includePphf,
      include_transfers: query.includeTransfers,
      include_pending_review: query.includePendingReview,
      review_mode: query.reviewMode,
      funding_scope_preset: query.fundingScopePreset,
      award_type: query.awardType,
      emergency_supplemental_scope: query.emergencySupplementalScope,
      review_status: query.reviewStatus,
      transfers_scope: query.transfersScope,
      data_source_scope: query.dataSourceScope,
      q: detailQuery,
      page: detailPage,
      page_size: detailPageSize,
      sort_by: detailSortBy,
      sort_dir: detailSortDir,
      signal: controller.signal,
    })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setDetails(payload);
      })
      .catch((fetchError) => {
        if (controller.signal.aborted) return;
        setDetailsError(fetchError?.message ?? "Failed to load CDC funding detail rows.");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setIsLoadingDetails(false);
      });

    return () => controller.abort();
  }, [
    hasState,
    normalizedStateCode,
    query.fiscalYear,
    query.fundingType,
    query.fundingMode,
    query.includeMandatory,
    query.includeEmergency,
    query.includeSupplemental,
    query.includePphf,
    query.includeTransfers,
    query.includePendingReview,
    query.reviewMode,
    query.fundingScopePreset,
    query.awardType,
    query.emergencySupplementalScope,
    query.reviewStatus,
    query.transfersScope,
    query.dataSourceScope,
    detailPage,
    detailPageSize,
    detailQuery,
    detailSortBy,
    detailSortDir,
  ]);

  const categoryRows = Array.isArray(categories?.rows) ? categories.rows : [];
  const subcategoryRows = Array.isArray(subcategories?.rows) ? subcategories.rows : [];
  const detailRows = Array.isArray(details?.rows) ? details.rows : [];
  const canonicalProfile = summary?.profile ?? categories?.profile ?? subcategories?.profile ?? null;
  const stateName = canonicalProfile?.state_name ?? summary?.state_name ?? normalizedStateCode;
  const filterContext = canonicalProfile?.metadata?.metric_context ?? summary?.filter_context ?? {};
  const fundingModeLabel = String(
    canonicalProfile?.funding_mode_label
    ?? summary?.funding_mode_label
    ?? getCdcFundingModeLabel(query.fundingMode)
  ).trim();
  const effectiveFundingMode = (
    canonicalProfile?.funding_mode_effective ?? summary?.funding_mode_effective ?? query.fundingMode
  );
  const isChipV1ProfileMode = isChipAccountClassificationCdcFundingMode(effectiveFundingMode);
  const fundingModeClass = (
    isChipV1ProfileMode
    || isNormalizedCdcFundingMode(effectiveFundingMode)
  )
    ? "is-normalized"
    : "is-raw";
  const fundingModeNote = String(
    canonicalProfile?.normalization_note
    ?? summary?.normalization_note
    ?? ""
  ).trim();
  const pendingReviewTotal = toFinite(
    firstDefined(
      canonicalProfile?.needs_review_obligations,
      canonicalProfile?.metadata?.pending_review_total,
      summary?.pending_review_total
    )
  );
  const reviewedTotal = toFinite(
    firstDefined(
      canonicalProfile?.reviewed_obligations,
      canonicalProfile?.metadata?.reviewed_total,
      summary?.reviewed_total,
      summary?.reviewed_obligations
    )
  );
  const pendingReviewAccountCount = toFinite(
    firstDefined(
      canonicalProfile?.needs_review_account_count,
      canonicalProfile?.metadata?.pending_review_account_count,
      summary?.pending_review_account_count
    )
  );
  const pendingReviewAwardCount = toFinite(
    firstDefined(
      canonicalProfile?.metadata?.pending_review_award_count,
      summary?.pending_review_award_count
    )
  );
  const hasReviewMetadata = isChipV1ProfileMode && Boolean(
    summary?.includes_pending_review !== undefined
    || canonicalProfile?.metadata?.includes_pending_review !== undefined
    || pendingReviewTotal != null
    || reviewedTotal != null
    || pendingReviewAccountCount != null
    || pendingReviewAwardCount != null
  );
  const includesPendingReview = hasReviewMetadata && Boolean(
    summary?.includes_pending_review
    || canonicalProfile?.metadata?.includes_pending_review
    || (pendingReviewTotal != null && pendingReviewTotal > 0)
    || (pendingReviewAccountCount != null && pendingReviewAccountCount > 0)
    || (pendingReviewAwardCount != null && pendingReviewAwardCount > 0)
  );
  const pendingReviewNote = includesPendingReview
    ? `* Includes some accounts pending final review. Pending-review amount included: ${formatCurrency(pendingReviewTotal)}.`
    : "";
  const dataSourcesLabel = isChipV1ProfileMode
    ? "USAspending account breakdowns"
    : "USAspending and TAGGS";
  const categoryTotalsByName = useMemo(() => {
    const totals = new Map();
    categoryRows.forEach((row) => {
      const category = String(row?.category ?? "").trim();
      if (!category) return;
      totals.set(category, toFinite(row?.amount));
    });
    return totals;
  }, [categoryRows]);
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
      total: categoryTotalsByName.get(category) ?? null,
    }));
  }, [categoryTotalsByName, subcategoryRows]);
  const detailTotalRows = Math.max(0, Number(details?.total_rows ?? 0));
  const detailResolvedPage = Math.max(1, Number(details?.page ?? detailPage));
  const detailResolvedPageSize = Math.max(1, Number(details?.page_size ?? detailPageSize));
  const detailTotalPages = Math.max(1, Math.ceil(detailTotalRows / detailResolvedPageSize));

  const summaryCards = [
    {
      label: "Total funding",
      value: formatCurrency(canonicalProfile?.total_funding ?? summary?.total_funding),
      note: canonicalProfile?.timeframe_label ?? summary?.timeframe_label ?? "Current filter context",
    },
    {
      label: summary?.selected_metric_label ?? "Selected metric",
      value: formatMetricValue(summary?.selected_metric, summary?.selected_metric_value),
      note: filterContext?.legend_title ?? null,
    },
    {
      label: "Awards represented",
      value: formatCount(canonicalProfile?.award_count ?? summary?.award_count),
      note: (canonicalProfile?.contract_award_count ?? summary?.contract_award_count)
        ? `${formatCount(canonicalProfile?.contract_award_count ?? summary?.contract_award_count)} contract awards`
        : null,
    },
    {
      label: "Population estimate",
      value: formatCount(canonicalProfile?.population ?? summary?.population),
      note: (canonicalProfile?.funding_per_capita ?? summary?.funding_per_capita) != null
        ? `${formatCurrency(canonicalProfile?.funding_per_capita ?? summary?.funding_per_capita)} per person`
        : null,
    },
    ...(hasReviewMetadata ? [
      {
        label: "Review status totals",
        value: `Reviewed ${formatCurrency(reviewedTotal)}`,
        note: [
          `Needs review ${formatCurrency(pendingReviewTotal)}`,
          pendingReviewAccountCount != null
            ? `${formatCount(pendingReviewAccountCount)} pending-review accounts`
            : null,
        ].filter(Boolean).join(" • "),
      },
    ] : []),
  ];

  const filterChips = [
    fundingModeLabel,
    canonicalProfile?.timeframe_label ?? summary?.timeframe_label,
    filterContext?.funding_type_label,
    filterContext?.cdc_center_label,
    filterContext?.mechanism_label,
    filterContext?.recipient_type_label,
    filterContext?.time_aggregation_label,
  ].filter(Boolean);

  const methodologyNotes = Array.isArray(summary?.methodology_notes)
    ? summary.methodology_notes.filter(Boolean)
    : [];
  const reportDateLabel = formatDate(
    canonicalProfile?.latest_action_date_max
    ?? summary?.latest_action_date_max
    ?? summary?.latest_action_date
    ?? ""
  );
  const reportVersionLabel = String(
    canonicalProfile?.funding_mode_effective
    ?? summary?.funding_mode_effective
    ?? query.fundingMode
    ?? "not_available"
  ).trim();
  const grouping = summary?.grouping ?? categories?.grouping ?? subcategories?.grouping ?? {};
  const categoryLabel = String(grouping?.category_label ?? "Program Area").trim() || "Program Area";
  const subcategoryLabel = String(grouping?.subcategory_label ?? "Program").trim() || "Program";
  const countLabel = String(grouping?.count_label ?? "Awards").trim() || "Awards";
  const subgroupCountLabel = String(grouping?.subcategory_count_label ?? "Programs").trim() || "Programs";

  function handleDetailSearchSubmit(event) {
    event.preventDefault();
    setDetailPage(1);
    setDetailQuery(String(detailSearchInput ?? "").trim());
  }

  function handleDetailSearchClear() {
    setDetailSearchInput("");
    setDetailPage(1);
    setDetailQuery("");
  }

  function handleDetailSort(nextSortBy) {
    const normalizedNextSortBy = String(nextSortBy ?? "").trim();
    if (!normalizedNextSortBy) return;
    setDetailPage(1);
    if (detailSortBy === normalizedNextSortBy) {
      setDetailSortDir((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setDetailSortBy(normalizedNextSortBy);
    setDetailSortDir("desc");
  }

  function renderSortLabel(label, sortBy) {
    if (detailSortBy !== sortBy) return label;
    return `${label} ${detailSortDir === "asc" ? "↑" : "↓"}`;
  }

  return (
    <div className="cdc-profile-page">
      <Header />
      <main className="cdc-profile-main">
        <header className="cdc-profile-hero">
          <div className="cdc-profile-hero-copy">
            <div className="cdc-profile-kicker">CHIP by Public Data Observatory</div>
            <div className="cdc-profile-mode-row">
              <span className={`cdc-profile-mode-badge ${fundingModeClass}`} data-testid="cdc-profile-mode-badge">
                {fundingModeLabel}
              </span>
            </div>
            <h1>CDC State Funding Profile</h1>
            <p className="cdc-profile-subtitle">
              {stateName} funding summarized for analytical review using the selected CHIP funding model. The default model uses federal account classifications and maps award-linked obligations.
            </p>
            {fundingModeNote ? <p className="cdc-profile-mode-note">{fundingModeNote}</p> : null}
            {pendingReviewNote ? <p className="cdc-profile-mode-note">{pendingReviewNote}</p> : null}
            <div className="cdc-profile-hero-amount">
              {formatCurrency(canonicalProfile?.total_funding ?? summary?.total_funding)}
            </div>
            <div className="cdc-profile-hero-label">
              {summary?.legend_title ?? "Filtered CDC funding total"}
            </div>
            <div className="cdc-profile-hero-meta">
              <span>Last Updated: {reportDateLabel}</span>
              <span>Version: {reportVersionLabel}</span>
              <span>Data Sources: {dataSourcesLabel}</span>
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

        {isLoadingOverview ? <div className="cdc-profile-status">Loading PDO funding report...</div> : null}
        {overviewError ? <div className="cdc-profile-status cdc-profile-status-error">{overviewError}</div> : null}

        {!overviewError ? (
          <>
            <section className="cdc-profile-section">
              <SectionTitle
                title="Summary Cards"
                subtitle="State totals and comparisons are aligned to the same filter context as the map."
              />
              {isLoadingOverview ? (
                <div className="cdc-profile-muted">Preparing state totals and summary cards...</div>
              ) : (
                <div className="cdc-profile-card-grid">
                  {summaryCards.map((card) => (
                    <article className="cdc-profile-card" key={card.label}>
                      <div className="cdc-profile-card-label">{card.label}</div>
                      <div className="cdc-profile-card-value">{card.value}</div>
                      {card.note ? <div className="cdc-profile-card-note">{card.note}</div> : null}
                    </article>
                  ))}
                </div>
              )}
            </section>

            <section className="cdc-profile-section">
              <SectionTitle
                title={`${categoryLabel} Summary`}
                subtitle={summary?.grouping?.category_method ?? "Rows are grouped using the active state-profile classification method for this funding view."}
              />
              {isLoadingOverview ? (
                <div className="cdc-profile-muted">Loading category summary...</div>
              ) : (
                <div className="cdc-profile-table-wrap">
                  <table className="cdc-profile-table">
                    <thead>
                      <tr>
                        <th>{categoryLabel}</th>
                        <th>Funding</th>
                        <th>Share of state total</th>
                        <th>{countLabel}</th>
                        <th>{subgroupCountLabel}</th>
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
              )}
            </section>

            <section className="cdc-profile-section">
              <SectionTitle
                title={`${subcategoryLabel} Breakdown`}
                subtitle={summary?.grouping?.subcategory_method ?? "Subgroup rows summarize the breakdown that sits under each top-level funding category for this state profile."}
              />
              {isLoadingOverview ? (
                <div className="cdc-profile-muted">Loading subcategory summary...</div>
              ) : (
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
                              <th>{subcategoryLabel}</th>
                              <th>Funding</th>
                              <th>Share of state total</th>
                              <th>{`Share of ${categoryLabel.toLowerCase()}`}</th>
                              <th>{countLabel}</th>
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
              )}
            </section>

            <section className="cdc-profile-section">
              <SectionTitle
                title="Detailed Awards"
                subtitle="Award-level detail loads separately so the summary sections render before the full table is ready."
              />
              <div className="cdc-profile-detail-tools">
                <form id="cdc-profile-detail-search" className="cdc-profile-search" onSubmit={handleDetailSearchSubmit}>
                  <span>Search detail rows</span>
                  <input
                    type="search"
                    value={detailSearchInput}
                    onChange={(event) => setDetailSearchInput(event.target.value)}
                    placeholder="Program, recipient, project title, city, county, or FAIN"
                    aria-label="Search detail rows"
                  />
                </form>
                <div className="cdc-profile-inline-actions">
                  <label>
                    Page size{" "}
                    <select
                      aria-label="Detail page size"
                      value={detailPageSize}
                      onChange={(event) => {
                        setDetailPage(1);
                        setDetailPageSize(Number(event.target.value));
                      }}
                    >
                      {[25, 50, 100].map((size) => (
                        <option key={size} value={size}>
                          {size}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button type="submit" className="chip-primary-btn" form="cdc-profile-detail-search">
                    Apply Search
                  </button>
                  <button
                    type="button"
                    className="chip-secondary-btn"
                    onClick={handleDetailSearchClear}
                    disabled={!detailQuery && !detailSearchInput}
                  >
                    Clear
                  </button>
                </div>
              </div>
              <div className="cdc-profile-inline-actions">
                <div className="cdc-profile-muted">
                  {detailTotalRows.toLocaleString("en-US")} rows
                  {detailQuery ? ` matching "${detailQuery}"` : ""}
                </div>
                <div className="cdc-profile-inline-actions">
                  <button
                    type="button"
                    className="chip-secondary-btn"
                    onClick={() => setDetailPage((current) => Math.max(1, current - 1))}
                    disabled={detailResolvedPage <= 1 || isLoadingDetails}
                  >
                    Previous
                  </button>
                  <div className="cdc-profile-muted">
                    Page {detailResolvedPage} of {detailTotalPages}
                  </div>
                  <button
                    type="button"
                    className="chip-secondary-btn"
                    onClick={() => setDetailPage((current) => Math.min(detailTotalPages, current + 1))}
                    disabled={detailResolvedPage >= detailTotalPages || isLoadingDetails}
                  >
                    Next
                  </button>
                </div>
              </div>
              {isLoadingDetails ? (
                <div className="cdc-profile-muted">Loading detailed awards table...</div>
              ) : null}
              {detailsError ? (
                <div className="cdc-profile-status cdc-profile-status-error">{detailsError}</div>
              ) : (
                <div className="cdc-profile-table-wrap">
                  <table className="cdc-profile-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>
                          <button type="button" className="cdc-profile-table-sort" onClick={() => handleDetailSort("category")}>
                            {renderSortLabel("Category", "category")}
                          </button>
                        </th>
                        <th>
                          <button type="button" className="cdc-profile-table-sort" onClick={() => handleDetailSort("subcategory")}>
                            {renderSortLabel("Program", "subcategory")}
                          </button>
                        </th>
                        <th>
                          <button type="button" className="cdc-profile-table-sort" onClick={() => handleDetailSort("grantee_name")}>
                            {renderSortLabel("Recipient", "grantee_name")}
                          </button>
                        </th>
                        <th>
                          <button type="button" className="cdc-profile-table-sort" onClick={() => handleDetailSort("amount")}>
                            {renderSortLabel("Amount", "amount")}
                          </button>
                        </th>
                        <th>
                          <button type="button" className="cdc-profile-table-sort" onClick={() => handleDetailSort("latest_action_date")}>
                            {renderSortLabel("Latest action", "latest_action_date")}
                          </button>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {detailRows.map((row) => (
                        <tr key={row.record_id ?? `${row.line_number}-${row.fain}`}>
                          <td>{formatCount(row.line_number)}</td>
                          <td>
                            <div>{clampText(row.category, 56)}</div>
                            <div className="cdc-profile-cell-meta">{row.record_type ?? "award"}</div>
                          </td>
                          <td>
                            <div title={row.subcategory ?? row.project_title}>
                              {clampText(row.subcategory ?? row.project_title, 88)}
                            </div>
                            {row.project_title ? (
                              <div className="cdc-profile-cell-meta" title={row.project_title}>
                                {clampText(row.project_title, 104)}
                              </div>
                            ) : null}
                          </td>
                          <td>
                            <div title={row.grantee_name}>{clampText(row.grantee_name, 72)}</div>
                            <div className="cdc-profile-cell-meta">
                              {[row.city, row.county].filter(Boolean).join(", ") || "Location not available"}
                            </div>
                            {row.fain ? (
                              <div className="cdc-profile-cell-meta">FAIN: {row.fain}</div>
                            ) : null}
                          </td>
                          <td>{formatCurrency(row.amount)}</td>
                          <td>
                            <div>{formatDate(row.latest_action_date)}</div>
                            {row.usaspending_permalink ? (
                              <div className="cdc-profile-cell-meta">
                                <a href={row.usaspending_permalink} target="_blank" rel="noreferrer">
                                  View USAspending
                                </a>
                              </div>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                      {detailRows.length === 0 && !isLoadingDetails ? (
                        <tr>
                          <td colSpan={6}>No award rows matched the current detail request.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="cdc-profile-section">
              <SectionTitle
                title="Data Sources"
                subtitle="Primary sources and scope notes for this state funding report."
              />
              <div className="cdc-profile-note-block">
                {isChipV1ProfileMode ? (
                  <>
                    <div>USAspending supplies award-level account breakdown rows and geographic fields.</div>
                    <div>CHIP Account Classification v1 identifies CDC-related federal accounts and includes pending-review accounts with a separate note.</div>
                  </>
                ) : (
                  <>
                    <div>USAspending supplies award, subaward, and contract transaction records.</div>
                    <div>TAGGS contributes CDC center, program-area, and ALN-linked enrichment where the source evidence supports classification.</div>
                  </>
                )}
                <div>Reported values may reflect filtered summaries, modeled grouping logic, or reconstructed scope alignment rather than source-system financial statements.</div>
              </div>
            </section>

            <section className="cdc-profile-section">
              <SectionTitle
                title="Method Notes"
                subtitle={
                  isChipV1ProfileMode
                    ? "How CHIP Account Classification v1 powers this state profile."
                    : "How the CHIP funding model combines USAspending and TAGGS."
                }
              />
              <div className="cdc-profile-note-block">
                {isChipV1ProfileMode ? (
                  <div>
                    Federal account classifications identify the public CDC map account set, then award-linked obligations distribute funding to state geographies.
                  </div>
                ) : (
                  <div>
                    USAspending supplies award, subaward, and contract transactions. TAGGS contributes ALN-linked CDC center and program-area enrichment so the funding map can be interpreted as a source-aware analytical layer rather than a raw transaction dump.
                  </div>
                )}
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
      <Footer />
    </div>
  );
}
