import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
  fetchCdcFundingAccounts,
  fetchCdcFundingFiscalYears,
  fetchCdcFundingOverview,
} from "../api/cdcFundingOverview";
import Footer from "../components/Footer";
import Header from "../components/Header";
import { API_BASE } from "../config/apiBase";
import {
  compareMoneyStrings,
  decimalStringToNumber,
  formatCurrencyFromDecimalString,
  formatPercentFromDecimalString,
  rowsToCsv,
  sumMoneyStrings,
} from "../utils/cdcFundingFormatting";
import "./CdcFundingOverview.css";

const CLASSIFICATION_DEFS = [
  {
    key: "emergency_grant",
    label: "Emergency Grants",
    emergencyStatus: "emergency",
    awardType: "grant",
    tone: "coral",
  },
  {
    key: "emergency_contract",
    label: "Emergency Contracts",
    emergencyStatus: "emergency",
    awardType: "contract",
    tone: "gold",
  },
  {
    key: "nonemergency_grant",
    label: "Nonemergency Grants",
    emergencyStatus: "nonemergency",
    awardType: "grant",
    tone: "teal",
  },
  {
    key: "nonemergency_contract",
    label: "Nonemergency Contracts",
    emergencyStatus: "nonemergency",
    awardType: "contract",
    tone: "blue",
  },
];

const SORT_OPTIONS = [
  { value: "total_desc", label: "Total obligations" },
  { value: "emergency_desc", label: "Emergency obligations" },
  { value: "nonemergency_desc", label: "Nonemergency obligations" },
  { value: "share_desc", label: "Emergency share" },
  { value: "account_asc", label: "Account name" },
];

const TABLE_SORT_LABELS = {
  account_name: "Federal Account",
  federal_account_symbol: "Account Symbol",
  emergency_obligations: "Emergency",
  nonemergency_obligations: "Nonemergency",
  total_obligations: "Total",
  emergency_share: "Emergency Share",
};

const PAGE_SCOPE = CDC_FUNDING_SCOPE_ALL_ACCOUNTS;

function classificationKey(emergencyStatus, awardType) {
  return `${String(emergencyStatus ?? "").toLowerCase()}_${String(awardType ?? "").toLowerCase()}`;
}

function updateFiscalYearUrl(year, mode = "push") {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set("fiscal_year", String(year));
  const nextPath = `${url.pathname}?${url.searchParams.toString()}${url.hash}`;
  if (mode === "replace") {
    window.history.replaceState({}, "", nextPath);
  } else {
    window.history.pushState({}, "", nextPath);
  }
}

function parseFiscalYearParam() {
  if (typeof window === "undefined") return { status: "missing", year: null };
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("fiscal_year");
  if (raw === null || raw === "") return { status: "missing", year: null };
  const numeric = Number(raw);
  if (!Number.isInteger(numeric) || numeric <= 0 || String(numeric) !== raw.trim()) {
    return { status: "invalid", year: null };
  }
  return { status: "valid", year: numeric };
}

function resolveSelectionFromUrl(years, latestFiscalYear) {
  const availableYears = new Set(years.map((item) => item.fiscal_year));
  const parsed = parseFiscalYearParam();
  if (parsed.status === "missing") {
    if (!latestFiscalYear) {
      return { selectedYear: null, error: "", shouldReplace: false };
    }
    return { selectedYear: latestFiscalYear, error: "", shouldReplace: true };
  }
  if (parsed.status === "invalid") {
    return {
      selectedYear: null,
      error: "Use a valid fiscal_year query parameter, such as fiscal_year=2026.",
      shouldReplace: false,
    };
  }
  if (!availableYears.has(parsed.year)) {
    return {
      selectedYear: null,
      error: `CDC funding data are not available for fiscal year ${parsed.year}.`,
      shouldReplace: false,
    };
  }
  return { selectedYear: parsed.year, error: "", shouldReplace: false };
}

function normalizeYears(payload) {
  return (Array.isArray(payload?.fiscal_years) ? payload.fiscal_years : [])
    .map((item) => ({
      fiscal_year: Number(item?.fiscal_year),
      is_latest: Boolean(item?.is_latest),
    }))
    .filter((item) => Number.isInteger(item.fiscal_year))
    .sort((a, b) => b.fiscal_year - a.fiscal_year);
}

