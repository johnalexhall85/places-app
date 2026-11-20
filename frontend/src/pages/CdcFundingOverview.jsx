import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
  fetchCdcFundingAccounts,
  fetchCdcFundingFiscalYears,
  fetchCdcFundingObligationTrends,
  fetchCdcFundingOverview,
  fetchCdcFundingTrendAccounts,
} from "../api/cdcFundingOverview";
import Footer from "../components/Footer";
import Header from "../components/Header";
import { API_BASE } from "../config/apiBase";
import {
  AccountDetailsTab,
  CdcFundingHeader,
  CdcFundingMethodology,
  CdcFundingTabs,
  FocusedObligationTrends,
  FundingOverviewTab,
} from "./CdcFundingOverviewRedesign";
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
    label: "Supplemental Grants",
    emergencyStatus: "emergency",
    awardType: "grant",
    tone: "coral",
  },
  {
    key: "emergency_contract",
    label: "Supplemental Contracts",
    emergencyStatus: "emergency",
    awardType: "contract",
    tone: "gold",
  },
  {
    key: "nonemergency_grant",
    label: "Non-supplemental Grants",
    emergencyStatus: "nonemergency",
    awardType: "grant",
    tone: "teal",
  },
  {
    key: "nonemergency_contract",
    label: "Non-supplemental Contracts",
    emergencyStatus: "nonemergency",
    awardType: "contract",
    tone: "blue",
  },
];

const SORT_OPTIONS = [
  { value: "total_desc", label: "Total obligations" },
  { value: "emergency_desc", label: "Supplemental obligations" },
  { value: "nonemergency_desc", label: "Non-supplemental obligations" },
  { value: "share_desc", label: "Supplemental share" },
  { value: "account_asc", label: "Account name" },
];

const TABLE_SORT_LABELS = {
  account_name: "Federal Account",
  federal_account_symbol: "Account Symbol",
  emergency_obligations: "Supplemental",
  nonemergency_obligations: "Non-supplemental",
  total_obligations: "Total",
  emergency_share: "Supplemental Share",
};

const PAGE_SCOPE = CDC_FUNDING_SCOPE_ALL_ACCOUNTS;
const TREND_DEFAULTS = {
  measure: "obligations",
  period: "month",
  display: "cumulative",
  years: null,
  comparisons: [],
  view: "total",
  account: "",
  emergency: "all",
  awardType: "all",
  includeFy2021: false,
  excludeDeobligations: false,
};
const PAGE_TAB_DEFAULT = "trends";
const PAGE_TABS = ["trends", "overview", "accounts"];
const TREND_COLORS = [
  "#075985",
  "#9f1239",
  "#166534",
  "#7c3aed",
  "#a16207",
  "#0f766e",
  "#334155",
];
const TREND_DASHES = ["", "8 4", "3 3", "12 4 3 4", "2 5", "10 3", "5 2 2 2"];

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

function parseTrendStateFromUrl() {
  if (typeof window === "undefined") return TREND_DEFAULTS;
  const params = new URLSearchParams(window.location.search);
  const allowed = (name, values, fallback) => {
    const value = params.get(name);
    return values.includes(value) ? value : fallback;
  };
  return {
    measure: allowed(
      "trend_funding_measure",
      ["obligations", "outlays"],
      TREND_DEFAULTS.measure,
    ),
    period: allowed(
      "trend_period",
      ["month", "quarter"],
      TREND_DEFAULTS.period,
    ),
    display: allowed(
      "trend_display",
      ["activity", "cumulative"],
      TREND_DEFAULTS.display,
    ),
    comparisons: (() => {
      const values = params.getAll("trend_compare");
      if (values.length === 0) return [...TREND_DEFAULTS.comparisons];
      const tokens = values
        .flatMap((value) => value.split(","))
        .map((value) => value.trim())
        .filter(
          (value) =>
            (value === "prior" || /^\d{4}$/.test(value)) &&
            value !== params.get("fiscal_year"),
        );
      if (values.some((value) => value === "none")) return [];
      return [...new Set(tokens)];
    })(),
    years: (() => {
      const raw = params.get("trend_years");
      if (raw === null && params.has("trend_compare")) {
        const selected = Number(params.get("fiscal_year"));
        const legacy = params
          .getAll("trend_compare")
          .flatMap((value) => value.split(","))
          .map((value) =>
            value === "prior" && Number.isInteger(selected)
              ? selected - 1
              : Number(value),
          )
          .filter(Number.isInteger);
        if (Number.isInteger(selected)) legacy.push(selected);
        if (params.get("trend_include_fy2021") === "true") legacy.push(2021);
        return [...new Set(legacy)].sort((a, b) => a - b);
      }
      if (raw === null) return null;
      return [...new Set(raw.split(",").map(Number).filter(Number.isInteger))]
        .sort((a, b) => a - b);
    })(),
    view: allowed(
      "trend_view",
      ["total", "federal_account"],
      TREND_DEFAULTS.view,
    ),
    account: String(params.get("trend_account") ?? "").trim(),
    emergency: allowed(
      "trend_emergency",
      ["all", "emergency", "nonemergency"],
      TREND_DEFAULTS.emergency,
    ),
    awardType: allowed(
      "trend_award_type",
      ["all", "grant", "contract"],
      TREND_DEFAULTS.awardType,
    ),
    includeFy2021:
      params.get("trend_include_fy2021") === "true" ||
      params.get("fiscal_year") === "2021" ||
      params
        .getAll("trend_compare")
        .flatMap((value) => value.split(","))
        .includes("2021"),
    excludeDeobligations:
      params.get("trend_exclude_deobligations") === "true",
  };
}

function updateTrendUrl(state, mode = "push") {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.delete("trend_measure");
  if (state.measure === "outlays") {
    url.searchParams.set("trend_funding_measure", "outlays");
  } else {
    url.searchParams.delete("trend_funding_measure");
  }
  url.searchParams.set("trend_period", state.period);
  url.searchParams.set("trend_display", state.display);
  if (Array.isArray(state.years)) {
    url.searchParams.delete("trend_compare");
    url.searchParams.set(
      "trend_years",
      [...new Set(state.years.map(Number).filter(Number.isInteger))]
        .sort((a, b) => a - b)
        .join(","),
    );
  } else {
    const comparisons = Array.isArray(state.comparisons)
      ? [...new Set(state.comparisons)]
      : [...TREND_DEFAULTS.comparisons];
    url.searchParams.set(
      "trend_compare",
      comparisons.length > 0 ? comparisons.join(",") : "none",
    );
    url.searchParams.delete("trend_years");
  }
  url.searchParams.set("trend_view", state.view);
  url.searchParams.set("trend_emergency", state.emergency);
  url.searchParams.set("trend_award_type", state.awardType);
  url.searchParams.set(
    "trend_include_fy2021",
    state.includeFy2021 ? "true" : "false",
  );
  if (state.excludeDeobligations) {
    url.searchParams.set("trend_exclude_deobligations", "true");
  } else {
    url.searchParams.delete("trend_exclude_deobligations");
  }
  if (state.account) url.searchParams.set("trend_account", state.account);
  else url.searchParams.delete("trend_account");
  const nextPath = `${url.pathname}?${url.searchParams.toString()}${url.hash}`;
  window.history[mode === "replace" ? "replaceState" : "pushState"](
    {},
    "",
    nextPath,
  );
}

