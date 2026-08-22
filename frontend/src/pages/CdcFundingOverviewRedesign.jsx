import { useEffect, useMemo, useRef, useState } from "react";
import {
  CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
  fetchCdcFundingObligationTrends,
  fetchCdcFundingTrendAccounts,
} from "../api/cdcFundingOverview";
import { API_BASE } from "../config/apiBase";
import {
  compareMoneyStrings,
  decimalStringToNumber,
  formatCompactCurrencyFromDecimalString,
  formatCurrencyFromDecimalString,
  formatPercentFromDecimalString,
  sumMoneyStrings,
} from "../utils/cdcFundingFormatting";

const TAB_DEFINITIONS = [
  { id: "overview", label: "Overview" },
  { id: "trends", label: "Trends" },
  { id: "accounts", label: "Account Details" },
];

const FISCAL_MONTHS = [
  "Oct",
  "Nov",
  "Dec",
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
];

const SERIES_STYLES = {
  primary: { color: "#075985", dash: "" },
  context: { color: "#64748b", dash: "3 5" },
};
const COMPARISON_STYLES = [
  { color: "#9f1239", dash: "9 5" },
  { color: "#166534", dash: "4 4" },
  { color: "#6d28d9", dash: "12 4 3 4" },
  { color: "#a16207", dash: "2 5" },
  { color: "#0f766e", dash: "10 3" },
  { color: "#334155", dash: "5 2 2 2" },
];

function comparisonStyle(fiscalYear) {
  return COMPARISON_STYLES[
    Math.abs(Number(fiscalYear)) % COMPARISON_STYLES.length
  ];
}

function accountName(account) {
  return String(account?.federal_account_name ?? "").trim();
}

function accountSymbol(account) {
  return String(account?.federal_account_symbol ?? "").trim();
}

export function conciseAccountName(account) {
  const official = accountName(account);
  if (!official) return accountSymbol(account) || "Unknown federal account";
  return (
    official
      .replace(
        /,\s*Centers for Disease Control and Prevention(?:,\s*Health and Human Services)?$/i,
        "",
      )
      .replace(/,\s*Health and Human Services$/i, "")
      .trim() || official
  );
}

function moneyMagnitude(value) {
  return Math.abs(decimalStringToNumber(value));
}

function negateMoney(value) {
  const normalized = String(value ?? "0.00");
  return normalized.startsWith("-") ? normalized.slice(1) : `-${normalized}`;
}

function percentChange(current, previous) {
  const currentValue = decimalStringToNumber(current);
  const previousValue = decimalStringToNumber(previous);
  if (
    !Number.isFinite(currentValue) ||
    !Number.isFinite(previousValue) ||
    currentValue < 0 ||
    previousValue <= 0
  ) {
    return null;
  }
  return ((currentValue - previousValue) / previousValue) * 100;
}

function signedPercentLabel(value, previousYear, ytd = false) {
  if (!Number.isFinite(value)) return null;
  const direction = value > 0 ? "Up" : value < 0 ? "Down" : "Unchanged";
  const amount = Math.abs(value).toFixed(1);
  if (direction === "Unchanged") {
    return `Unchanged from FY${previousYear}${ytd ? " at the same point" : ""}`;
  }
  return `${direction} ${amount}% from FY${previousYear}${ytd ? " at the same point" : ""}`;
}

function getSeries(payload, fiscalYear) {
  return (payload?.series ?? []).find(
    (series) => Number(series.fiscal_year) === Number(fiscalYear),
  );
}

function lastAvailablePoint(series) {
  return [...(series?.points ?? [])]
    .reverse()
    .find((point) => point.available && point.cumulative_amount !== null);
}

function equivalentComparisonPoint(series, periodNumber) {
  return (series?.points ?? []).find(
    (point) =>
      point.period_number === periodNumber &&
      point.available &&
      point.cumulative_amount !== null,
  );
}

export function CdcFundingHeader({
  fiscalYears,
  latestYear,
  onDownload,
  onYearChange,
  selectedYear,
  yearsLoading,
}) {
  return (
    <section
      className="cdc-redesign-header"
      aria-labelledby="cdc-funding-title"
    >
      <div className="cdc-redesign-header-copy">
        <div className="cdc-redesign-eyebrow">CDC Funding</div>
        <h1 id="cdc-funding-title">CDC Funding</h1>
        <p>
          Explore CDC-awarded obligations by fiscal year, federal funding
          account, emergency designation, and award type.
        </p>
      </div>
      <div className="cdc-redesign-header-actions">
        <label>
          <span>Fiscal year</span>
          <select
            aria-label="Fiscal year"
            value={selectedYear ?? ""}
            onChange={onYearChange}
            disabled={yearsLoading || fiscalYears.length === 0}
          >
            {selectedYear === null ? (
              <option value="">Select fiscal year</option>
            ) : null}
            {fiscalYears.map((item) => (
              <option value={item.fiscal_year} key={item.fiscal_year}>
                FY{item.fiscal_year}
                {item.is_latest ? " latest" : ""}
              </option>
            ))}
          </select>
          <small>
            {latestYear
              ? `Latest available: FY${latestYear}`
              : "Latest available: none"}
          </small>
        </label>
        <button
          type="button"
          className="cdc-funding-button"
          onClick={onDownload}
          disabled={!selectedYear}
        >
          Download CSV
        </button>
        <a
          className="cdc-methodology-link"
          href="#cdc-funding-methodology"
          onClick={(event) => {
            event.preventDefault();
            const methodology = document.getElementById(
              "cdc-funding-methodology",
            );
            methodology?.setAttribute("open", "");
            methodology?.scrollIntoView?.({ block: "start" });
          }}
        >
          Methodology
        </a>
      </div>
    </section>
  );
}