function getAccountName(account) {
  return String(account?.federal_account_name ?? "").trim();
}

function getAccountSymbol(account) {
  return String(account?.federal_account_symbol ?? "").trim();
}

function getAccountPrimaryLabel(account) {
  return getAccountName(account) || getAccountSymbol(account) || "Unknown federal account";
}

function getAccountSecondaryLabel(account) {
  return getAccountName(account) ? getAccountSymbol(account) : "Account name unavailable";
}

function getAccountSortLabel(account) {
  return getAccountName(account) || getAccountSymbol(account);
}

function getClassificationRows(overview) {
  const byKey = new Map();
  (Array.isArray(overview?.classifications) ? overview.classifications : []).forEach((item) => {
    const key = classificationKey(item?.emergency_status, item?.award_type);
    byKey.set(key, item);
  });
  return CLASSIFICATION_DEFS.map((definition) => {
    const row = byKey.get(definition.key);
    return {
      ...definition,
      obligations: row?.obligations ?? "0.00",
      percent_of_total: row?.percent_of_total ?? "0.0000",
      isMissing: !row,
    };
  });
}

function validatePayloadScope(payload, expectedScope, label) {
  if (payload?.scope !== expectedScope) {
    const actualScope = payload?.scope ? ` Received "${payload.scope}".` : "";
    throw new Error(`The CDC funding ${label} response did not use the requested all-account scope.${actualScope}`);
  }
}

function validatePayloads(overview, accountsPayload, selectedYear, expectedScope) {
  const errors = [];
  const fiscalYear = Number(selectedYear);
  if (overview?.scope !== expectedScope) {
    errors.push("The CDC funding overview response did not use the requested all-account scope.");
  }
  if (accountsPayload?.scope !== expectedScope) {
    errors.push("The CDC funding account response did not use the requested all-account scope.");
  }
  if (Number(overview?.fiscal_year) !== fiscalYear) {
    errors.push("The overview response fiscal year did not match the selected fiscal year.");
  }
  if (Number(accountsPayload?.fiscal_year) !== fiscalYear) {
    errors.push("The account response fiscal year did not match the selected fiscal year.");
  }
  if (compareMoneyStrings(overview?.reconciliation?.difference ?? "0.00", "0.00") !== 0) {
    errors.push("The overview classification reconciliation did not balance.");
  }
  if (compareMoneyStrings(accountsPayload?.reconciliation?.difference ?? "0.00", "0.00") !== 0) {
    errors.push("The account reconciliation did not balance.");
  }
  if (
    accountsPayload?.reconciliation?.account_total
    && compareMoneyStrings(accountsPayload.reconciliation.account_total, overview?.total_obligations) !== 0
  ) {
    errors.push("The account total did not match the overview total.");
  }

  const classificationRows = getClassificationRows(overview);
  const classificationSum = sumMoneyStrings(classificationRows.map((row) => row.obligations));
  if (compareMoneyStrings(classificationSum, overview?.total_obligations) !== 0) {
    errors.push("The four classification totals did not equal the overview total.");
  }

  const accounts = Array.isArray(accountsPayload?.accounts) ? accountsPayload.accounts : [];
  accounts.forEach((account) => {
    const breakdown = account?.breakdown ?? {};
    const breakdownTotal = sumMoneyStrings([
      breakdown.emergency_grants,
      breakdown.emergency_contracts,
      breakdown.nonemergency_grants,
      breakdown.nonemergency_contracts,
    ]);
    const emergencyTotal = sumMoneyStrings([
      breakdown.emergency_grants,
      breakdown.emergency_contracts,
    ]);
    const nonemergencyTotal = sumMoneyStrings([
      breakdown.nonemergency_grants,
      breakdown.nonemergency_contracts,
    ]);
    if (compareMoneyStrings(breakdownTotal, account?.total_obligations) !== 0) {
      errors.push(`Breakdown totals did not reconcile for ${getAccountPrimaryLabel(account)}.`);
    }
    if (compareMoneyStrings(emergencyTotal, account?.emergency_obligations) !== 0) {
      errors.push(`Emergency totals did not reconcile for ${getAccountPrimaryLabel(account)}.`);
    }
    if (compareMoneyStrings(nonemergencyTotal, account?.nonemergency_obligations) !== 0) {
      errors.push(`Nonemergency totals did not reconcile for ${getAccountPrimaryLabel(account)}.`);
    }
  });

  return {
    classificationRows,
    accounts,
    errors,
  };
}