function parsePageTabFromUrl() {
  if (typeof window === "undefined") return PAGE_TAB_DEFAULT;
  const params = new URLSearchParams(window.location.search);
  const value = params.get("tab");
  if (PAGE_TABS.includes(value)) return value;
  const legacyTrendParameters = [
    "trend_view",
    "trend_emergency",
    "trend_award_type",
    "trend_account",
    "trend_period",
    "trend_include_fy2021",
    "trend_exclude_deobligations",
    "trend_measure",
    "trend_funding_measure",
    "trend_years",
  ];
  return legacyTrendParameters.some((name) => params.has(name))
    ? "trends"
    : PAGE_TAB_DEFAULT;
}

function updatePageTabUrl(tab, mode = "push") {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (tab === PAGE_TAB_DEFAULT) url.searchParams.delete("tab");
  else url.searchParams.set("tab", tab);
  const query = url.searchParams.toString();
  const nextPath = `${url.pathname}${query ? `?${query}` : ""}${url.hash}`;
  window.history[mode === "replace" ? "replaceState" : "pushState"](
    {},
    "",
    nextPath,
  );
}

function parseFiscalYearParam() {
  if (typeof window === "undefined") return { status: "missing", year: null };
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("fiscal_year");
  if (raw === null || raw === "") return { status: "missing", year: null };
  const numeric = Number(raw);
  if (
    !Number.isInteger(numeric) ||
    numeric <= 0 ||
    String(numeric) !== raw.trim()
  ) {
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
      error:
        "Use a valid fiscal_year query parameter, such as fiscal_year=2026.",
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
  return (
    getAccountName(account) ||
    getAccountSymbol(account) ||
    "Unknown federal account"
  );
}

function getAccountSecondaryLabel(account) {
  return getAccountName(account)
    ? getAccountSymbol(account)
    : "Account name unavailable";
}

function getAccountSortLabel(account) {
  return getAccountName(account) || getAccountSymbol(account);
}

function getClassificationRows(overview) {
  const byKey = new Map();
  (Array.isArray(overview?.classifications)
    ? overview.classifications
    : []
  ).forEach((item) => {
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
    throw new Error(
      `The CDC funding ${label} response did not use the requested all-account scope.${actualScope}`,
    );
  }
}

function validatePayloads(
  overview,
  accountsPayload,
  selectedYear,
  expectedScope,
) {
  const errors = [];
  const fiscalYear = Number(selectedYear);
  if (overview?.scope !== expectedScope) {
    errors.push(
      "The CDC funding overview response did not use the requested all-account scope.",
    );
  }
  if (accountsPayload?.scope !== expectedScope) {
    errors.push(
      "The CDC funding account response did not use the requested all-account scope.",
    );
  }
  if (Number(overview?.fiscal_year) !== fiscalYear) {
    errors.push(
      "The overview response fiscal year did not match the selected fiscal year.",
    );
  }
  if (Number(accountsPayload?.fiscal_year) !== fiscalYear) {
    errors.push(
      "The account response fiscal year did not match the selected fiscal year.",
    );
  }
  if (
    compareMoneyStrings(
      overview?.reconciliation?.difference ?? "0.00",
      "0.00",
    ) !== 0
  ) {
    errors.push("The overview classification reconciliation did not balance.");
  }
  if (
    compareMoneyStrings(
      accountsPayload?.reconciliation?.difference ?? "0.00",
      "0.00",
    ) !== 0
  ) {
    errors.push("The account reconciliation did not balance.");
  }
  if (
    accountsPayload?.reconciliation?.account_total &&
    compareMoneyStrings(
      accountsPayload.reconciliation.account_total,
      overview?.total_obligations,
    ) !== 0
  ) {
    errors.push("The account total did not match the overview total.");
  }

  const classificationRows = getClassificationRows(overview);
  const classificationSum = sumMoneyStrings(
    classificationRows.map((row) => row.obligations),
  );
  if (
    compareMoneyStrings(classificationSum, overview?.total_obligations) !== 0
  ) {
    errors.push(
      "The four classification totals did not equal the overview total.",
    );
  }

  const accounts = Array.isArray(accountsPayload?.accounts)
    ? accountsPayload.accounts
    : [];
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
      errors.push(
        `Breakdown totals did not reconcile for ${getAccountPrimaryLabel(account)}.`,
      );
    }
    if (
      compareMoneyStrings(emergencyTotal, account?.emergency_obligations) !== 0
    ) {
      errors.push(
        `Supplemental totals did not reconcile for ${getAccountPrimaryLabel(account)}.`,
      );
    }
    if (
      compareMoneyStrings(
        nonemergencyTotal,
        account?.nonemergency_obligations,
      ) !== 0
    ) {
      errors.push(
        `Non-supplemental totals did not reconcile for ${getAccountPrimaryLabel(account)}.`,
      );
    }
  });

  return {
    classificationRows,
    accounts,
    errors,
  };
}

function compareAccountLabels(a, b) {
  const nameResult = getAccountSortLabel(a).localeCompare(
    getAccountSortLabel(b),
  );
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
      const left =
        a.emergency_share === null || a.emergency_share === undefined
          ? -Infinity
          : Number(a.emergency_share);
      const right =
        b.emergency_share === null || b.emergency_share === undefined
          ? -Infinity
          : Number(b.emergency_share);
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
  if (field === "account")
    return sortAccounts(accounts, "account_name", direction);
  if (field === "share")
    return sortAccounts(accounts, "emergency_share", direction);
  return sortAccounts(accounts, `${field}_obligations`, direction);
}