export function CdcFundingTabs({ activeTab, onChange }) {
  const tabRefs = useRef([]);
  const handleKeyDown = (event, index) => {
    let nextIndex = null;
    if (event.key === "ArrowRight")
      nextIndex = (index + 1) % TAB_DEFINITIONS.length;
    if (event.key === "ArrowLeft")
      nextIndex = (index - 1 + TAB_DEFINITIONS.length) % TAB_DEFINITIONS.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = TAB_DEFINITIONS.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const next = TAB_DEFINITIONS[nextIndex];
    onChange(next.id);
    tabRefs.current[nextIndex]?.focus();
  };
  return (
    <div className="cdc-tabs-wrap">
      <div
        className="cdc-tabs"
        role="tablist"
        aria-label="CDC funding sections"
      >
        {TAB_DEFINITIONS.map((tab, index) => (
          <button
            type="button"
            role="tab"
            id={`cdc-tab-${tab.id}`}
            aria-controls={`cdc-panel-${tab.id}`}
            aria-selected={activeTab === tab.id}
            tabIndex={activeTab === tab.id ? 0 : -1}
            key={tab.id}
            ref={(node) => {
              tabRefs.current[index] = node;
            }}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            {tab.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function ExecutiveSummary({
  accounts,
  classificationRows,
  fiscalYear,
  overview,
  trendMetadata,
}) {
  const selectedSeries = getSeries(trendMetadata, fiscalYear);
  const currentPoint = lastAvailablePoint(selectedSeries);
  const previousSeries = getSeries(trendMetadata, Number(fiscalYear) - 1);
  const comparisonPoint = equivalentComparisonPoint(
    previousSeries,
    currentPoint?.period_number,
  );
  const comparison =
    currentPoint && comparisonPoint
      ? percentChange(
          currentPoint.cumulative_amount,
          comparisonPoint.cumulative_amount,
        )
      : null;
  const comparisonCopy =
    comparison === null
      ? null
      : signedPercentLabel(
          comparison,
          Number(fiscalYear) - 1,
          !selectedSeries?.is_complete,
        );
  const throughLabel =
    selectedSeries && !selectedSeries.is_complete
      ? `FY${fiscalYear} through ${selectedSeries.available_through_month ?? selectedSeries.available_through_period}`
      : `FY${fiscalYear}`;
  const metrics = [
    {
      label: "Total obligations",
      value: overview?.total_obligations ?? "0.00",
      helper: comparisonCopy,
    },
    {
      label: "Federal funding accounts",
      value: accounts.length.toLocaleString("en-US"),
      isCount: true,
    },
    {
      label: "Grant obligations",
      value: overview?.totals?.grants ?? "0.00",
    },
    {
      label: "Contract obligations",
      value: overview?.totals?.contracts ?? "0.00",
    },
  ];
  return (
    <section
      className="cdc-overview-summary"
      aria-labelledby="cdc-summary-heading"
    >
      <div className="cdc-section-heading">
        <div>
          <h2 id="cdc-summary-heading">Executive summary</h2>
          <p>{throughLabel} · all federal accounts</p>
        </div>
      </div>
      <div className="cdc-summary-grid">
        {metrics.map((metric) => (
          <article className="cdc-summary-metric" key={metric.label}>
            <span>{metric.label}</span>
            <strong
              title={
                metric.isCount
                  ? metric.value
                  : formatCurrencyFromDecimalString(metric.value)
              }
            >
              {metric.isCount
                ? metric.value
                : formatCompactCurrencyFromDecimalString(metric.value)}
            </strong>
            {metric.helper ? <small>{metric.helper}</small> : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function EmergencyAdjustmentCallout({ classificationRows }) {
  const negativeEmergencyRows = classificationRows.filter(
    (row) =>
      row.emergencyStatus === "emergency" &&
      compareMoneyStrings(row.obligations, "0.00") < 0,
  );
  if (negativeEmergencyRows.length === 0) return null;
  const reduction = negateMoney(
    sumMoneyStrings(negativeEmergencyRows.map((row) => row.obligations)),
  );
  return (
    <aside className="cdc-emergency-callout" role="note">
      <div aria-hidden="true" className="cdc-emergency-callout-mark">
        i
      </div>
      <div>
        <h3>
          Emergency adjustments reduced net obligations by{" "}
          {formatCompactCurrencyFromDecimalString(reduction)}.
        </h3>
        <p>
          Negative amounts represent net downward adjustments recorded during
          the selected fiscal year. They may include deobligations, corrections,
          or other reductions reflected in the source data.
        </p>
        <details>
          <summary>Learn more</summary>
          <p>
            The source identifies the amounts as transaction obligations but
            does not provide enough information here to attribute a more
            specific cause. Values are retained exactly as reported.
          </p>
        </details>
      </div>
    </aside>
  );
}

function ClassificationMatrix({ rows, showPercentages }) {
  const byKey = new Map(rows.map((row) => [row.key, row]));
  return (
    <table className="cdc-classification-matrix">
      <caption>Emergency status by award type</caption>
      <thead>
        <tr>
          <th scope="col">Classification</th>
          <th scope="col">Grants</th>
          <th scope="col">Contracts</th>
        </tr>
      </thead>
      <tbody>
        {[
          ["Emergency", "emergency"],
          ["Nonemergency", "nonemergency"],
        ].map(([label, prefix]) => (
          <tr key={prefix}>
            <th scope="row">{label}</th>
            {["grant", "contract"].map((awardType) => {
              const row = byKey.get(`${prefix}_${awardType}`);
              return (
                <td key={awardType}>
                  <strong>
                    {formatCurrencyFromDecimalString(
                      row?.obligations ?? "0.00",
                    )}
                  </strong>
                  {showPercentages ? (
                    <small>
                      {formatPercentFromDecimalString(
                        row?.percent_of_total ?? "0.0000",
                      )}
                    </small>
                  ) : null}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FundingClassification({ rows, total }) {
  const maxMagnitude = Math.max(
    1,
    ...rows.map((row) => moneyMagnitude(row.obligations)),
  );
  const showPercentages =
    compareMoneyStrings(total, "0.00") > 0 &&
    rows.every((row) => compareMoneyStrings(row.obligations, "0.00") >= 0);
  return (
    <section
      className="cdc-composition-section"
      aria-labelledby="cdc-composition-heading"
    >
      <div className="cdc-section-heading">
        <div>
          <h2 id="cdc-composition-heading">Funding composition</h2>
          <p>Net obligations by emergency designation and award type.</p>
        </div>
      </div>
      <div
        className="cdc-diverging-chart"
        role="img"
        aria-label="Diverging funding classification chart centered on zero"
      >
        <div className="cdc-diverging-axis" aria-hidden="true">
          <span>Negative adjustments</span>
          <span>0</span>
          <span>Positive obligations</span>
        </div>
        {rows.map((row) => {
          const value = decimalStringToNumber(row.obligations);
          const width = `${(Math.abs(value) / maxMagnitude) * 50}%`;
          return (
            <div className="cdc-diverging-row" key={row.key}>
              <div className="cdc-diverging-label">
                <span
                  className={`cdc-classification-key is-${row.tone}`}
                  aria-hidden="true"
                />
                <span>{row.label}</span>
              </div>
              <div
                className="cdc-diverging-track"
                title={`${row.label}: ${formatCurrencyFromDecimalString(row.obligations)}`}
              >
                <span className="cdc-diverging-zero" aria-hidden="true" />
                {value !== 0 ? (
                  <span
                    className={`cdc-diverging-bar is-${row.tone} ${value < 0 ? "is-negative" : "is-positive"} ${row.awardType === "contract" ? "is-contract" : "is-grant"}`}
                    style={{ width }}
                    aria-hidden="true"
                  />
                ) : (
                  <span
                    className="cdc-diverging-zero-value"
                    aria-hidden="true"
                  />
                )}
              </div>
              <strong
                className={value < 0 ? "is-negative" : ""}
                aria-label={`${row.label}: ${formatCurrencyFromDecimalString(row.obligations)}`}
              >
                {formatCompactCurrencyFromDecimalString(row.obligations)}
              </strong>
            </div>
          );
        })}
      </div>
      {!showPercentages ? (
        <p className="cdc-helper-text">
          Percentages are omitted because zero or negative net values would make
          them misleading.
        </p>
      ) : null}
      <details className="cdc-classification-details">
        <summary>View classification details</summary>
        <ClassificationMatrix rows={rows} showPercentages={showPercentages} />
      </details>
    </section>
  );
}

function AccountRanking({
  accounts,
  excludeLargest,
  limit,
  mode,
  onExcludeLargest,
  onLimitChange,
  onModeChange,
  onViewAll,
  priorAccounts,
  showYearComparison,
}) {
  const sorted = useMemo(
    () =>
      [...accounts].sort((a, b) => {
        const result = compareMoneyStrings(
          b.total_obligations,
          a.total_obligations,
        );
        return (
          result || conciseAccountName(a).localeCompare(conciseAccountName(b))
        );
      }),
    [accounts],
  );
  const ranked = (excludeLargest ? sorted.slice(1) : sorted).slice(
    0,
    Number(limit),
  );
  const scaleMaximum = Math.max(
    1,
    ...ranked.map((account) => moneyMagnitude(account.total_obligations)),
  );
  const total = sumMoneyStrings(
    accounts.map((account) => account.total_obligations),
  );
  const shareIsValid =
    compareMoneyStrings(total, "0.00") > 0 &&
    accounts.every(
      (account) => compareMoneyStrings(account.total_obligations, "0.00") >= 0,
    );
  const priorBySymbol = new Map(
    (priorAccounts ?? []).map((account) => [accountSymbol(account), account]),
  );
  const activeMode = mode === "share" && !shareIsValid ? "dollars" : mode;
  return (
    <section
      className="cdc-ranking-section"
      aria-labelledby="cdc-ranking-heading"
    >
      <div className="cdc-section-heading cdc-section-heading-with-controls">
        <div>
          <h2 id="cdc-ranking-heading">Top federal funding accounts</h2>
          <p>
            Accounts with the largest net obligations for the selected fiscal
            year.
          </p>
        </div>
        <div className="cdc-ranking-controls">
          <label>
            <span>Account metric</span>
            <select
              aria-label="Account metric"
              value={activeMode}
              onChange={(event) => onModeChange(event.target.value)}
            >
              <option value="dollars">Dollars</option>
              <option value="share" disabled={!shareIsValid}>
                Share of total
              </option>
            </select>
          </label>
          <label>
            <span>Rows</span>
            <select
              value={limit}
              onChange={(event) => onLimitChange(event.target.value)}
            >
              <option value="10">Top 10</option>
              <option value="15">Top 15</option>
              <option value="25">Top 25</option>
            </select>
          </label>
          <label className="cdc-checkbox-control">
            <input
              type="checkbox"
              checked={excludeLargest}
              onChange={(event) => onExcludeLargest(event.target.checked)}
            />
            <span>Exclude largest account</span>
          </label>
        </div>
      </div>
      {!shareIsValid ? (
        <p className="cdc-helper-text">
          Share view is unavailable because negative or zero net values would
          make account shares misleading.
        </p>
      ) : null}
      <div className="cdc-ranking-table-wrap">
        <table className="cdc-ranking-table">
          <caption>Federal accounts ranked by net obligations</caption>
          <thead>
            <tr>
              <th scope="col">Rank</th>
              <th scope="col">Federal account</th>
              <th scope="col">Account symbol</th>
              <th scope="col">Obligations</th>
              {shareIsValid ? <th scope="col">Share of total</th> : null}
              {showYearComparison ? <th scope="col">Year-over-year</th> : null}
            </tr>
          </thead>
          <tbody>
            {ranked.map((account, index) => {
              const value = decimalStringToNumber(account.total_obligations);
              const share =
                shareIsValid && decimalStringToNumber(total) !== 0
                  ? (value / decimalStringToNumber(total)) * 100
                  : null;
              const previous = priorBySymbol.get(accountSymbol(account));
              const change = showYearComparison
                ? percentChange(
                    account.total_obligations,
                    previous?.total_obligations,
                  )
                : null;
              const barWidth =
                activeMode === "share" && share !== null
                  ? Math.max(1, share)
                  : Math.max(1, (Math.abs(value) / scaleMaximum) * 100);
              return (
                <tr key={accountSymbol(account)}>
                  <td>{excludeLargest ? index + 2 : index + 1}</td>
                  <th scope="row">
                    <span title={accountName(account)}>
                      {conciseAccountName(account)}
                    </span>
                    <span className="cdc-ranking-bar" aria-hidden="true">
                      <span
                        className={value < 0 ? "is-negative" : ""}
                        style={{ width: `${Math.min(100, barWidth)}%` }}
                      />
                    </span>
                  </th>
                  <td>{accountSymbol(account) || "Not available"}</td>
                  <td
                    className={
                      value < 0 ? "cdc-money is-negative" : "cdc-money"
                    }
                    title={formatCurrencyFromDecimalString(
                      account.total_obligations,
                    )}
                  >
                    {formatCompactCurrencyFromDecimalString(
                      account.total_obligations,
                    )}
                  </td>
                  {shareIsValid ? (
                    <td className="cdc-money">{share.toFixed(1)}%</td>
                  ) : null}
                  {showYearComparison ? (
                    <td>
                      {change === null
                        ? "Not comparable"
                        : `${change > 0 ? "+" : ""}${change.toFixed(1)}%`}
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <button type="button" className="cdc-text-action" onClick={onViewAll}>
        View all accounts
      </button>
    </section>
  );
}

export function FundingOverviewTab({
  accounts,
  classificationRows,
  excludeLargest,
  fiscalYear,
  onExcludeLargest,
  onLimitChange,
  onModeChange,
  onViewAll,
  overview,
  priorAccounts,
  rankingLimit,
  rankingMode,
  trendMetadata,
}) {
  const selectedSeries = getSeries(trendMetadata, fiscalYear);
  return (
    <div
      role="tabpanel"
      id="cdc-panel-overview"
      aria-labelledby="cdc-tab-overview"
      className="cdc-tab-panel"
    >
      <ExecutiveSummary
        accounts={accounts}
        classificationRows={classificationRows}
        fiscalYear={fiscalYear}
        overview={overview}
        trendMetadata={trendMetadata}
      />
      <EmergencyAdjustmentCallout classificationRows={classificationRows} />
      <FundingClassification
        rows={classificationRows}
        total={overview?.total_obligations ?? "0.00"}
      />
      <AccountRanking
        accounts={accounts}
        excludeLargest={excludeLargest}
        limit={rankingLimit}
        mode={rankingMode}
        onExcludeLargest={onExcludeLargest}
        onLimitChange={onLimitChange}
        onModeChange={onModeChange}
        onViewAll={onViewAll}
        priorAccounts={priorAccounts}
        showYearComparison={Boolean(selectedSeries?.is_complete)}
      />
    </div>
  );
}

function trendAccountLabel(account) {
  const name = accountName(account);
  const symbol = accountSymbol(account);
  return name ? `${name} — ${symbol}` : `${symbol} — Account name unavailable`;
}

function resolveComparisonYears(
  payload,
  selectedYear,
  comparisons,
  includeFy2021,
) {
  const available = new Set(
    (payload?.available_fiscal_years ?? []).map(Number),
  );
  const years = [];
  for (const comparison of comparisons ?? []) {
    const year =
      comparison === "prior"
        ? Number(selectedYear) - 1
        : Number(comparison);
    if (
      !Number.isInteger(year) ||
      year === Number(selectedYear) ||
      !available.has(year) ||
      (year === 2021 && !includeFy2021)
    ) {
      continue;
    }
    if (!years.includes(year)) years.push(year);
  }
  return years;
}

function trendNarrative(
  payload,
  selectedYear,
  comparisonYears,
  excludeDeobligations,
) {
  const primary = getSeries(payload, selectedYear);
  const primaryPoint = lastAvailablePoint(primary);
  if (!primaryPoint) return null;
  const through =
    primary.available_through_period ?? primaryPoint.period ?? "latest period";
  const amount = formatCompactCurrencyFromDecimalString(
    primaryPoint.cumulative_amount,
  );
  const comparisonYear = comparisonYears[0] ?? null;
  const comparison = getSeries(payload, comparisonYear);
  const comparisonPoint = equivalentComparisonPoint(
    comparison,
    primaryPoint.period_number,
  );
  const change = comparisonPoint
    ? percentChange(
        primaryPoint.cumulative_amount,
        comparisonPoint.cumulative_amount,
      )
    : null;
  const mode = excludeDeobligations ? " excluding deobligations" : "";
  if (change === null || !comparisonYear) {
    return `FY${selectedYear} reached ${amount} through ${through}${mode}.`;
  }
  const relation =
    change === 0
      ? `the same as FY${comparisonYear}`
      : `${Math.abs(change).toFixed(1)}% ${change > 0 ? "above" : "below"} FY${comparisonYear}`;
  const additional =
    comparisonYears.length > 1
      ? ` Also comparing ${comparisonYears
          .slice(1)
          .map((year) => `FY${year}`)
          .join(" and ")}.`
      : "";
  return `FY${selectedYear} reached ${amount} through ${through}${mode}, ${relation} at the same point.${additional}`;
}

function ComparisonYearMultiselect({
  availableYears,
  comparisons,
  includeFy2021,
  onChange,
  selectedYear,
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const comparisonYears = resolveComparisonYears(
    { available_fiscal_years: availableYears },
    selectedYear,
    comparisons,
    includeFy2021,
  );
  const priorYear = Number(selectedYear) - 1;
  const priorAvailable =
    availableYears.includes(priorYear) &&
    (priorYear !== 2021 || includeFy2021);
  const options = [...availableYears]
    .filter(
      (year) =>
        Number(year) !== Number(selectedYear) &&
        (Number(year) !== 2021 || includeFy2021),
    )
    .sort((a, b) => Number(b) - Number(a));
  const summary =
    comparisons.length === 1 && comparisons[0] === "prior" && priorAvailable
      ? "Prior fiscal year"
      : comparisonYears.length === 0
        ? "No comparisons"
        : comparisonYears.length <= 2
          ? comparisonYears.map((year) => `FY${year}`).join(", ")
          : `${comparisonYears.length} fiscal years selected`;

  useEffect(() => {
    if (!open) return undefined;
    const handleDocumentEvent = (event) => {
      if (event.type === "keydown" && event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
        return;
      }
      if (
        event.type === "mousedown" &&
        !rootRef.current?.contains(event.target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", handleDocumentEvent);
    document.addEventListener("mousedown", handleDocumentEvent);
    return () => {
      document.removeEventListener("keydown", handleDocumentEvent);
      document.removeEventListener("mousedown", handleDocumentEvent);
    };
  }, [open]);

  const toggleYear = (year, checked) => {
    const next = checked
      ? [...comparisonYears, Number(year)]
      : comparisonYears.filter((value) => value !== Number(year));
    onChange([...new Set(next)].map(String));
  };

  return (
    <div className="cdc-comparison-multiselect" ref={rootRef}>
      <span id="cdc-comparison-label">Comparison fiscal years</span>
      <button
        type="button"
        className="cdc-comparison-trigger"
        aria-labelledby="cdc-comparison-label cdc-comparison-summary"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        ref={triggerRef}
      >
        <span id="cdc-comparison-summary">{summary}</span>
        <span aria-hidden="true">⌄</span>
      </button>
      {open ? (
        <div
          className="cdc-comparison-popover"
          role="dialog"
          aria-label="Choose comparison fiscal years"
        >
          <div className="cdc-comparison-actions">
            <button
              type="button"
              onClick={() => onChange([])}
              disabled={comparisonYears.length === 0}
            >
              Clear all
            </button>
            {priorAvailable ? (
              <button type="button" onClick={() => onChange(["prior"])}>
                Select prior fiscal year
              </button>
            ) : null}
          </div>
          <div
            className="cdc-comparison-options"
            role="group"
            aria-label="Available comparison fiscal years"
          >
            {options.map((year) => (
              <label key={year}>
                <input
                  type="checkbox"
                  checked={comparisonYears.includes(Number(year))}
                  onChange={(event) => toggleYear(year, event.target.checked)}
                />
                <span>
                  FY{year}
                  {Number(year) === priorYear ? " · prior" : ""}
                </span>
              </label>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ActiveFilterChips({ accounts, state, onChange }) {
  const selectedAccount = accounts.find(
    (account) => accountSymbol(account) === state.account,
  );
  const chips = [
    state.emergency !== "all"
      ? {
          key: "emergency",
          label: state.emergency === "emergency" ? "Emergency" : "Nonemergency",
          clear: () => onChange({ ...state, emergency: "all" }),
        }
      : null,
    state.awardType !== "all"
      ? {
          key: "award",
          label: state.awardType === "grant" ? "Grants" : "Contracts",
          clear: () => onChange({ ...state, awardType: "all" }),
        }
      : null,
    state.view === "federal_account" && state.account
      ? {
          key: "account",
          label: conciseAccountName(selectedAccount),
          clear: () =>
            onChange({
              ...state,
              view: "total",
              account: "",
            }),
        }
      : null,
    state.excludeDeobligations
      ? {
          key: "deobligations",
          label: "Deobligations excluded",
          clear: () => onChange({ ...state, excludeDeobligations: false }),
        }
      : null,
  ].filter(Boolean);
  if (chips.length === 0) return null;
  return (
    <div className="cdc-filter-chips" aria-label="Active trend filters">
      {chips.map((chip) => (
        <button type="button" key={chip.key} onClick={chip.clear}>
          {chip.label}
          <span aria-hidden="true"> ×</span>
          <span className="cdc-sr-only">Remove filter</span>
        </button>
      ))}
    </div>
  );
}

function TrendChart({
  account,
  comparisonYears,
  display,
  includeFy2021,
  payload,
  selectedYear,
}) {
  const [highlightedYear, setHighlightedYear] = useState(null);
  const [tooltipState, setTooltipState] = useState(null);
  const [announcement, setAnnouncement] = useState("");
  const cycleRef = useRef({ periodNumber: null, candidateYears: [] });
  const visibleYears = [
    Number(selectedYear),
    ...comparisonYears,
    includeFy2021 || Number(selectedYear) === 2021 ? 2021 : null,
  ].filter((year, index, values) => year && values.indexOf(year) === index);
  const series = visibleYears
    .map((year) => getSeries(payload, year))
    .filter(Boolean);
  const orderedSeries = highlightedYear
    ? [
        ...series.filter(
          (item) => Number(item.fiscal_year) !== Number(highlightedYear),
        ),
        ...series.filter(
          (item) => Number(item.fiscal_year) === Number(highlightedYear),
        ),
      ]
    : series;
  const valueField =
    display === "activity" ? "period_amount" : "cumulative_amount";
  const primaryLatestPeriod =
    lastAvailablePoint(getSeries(payload, selectedYear))?.period_number ??
    (payload.period === "month" ? 12 : 4);
  const isPointAvailable = (item, point) =>
    point.available &&
    point[valueField] !== null &&
    (Number(item.fiscal_year) === Number(selectedYear) ||
      Number(point.period_number) <= Number(primaryLatestPeriod));
  const points = series.flatMap((item) =>
    (item.points ?? []).filter((point) => isPointAvailable(item, point)),
  );
  useEffect(() => {
    setHighlightedYear(null);
    setTooltipState(null);
    setAnnouncement("");
    cycleRef.current = { periodNumber: null, candidateYears: [] };
  }, [comparisonYears.join(","), display, payload, selectedYear]);
  if (points.length === 0 || !series.some((item) => item.has_activity)) {
    return (
      <p className="cdc-trend-empty">
        No obligation activity matches these trend filters.
      </p>
    );
  }
  const values = points.map((point) =>
    decimalStringToNumber(point[valueField]),
  );
  const rawMinimum = Math.min(0, ...values);
  const rawMaximum = Math.max(0, ...values);
  const padding = Math.max((rawMaximum - rawMinimum) * 0.1, 1);
  const minimum = rawMinimum < 0 ? rawMinimum - padding : 0;
  const maximum = rawMaximum + padding;
  const width = 980;
  const height = 400;
  const margins = { left: 94, right: 84, top: 32, bottom: 58 };
  const plotWidth = width - margins.left - margins.right;
  const plotHeight = height - margins.top - margins.bottom;
  const labels =
    payload.period === "month" ? FISCAL_MONTHS : ["Q1", "Q2", "Q3", "Q4"];
  const xFor = (periodNumber) =>
    margins.left +
    ((periodNumber - 1) / Math.max(1, labels.length - 1)) * plotWidth;
  const yFor = (value) =>
    margins.top +
    ((maximum - value) / Math.max(1, maximum - minimum)) * plotHeight;
  const zeroY = yFor(0);
  const ticks = Array.from(
    { length: 5 },
    (_, index) => minimum + ((maximum - minimum) * index) / 4,
  );
  const activityLabel =
    payload.period === "month"
      ? "Monthly obligation activity"
      : "Quarterly obligation activity";
  const pointLabel = (item, point) => {
    const periodName = point.source_period_label || point.period;
    return [
      `FY${item.fiscal_year} · ${periodName}.`,
      `${activityLabel}: ${formatCurrencyFromDecimalString(point.period_amount)}.`,
      `Cumulative obligations: ${formatCurrencyFromDecimalString(point.cumulative_amount)}.`,
      payload.view === "federal_account" && account
        ? `Federal account: ${trendAccountLabel(account)}.`
        : "",
      `Emergency classification: ${
        {
          all: "All",
          emergency: "Emergency",
          nonemergency: "Nonemergency",
        }[payload.filters?.emergency_status] ?? "All"
      }.`,
      `Award type: ${
        { all: "All", grant: "Grants", contract: "Contracts" }[
          payload.filters?.award_type
        ] ?? "All"
      }.`,
      item.is_complete ? "" : "Partial fiscal year.",
    ]
      .filter(Boolean)
      .join(" ");
  };
  const barWidth = Math.max(10, Math.min(28, plotWidth / labels.length / 2));
  const styleFor = (item) => {
    const year = Number(item.fiscal_year);
    if (year === Number(selectedYear)) return SERIES_STYLES.primary;
    if (comparisonYears.includes(year)) return comparisonStyle(year);
    return SERIES_STYLES.context;
  };
  const roleFor = (item) => {
    const year = Number(item.fiscal_year);
    if (year === Number(selectedYear)) return "Primary";
    if (comparisonYears.includes(year)) return "Comparison";
    return "Context";
  };
  const pointAt = (item, periodNumber) =>
    (item?.points ?? []).find(
      (point) =>
        Number(point.period_number) === Number(periodNumber) &&
        isPointAvailable(item, point),
    );
  const showTooltip = (
    candidateYears,
    periodNumber,
    priorityYear = highlightedYear,
  ) => {
    const orderedYears =
      priorityYear && candidateYears.includes(Number(priorityYear))
        ? [
            Number(priorityYear),
            ...candidateYears.filter(
              (year) => Number(year) !== Number(priorityYear),
            ),
          ]
        : candidateYears;
    setTooltipState({
      periodNumber,
      candidates: orderedYears
        .map((year) => {
          const item = series.find(
            (candidate) => Number(candidate.fiscal_year) === Number(year),
          );
          const point = pointAt(item, periodNumber);
          return item && point ? { item, point } : null;
        })
        .filter(Boolean),
    });
  };
  const clearHighlight = () => {
    setHighlightedYear(null);
    setTooltipState(null);
    setAnnouncement("Chart highlight cleared.");
    cycleRef.current = { periodNumber: null, candidateYears: [] };
  };
  const selectCandidates = (candidateYears, periodNumber) => {
    if (candidateYears.length === 0) {
      clearHighlight();
      return;
    }
    const previous = cycleRef.current;
    const sameCandidates =
      previous.periodNumber === periodNumber &&
      previous.candidateYears.join(",") === candidateYears.join(",");
    const currentIndex = candidateYears.indexOf(Number(highlightedYear));
    const nextIndex =
      sameCandidates && currentIndex >= 0
        ? (currentIndex + 1) % candidateYears.length
        : 0;
    const nextYear = candidateYears[nextIndex];
    setHighlightedYear(nextYear);
    cycleRef.current = { periodNumber, candidateYears };
    showTooltip(candidateYears, periodNumber, nextYear);
    const periodLabel =
      pointAt(
        series.find(
          (item) => Number(item.fiscal_year) === Number(nextYear),
        ),
        periodNumber,
      )?.source_period_label ?? labels[periodNumber - 1];
    const nextCandidate =
      candidateYears.length > 1
        ? candidateYears[(nextIndex + 1) % candidateYears.length]
        : null;
    setAnnouncement(
      `FY${nextYear} highlighted.${
        candidateYears.length > 1
          ? ` ${candidateYears.length} overlapping series at ${periodLabel}. Select again to view FY${nextCandidate}.`
          : ""
      }`,
    );
  };
  const selectFromPoint = (item, point) => {
    const targetY = yFor(decimalStringToNumber(point[valueField]));
    const candidates = series
      .filter((candidate) => {
        const candidatePoint = pointAt(candidate, point.period_number);
        return (
          candidatePoint &&
          Math.abs(
            yFor(decimalStringToNumber(candidatePoint[valueField])) - targetY,
          ) <= 18
        );
      })
      .map((candidate) => Number(candidate.fiscal_year));
    selectCandidates(candidates, point.period_number);
  };
  const handleChartPointer = (event, shouldSelect) => {
    const bounds = (
      event.currentTarget.ownerSVGElement ?? event.currentTarget
    ).getBoundingClientRect();
    const pointerX = ((event.clientX - bounds.left) / bounds.width) * width;
    const pointerY = ((event.clientY - bounds.top) / bounds.height) * height;
    if (
      pointerX < margins.left ||
      pointerX > width - margins.right ||
      pointerY < margins.top ||
      pointerY > height - margins.bottom
    ) {
      if (shouldSelect) clearHighlight();
      return;
    }
    const periodPosition =
      1 + ((pointerX - margins.left) / plotWidth) * (labels.length - 1);
    const periodNumber = Math.max(
      1,
      Math.min(labels.length, Math.round(periodPosition)),
    );
    const candidates = series
      .filter((item) => {
        const available = (item.points ?? []).filter((point) =>
          isPointAvailable(item, point),
        );
        if (
          display === "activity" &&
          Number(item.fiscal_year) === Number(selectedYear)
        ) {
          const point = pointAt(item, periodNumber);
          if (!point || Math.abs(periodPosition - periodNumber) > 0.45) {
            return false;
          }
          const pointY = yFor(decimalStringToNumber(point.period_amount));
          return (
            pointerY >= Math.min(pointY, zeroY) - 12 &&
            pointerY <= Math.max(pointY, zeroY) + 12
          );
        }
        const before = [...available]
          .reverse()
          .find((point) => point.period_number <= periodPosition);
        const after = available.find(
          (point) => point.period_number >= periodPosition,
        );
        if (!before || !after) return false;
        if (
          after.period_number !== before.period_number &&
          after.period_number !== before.period_number + 1
        ) {
          return false;
        }
        const fraction =
          after.period_number === before.period_number
            ? 0
            : (periodPosition - before.period_number) /
              (after.period_number - before.period_number);
        const beforeValue = decimalStringToNumber(before[valueField]);
        const afterValue = decimalStringToNumber(after[valueField]);
        const renderedY = yFor(
          beforeValue + (afterValue - beforeValue) * fraction,
        );
        return Math.abs(renderedY - pointerY) <= 20;
      })
      .map((item) => Number(item.fiscal_year));
    if (shouldSelect) selectCandidates(candidates, periodNumber);
    else if (candidates.length) showTooltip(candidates, periodNumber);
    else setTooltipState(null);
  };
  const directLabelYears = [
    Number(selectedYear),
    comparisonYears[0] ?? null,
  ].filter(Boolean);
  const directLabelY = (item, point) => {
    const currentY = yFor(decimalStringToNumber(point[valueField]));
    const otherYear = directLabelYears.find(
      (year) => year !== Number(item.fiscal_year),
    );
    const otherPoint = otherYear
      ? [...(getSeries(payload, otherYear)?.points ?? [])]
          .reverse()
          .find((candidate) =>
            isPointAvailable(getSeries(payload, otherYear), candidate),
          )
      : null;
    if (!otherPoint) return currentY - 10;
    const otherY = yFor(decimalStringToNumber(otherPoint[valueField]));
    if (Math.abs(currentY - otherY) < 34) {
      return currentY < otherY ? currentY - 12 : currentY + 18;
    }
    return currentY - 10;
  };

  return (
    <>
      <div
        className="cdc-focused-chart-wrap"
        role="region"
        aria-label="Scrollable obligation trend chart"
        tabIndex="0"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            clearHighlight();
          }
        }}
      >
        <svg
          className="cdc-focused-chart"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-labelledby="cdc-focused-chart-title cdc-focused-chart-desc"
          data-display={display}
        >
          <title id="cdc-focused-chart-title">
            {display === "activity"
              ? "CDC obligation activity by reporting period"
              : "Cumulative CDC obligations by fiscal year"}
          </title>
          <desc id="cdc-focused-chart-desc">
            FY{selectedYear} is the primary series
            {comparisonYears.length
              ? ` with comparison series for ${comparisonYears
                  .map((year) => `FY${year}`)
                  .join(", ")}`
              : ""}
            . Select a line repeatedly to cycle through overlapping series.
            Exact values are available from every focusable point and the
            accessible data table.
          </desc>
          <line
            x1={margins.left}
            x2={width - margins.right}
            y1={zeroY}
            y2={zeroY}
            className="cdc-trend-zero"
          />
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={margins.left}
                x2={width - margins.right}
                y1={yFor(tick)}
                y2={yFor(tick)}
                className={
                  Math.abs(tick) < 0.001 ? "cdc-trend-zero" : "cdc-trend-grid"
                }
              />
              <text
                x={margins.left - 12}
                y={yFor(tick) + 4}
                textAnchor="end"
                className="cdc-trend-axis-label"
              >
                {formatCompactCurrencyFromDecimalString(
                  String(Math.round(tick * 100) / 100),
                )}
              </text>
            </g>
          ))}
          {labels.map((label, index) => (
            <text
              key={label}
              x={xFor(index + 1)}
              y={height - 20}
              textAnchor="middle"
              className="cdc-trend-axis-label"
            >
              {label}
            </text>
          ))}
          {orderedSeries.map((item) => {
            const isPrimary = Number(item.fiscal_year) === Number(selectedYear);
            const isHighlighted =
              Number(item.fiscal_year) === Number(highlightedYear);
            const style = styleFor(item);
            const available = (item.points ?? []).filter(
              (point) => isPointAvailable(item, point),
            );
            const seriesClass = [
              "cdc-chart-series",
              isHighlighted ? "is-highlighted" : "",
              highlightedYear && !isHighlighted ? "is-dimmed" : "",
            ]
              .filter(Boolean)
              .join(" ");
            if (display === "activity" && isPrimary) {
              return (
                <g
                  key={item.fiscal_year}
                  className={seriesClass}
                  data-testid={`trend-series-${item.fiscal_year}`}
                  data-highlighted={isHighlighted ? "true" : "false"}
                >
                  {available.map((point) => {
                    const value = decimalStringToNumber(point.period_amount);
                    const y = yFor(value);
                    const label = pointLabel(item, point);
                    return (
                      <rect
                        key={point.period}
                        x={xFor(point.period_number) - barWidth / 2}
                        y={Math.min(y, zeroY)}
                        width={barWidth}
                        height={Math.max(2, Math.abs(zeroY - y))}
                        className={
                          value < 0
                            ? "cdc-activity-bar is-negative"
                            : "cdc-activity-bar"
                        }
                        role="button"
                        tabIndex="0"
                        aria-label={`${label} Activate to highlight FY${item.fiscal_year}.`}
                        onFocus={() =>
                          showTooltip(
                            series
                              .filter((candidate) =>
                                pointAt(candidate, point.period_number),
                              )
                              .map((candidate) =>
                                Number(candidate.fiscal_year),
                              ),
                            point.period_number,
                          )
                        }
                        onClick={() => selectFromPoint(item, point)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            selectFromPoint(item, point);
                          }
                        }}
                      />
                    );
                  })}
                </g>
              );
            }
            const segments = available.reduce((result, point) => {
              const current = result[result.length - 1];
              const previous = current?.[current.length - 1];
              if (
                !previous ||
                point.period_number === previous.period_number + 1
              ) {
                if (current) current.push(point);
                else result.push([point]);
              } else result.push([point]);
              return result;
            }, []);
            const last = available[available.length - 1];
            return (
              <g
                key={item.fiscal_year}
                className={seriesClass}
                data-testid={`trend-series-${item.fiscal_year}`}
                data-highlighted={isHighlighted ? "true" : "false"}
              >
                {segments.map((segment, index) => (
                  <polyline
                    key={`${item.fiscal_year}-${index}`}
                    points={segment
                      .map(
                        (point) =>
                          `${xFor(point.period_number)},${yFor(
                            decimalStringToNumber(point[valueField]),
                          )}`,
                      )
                      .join(" ")}
                    fill="none"
                    stroke={style.color}
                    strokeWidth={isPrimary ? 5 : 3}
                    strokeDasharray={
                      !item.is_complete && isPrimary ? "12 4" : style.dash
                    }
                    className="cdc-trend-line"
                    aria-hidden="true"
                  />
                ))}
                {available.map((point) => {
                  const label = pointLabel(item, point);
                  return (
                    <circle
                      key={point.period}
                      cx={xFor(point.period_number)}
                      cy={yFor(decimalStringToNumber(point[valueField]))}
                      r="4"
                      fill="#ffffff"
                      stroke={style.color}
                      strokeWidth="3"
                      className="cdc-trend-focus-point"
                      role="button"
                      tabIndex="0"
                      aria-label={`${label} Activate to highlight FY${item.fiscal_year}.`}
                      onFocus={() =>
                        showTooltip(
                          series
                            .filter((candidate) =>
                              pointAt(candidate, point.period_number),
                            )
                            .map((candidate) =>
                              Number(candidate.fiscal_year),
                            ),
                          point.period_number,
                        )
                      }
                      onClick={() => selectFromPoint(item, point)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          selectFromPoint(item, point);
                        }
                      }}
                    />
                  );
                })}
                {last &&
                directLabelYears.includes(Number(item.fiscal_year)) ? (
                  <text
                    x={xFor(last.period_number) + 10}
                    y={directLabelY(item, last)}
                    fill={style.color}
                    className={`cdc-trend-year-label${
                      isHighlighted ? " is-highlighted" : ""
                    }`}
                  >
                    FY{item.fiscal_year}
                  </text>
                ) : null}
              </g>
            );
          })}
          <rect
            x={margins.left}
            y={margins.top}
            width={plotWidth}
            height={plotHeight}
            className="cdc-chart-hit-target"
            onPointerMove={(event) => handleChartPointer(event, false)}
            onPointerLeave={() => setTooltipState(null)}
            onClick={(event) => handleChartPointer(event, true)}
          />
        </svg>
      </div>
      <div className="cdc-focused-legend" aria-label="Trend series legend">
        {series.map((item) => {
          const role = roleFor(item);
          const isHighlighted =
            Number(item.fiscal_year) === Number(highlightedYear);
          return (
            <button
              type="button"
              key={item.fiscal_year}
              className={
                highlightedYear && !isHighlighted ? "is-dimmed" : undefined
              }
              onClick={() => {
                if (isHighlighted) clearHighlight();
                else {
                  setHighlightedYear(Number(item.fiscal_year));
                  setAnnouncement(`FY${item.fiscal_year} highlighted.`);
                  cycleRef.current = {
                    periodNumber: null,
                    candidateYears: [],
                  };
                }
              }}
              aria-pressed={isHighlighted}
            >
              <span
                className={`is-${role.toLowerCase()}`}
                style={{ "--series-color": styleFor(item).color }}
                aria-hidden="true"
              />
              FY{item.fiscal_year} · {role}
              {!item.is_complete
                ? ` · through ${item.available_through_period}`
                : ""}
            </button>
          );
        })}
      </div>
      <div className="cdc-trend-tooltip" role="status" aria-live="polite">
        {tooltipState?.candidates?.length ? (
          <>
            <strong>
              {tooltipState.candidates[0].point.source_period_label ||
                tooltipState.candidates[0].point.period}
            </strong>
            <ul>
              {tooltipState.candidates.map(({ item, point }) => (
                <li
                  key={item.fiscal_year}
                  className={
                    Number(item.fiscal_year) === Number(highlightedYear)
                      ? "is-highlighted"
                      : undefined
                  }
                >
                  <strong>FY{item.fiscal_year}</strong>:{" "}
                  {display === "activity"
                    ? formatCurrencyFromDecimalString(point.period_amount)
                    : formatCurrencyFromDecimalString(point.cumulative_amount)}
                </li>
              ))}
            </ul>
          </>
        ) : (
          "Focus, hover, or select a data point to view exact values."
        )}
      </div>
      <p className="cdc-sr-only" aria-live="polite">
        {announcement}
      </p>
      <details className="cdc-trend-data">
        <summary>View accessible chart data</summary>
        <div className="cdc-funding-table-wrap">
          <table className="cdc-funding-table">
            <caption>
              {display === "activity"
                ? "Period obligation activity"
                : "Cumulative obligation values"}{" "}
              for the primary and comparison fiscal years.
            </caption>
            <thead>
              <tr>
                <th scope="col">Fiscal year</th>
                <th scope="col">
                  {payload.period === "month"
                    ? "Fiscal month"
                    : "Fiscal quarter"}
                </th>
                <th scope="col">Available</th>
                <th scope="col">{activityLabel}</th>
                <th scope="col">Cumulative fiscal-year-to-date obligations</th>
              </tr>
            </thead>
            <tbody>
              {series.flatMap((item) =>
                (item.points ?? []).map((point) => (
                  <tr key={`${item.fiscal_year}-${point.period}`}>
                    <th scope="row">FY{item.fiscal_year}</th>
                    <td>{point.source_period_label || point.period}</td>
                    <td>
                      {isPointAvailable(item, point)
                        ? "Available"
                        : "Not available"}
                    </td>
                    <td>
                      {isPointAvailable(item, point)
                        ? formatCurrencyFromDecimalString(point.period_amount)
                        : "Not available"}
                    </td>
                    <td>
                      {isPointAvailable(item, point)
                        ? formatCurrencyFromDecimalString(
                            point.cumulative_amount,
                          )
                        : "Not available"}
                    </td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

export function FocusedObligationTrends({
  onSelectYear,
  onTrendStateChange,
  selectedYear,
  trendState,
}) {
  const [accounts, setAccounts] = useState([]);
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [accountsError, setAccountsError] = useState("");
  const [payload, setPayload] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchCdcFundingTrendAccounts({
      apiBase: API_BASE,
      signal: controller.signal,
      scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    })
      .then((response) => {
        if (controller.signal.aborted) return;
        if (response?.scope !== CDC_FUNDING_SCOPE_ALL_ACCOUNTS) {
          throw new Error(
            "The trend-account response did not use all-account scope.",
          );
        }
        setAccounts(Array.isArray(response?.accounts) ? response.accounts : []);
        setAccountsError("");
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) {
          setAccountsError(
            requestError?.message ?? "Failed to load federal account options.",
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setAccountsLoading(false);
      });
    return () => controller.abort();
  }, []);

  const accountIsValid =
    !trendState.account ||
    accounts.some((account) => accountSymbol(account) === trendState.account);
  const needsAccount =
    trendState.view === "federal_account" && !trendState.account;
  const accountPending =
    trendState.view === "federal_account" && accountsLoading;
  const invalidAccount =
    trendState.view === "federal_account" &&
    trendState.account &&
    !accountsLoading &&
    !accountIsValid;

  useEffect(() => {
    if (
      needsAccount ||
      accountPending ||
      invalidAccount ||
      (trendState.view === "federal_account" && accountsError)
    ) {
      setPayload(null);
      setLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setPayload(null);
    fetchCdcFundingObligationTrends({
      apiBase: API_BASE,
      signal: controller.signal,
      scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
      period: trendState.period,
      view: trendState.view,
      federalAccountSymbol:
        trendState.view === "federal_account" ? trendState.account : undefined,
      emergencyStatus: trendState.emergency,
      awardType: trendState.awardType,
      excludeDeobligations: trendState.excludeDeobligations,
    })
      .then((response) => {
        if (controller.signal.aborted) return;
        if (response?.scope !== CDC_FUNDING_SCOPE_ALL_ACCOUNTS) {
          throw new Error(
            "The obligation-trend response did not use all-account scope.",
          );
        }
        if (
          (response?.series ?? []).some(
            (series) =>
              compareMoneyStrings(
                series?.reconciliation?.difference ?? "0.00",
                "0.00",
              ) !== 0,
          )
        ) {
          throw new Error("Obligation trend data did not reconcile.");
        }
        setPayload(response);
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) {
          setError(
            requestError?.message ?? "Failed to load obligation trends.",
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [
    accountPending,
    accountsError,
    invalidAccount,
    needsAccount,
    reloadKey,
    trendState.account,
    trendState.awardType,
    trendState.emergency,
    trendState.excludeDeobligations,
    trendState.period,
    trendState.view,
  ]);

  const comparisonYears = resolveComparisonYears(
    payload,
    selectedYear,
    trendState.comparisons,
    trendState.includeFy2021,
  );
  useEffect(() => {
    if (!payload) return;
    const available = new Set(
      (payload.available_fiscal_years ?? []).map(Number),
    );
    const seenYears = new Set();
    const normalized = [];
    for (const comparison of trendState.comparisons) {
      const year =
        comparison === "prior"
          ? Number(selectedYear) - 1
          : Number(comparison);
      if (
        !available.has(year) ||
        year === Number(selectedYear) ||
        (year === 2021 && !trendState.includeFy2021) ||
        seenYears.has(year)
      ) {
        continue;
      }
      seenYears.add(year);
      normalized.push(comparison === "prior" ? "prior" : String(year));
    }
    if (normalized.join(",") !== trendState.comparisons.join(",")) {
      onTrendStateChange(
        { ...trendState, comparisons: normalized },
        "replace",
      );
    }
  }, [
    onTrendStateChange,
    payload,
    selectedYear,
    trendState,
  ]);
  const activeFilterCount =
    (trendState.emergency !== "all" ? 1 : 0) +
    (trendState.awardType !== "all" ? 1 : 0) +
    (trendState.view === "federal_account" && trendState.account ? 1 : 0) +
    (trendState.excludeDeobligations ? 1 : 0);
  const selectedAccount = accounts.find(
    (account) => accountSymbol(account) === trendState.account,
  );
  const setField = (field, value) =>
    onTrendStateChange({ ...trendState, [field]: value });
  const clearFilters = () =>
    onTrendStateChange({
      ...trendState,
      view: "total",
      account: "",
      emergency: "all",
      awardType: "all",
      excludeDeobligations: false,
    });

  return (
    <div
      role="tabpanel"
      id="cdc-panel-trends"
      aria-labelledby="cdc-tab-trends"
      className="cdc-tab-panel"
    >
      <section
        className="cdc-trend-workspace"
        aria-labelledby="cdc-trends-heading"
      >
        <div className="cdc-section-heading">
          <div>
            <h2 id="cdc-trends-heading">Obligation trends</h2>
            <p>
              Compare monthly or quarterly CDC-awarded obligation activity and
              fiscal-year-to-date totals.
            </p>
          </div>
        </div>
        {payload ? (
          <p className="cdc-trend-narrative">
            {trendNarrative(
              payload,
              selectedYear,
              comparisonYears,
              trendState.excludeDeobligations,
            )}
          </p>
        ) : null}
        <div className="cdc-trend-primary-controls">
          <label>
            <span>Reporting period</span>
            <select
              aria-label="Reporting period"
              value={trendState.period}
              onChange={(event) => setField("period", event.target.value)}
            >
              <option value="month">Monthly</option>
              <option value="quarter">Quarterly</option>
            </select>
          </label>
          <label>
            <span>Trend measure</span>
            <select
              aria-label="Trend measure"
              value={trendState.display}
              onChange={(event) => setField("display", event.target.value)}
            >
              <option value="activity">Period activity</option>
              <option value="cumulative">Cumulative obligations</option>
            </select>
          </label>
          <ComparisonYearMultiselect
            availableYears={(payload?.available_fiscal_years ?? []).map(Number)}
            comparisons={trendState.comparisons}
            includeFy2021={trendState.includeFy2021}
            onChange={(comparisons) => setField("comparisons", comparisons)}
            selectedYear={selectedYear}
          />
          <label className="cdc-checkbox-control cdc-trend-fy-control">
            <input
              type="checkbox"
              checked={
                trendState.includeFy2021 || Number(selectedYear) === 2021
              }
              disabled={Number(selectedYear) === 2021}
              onChange={(event) => {
                const checked = event.target.checked;
                onTrendStateChange({
                  ...trendState,
                  includeFy2021: checked,
                  comparisons: checked
                    ? trendState.comparisons
                    : trendState.comparisons.filter(
                        (comparison) =>
                          Number(
                            comparison === "prior"
                              ? Number(selectedYear) - 1
                              : comparison,
                          ) !== 2021,
                      ),
                });
              }}
              aria-describedby="cdc-focused-fy2021-help"
            />
            <span>Include FY2021</span>
          </label>
          <label className="cdc-checkbox-control cdc-trend-deobligation-control">
            <input
              type="checkbox"
              checked={trendState.excludeDeobligations}
              onChange={(event) =>
                setField("excludeDeobligations", event.target.checked)
              }
              aria-describedby="cdc-focused-deobligations-help"
            />
            <span>Exclude deobligations</span>
          </label>
        </div>
        <p id="cdc-focused-fy2021-help" className="cdc-helper-text">
          FY2021 is hidden by default because its unusually large funding total
          can compress the scale for later fiscal years.
        </p>
        <p id="cdc-focused-deobligations-help" className="cdc-helper-text">
          Shows positive obligation activity without downward adjustments or
          deobligations.
        </p>
        <details className="cdc-filter-panel">
          <summary>
            Filters
            {activeFilterCount ? (
              <span className="cdc-filter-count">{activeFilterCount}</span>
            ) : null}
          </summary>
          <div className="cdc-filter-panel-grid">
            <label>
              <span>Emergency classification</span>
              <select
                value={trendState.emergency}
                onChange={(event) => setField("emergency", event.target.value)}
              >
                <option value="all">All classifications</option>
                <option value="emergency">Emergency</option>
                <option value="nonemergency">Nonemergency</option>
              </select>
            </label>
            <label>
              <span>Award type</span>
              <select
                value={trendState.awardType}
                onChange={(event) => setField("awardType", event.target.value)}
              >
                <option value="all">All award types</option>
                <option value="grant">Grants</option>
                <option value="contract">Contracts</option>
              </select>
            </label>
            <label>
              <span>Federal account</span>
              <select
                aria-label="Federal account"
                value={accountIsValid ? trendState.account : ""}
                disabled={accountsLoading}
                onChange={(event) => {
                  const account = event.target.value;
                  onTrendStateChange({
                    ...trendState,
                    view: account ? "federal_account" : "total",
                    account,
                  });
                }}
              >
                <option value="">All federal accounts</option>
                {accounts.map((account) => (
                  <option
                    value={accountSymbol(account)}
                    key={accountSymbol(account)}
                  >
                    {trendAccountLabel(account)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button
            type="button"
            className="cdc-text-action"
            onClick={clearFilters}
            disabled={activeFilterCount === 0}
          >
            Clear filters
          </button>
        </details>
        <ActiveFilterChips
          accounts={accounts}
          state={trendState}
          onChange={onTrendStateChange}
        />
        {accountsError ? (
          <p className="cdc-funding-note">{accountsError}</p>
        ) : null}
        {needsAccount ? (
          <p className="cdc-trend-empty">
            Select a federal account to compare obligation trends across fiscal
            years.
          </p>
        ) : null}
        {invalidAccount ? (
          <p className="cdc-funding-note">
            The federal account in this URL is not available. Choose a valid
            account to continue.
          </p>
        ) : null}
        {loading ? (
          <div className="cdc-trend-loading" role="status">
            Loading obligation trends…
          </div>
        ) : null}
        {error ? (
          <div className="cdc-funding-status" role="alert">
            <h3>Obligation trends could not be loaded</h3>
            <p>{error}</p>
            <button
              type="button"
              className="cdc-funding-button"
              onClick={() => setReloadKey((value) => value + 1)}
            >
              Retry
            </button>
          </div>
        ) : null}
        {!loading && payload ? (
          <TrendChart
            account={selectedAccount}
            comparisonYears={comparisonYears}
            display={trendState.display}
            includeFy2021={trendState.includeFy2021}
            payload={payload}
            selectedYear={selectedYear}
          />
        ) : null}
      </section>
    </div>
  );
}

function AccountTrendPreview({ account, fiscalYear }) {
  const [state, setState] = useState({
    loading: false,
    error: "",
    payload: null,
  });

  useEffect(() => {
    if (!account) {
      setState({ loading: false, error: "", payload: null });
      return undefined;
    }
    const controller = new AbortController();
    setState({ loading: true, error: "", payload: null });
    fetchCdcFundingObligationTrends({
      apiBase: API_BASE,
      signal: controller.signal,
      scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
      period: "month",
      view: "federal_account",
      federalAccountSymbol: accountSymbol(account),
      emergencyStatus: "all",
      awardType: "all",
    })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setState({ loading: false, error: "", payload });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({
          loading: false,
          error: error?.message ?? "Account trend unavailable.",
          payload: null,
        });
      });
    return () => controller.abort();
  }, [account]);

  if (!account) return null;
  if (state.loading) {
    return (
      <section
        className="cdc-account-trend-preview"
        aria-labelledby="drawer-trend-heading"
      >
        <h3 id="drawer-trend-heading">Account obligation trend</h3>
        <p role="status">Loading monthly account trend…</p>
      </section>
    );
  }
  if (state.error) {
    return (
      <section
        className="cdc-account-trend-preview"
        aria-labelledby="drawer-trend-heading"
      >
        <h3 id="drawer-trend-heading">Account obligation trend</h3>
        <p>{state.error}</p>
      </section>
    );
  }

  const series = getSeries(state.payload, fiscalYear);
  const points = (series?.points ?? []).filter(
    (point) => point.available && point.cumulative_amount !== null,
  );
  if (!series || points.length === 0) return null;

  const width = 420;
  const height = 150;
  const margins = { left: 12, right: 12, top: 16, bottom: 28 };
  const plotWidth = width - margins.left - margins.right;
  const plotHeight = height - margins.top - margins.bottom;
  const values = points.map((point) =>
    decimalStringToNumber(point.cumulative_amount),
  );
  const rawMinimum = Math.min(0, ...values);
  const rawMaximum = Math.max(0, ...values);
  const padding = Math.max((rawMaximum - rawMinimum) * 0.08, 1);
  const minimum = rawMinimum < 0 ? rawMinimum - padding : 0;
  const maximum = rawMaximum + padding;
  const xFor = (periodNumber) =>
    margins.left + ((periodNumber - 1) / 11) * plotWidth;
  const yFor = (value) =>
    margins.top +
    ((maximum - value) / Math.max(1, maximum - minimum)) * plotHeight;
  const segments = points.reduce((result, point) => {
    const current = result[result.length - 1];
    const previous = current?.[current.length - 1];
    if (!previous || point.period_number === previous.period_number + 1) {
      if (current) current.push(point);
      else result.push([point]);
    } else {
      result.push([point]);
    }
    return result;
  }, []);
  const latest = points[points.length - 1];

  return (
    <section
      className="cdc-account-trend-preview"
      aria-labelledby="drawer-trend-heading"
    >
      <div>
        <h3 id="drawer-trend-heading">Account obligation trend</h3>
        <p>
          Monthly cumulative obligations through{" "}
          {series.available_through_period}.
        </p>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`FY${fiscalYear} monthly cumulative obligations for ${conciseAccountName(account)}`}
      >
        <line
          x1={margins.left}
          x2={width - margins.right}
          y1={yFor(0)}
          y2={yFor(0)}
          className="cdc-account-trend-zero"
        />
        {segments.map((segment, index) => (
          <polyline
            key={index}
            points={segment
              .map(
                (point) =>
                  `${xFor(point.period_number)},${yFor(
                    decimalStringToNumber(point.cumulative_amount),
                  )}`,
              )
              .join(" ")}
            className="cdc-account-trend-line"
          />
        ))}
        {points.map((point) => (
          <circle
            key={point.period}
            cx={xFor(point.period_number)}
            cy={yFor(decimalStringToNumber(point.cumulative_amount))}
            r="3"
          >
            <title>
              {point.source_period_label || point.period}:{" "}
              {formatCurrencyFromDecimalString(point.cumulative_amount)}
            </title>
          </circle>
        ))}
        {[
          ["Oct", 1],
          ["Jan", 4],
          ["Apr", 7],
          ["Jul", 10],
          ["Sep", 12],
        ].map(([label, periodNumber]) => (
          <text
            key={label}
            x={xFor(periodNumber)}
            y={height - 7}
            textAnchor={
              periodNumber === 1
                ? "start"
                : periodNumber === 12
                  ? "end"
                  : "middle"
            }
          >
            {label}
          </text>
        ))}
      </svg>
      <strong title={formatCurrencyFromDecimalString(latest.cumulative_amount)}>
        {formatCompactCurrencyFromDecimalString(latest.cumulative_amount)}
      </strong>
      <details>
        <summary>View exact monthly account data</summary>
        <div className="cdc-account-trend-table-wrap">
          <table>
            <caption>
              FY{fiscalYear} monthly account activity and cumulative obligations
            </caption>
            <thead>
              <tr>
                <th scope="col">Fiscal month</th>
                <th scope="col">Activity</th>
                <th scope="col">Cumulative</th>
              </tr>
            </thead>
            <tbody>
              {(series.points ?? []).map((point) => (
                <tr key={point.period}>
                  <th scope="row">
                    {point.source_period_label || point.period}
                  </th>
                  <td>
                    {point.available
                      ? formatCurrencyFromDecimalString(point.period_amount)
                      : "Not available"}
                  </td>
                  <td>
                    {point.available
                      ? formatCurrencyFromDecimalString(point.cumulative_amount)
                      : "Not available"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function AccountDrawer({
  account,
  fiscalYear,
  onAnalyze,
  onClose,
  onDownload,
  trigger,
}) {
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  useEffect(() => {
    if (!account) return undefined;
    closeRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [
        ...dialogRef.current.querySelectorAll(
          'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ];
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [account, onClose]);

  useEffect(
    () => () => {
      trigger?.focus?.();
    },
    [trigger],
  );

  if (!account) return null;
  const grants = sumMoneyStrings([
    account.breakdown?.emergency_grants,
    account.breakdown?.nonemergency_grants,
  ]);
  const contracts = sumMoneyStrings([
    account.breakdown?.emergency_contracts,
    account.breakdown?.nonemergency_contracts,
  ]);
  const values = [
    ["Total obligations", account.total_obligations],
    ["Emergency grants", account.breakdown?.emergency_grants],
    ["Emergency contracts", account.breakdown?.emergency_contracts],
    ["Nonemergency grants", account.breakdown?.nonemergency_grants],
    ["Nonemergency contracts", account.breakdown?.nonemergency_contracts],
    ["Emergency net amount", account.emergency_obligations],
    ["Nonemergency net amount", account.nonemergency_obligations],
    ["Grants net amount", grants],
    ["Contracts net amount", contracts],
  ];
  return (
    <div className="cdc-drawer-backdrop" onMouseDown={onClose}>
      <aside
        className="cdc-account-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cdc-account-drawer-title"
        ref={dialogRef}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="cdc-account-drawer-header">
          <div>
            <span>FY{fiscalYear} federal account</span>
            <h2 id="cdc-account-drawer-title">{conciseAccountName(account)}</h2>
          </div>
          <button
            type="button"
            className="cdc-drawer-close"
            aria-label="Close account details"
            onClick={onClose}
            ref={closeRef}
          >
            ×
          </button>
        </div>
        <p className="cdc-account-official-name">{accountName(account)}</p>
        <p className="cdc-account-symbol">
          Treasury account symbol <strong>{accountSymbol(account)}</strong>
        </p>
        <dl className="cdc-account-drawer-values">
          {values.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd
                className={
                  compareMoneyStrings(value, "0.00") < 0 ? "is-negative" : ""
                }
              >
                {formatCurrencyFromDecimalString(value ?? "0.00")}
              </dd>
            </div>
          ))}
        </dl>
        <AccountTrendPreview account={account} fiscalYear={fiscalYear} />
        <div className="cdc-account-drawer-actions">
          <div>
            <button
              type="button"
              className="cdc-funding-button"
              onClick={() => onAnalyze(account)}
            >
              Analyze this account in Trends
            </button>
            <button
              type="button"
              className="cdc-funding-button is-secondary"
              onClick={() => onDownload(account)}
            >
              Download this account
            </button>
          </div>
          <p>
            The Trends tab provides account-specific monthly and quarterly
            activity with exact accessible values.
          </p>
        </div>
      </aside>
    </div>
  );
}

export function AccountDetailsTab({
  accounts,
  fiscalYear,
  onAnalyzeAccount,
  onCloseDetails,
  onDownload,
  onDownloadAccount,
  onOpenDetails,
  onSearch,
  onSort,
  search,
  selectedAccount,
  selectedAccountTrigger,
  sortDir,
  sortKey,
}) {
  const grantTotal = (account) =>
    sumMoneyStrings([
      account.breakdown?.emergency_grants,
      account.breakdown?.nonemergency_grants,
    ]);
  const contractTotal = (account) =>
    sumMoneyStrings([
      account.breakdown?.emergency_contracts,
      account.breakdown?.nonemergency_contracts,
    ]);
  return (
    <div
      role="tabpanel"
      id="cdc-panel-accounts"
      aria-labelledby="cdc-tab-accounts"
      className="cdc-tab-panel"
    >
      <section
        className="cdc-account-details-section"
        aria-labelledby="cdc-account-details-heading"
      >
        <div className="cdc-section-heading cdc-section-heading-with-controls">
          <div>
            <h2 id="cdc-account-details-heading">Federal account details</h2>
            <p>
              Search, sort, inspect, and download all{" "}
              {accounts.length.toLocaleString("en-US")} accounts in the current
              view.
            </p>
          </div>
          <div className="cdc-account-table-controls">
            <label>
              <span>Account search</span>
              <input
                type="search"
                value={search}
                onChange={(event) => onSearch(event.target.value)}
                placeholder="Search name or symbol"
              />
            </label>
            <label>
              <span>Sort accounts</span>
              <select
                aria-label="Sort accounts"
                value={`${sortKey}:${sortDir}`}
                onChange={(event) => {
                  const [key, direction] = event.target.value.split(":");
                  onSort(key, direction);
                }}
              >
                <option value="total_obligations:desc">
                  Total obligations
                </option>
                <option value="emergency_obligations:desc">
                  Emergency obligations
                </option>
                <option value="nonemergency_obligations:desc">
                  Nonemergency obligations
                </option>
                <option value="account_name:asc">Account name</option>
                <option value="federal_account_symbol:asc">
                  Account symbol
                </option>
              </select>
            </label>
            <button
              type="button"
              className="cdc-funding-button"
              onClick={onDownload}
            >
              Download CSV
            </button>
          </div>
        </div>
        <div className="cdc-account-filter-summary">
          FY{fiscalYear} · All emergency classifications · Grants and contracts
        </div>
        <div className="cdc-account-table-wrap">
          <table className="cdc-account-table">
            <caption>
              Federal funding account obligations for fiscal year {fiscalYear}
            </caption>
            <thead>
              <tr>
                <th scope="col">Federal account</th>
                <th scope="col">Account symbol</th>
                <th scope="col">Emergency</th>
                <th scope="col">Nonemergency</th>
                <th scope="col">Grants</th>
                <th scope="col">Contracts</th>
                <th scope="col">Total obligations</th>
                <th scope="col">Emergency share</th>
                <th scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
              {accounts.length === 0 ? (
                <tr>
                  <td colSpan={9}>
                    No federal accounts match the current search.
                  </td>
                </tr>
              ) : (
                accounts.map((account) => (
                  <tr key={accountSymbol(account)}>
                    <th scope="row">
                      <span title={accountName(account)}>
                        {conciseAccountName(account)}
                      </span>
                      {conciseAccountName(account) !== accountName(account) ? (
                        <small>{accountName(account)}</small>
                      ) : null}
                    </th>
                    <td>{accountSymbol(account) || "Not available"}</td>
                    <td className="cdc-money">
                      {formatCurrencyFromDecimalString(
                        account.emergency_obligations,
                      )}
                    </td>
                    <td className="cdc-money">
                      {formatCurrencyFromDecimalString(
                        account.nonemergency_obligations,
                      )}
                    </td>
                    <td className="cdc-money">
                      {formatCurrencyFromDecimalString(grantTotal(account))}
                    </td>
                    <td className="cdc-money">
                      {formatCurrencyFromDecimalString(contractTotal(account))}
                    </td>
                    <td className="cdc-money">
                      {formatCurrencyFromDecimalString(
                        account.total_obligations,
                      )}
                    </td>
                    <td className="cdc-money cdc-priority-secondary">
                      {formatPercentFromDecimalString(
                        account.emergency_share,
                        1,
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="cdc-text-action"
                        onClick={(event) =>
                          onOpenDetails(account, event.currentTarget)
                        }
                      >
                        View details
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
      <AccountDrawer
        account={selectedAccount}
        fiscalYear={fiscalYear}
        onAnalyze={onAnalyzeAccount}
        onClose={onCloseDetails}
        onDownload={onDownloadAccount}
        trigger={selectedAccountTrigger}
      />
    </div>
  );
}

export function CdcFundingMethodology() {
  return (
    <details className="cdc-funding-about" id="cdc-funding-methodology">
      <summary>About this data and methodology</summary>
      <p>
        This page displays transaction obligations from the ingested CDC-awarded
        funding dataset. It includes all federal accounts, regardless of CDC
        Funding Profile mapping, and represents CDC as the awarding agency.
      </p>
      <p>
        Grants, contracts, emergency, and nonemergency classifications retain
        their reported signs. Negative amounts may represent deobligations,
        corrections, or other downward adjustments; they are not converted to
        positive values.
      </p>
      <p>
        Monthly trends add activity for each available fiscal reporting period.
        The source combines October and November in P02, so October is shown as
        unavailable and the combined activity appears once in November.
        Quarterly trends add quarterly activity. Missing future periods remain
        unavailable rather than zero.
      </p>
      <p>
        Trend filters affect only the trend analysis. The geographic CDC Funding
        Map is a separate product. Annual obligations should not be interpreted
        as appropriations, expenditures, outlays, or award ceilings.
      </p>
    </details>
  );
}