function compareAccountLabels(a, b) {
  const nameResult = getAccountSortLabel(a).localeCompare(getAccountSortLabel(b));
  if (nameResult !== 0) return nameResult;
  return getAccountSymbol(a).localeCompare(getAccountSymbol(b));
}

function sortAccounts(accounts, sortKey, sortDir = "desc") {
  const direction = sortDir === "asc" ? 1 : -1;
  const rows = [...accounts];
  rows.sort((a, b) => {
    if (sortKey === "account_name") {
      return direction * compareAccountLabels(a, b);
    }
    if (sortKey === "federal_account_symbol") {
      const result = getAccountSymbol(a).localeCompare(getAccountSymbol(b));
      return result === 0 ? compareAccountLabels(a, b) : direction * result;
    }
    if (sortKey === "emergency_share") {
      const left = a.emergency_share === null || a.emergency_share === undefined ? -Infinity : Number(a.emergency_share);
      const right = b.emergency_share === null || b.emergency_share === undefined ? -Infinity : Number(b.emergency_share);
      const result = left - right;
      return result === 0 ? compareAccountLabels(a, b) : direction * result;
    }
    const result = compareMoneyStrings(a?.[sortKey], b?.[sortKey]);
    return result === 0 ? compareAccountLabels(a, b) : direction * result;
  });
  return rows;
}

function sortAccountsForChart(accounts, chartSort) {
  const [field, direction] = chartSort.split("_");
  if (field === "account") return sortAccounts(accounts, "account_name", direction);
  if (field === "share") return sortAccounts(accounts, "emergency_share", direction);
  return sortAccounts(accounts, `${field}_obligations`, direction);
}

function makeCsvRows(accounts, fiscalYear) {
  return [
    [
      "Fiscal Year",
      "Federal Account Name",
      "Federal Account Symbol",
      "Emergency Grants",
      "Emergency Contracts",
      "Emergency Total",
      "Nonemergency Grants",
      "Nonemergency Contracts",
      "Nonemergency Total",
      "Total Obligations",
      "Emergency Share Percent",
    ],
    ...accounts.map((account) => [
      fiscalYear,
      getAccountName(account),
      getAccountSymbol(account),
      account.breakdown?.emergency_grants ?? "0.00",
      account.breakdown?.emergency_contracts ?? "0.00",
      account.emergency_obligations,
      account.breakdown?.nonemergency_grants ?? "0.00",
      account.breakdown?.nonemergency_contracts ?? "0.00",
      account.nonemergency_obligations,
      account.total_obligations,
      account.emergency_share ?? "",
    ]),
  ];
}

function SectionTitle({ title, subtitle }) {
  return (
    <div className="cdc-funding-section-title">
      <h2>{title}</h2>
      {subtitle ? <p>{subtitle}</p> : null}
    </div>
  );
}

function StatusPanel({ title, message, actionLabel, onAction }) {
  return (
    <section className="cdc-funding-status" aria-live="polite">
      <h2>{title}</h2>
      {message ? <p>{message}</p> : null}
      {onAction ? (
        <button type="button" className="cdc-funding-button" onClick={onAction}>
          {actionLabel ?? "Retry"}
        </button>
      ) : null}
    </section>
  );
}

function Skeleton() {
  return (
    <div className="cdc-funding-skeleton" aria-label="Loading CDC funding overview">
      <span />
      <span />
      <span />
      <span />
    </div>
  );
}