function makeCsvRows(accounts, fiscalYear) {
  return [
    [
      "Fiscal Year",
      "Federal Account Name",
      "Federal Account Symbol",
      "Supplemental Grants",
      "Supplemental Contracts",
      "Supplemental Total",
      "Non-supplemental Grants",
      "Non-supplemental Contracts",
      "Non-supplemental Total",
      "Total Obligations",
      "Supplemental Share Percent",
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

function SectionTitle({ title, subtitle, id }) {
  return (
    <div className="cdc-funding-section-title">
      <h2 id={id}>{title}</h2>
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
    <div
      className="cdc-funding-skeleton"
      aria-label="Loading CDC funding overview"
    >
      <span />
      <span />
      <span />
      <span />
    </div>
  );
}

function ClassificationCards({ rows }) {
  return (
    <section
      className="cdc-funding-card-grid"
      aria-label="Annual transaction obligation classifications"
    >
      {rows.map((row) => (
        <article className={`cdc-funding-kpi is-${row.tone}`} key={row.key}>
          <span className="cdc-funding-kpi-label">{row.label}</span>
          <strong>{formatCurrencyFromDecimalString(row.obligations)}</strong>
          <span>
            {formatPercentFromDecimalString(row.percent_of_total)} of
            all-account obligations
          </span>
        </article>
      ))}
    </section>
  );
}

function CompositionBar({ rows, total }) {
  const hasPositiveTotal = compareMoneyStrings(total, "0.00") > 0;
  const hasNegativeSegment = rows.some(
    (row) => compareMoneyStrings(row.obligations, "0.00") < 0,
  );
  if (!hasPositiveTotal || hasNegativeSegment) {
    return (
      <div className="cdc-funding-note" role="note">
        The composition bar is hidden because this fiscal year includes zero or
        negative values. The amounts remain visible in the classification cards
        and matrix.
      </div>
    );
  }
  return (
    <div
      className="cdc-funding-composition"
      aria-label="Funding composition by classification"
    >
      <div className="cdc-funding-composition-bar" aria-hidden="true">
        {rows.map((row) => (
          <span
            className={`is-${row.tone}`}
            key={row.key}
            style={{
              width: `${Math.max(0, decimalStringToNumber(row.percent_of_total))}%`,
            }}
          />
        ))}
      </div>
      <ul className="cdc-funding-composition-list">
        {rows.map((row) => (
          <li key={row.key}>
            <span className={`cdc-funding-dot is-${row.tone}`} />
            <span>{row.label}</span>
            <strong>
              {formatPercentFromDecimalString(row.percent_of_total)}
            </strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Matrix({ rows }) {
  const byKey = new Map(rows.map((row) => [row.key, row]));
  const matrixRows = [
    { label: "Supplemental", prefix: "emergency" },
    { label: "Non-supplemental", prefix: "nonemergency" },
  ];
  return (
    <div
      className="cdc-funding-matrix"
      role="table"
      aria-label="Funding type by award type"
    >
      <div className="cdc-funding-matrix-row is-header" role="row">
        <span role="columnheader" />
        <span role="columnheader">Grants</span>
        <span role="columnheader">Contracts</span>
      </div>
      {matrixRows.map((matrixRow) => (
        <div
          className="cdc-funding-matrix-row"
          role="row"
          key={matrixRow.prefix}
        >
          <span role="rowheader">{matrixRow.label}</span>
          {["grant", "contract"].map((awardType) => {
            const row = byKey.get(`${matrixRow.prefix}_${awardType}`);
            return (
              <span role="cell" key={awardType}>
                <strong>
                  {formatCurrencyFromDecimalString(row?.obligations ?? "0.00")}
                </strong>
                <small>
                  {formatPercentFromDecimalString(
                    row?.percent_of_total ?? "0.0000",
                  )}
                </small>
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function AccountsChart({
  accounts,
  chartMode,
  chartLimit,
  chartSort,
  onModeChange,
  onLimitChange,
  onSortChange,
}) {
  const chartAccounts = useMemo(() => {
    const sorted = sortAccountsForChart(accounts, chartSort);
    return chartLimit === "top15" ? sorted.slice(0, 15) : sorted;
  }, [accounts, chartLimit, chartSort]);
  const maxTotal = useMemo(
    () =>
      chartAccounts.reduce(
        (max, account) =>
          Math.max(
            max,
            Math.abs(decimalStringToNumber(account.total_obligations)),
          ),
        0,
      ),
    [chartAccounts],
  );
  const canRenderDollarBars =
    chartMode === "dollars" &&
    maxTotal > 0 &&
    chartAccounts.every(
      (account) => compareMoneyStrings(account.total_obligations, "0.00") >= 0,
    );

  return (
    <section className="cdc-funding-section">
      <div className="cdc-funding-section-header">
        <SectionTitle
          title="Funding by Federal Account"
          subtitle="Compare federal account totals or supplemental share for the selected fiscal year."
        />
        <div className="cdc-funding-control-row">
          <label>
            <span>View</span>
            <select
              value={chartMode}
              onChange={(event) => onModeChange(event.target.value)}
            >
              <option value="dollars">Dollars</option>
              <option value="share">Supplemental share</option>
            </select>
          </label>
          <label>
            <span>Rows</span>
            <select
              value={chartLimit}
              onChange={(event) => onLimitChange(event.target.value)}
            >
              <option value="top15">Top 15</option>
              <option value="all">All</option>
            </select>
          </label>
          <label>
            <span>Sort</span>
            <select
              value={chartSort}
              onChange={(event) => onSortChange(event.target.value)}
            >
              {SORT_OPTIONS.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div
        className="cdc-funding-chart"
        role="list"
        aria-label="Federal account chart rows"
      >
        {chartAccounts.length === 0 ? (
          <p className="cdc-funding-muted">
            No federal accounts match the current search.
          </p>
        ) : (
          chartAccounts.map((account) => {
            const totalWidth = canRenderDollarBars
              ? Math.max(
                  2,
                  (decimalStringToNumber(account.total_obligations) /
                    maxTotal) *
                    100,
                )
              : 100;
            const share =
              account.emergency_share === null
                ? null
                : Math.max(0, Math.min(100, Number(account.emergency_share)));
            return (
              <div
                className="cdc-funding-chart-row"
                role="listitem"
                key={getAccountSymbol(account)}
              >
                <div className="cdc-funding-chart-label">
                  <strong title={getAccountPrimaryLabel(account)}>
                    {getAccountPrimaryLabel(account)}
                  </strong>
                  <span title={getAccountSecondaryLabel(account)}>
                    {getAccountSecondaryLabel(account)}
                  </span>
                </div>
                <div className="cdc-funding-chart-track" aria-hidden="true">
                  {chartMode === "share" ? (
                    <>
                      <span
                        className="cdc-funding-chart-emergency"
                        style={{ width: `${share ?? 0}%` }}
                      />
                      <span
                        className="cdc-funding-chart-nonemergency"
                        style={{
                          width: `${share === null ? 0 : 100 - share}%`,
                        }}
                      />
                    </>
                  ) : canRenderDollarBars ? (
                    <span
                      className="cdc-funding-chart-total"
                      style={{ width: `${totalWidth}%` }}
                    />
                  ) : (
                    <span className="cdc-funding-chart-total is-unusual" />
                  )}
                </div>
                <div className="cdc-funding-chart-value">
                  {chartMode === "share"
                    ? formatPercentFromDecimalString(account.emergency_share, 1)
                    : formatCurrencyFromDecimalString(
                        account.total_obligations,
                      )}
                </div>
              </div>
            );
          })
        )}
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
          <button
            type="button"
            className="cdc-funding-button"
            onClick={onDownload}
          >
            Download CSV
          </button>
        </div>
      </div>
      <div className="cdc-funding-table-wrap">
        <table className="cdc-funding-table">
          <caption>
            Federal funding account obligations for fiscal year {fiscalYear}
          </caption>
          <thead>
            <tr>
              <th scope="col">Details</th>
              {Object.entries(TABLE_SORT_LABELS).map(([key, label]) => (
                <th scope="col" key={key}>
                  <button type="button" onClick={() => onSort(key)}>
                    {label}
                    {sortKey === key
                      ? sortDir === "asc"
                        ? " asc"
                        : " desc"
                      : ""}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {accounts.length === 0 ? (
              <tr>
                <td colSpan={7}>
                  No federal accounts match the current search.
                </td>
              </tr>
            ) : (
              accounts.map((account) => {
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
                      <td>
                        {formatCurrencyFromDecimalString(
                          account.emergency_obligations,
                        )}
                      </td>
                      <td>
                        {formatCurrencyFromDecimalString(
                          account.nonemergency_obligations,
                        )}
                      </td>
                      <td>
                        {formatCurrencyFromDecimalString(
                          account.total_obligations,
                        )}
                      </td>
                      <td>
                        {formatPercentFromDecimalString(
                          account.emergency_share,
                          1,
                        )}
                      </td>
                    </tr>
                    {expanded ? (
                      <tr
                        className="cdc-funding-breakdown-row"
                        key={`${symbol}-details`}
                      >
                        <td colSpan={7} id={rowId}>
                          <div className="cdc-funding-breakdown-grid">
                            <span>
                              Supplemental grants{" "}
                              <strong>
                                {formatCurrencyFromDecimalString(
                                  account.breakdown?.emergency_grants,
                                )}
                              </strong>
                            </span>
                            <span>
                              Supplemental contracts{" "}
                              <strong>
                                {formatCurrencyFromDecimalString(
                                  account.breakdown?.emergency_contracts,
                                )}
                              </strong>
                            </span>
                            <span>
                              Non-supplemental grants{" "}
                              <strong>
                                {formatCurrencyFromDecimalString(
                                  account.breakdown?.nonemergency_grants,
                                )}
                              </strong>
                            </span>
                            <span>
                              Non-supplemental contracts{" "}
                              <strong>
                                {formatCurrencyFromDecimalString(
                                  account.breakdown?.nonemergency_contracts,
                                )}
                              </strong>
                            </span>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })
            )}
            {accounts.length > 0 ? (
              <tr className="cdc-funding-total-row">
                <td colSpan={3}>Current view total</td>
                <td>
                  {formatCurrencyFromDecimalString(
                    sumMoneyStrings(
                      accounts.map((account) => account.emergency_obligations),
                    ),
                  )}
                </td>
                <td>
                  {formatCurrencyFromDecimalString(
                    sumMoneyStrings(
                      accounts.map(
                        (account) => account.nonemergency_obligations,
                      ),
                    ),
                  )}
                </td>
                <td>
                  {formatCurrencyFromDecimalString(
                    sumMoneyStrings(
                      accounts.map((account) => account.total_obligations),
                    ),
                  )}
                </td>
                <td />
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function compactDollar(value) {
  const absolute = Math.abs(value);
  if (absolute >= 1e9)
    return `${value < 0 ? "-" : ""}$${(absolute / 1e9).toFixed(absolute >= 10e9 ? 0 : 1)}B`;
  if (absolute >= 1e6)
    return `${value < 0 ? "-" : ""}$${(absolute / 1e6).toFixed(absolute >= 10e6 ? 0 : 1)}M`;
  return `${value < 0 ? "-" : ""}$${Math.round(absolute).toLocaleString("en-US")}`;
}

function trendAccountLabel(account) {
  const name = String(account?.federal_account_name ?? "").trim();
  const symbol = String(account?.federal_account_symbol ?? "").trim();
  return name ? `${name} — ${symbol}` : `${symbol} — Account name unavailable`;
}

function TrendControl({ label, ariaLabel, value, options, onChange }) {
  return (
    <div className="cdc-trend-control">
      <span>{label}</span>
      <select
        aria-label={ariaLabel ?? label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option value={option.value} key={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function ObligationTrendChart({
  payload,
  selectedYear,
  onSelectYear,
  account,
  includeFy2021,
}) {
  const [activePoint, setActivePoint] = useState(null);
  const allSeries = Array.isArray(payload?.series) ? payload.series : [];
  const series = allSeries.filter(
    (item) =>
      item.fiscal_year !== 2021 || includeFy2021 || selectedYear === 2021,
  );
  const availablePoints = series.flatMap((item) =>
    (item.points ?? []).filter(
      (point) => point.available && point.cumulative_amount !== null,
    ),
  );
  if (
    availablePoints.length === 0 ||
    !series.some((item) => item.has_activity)
  ) {
    return (
      <p className="cdc-trend-empty">
        No obligation activity matches these trend filters.
      </p>
    );
  }

  // Number conversion is used only for SVG coordinates. Exact decimal strings remain authoritative.
  const plotValues = availablePoints.map((point) =>
    decimalStringToNumber(point.cumulative_amount),
  );
  const rawMin = Math.min(0, ...plotValues);
  const rawMax = Math.max(0, ...plotValues);
  const padding = Math.max((rawMax - rawMin) * 0.1, 1);
  const minValue = rawMin - (rawMin < 0 ? padding : 0);
  const maxValue = rawMax + padding;
  const width = 980;
  const height = 390;
  const left = 92;
  const right = 90;
  const top = 28;
  const bottom = 54;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const axisLabels =
    payload.period === "month"
      ? [
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
        ]
      : ["Q1", "Q2", "Q3", "Q4"];
  const xFor = (periodNumber) =>
    left +
    ((periodNumber - 1) / Math.max(1, axisLabels.length - 1)) * plotWidth;
  const yFor = (value) =>
    top + ((maxValue - value) / (maxValue - minValue || 1)) * plotHeight;
  const ticks = Array.from(
    { length: 5 },
    (_, index) => minValue + ((maxValue - minValue) * index) / 4,
  );
  const activityLabel =
    payload.period === "month"
      ? "Monthly obligations"
      : "Quarterly obligations";
  const emergencyLabel =
    {
      all: "All",
      emergency: "Supplemental",
      nonemergency: "Non-supplemental",
    }[payload.filters?.emergency_status] ?? "All";
  const awardLabel =
    {
      all: "All",
      grant: "Grants",
      contract: "Contracts",
    }[payload.filters?.award_type] ?? "All";
  const pointLabel = (fiscalYear, point, isComplete) =>
    [
      `FY${fiscalYear} ${point.source_period_label || point.period}.`,
      `${activityLabel}: ${formatCurrencyFromDecimalString(point.period_amount)}.`,
      `Fiscal year to date: ${formatCurrencyFromDecimalString(point.cumulative_amount)}.`,
      payload.view === "federal_account" && account
        ? `Federal account: ${trendAccountLabel(account)}.`
        : "",
      `Funding type: ${emergencyLabel}.`,
      `Award type: ${awardLabel}.`,
      isComplete ? "" : "Partial fiscal year.",
    ]
      .filter(Boolean)
      .join(" ");

  return (
    <>
      <div className="cdc-trend-chart-wrap">
        <svg
          className="cdc-trend-chart"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          data-y-min={minValue}
          data-y-max={maxValue}
          aria-labelledby="cdc-trend-chart-title cdc-trend-chart-description"
        >
          <title id="cdc-trend-chart-title">
            Cumulative CDC obligations by fiscal year
          </title>
          <desc id="cdc-trend-chart-description">
            Each line is a fiscal year. Use the legend or accessible data table
            to select and compare years.
          </desc>
          {ticks.map((tick) => {
            const y = yFor(tick);
            return (
              <g key={tick}>
                <line
                  x1={left}
                  x2={width - right}
                  y1={y}
                  y2={y}
                  className={
                    Math.abs(tick) < 0.001 ? "cdc-trend-zero" : "cdc-trend-grid"
                  }
                />
                <text
                  x={left - 12}
                  y={y + 4}
                  textAnchor="end"
                  className="cdc-trend-axis-label"
                >
                  {compactDollar(tick)}
                </text>
              </g>
            );
          })}
          {axisLabels.map((periodLabel, index) => (
            <text
              key={periodLabel}
              x={xFor(index + 1)}
              y={height - 18}
              textAnchor="middle"
              className="cdc-trend-axis-label"
            >
              {periodLabel}
            </text>
          ))}
          {series.map((item, seriesIndex) => {
            const styleIndex = allSeries.findIndex(
              (candidate) => candidate.fiscal_year === item.fiscal_year,
            );
            const points = (item.points ?? []).filter(
              (point) => point.available && point.cumulative_amount !== null,
            );
            const segments = points.reduce((result, point) => {
              const current = result[result.length - 1];
              const previous = current?.[current.length - 1];
              if (
                !previous ||
                point.period_number === previous.period_number + 1
              ) {
                if (current) current.push(point);
                else result.push([point]);
              } else {
                result.push([point]);
              }
              return result;
            }, []);
            const selected = Number(item.fiscal_year) === Number(selectedYear);
            const color = TREND_COLORS[styleIndex % TREND_COLORS.length];
            const lastPoint = points[points.length - 1];
            return (
              <g
                key={item.fiscal_year}
                data-testid={`trend-series-${item.fiscal_year}`}
                className={selected ? "is-selected" : ""}
              >
                {segments.map((segment, segmentIndex) => (
                  <polyline
                    key={`${item.fiscal_year}-segment-${segmentIndex}`}
                    points={segment
                      .map(
                        (point) =>
                          `${xFor(point.period_number)},${yFor(decimalStringToNumber(point.cumulative_amount))}`,
                      )
                      .join(" ")}
                    fill="none"
                    stroke={color}
                    strokeWidth={selected ? 5 : 3}
                    strokeDasharray={
                      TREND_DASHES[styleIndex % TREND_DASHES.length]
                    }
                    className="cdc-trend-line"
                    role="button"
                    tabIndex="0"
                    aria-pressed={selected}
                    aria-label={`Select FY${item.fiscal_year}${selected ? ", currently selected" : ""}`}
                    onClick={() => onSelectYear(item.fiscal_year)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelectYear(item.fiscal_year);
                      }
                    }}
                  />
                ))}
                {points.map((point, pointIndex) => {
                  const label = pointLabel(
                    item.fiscal_year,
                    point,
                    item.is_complete,
                  );
                  const x = xFor(point.period_number);
                  const y = yFor(
                    decimalStringToNumber(point.cumulative_amount),
                  );
                  return (
                    <circle
                      key={point.period}
                      cx={x}
                      cy={y}
                      r={selected ? 7 : 5}
                      fill={pointIndex % 2 === 0 ? "#ffffff" : color}
                      stroke={color}
                      strokeWidth={selected ? 4 : 3}
                      role="button"
                      tabIndex="0"
                      aria-label={`${label} Activate to select FY${item.fiscal_year}.`}
                      onMouseEnter={() => setActivePoint(label)}
                      onMouseLeave={() => setActivePoint(null)}
                      onFocus={() => setActivePoint(label)}
                      onBlur={() => setActivePoint(null)}
                      onClick={() => onSelectYear(item.fiscal_year)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onSelectYear(item.fiscal_year);
                        }
                      }}
                    />
                  );
                })}
                {lastPoint ? (
                  <text
                    x={xFor(lastPoint.period_number) + 10}
                    y={
                      yFor(decimalStringToNumber(lastPoint.cumulative_amount)) -
                      10 +
                      (seriesIndex % 3) * 9
                    }
                    fill={color}
                    className="cdc-trend-year-label"
                    role="button"
                    tabIndex="0"
                    aria-pressed={selected}
                    aria-label={`Select FY${item.fiscal_year}`}
                    onClick={() => onSelectYear(item.fiscal_year)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ")
                        onSelectYear(item.fiscal_year);
                    }}
                  >
                    FY{item.fiscal_year}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="cdc-trend-legend" aria-label="Select fiscal year">
        {series.map((item) => {
          const styleIndex = allSeries.findIndex(
            (candidate) => candidate.fiscal_year === item.fiscal_year,
          );
          return (
            <button
              type="button"
              key={item.fiscal_year}
              aria-pressed={Number(item.fiscal_year) === Number(selectedYear)}
              onClick={() => onSelectYear(item.fiscal_year)}
            >
              <span
                style={{
                  background: TREND_COLORS[styleIndex % TREND_COLORS.length],
                }}
                aria-hidden="true"
              />
              FY{item.fiscal_year}
              {item.is_complete
                ? ""
                : ` through ${item.available_through_period}`}
            </button>
          );
        })}
      </div>
      <div className="cdc-trend-tooltip" role="status" aria-live="polite">
        {activePoint ||
          "Focus or hover a point to view exact period activity and cumulative obligations."}
      </div>
      <details className="cdc-trend-data">
        <summary>View accessible chart data</summary>
        <div className="cdc-funding-table-wrap">
          <table className="cdc-funding-table">
            <caption>
              Obligation trend values for the active trend filters.
              {!includeFy2021 && selectedYear !== 2021
                ? " FY2021 is hidden from this chart and table."
                : ""}
            </caption>
            <thead>
              <tr>
                <th>Fiscal Year</th>
                <th>
                  {payload.period === "month"
                    ? "Fiscal Month"
                    : "Fiscal Quarter"}
                </th>
                <th>Available</th>
                <th>
                  {payload.period === "month"
                    ? "Monthly Obligation Activity"
                    : "Quarterly Obligation Activity"}
                </th>
                <th>Cumulative Fiscal-Year-to-Date Obligations</th>
              </tr>
            </thead>
            <tbody>
              {series.flatMap((item) =>
                (item.points ?? []).map((point) => (
                  <tr key={`${item.fiscal_year}-${point.period}`}>
                    <td>FY{item.fiscal_year}</td>
                    <td>{point.source_period_label || point.period}</td>
                    <td>{point.available ? "Available" : "Not available"}</td>
                    <td>
                      {point.available
                        ? formatCurrencyFromDecimalString(point.period_amount)
                        : "Not available"}
                    </td>
                    <td>
                      {point.available
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

function ObligationTrends({
  selectedYear,
  onSelectYear,
  trendState,
  onTrendStateChange,
}) {
  const [accounts, setAccounts] = useState([]);
  const [accountSearch, setAccountSearch] = useState("");
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [accountsError, setAccountsError] = useState("");
  const [trendPayload, setTrendPayload] = useState(null);
  const [trendLoading, setTrendLoading] = useState(true);
  const [trendError, setTrendError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setAccountsLoading(true);
    fetchCdcFundingTrendAccounts({
      apiBase: API_BASE,
      signal: controller.signal,
      scope: PAGE_SCOPE,
    })
      .then((response) => {
        if (controller.signal.aborted) return;
        validatePayloadScope(response, PAGE_SCOPE, "trend-account");
        setAccounts(Array.isArray(response?.accounts) ? response.accounts : []);
        setAccountsError("");
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setAccountsError(
            error?.message ?? "Failed to load federal account options.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setAccountsLoading(false);
      });
    return () => controller.abort();
  }, []);

  const accountIsValid =
    !trendState.account ||
    accounts.some(
      (account) => account.federal_account_symbol === trendState.account,
    );
  const needsAccount =
    trendState.view === "federal_account" && !trendState.account;
  const invalidAccount =
    trendState.view === "federal_account" &&
    trendState.account &&
    !accountsLoading &&
    !accountIsValid;
  const accountPending =
    trendState.view === "federal_account" && accountsLoading;
  const accountFailure =
    trendState.view === "federal_account" && Boolean(accountsError);

  useEffect(() => {
    if (needsAccount || invalidAccount || accountPending || accountFailure) {
      setTrendPayload(null);
      setTrendLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    setTrendLoading(true);
    setTrendError("");
    setTrendPayload(null);
    fetchCdcFundingObligationTrends({
      apiBase: API_BASE,
      signal: controller.signal,
      scope: PAGE_SCOPE,
      period: trendState.period,
      view: trendState.view,
      federalAccountSymbol:
        trendState.view === "federal_account" ? trendState.account : undefined,
      emergencyStatus: trendState.emergency,
      awardType: trendState.awardType,
    })
      .then((response) => {
        if (controller.signal.aborted) return;
        validatePayloadScope(response, PAGE_SCOPE, "obligation-trend");
        if (
          (response?.series ?? []).some(
            (item) =>
              compareMoneyStrings(
                item?.reconciliation?.difference ?? "0.00",
                "0.00",
              ) !== 0,
          )
        ) {
          throw new Error("Obligation trend data did not reconcile.");
        }
        setTrendPayload(response);
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setTrendError(error?.message ?? "Failed to load obligation trends.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setTrendLoading(false);
      });
    return () => controller.abort();
  }, [
    accountFailure,
    accountPending,
    invalidAccount,
    needsAccount,
    reloadKey,
    trendState.account,
    trendState.awardType,
    trendState.emergency,
    trendState.period,
    trendState.view,
  ]);

  const normalizedSearch = accountSearch.trim().toLowerCase();
  const filteredAccounts = normalizedSearch
    ? accounts.filter((account) =>
        trendAccountLabel(account).toLowerCase().includes(normalizedSearch),
      )
    : accounts;
  const selectedAccount = accounts.find(
    (account) => account.federal_account_symbol === trendState.account,
  );
  const setField = (field, value) =>
    onTrendStateChange({ ...trendState, [field]: value });

  return (
    <section
      className="cdc-funding-section cdc-trend-section"
      aria-labelledby="cdc-obligation-trends-heading"
    >
      <SectionTitle
        id="cdc-obligation-trends-heading"
        title="Obligation Trends"
        subtitle="Compare how CDC-awarded obligations accumulated across fiscal years."
      />
      <p className="cdc-funding-muted">
        Values are cumulative fiscal-year-to-date. Switch between monthly and
        quarterly views. Hover or focus a point to see both activity during the
        period and the cumulative amount.
      </p>
      <div className="cdc-trend-filter-label">Trend filters</div>
      <div className="cdc-trend-controls">
        <TrendControl
          label="Period"
          value={trendState.period}
          onChange={(value) => setField("period", value)}
          options={[
            { value: "month", label: "Monthly" },
            { value: "quarter", label: "Quarterly" },
          ]}
        />
        <TrendControl
          label="View"
          ariaLabel="Trend view"
          value={trendState.view}
          onChange={(value) => setField("view", value)}
          options={[
            { value: "total", label: "Total" },
            { value: "federal_account", label: "By federal account" },
          ]}
        />
        <TrendControl
          label="Funding type"
          value={trendState.emergency}
          onChange={(value) => setField("emergency", value)}
          options={[
            { value: "all", label: "All" },
            { value: "emergency", label: "Supplemental" },
            { value: "nonemergency", label: "Non-supplemental" },
          ]}
        />
        <TrendControl
          label="Award type"
          value={trendState.awardType}
          onChange={(value) => setField("awardType", value)}
          options={[
            { value: "all", label: "All" },
            { value: "grant", label: "Grants" },
            { value: "contract", label: "Contracts" },
          ]}
        />
      </div>
      <label className="cdc-trend-fy2021-control">
        <input
          type="checkbox"
          checked={trendState.includeFy2021 || selectedYear === 2021}
          disabled={selectedYear === 2021}
          onChange={(event) => setField("includeFy2021", event.target.checked)}
          aria-describedby="cdc-trend-fy2021-note"
        />
        <span>Include FY2021</span>
      </label>
      <p id="cdc-trend-fy2021-note" className="cdc-funding-muted">
        FY2021 is hidden by default because its unusually large funding total
        can compress the scale for later fiscal years. Turn on Include FY2021 to
        compare it.
      </p>
      {trendState.view === "federal_account" ? (
        <div className="cdc-trend-account-controls">
          <label>
            <span>Search federal accounts</span>
            <input
              type="search"
              value={accountSearch}
              onChange={(event) => setAccountSearch(event.target.value)}
              placeholder="Search name or symbol"
            />
          </label>
          <label>
            <span>Federal account</span>
            <select
              aria-label="Federal account"
              value={accountIsValid ? trendState.account : ""}
              onChange={(event) => setField("account", event.target.value)}
              disabled={accountsLoading}
            >
              <option value="">Select a federal account</option>
              {filteredAccounts.map((account) => (
                <option
                  value={account.federal_account_symbol}
                  key={account.federal_account_symbol}
                >
                  {trendAccountLabel(account)}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}
      {accountFailure ? (
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
      {trendLoading ? (
        <div className="cdc-trend-loading" role="status">
          Loading obligation trends…
        </div>
      ) : null}
      {trendError ? (
        <StatusPanel
          title="Obligation trends could not be loaded"
          message={trendError}
          actionLabel="Retry"
          onAction={() => setReloadKey((value) => value + 1)}
        />
      ) : null}
      {!trendLoading && trendPayload ? (
        <ObligationTrendChart
          payload={trendPayload}
          selectedYear={selectedYear}
          onSelectYear={onSelectYear}
          account={selectedAccount}
          includeFy2021={trendState.includeFy2021}
        />
      ) : null}
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
  const [chartLimit, setChartLimit] = useState("10");
  const [chartSort, setChartSort] = useState("total_desc");
  const [excludeLargestAccount, setExcludeLargestAccount] = useState(false);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("total_obligations");
  const [sortDir, setSortDir] = useState("desc");
  const [expandedAccounts, setExpandedAccounts] = useState(() => new Set());
  const [trendState, setTrendState] = useState(parseTrendStateFromUrl);
  const [activeTab, setActiveTab] = useState(parsePageTabFromUrl);
  const [accountDetail, setAccountDetail] = useState(null);

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
        const latest =
          response?.latest_fiscal_year ??
          years.find((item) => item.is_latest)?.fiscal_year ??
          years[0]?.fiscal_year ??
          null;
        setFiscalYears(years);
        setLatestYear(latest);
        const selection = resolveSelectionFromUrl(years, latest);
        const resolvedTrendState = parseTrendStateFromUrl();
        setSelectedYear(selection.selectedYear);
        setTrendState(resolvedTrendState);
        setActiveTab(parsePageTabFromUrl());
        setYearError(selection.error);
        if (selection.shouldReplace && selection.selectedYear) {
          updateFiscalYearUrl(selection.selectedYear, "replace");
        }
        if (typeof window !== "undefined") {
          const params = new URLSearchParams(window.location.search);
          if (
            params.has("trend_measure") ||
            (selection.selectedYear === 2021 &&
              params.get("trend_include_fy2021") !== "true")
          ) {
            updateTrendUrl(resolvedTrendState, "replace");
          }
        }
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (error?.status === 404) {
          setYearError(
            "CDC Funding API v1 was not found on the active backend. Restart the FastAPI server from the current branch and confirm /api/cdc-funding/v1/fiscal-years returns data.",
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
      const resolvedTrendState = parseTrendStateFromUrl();
      setSelectedYear(selection.selectedYear);
      setYearError(selection.error);
      setTrendState(resolvedTrendState);
      setActiveTab(parsePageTabFromUrl());
      setAccountDetail(null);
      setExpandedAccounts(new Set());
      if (selection.shouldReplace && selection.selectedYear) {
        updateFiscalYearUrl(selection.selectedYear, "replace");
      }
      if (
        selection.selectedYear === 2021 &&
        new URLSearchParams(window.location.search).get(
          "trend_include_fy2021",
        ) !== "true"
      ) {
        updateTrendUrl(resolvedTrendState, "replace");
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
    const previousYear = fiscalYears.some(
      (item) => item.fiscal_year === Number(selectedYear) - 1,
    )
      ? Number(selectedYear) - 1
      : null;
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
      fetchCdcFundingObligationTrends({
        apiBase: API_BASE,
        signal: controller.signal,
        scope: PAGE_SCOPE,
        period: "month",
        view: "total",
        emergencyStatus: "all",
        awardType: "all",
      }),
      previousYear
        ? fetchCdcFundingAccounts(previousYear, {
            apiBase: API_BASE,
            signal: controller.signal,
            scope: PAGE_SCOPE,
          })
        : Promise.resolve(null),
    ])
      .then(
        ([overview, accountsPayload, trendMetadata, priorAccountsPayload]) => {
          if (controller.signal.aborted) return;
          const validation = validatePayloads(
            overview,
            accountsPayload,
            selectedYear,
            PAGE_SCOPE,
          );
          if (validation.errors.length > 0) {
            throw new Error(validation.errors[0]);
          }
          validatePayloadScope(trendMetadata, PAGE_SCOPE, "obligation-trend");
          if (
            (trendMetadata?.series ?? []).some(
              (series) =>
                compareMoneyStrings(
                  series?.reconciliation?.difference ?? "0.00",
                  "0.00",
                ) !== 0,
            )
          ) {
            throw new Error(
              "The obligation trend reconciliation did not balance.",
            );
          }
          if (priorAccountsPayload) {
            validatePayloadScope(
              priorAccountsPayload,
              PAGE_SCOPE,
              "prior-year account",
            );
            if (
              Number(priorAccountsPayload.fiscal_year) !== Number(previousYear)
            ) {
              throw new Error(
                "The prior-year account response fiscal year did not match.",
              );
            }
          }
          setPayload({
            overview,
            accountsPayload,
            classificationRows: validation.classificationRows,
            accounts: validation.accounts,
            trendMetadata,
            priorAccounts: Array.isArray(priorAccountsPayload?.accounts)
              ? priorAccountsPayload.accounts
              : [],
          });
        },
      )
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
  }, [selectedYear, yearError, dataReloadKey, fiscalYears]);

  useEffect(() => {
    setSearch("");
    setExpandedAccounts(new Set());
    setSortKey("total_obligations");
    setSortDir("desc");
    setChartMode("dollars");
    setChartLimit("10");
    setChartSort("total_desc");
    setExcludeLargestAccount(false);
    setAccountDetail(null);
  }, [selectedYear]);

  const filteredAccounts = useMemo(() => {
    const normalizedSearch = search.trim().replace(/\s+/g, " ").toLowerCase();
    const accounts = payload?.accounts ?? [];
    const filtered = normalizedSearch
      ? accounts.filter((account) => {
          const searchable =
            `${getAccountName(account)} ${getAccountSymbol(account)}`
              .replace(/\s+/g, " ")
              .toLowerCase();
          return searchable.includes(normalizedSearch);
        })
      : accounts;
    return sortAccounts(filtered, sortKey, sortDir);
  }, [payload, search, sortDir, sortKey]);

  const handleYearChange = (event) => {
    const nextYear = Number(event.target.value);
    const nextTrendState = {
      ...trendState,
      comparisons: trendState.comparisons.filter(
        (comparison) => comparison !== String(nextYear),
      ),
      includeFy2021:
        nextYear === 2021 ? true : trendState.includeFy2021,
    };
    setSelectedYear(nextYear);
    setYearError("");
    updateFiscalYearUrl(nextYear, "push");
    setTrendState(nextTrendState);
    updateTrendUrl(nextTrendState, "replace");
  };

  const handleTrendYearSelect = useCallback(
    (year) => {
      if (Number(year) === Number(selectedYear)) return;
      const nextTrendState = {
        ...trendState,
        comparisons: trendState.comparisons.filter(
          (comparison) => comparison !== String(year),
        ),
        includeFy2021:
          Number(year) === 2021 ? true : trendState.includeFy2021,
      };
      setSelectedYear(Number(year));
      setYearError("");
      setExpandedAccounts(new Set());
      updateFiscalYearUrl(year, "push");
      setTrendState(nextTrendState);
      updateTrendUrl(nextTrendState, "replace");
    },
    [selectedYear, trendState],
  );

  const handleTrendStateChange = useCallback((nextState, mode = "push") => {
    setTrendState(nextState);
    updateTrendUrl(nextState, mode);
  }, []);

  const handleTabChange = useCallback((nextTab) => {
    setActiveTab(nextTab);
    setAccountDetail(null);
    updatePageTabUrl(nextTab, "push");
  }, []);

  const handleSort = useCallback((key) => {
    setSortKey((currentKey) => {
      if (currentKey !== key) {
        setSortDir(
          key === "account_name" || key === "federal_account_symbol"
            ? "asc"
            : "desc",
        );
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

  const handleDownloadCsv = (accountRows = filteredAccounts) => {
    const rows = Array.isArray(accountRows) ? accountRows : filteredAccounts;
    const csv = `${rowsToCsv(makeCsvRows(rows, selectedYear))}\r\n`;
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

  const handleOpenAccountDetails = (account, trigger) => {
    setAccountDetail({ account, trigger });
  };

  const handleCloseAccountDetails = useCallback(() => {
    setAccountDetail(null);
  }, []);

  const handleAnalyzeAccount = (account) => {
    const nextTrendState = {
      ...trendState,
      view: "federal_account",
      account: getAccountSymbol(account),
    };
    setTrendState(nextTrendState);
    setAccountDetail(null);
    setActiveTab("trends");
    updateTrendUrl(nextTrendState, "push");
    updatePageTabUrl("trends", "replace");
  };

  const handleAccountSortSelection = (key, direction) => {
    setSortKey(key);
    setSortDir(direction);
  };

  const classificationRows = payload?.classificationRows ?? [];
  const hasEmptyYears = !yearsLoading && fiscalYears.length === 0 && !yearError;
  const showingData = selectedYear && payload && !dataLoading && !dataError;

  return (
    <div className="cdc-funding-page">
      <Header />
      <main className="cdc-funding-main">
        <CdcFundingHeader />
        <a href="/cdc-funding/map">National map</a>

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
            <CdcFundingTabs activeTab={activeTab} onChange={handleTabChange} />
            {activeTab === "overview" ? (
              <FundingOverviewTab
                accounts={payload.accounts}
                classificationRows={classificationRows}
                excludeLargest={excludeLargestAccount}
                fiscalYear={selectedYear}
                onExcludeLargest={setExcludeLargestAccount}
                onLimitChange={setChartLimit}
                onModeChange={setChartMode}
                onViewAll={() => handleTabChange("accounts")}
                overview={payload.overview}
                priorAccounts={payload.priorAccounts}
                rankingLimit={chartLimit}
                rankingMode={chartMode}
                trendMetadata={payload.trendMetadata}
                fiscalYears={fiscalYears}
                onYearChange={handleYearChange}
                onDownload={() => handleDownloadCsv(payload?.accounts ?? [])}
              />
            ) : null}
            {activeTab === "trends" ? (
              <FocusedObligationTrends
                selectedYear={selectedYear}
                onSelectYear={handleTrendYearSelect}
                trendState={trendState}
                onTrendStateChange={handleTrendStateChange}
              />
            ) : null}
            {activeTab === "accounts" ? (
              <AccountDetailsTab
                accounts={filteredAccounts}
                fiscalYear={selectedYear}
                onAnalyzeAccount={handleAnalyzeAccount}
                onCloseDetails={handleCloseAccountDetails}
                onDownload={() => handleDownloadCsv(filteredAccounts)}
                onDownloadAccount={(account) => handleDownloadCsv([account])}
                onOpenDetails={handleOpenAccountDetails}
                onSearch={setSearch}
                onSort={handleAccountSortSelection}
                search={search}
                selectedAccount={accountDetail?.account ?? null}
                selectedAccountTrigger={accountDetail?.trigger ?? null}
                sortDir={sortDir}
                sortKey={sortKey}
                fiscalYears={fiscalYears}
                onYearChange={handleYearChange}
              />
            ) : null}
            <CdcFundingMethodology />
          </>
        ) : null}
      </main>
      <Footer />
    </div>
  );
}