function ClassificationCards({ rows }) {
  return (
    <section className="cdc-funding-card-grid" aria-label="Annual transaction obligation classifications">
      {rows.map((row) => (
        <article className={`cdc-funding-kpi is-${row.tone}`} key={row.key}>
          <span className="cdc-funding-kpi-label">{row.label}</span>
          <strong>{formatCurrencyFromDecimalString(row.obligations)}</strong>
          <span>{formatPercentFromDecimalString(row.percent_of_total)} of all-account obligations</span>
        </article>
      ))}
    </section>
  );
}

function CompositionBar({ rows, total }) {
  const hasPositiveTotal = compareMoneyStrings(total, "0.00") > 0;
  const hasNegativeSegment = rows.some((row) => compareMoneyStrings(row.obligations, "0.00") < 0);
  if (!hasPositiveTotal || hasNegativeSegment) {
    return (
      <div className="cdc-funding-note" role="note">
        The composition bar is hidden because this fiscal year includes zero or negative values. The amounts remain
        visible in the classification cards and matrix.
      </div>
    );
  }
  return (
    <div className="cdc-funding-composition" aria-label="Funding composition by classification">
      <div className="cdc-funding-composition-bar" aria-hidden="true">
        {rows.map((row) => (
          <span
            className={`is-${row.tone}`}
            key={row.key}
            style={{ width: `${Math.max(0, decimalStringToNumber(row.percent_of_total))}%` }}
          />
        ))}
      </div>
      <ul className="cdc-funding-composition-list">
        {rows.map((row) => (
          <li key={row.key}>
            <span className={`cdc-funding-dot is-${row.tone}`} />
            <span>{row.label}</span>
            <strong>{formatPercentFromDecimalString(row.percent_of_total)}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Matrix({ rows }) {
  const byKey = new Map(rows.map((row) => [row.key, row]));
  const matrixRows = [
    { label: "Emergency", prefix: "emergency" },
    { label: "Nonemergency", prefix: "nonemergency" },
  ];
  return (
    <div className="cdc-funding-matrix" role="table" aria-label="Emergency status by award type">
      <div className="cdc-funding-matrix-row is-header" role="row">
        <span role="columnheader" />
        <span role="columnheader">Grants</span>
        <span role="columnheader">Contracts</span>
      </div>
      {matrixRows.map((matrixRow) => (
        <div className="cdc-funding-matrix-row" role="row" key={matrixRow.prefix}>
          <span role="rowheader">{matrixRow.label}</span>
          {["grant", "contract"].map((awardType) => {
            const row = byKey.get(`${matrixRow.prefix}_${awardType}`);
            return (
              <span role="cell" key={awardType}>
                <strong>{formatCurrencyFromDecimalString(row?.obligations ?? "0.00")}</strong>
                <small>{formatPercentFromDecimalString(row?.percent_of_total ?? "0.0000")}</small>
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function AccountsChart({ accounts, chartMode, chartLimit, chartSort, onModeChange, onLimitChange, onSortChange }) {
  const chartAccounts = useMemo(() => {
    const sorted = sortAccountsForChart(accounts, chartSort);
    return chartLimit === "top15" ? sorted.slice(0, 15) : sorted;
  }, [accounts, chartLimit, chartSort]);
  const maxTotal = useMemo(
    () => chartAccounts.reduce((max, account) => Math.max(max, Math.abs(decimalStringToNumber(account.total_obligations))), 0),
    [chartAccounts]
  );
  const canRenderDollarBars = chartMode === "dollars"
    && maxTotal > 0
    && chartAccounts.every((account) => compareMoneyStrings(account.total_obligations, "0.00") >= 0);

  return (
    <section className="cdc-funding-section">
      <div className="cdc-funding-section-header">
        <SectionTitle
          title="Funding by Federal Account"
          subtitle="Compare federal account totals or emergency share for the selected fiscal year."
        />
        <div className="cdc-funding-control-row">
          <label>
            <span>View</span>
            <select value={chartMode} onChange={(event) => onModeChange(event.target.value)}>
              <option value="dollars">Dollars</option>
              <option value="share">Emergency share</option>
            </select>
          </label>
          <label>
            <span>Rows</span>
            <select value={chartLimit} onChange={(event) => onLimitChange(event.target.value)}>
              <option value="top15">Top 15</option>
              <option value="all">All</option>
            </select>
          </label>
          <label>
            <span>Sort</span>
            <select value={chartSort} onChange={(event) => onSortChange(event.target.value)}>
              {SORT_OPTIONS.map((option) => (
                <option value={option.value} key={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div className="cdc-funding-chart" role="list" aria-label="Federal account chart rows">
        {chartAccounts.length === 0 ? (
          <p className="cdc-funding-muted">No federal accounts match the current search.</p>
        ) : chartAccounts.map((account) => {
          const totalWidth = canRenderDollarBars
            ? Math.max(2, (decimalStringToNumber(account.total_obligations) / maxTotal) * 100)
            : 100;
          const share = account.emergency_share === null ? null : Math.max(0, Math.min(100, Number(account.emergency_share)));
          return (
            <div className="cdc-funding-chart-row" role="listitem" key={getAccountSymbol(account)}>
              <div className="cdc-funding-chart-label">
                <strong title={getAccountPrimaryLabel(account)}>{getAccountPrimaryLabel(account)}</strong>
                <span title={getAccountSecondaryLabel(account)}>{getAccountSecondaryLabel(account)}</span>
              </div>
              <div className="cdc-funding-chart-track" aria-hidden="true">
                {chartMode === "share" ? (
                  <>
                    <span className="cdc-funding-chart-emergency" style={{ width: `${share ?? 0}%` }} />
                    <span className="cdc-funding-chart-nonemergency" style={{ width: `${share === null ? 0 : 100 - share}%` }} />
                  </>
                ) : canRenderDollarBars ? (
                  <span className="cdc-funding-chart-total" style={{ width: `${totalWidth}%` }} />
                ) : (
                  <span className="cdc-funding-chart-total is-unusual" />
                )}
              </div>
              <div className="cdc-funding-chart-value">
                {chartMode === "share"
                  ? formatPercentFromDecimalString(account.emergency_share, 1)
                  : formatCurrencyFromDecimalString(account.total_obligations)}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function AccountsTable({
  accounts,
  expandedAccounts,
  fiscalYear,
  onDownload,
  onSearch,
  onSort,
  onToggleExpand,
  search,
  sortDir,
  sortKey,
}) {
  return (
    <section className="cdc-funding-section">
      <div className="cdc-funding-section-header">
        <SectionTitle
          title="Federal Funding Account Details"
          subtitle={`${accounts.length.toLocaleString("en-US")} account${accounts.length === 1 ? "" : "s"} in the current view.`}
        />
        <div className="cdc-funding-table-actions">
          <label>
            <span>Account search</span>
            <input
              type="search"
              value={search}
              onChange={(event) => onSearch(event.target.value)}
              placeholder="Search federal accounts"
            />
          </label>
          <button type="button" className="cdc-funding-button" onClick={onDownload}>
            Download CSV
          </button>
        </div>
      </div>
      <div className="cdc-funding-table-wrap">
        <table className="cdc-funding-table">
          <caption>Federal funding account obligations for fiscal year {fiscalYear}</caption>
          <thead>
            <tr>
              <th scope="col">Details</th>
              {Object.entries(TABLE_SORT_LABELS).map(([key, label]) => (
                <th scope="col" key={key}>
                  <button type="button" onClick={() => onSort(key)}>
                    {label}{sortKey === key ? (sortDir === "asc" ? " asc" : " desc") : ""}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {accounts.length === 0 ? (
              <tr>
                <td colSpan={7}>No federal accounts match the current search.</td>
              </tr>
            ) : accounts.map((account) => {
              const symbol = getAccountSymbol(account);
              const name = getAccountName(account);
              const primary = getAccountPrimaryLabel(account);
              const expanded = expandedAccounts.has(symbol);
              const rowId = `cdc-account-${symbol.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;
              return (
                <Fragment key={symbol}>
                  <tr>
                    <td>
                      <button
                        type="button"
                        className="cdc-funding-expand"
                        aria-expanded={expanded}
                        aria-controls={rowId}
                        onClick={() => onToggleExpand(symbol)}
                      >
                        {expanded ? "Hide" : "Show"}
                      </button>
                    </td>
                    <td>{name || primary}</td>
                    <td>{symbol || "Not available"}</td>
                    <td>{formatCurrencyFromDecimalString(account.emergency_obligations)}</td>
                    <td>{formatCurrencyFromDecimalString(account.nonemergency_obligations)}</td>
                    <td>{formatCurrencyFromDecimalString(account.total_obligations)}</td>
                    <td>{formatPercentFromDecimalString(account.emergency_share, 1)}</td>
                  </tr>
                  {expanded ? (
                    <tr className="cdc-funding-breakdown-row" key={`${symbol}-details`}>
                      <td colSpan={7} id={rowId}>
                        <div className="cdc-funding-breakdown-grid">
                          <span>Emergency grants <strong>{formatCurrencyFromDecimalString(account.breakdown?.emergency_grants)}</strong></span>
                          <span>Emergency contracts <strong>{formatCurrencyFromDecimalString(account.breakdown?.emergency_contracts)}</strong></span>
                          <span>Nonemergency grants <strong>{formatCurrencyFromDecimalString(account.breakdown?.nonemergency_grants)}</strong></span>
                          <span>Nonemergency contracts <strong>{formatCurrencyFromDecimalString(account.breakdown?.nonemergency_contracts)}</strong></span>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
            {accounts.length > 0 ? (
              <tr className="cdc-funding-total-row">
                <td colSpan={3}>Current view total</td>
                <td>{formatCurrencyFromDecimalString(sumMoneyStrings(accounts.map((account) => account.emergency_obligations)))}</td>
                <td>{formatCurrencyFromDecimalString(sumMoneyStrings(accounts.map((account) => account.nonemergency_obligations)))}</td>
                <td>{formatCurrencyFromDecimalString(sumMoneyStrings(accounts.map((account) => account.total_obligations)))}</td>
                <td />
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function CdcFundingOverview() {
  const [fiscalYears, setFiscalYears] = useState([]);
  const [latestYear, setLatestYear] = useState(null);
  const [selectedYear, setSelectedYear] = useState(null);
  const [yearsLoading, setYearsLoading] = useState(true);
  const [yearError, setYearError] = useState("");
  const [yearsReloadKey, setYearsReloadKey] = useState(0);
  const [payload, setPayload] = useState(null);
  const [dataLoading, setDataLoading] = useState(false);
  const [dataError, setDataError] = useState("");
  const [dataReloadKey, setDataReloadKey] = useState(0);
  const [chartMode, setChartMode] = useState("dollars");
  const [chartLimit, setChartLimit] = useState("top15");
  const [chartSort, setChartSort] = useState("total_desc");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("total_obligations");
  const [sortDir, setSortDir] = useState("desc");
  const [expandedAccounts, setExpandedAccounts] = useState(() => new Set());

  useEffect(() => {
    const controller = new AbortController();
    setYearsLoading(true);
    setYearError("");
    fetchCdcFundingFiscalYears({
      apiBase: API_BASE,
      signal: controller.signal,
      scope: PAGE_SCOPE,
    })
      .then((response) => {
        if (controller.signal.aborted) return;
        validatePayloadScope(response, PAGE_SCOPE, "fiscal-year");
        const years = normalizeYears(response);
        const latest = response?.latest_fiscal_year ?? years.find((item) => item.is_latest)?.fiscal_year ?? years[0]?.fiscal_year ?? null;
        setFiscalYears(years);
        setLatestYear(latest);
        const selection = resolveSelectionFromUrl(years, latest);
        setSelectedYear(selection.selectedYear);
        setYearError(selection.error);
        if (selection.shouldReplace && selection.selectedYear) {
          updateFiscalYearUrl(selection.selectedYear, "replace");
        }
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (error?.status === 404) {
          setYearError(
            "CDC Funding API v1 was not found on the active backend. Restart the FastAPI server from the current branch and confirm /api/cdc-funding/v1/fiscal-years returns data."
          );
          return;
        }
        setYearError(error?.message ?? "Failed to load fiscal years.");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setYearsLoading(false);
      });
    return () => controller.abort();
  }, [yearsReloadKey]);

  useEffect(() => {
    if (fiscalYears.length === 0) return undefined;
    const handlePopState = () => {
      const selection = resolveSelectionFromUrl(fiscalYears, latestYear);
      setSelectedYear(selection.selectedYear);
      setYearError(selection.error);
      setExpandedAccounts(new Set());
      if (selection.shouldReplace && selection.selectedYear) {
        updateFiscalYearUrl(selection.selectedYear, "replace");
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [fiscalYears, latestYear]);

  useEffect(() => {
    if (!selectedYear || yearError) {
      setPayload(null);
      setDataLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    setDataLoading(true);
    setDataError("");
    Promise.all([
      fetchCdcFundingOverview(selectedYear, {
        apiBase: API_BASE,
        signal: controller.signal,
        scope: PAGE_SCOPE,
      }),
      fetchCdcFundingAccounts(selectedYear, {
        apiBase: API_BASE,
        signal: controller.signal,
        scope: PAGE_SCOPE,
      }),
    ])
      .then(([overview, accountsPayload]) => {
        if (controller.signal.aborted) return;
        const validation = validatePayloads(
          overview,
          accountsPayload,
          selectedYear,
          PAGE_SCOPE
        );
        if (validation.errors.length > 0) {
          throw new Error(validation.errors[0]);
        }
        setPayload({
          overview,
          accountsPayload,
          classificationRows: validation.classificationRows,
          accounts: validation.accounts,
        });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setPayload(null);
        setDataError(error?.message ?? "Failed to load CDC funding data.");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setDataLoading(false);
      });
    return () => controller.abort();
  }, [selectedYear, yearError, dataReloadKey]);

  useEffect(() => {
    setSearch("");
    setExpandedAccounts(new Set());
    setSortKey("total_obligations");
    setSortDir("desc");
    setChartMode("dollars");
    setChartLimit("top15");
    setChartSort("total_desc");
  }, [selectedYear]);

  const filteredAccounts = useMemo(() => {
    const normalizedSearch = search.trim().replace(/\s+/g, " ").toLowerCase();
    const accounts = payload?.accounts ?? [];
    const filtered = normalizedSearch
      ? accounts.filter((account) => {
        const searchable = `${getAccountName(account)} ${getAccountSymbol(account)}`.replace(/\s+/g, " ").toLowerCase();
        return searchable.includes(normalizedSearch);
      })
      : accounts;
    return sortAccounts(filtered, sortKey, sortDir);
  }, [payload, search, sortDir, sortKey]);

  const handleYearChange = (event) => {
    const nextYear = Number(event.target.value);
    setSelectedYear(nextYear);
    setYearError("");
    updateFiscalYearUrl(nextYear, "push");
  };

  const handleSort = useCallback((key) => {
    setSortKey((currentKey) => {
      if (currentKey !== key) {
        setSortDir(key === "account_name" || key === "federal_account_symbol" ? "asc" : "desc");
        return key;
      }
      setSortDir((currentDir) => (currentDir === "asc" ? "desc" : "asc"));
      return currentKey;
    });
  }, []);

  const handleToggleExpand = (accountSymbol) => {
    setExpandedAccounts((current) => {
      const next = new Set(current);
      if (next.has(accountSymbol)) {
        next.delete(accountSymbol);
      } else {
        next.add(accountSymbol);
      }
      return next;
    });
  };

  const handleDownloadCsv = () => {
    const csv = `${rowsToCsv(makeCsvRows(filteredAccounts, selectedYear))}\r\n`;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `cdc-funding-accounts-fy${selectedYear}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const total = payload?.overview?.total_obligations ?? "0.00";
  const classificationRows = payload?.classificationRows ?? [];
  const totalAccounts = payload?.accountsPayload?.total_accounts ?? payload?.accounts?.length ?? 0;
  const hasEmptyYears = !yearsLoading && fiscalYears.length === 0 && !yearError;
  const showingData = selectedYear && payload && !dataLoading && !dataError;

  return (
    <div className="cdc-funding-page">
      <Header />
      <main className="cdc-funding-main">
        <section className="cdc-funding-hero">
          <div>
            <div className="cdc-funding-kicker">CDC Funding Overview</div>
            <h1>CDC Funding Overview</h1>
            <p>
              Explore annual CDC-awarded obligations by emergency designation, award type, and federal funding account.
            </p>
            <p className="cdc-funding-scope-copy">
              This page includes all federal accounts in the ingested CDC-awarded funding dataset.
            </p>
          </div>
          <div className="cdc-funding-year-panel">
            <label>
              <span>Fiscal year</span>
              <select
                aria-label="Fiscal year"
                value={selectedYear ?? ""}
                onChange={handleYearChange}
                disabled={yearsLoading || fiscalYears.length === 0}
              >
                {selectedYear === null ? <option value="">Select fiscal year</option> : null}
                {fiscalYears.map((item) => (
                  <option value={item.fiscal_year} key={item.fiscal_year}>
                    FY{item.fiscal_year}{item.is_latest ? " latest" : ""}
                  </option>
                ))}
              </select>
            </label>
            <span>{latestYear ? `Latest available: FY${latestYear}` : "Latest available: none"}</span>
          </div>
        </section>

        {yearsLoading ? <Skeleton /> : null}
        {hasEmptyYears ? (
          <StatusPanel
            title="No fiscal years available"
            message="The CDC funding API responded successfully, but no completed fiscal years are ready to display."
          />
        ) : null}
        {yearError ? (
          <StatusPanel
            title="Fiscal year unavailable"
            message={yearError}
            actionLabel="Reload fiscal years"
            onAction={() => setYearsReloadKey((value) => value + 1)}
          />
        ) : null}
        {dataLoading ? <Skeleton /> : null}
        {dataError ? (
          <StatusPanel
            title="CDC funding data could not be loaded"
            message={dataError}
            actionLabel="Retry"
            onAction={() => setDataReloadKey((value) => value + 1)}
          />
        ) : null}

        {showingData ? (
          <>
            <section className="cdc-funding-section">
              <div className="cdc-funding-overview-header">
                <div>
                  <SectionTitle
                    title={`FY${selectedYear} Overview`}
                    subtitle={`${totalAccounts.toLocaleString("en-US")} federal funding account${totalAccounts === 1 ? "" : "s"} reconciled to the all-account annual total.`}
                  />
                </div>
                <div className="cdc-funding-total">
                  <span>All-account obligations</span>
                  <strong>{formatCurrencyFromDecimalString(total)}</strong>
                </div>
              </div>
              <ClassificationCards rows={classificationRows} />
              <CompositionBar rows={classificationRows} total={total} />
              <Matrix rows={classificationRows} />
            </section>

            <AccountsChart
              accounts={filteredAccounts}
              chartMode={chartMode}
              chartLimit={chartLimit}
              chartSort={chartSort}
              onModeChange={setChartMode}
              onLimitChange={setChartLimit}
              onSortChange={setChartSort}
            />

            <AccountsTable
              accounts={filteredAccounts}
              expandedAccounts={expandedAccounts}
              fiscalYear={selectedYear}
              onDownload={handleDownloadCsv}
              onSearch={setSearch}
              onSort={handleSort}
              onToggleExpand={handleToggleExpand}
              search={search}
              sortDir={sortDir}
              sortKey={sortKey}
            />

            <details className="cdc-funding-about">
              <summary>About this data</summary>
              <p>
                This page displays annual transaction obligations from the ingested CDC-awarded funding dataset. It
                includes all federal funding accounts in the selected fiscal year, regardless of whether an account
                maps to a CDC Funding Profile budget category. Grants and contracts are shown separately, emergency
                and nonemergency classifications are retained, and negative obligations or adjustments remain
                included.
              </p>
              <p>
                Federal accounts are identified by federal account symbol. Account totals can contain grants,
                contracts, emergency funding, and nonemergency funding. CDC Funding Profile mappings are not used to
                determine inclusion, and the latest year is determined dynamically from the fiscal years available in
                the ingested dataset.
              </p>
              <p>
                FY2026 is currently the latest available year. These values represent obligations and should not be
                interpreted as appropriations, outlays, expenditures, or award ceilings. Monthly, quarterly,
                recipient, and geographic detail remain outside this page, which is separate from the geographic CDC
                Funding Map.
              </p>
            </details>
          </>
        ) : null}
      </main>
      <Footer />
    </div>
  );
}
