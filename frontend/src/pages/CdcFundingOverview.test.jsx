import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CdcFundingOverview from "./CdcFundingOverview";

vi.mock("../components/Header", () => ({
  default: () => <div data-testid="header-mock">Header</div>,
}));

vi.mock("../components/Footer", () => ({
  default: () => <div data-testid="footer-mock">Footer</div>,
}));

vi.mock("../api/cdcFundingOverview", () => ({
  CDC_FUNDING_SCOPE_ALL_ACCOUNTS: "all_accounts",
  fetchCdcFundingAccounts: vi.fn(),
  fetchCdcFundingCategories: vi.fn(),
  fetchCdcFundingFiscalYears: vi.fn(),
  fetchCdcFundingObligationTrends: vi.fn(),
  fetchCdcFundingOverview: vi.fn(),
  fetchCdcFundingQuarterlyTrends: vi.fn(),
  fetchCdcFundingTrendAccounts: vi.fn(),
}));

const {
  CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
  fetchCdcFundingAccounts,
  fetchCdcFundingCategories,
  fetchCdcFundingFiscalYears,
  fetchCdcFundingObligationTrends,
  fetchCdcFundingOverview,
  fetchCdcFundingQuarterlyTrends,
  fetchCdcFundingTrendAccounts,
} = await import("../api/cdcFundingOverview");

function fiscalYearsPayload() {
  return {
    scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    fiscal_years: [2026, 2025, 2024, 2023, 2022, 2021].map((fiscalYear) => ({
      fiscal_year: fiscalYear,
      is_latest: fiscalYear === 2026,
    })),
    latest_fiscal_year: 2026,
  };
}

function overviewPayload(year = 2026) {
  return {
    scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    fiscal_year: year,
    total_obligations: "1000.00",
    classifications: [
      {
        emergency_status: "emergency",
        award_type: "grant",
        label: "Emergency Grants",
        obligations: "200.00",
        percent_of_total: "20.0000",
      },
      {
        emergency_status: "emergency",
        award_type: "contract",
        label: "Emergency Contracts",
        obligations: "100.00",
        percent_of_total: "10.0000",
      },
      {
        emergency_status: "nonemergency",
        award_type: "grant",
        label: "Nonemergency Grants",
        obligations: "300.00",
        percent_of_total: "30.0000",
      },
      {
        emergency_status: "nonemergency",
        award_type: "contract",
        label: "Nonemergency Contracts",
        obligations: "400.00",
        percent_of_total: "40.0000",
      },
    ],
    totals: {
      emergency: "300.00",
      nonemergency: "700.00",
      grants: "500.00",
      contracts: "500.00",
    },
    reconciliation: { classification_sum: "1000.00", difference: "0.00" },
  };
}

function accountsPayload(year = 2026, overrides = {}) {
  return {
    scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    fiscal_year: year,
    total_accounts: 3,
    accounts: [
      {
        federal_account_name: "Alpha Prevention Account",
        federal_account_symbol: "075-2000",
        total_obligations: "600.00",
        emergency_obligations: "300.00",
        nonemergency_obligations: "300.00",
        emergency_share: "50.0000",
        breakdown: {
          emergency_grants: "200.00",
          emergency_contracts: "100.00",
          nonemergency_grants: "100.00",
          nonemergency_contracts: "200.00",
        },
      },
      {
        federal_account_name: 'Beta, "Quoted" Account',
        federal_account_symbol: "075-3000",
        total_obligations: "400.00",
        emergency_obligations: "0.00",
        nonemergency_obligations: "400.00",
        emergency_share: "0.0000",
        breakdown: {
          emergency_grants: "0.00",
          emergency_contracts: "0.00",
          nonemergency_grants: "200.00",
          nonemergency_contracts: "200.00",
        },
      },
      {
        federal_account_name: null,
        federal_account_symbol: "075-UNMAPPED",
        total_obligations: "0.00",
        emergency_obligations: "0.00",
        nonemergency_obligations: "0.00",
        emergency_share: null,
        breakdown: {
          emergency_grants: "0.00",
          emergency_contracts: "0.00",
          nonemergency_grants: "0.00",
          nonemergency_contracts: "0.00",
        },
      },
    ],
    reconciliation: {
      account_total: "1000.00",
      overview_total: "1000.00",
      difference: "0.00",
    },
    ...overrides,
  };
}

function trendPayload(overrides = {}) {
  const period = overrides.period ?? "month";
  const labels =
    period === "month"
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
  return {
    scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    measure: overrides.measure ?? "obligations",
    period,
    view: overrides.view ?? "total",
    calculation: "cumulative_fiscal_year_to_date",
    filters: overrides.filters ?? {
      federal_account_symbol: null,
      emergency_status: "all",
      award_type: "all",
      exclude_deobligations: false,
    },
    available_fiscal_years: [2021, 2022, 2023, 2024, 2025, 2026],
    series: [2021, 2022, 2023, 2024, 2025, 2026].map((year) => {
      const partial = year === 2026;
      const scale = year === 2021 ? 100 : 1;
      const availableCount = partial
        ? period === "month"
          ? 6
          : 2
        : labels.length;
      return {
        fiscal_year: year,
        available_through_period: labels[availableCount - 1],
        available_through_month:
          period === "month" ? labels[availableCount - 1] : undefined,
        available_through_quarter: partial ? "Q2" : "Q4",
        is_complete: !partial,
        has_activity: true,
        points: labels.map((label, index) => {
          const available =
            (period !== "month" || index !== 0) && index < availableCount;
          const baseAmount = (100 + index) * scale;
          const periodAmount = overrides.excludeDeobligations
            ? baseAmount + 40
            : baseAmount;
          return {
            period: label,
            period_type: period,
            period_number: index + 1,
            available,
            period_amount: available ? `${periodAmount}.00` : null,
            cumulative_amount: available
              ? `${
                  overrides.excludeDeobligations
                    ? (100 + 40) * (index + 1) * scale
                    : 100 * (index + 1) * scale
                }.00`
              : null,
            source_period_label:
              period === "month" && index === 1
                ? "October-November (combined P01/P02 submission)"
                : undefined,
          };
        }),
        reconciliation: {
          latest_available_cumulative: `${100 * availableCount * scale}.00`,
          annual_or_current_ytd_total: `${100 * availableCount * scale}.00`,
          difference: "0.00",
        },
      };
    }),
  };
}

function negativeOverviewPayload(year = 2026) {
  return {
    ...overviewPayload(year),
    total_obligations: "600.00",
    classifications: [
      {
        emergency_status: "emergency",
        award_type: "grant",
        label: "Emergency Grants",
        obligations: "-200.00",
        percent_of_total: null,
      },
      {
        emergency_status: "emergency",
        award_type: "contract",
        label: "Emergency Contracts",
        obligations: "100.00",
        percent_of_total: null,
      },
      {
        emergency_status: "nonemergency",
        award_type: "grant",
        label: "Nonemergency Grants",
        obligations: "300.00",
        percent_of_total: null,
      },
      {
        emergency_status: "nonemergency",
        award_type: "contract",
        label: "Nonemergency Contracts",
        obligations: "400.00",
        percent_of_total: null,
      },
    ],
    totals: {
      emergency: "-100.00",
      nonemergency: "700.00",
      grants: "100.00",
      contracts: "500.00",
    },
    reconciliation: { classification_sum: "600.00", difference: "0.00" },
  };
}

function negativeAccountsPayload(year = 2026) {
  return accountsPayload(year, {
    total_accounts: 2,
    accounts: [
      {
        federal_account_name: "Adjustment Account",
        federal_account_symbol: "075-9000",
        total_obligations: "-100.00",
        emergency_obligations: "-100.00",
        nonemergency_obligations: "0.00",
        emergency_share: null,
        breakdown: {
          emergency_grants: "-200.00",
          emergency_contracts: "100.00",
          nonemergency_grants: "0.00",
          nonemergency_contracts: "0.00",
        },
      },
      {
        federal_account_name: "Ongoing Programs Account",
        federal_account_symbol: "075-9001",
        total_obligations: "700.00",
        emergency_obligations: "0.00",
        nonemergency_obligations: "700.00",
        emergency_share: "0.0000",
        breakdown: {
          emergency_grants: "0.00",
          emergency_contracts: "0.00",
          nonemergency_grants: "300.00",
          nonemergency_contracts: "400.00",
        },
      },
    ],
    reconciliation: {
      account_total: "600.00",
      overview_total: "600.00",
      difference: "0.00",
    },
  });
}

function mockHappyApi() {
  fetchCdcFundingFiscalYears.mockResolvedValue(fiscalYearsPayload());
  fetchCdcFundingOverview.mockImplementation((year) =>
    Promise.resolve(overviewPayload(year)),
  );
  fetchCdcFundingAccounts.mockImplementation((year) =>
    Promise.resolve(accountsPayload(year)),
  );
  fetchCdcFundingObligationTrends.mockImplementation((options) =>
    Promise.resolve(
      trendPayload({
        measure: options?.measure ?? "obligations",
        period: options?.period ?? "month",
        view: options?.view ?? "total",
        filters: {
          federal_account_symbol: options?.federalAccountSymbol ?? null,
          emergency_status: options?.emergencyStatus ?? "all",
          award_type: options?.awardType ?? "all",
          exclude_deobligations: Boolean(options?.excludeDeobligations),
        },
        excludeDeobligations: Boolean(options?.excludeDeobligations),
      }),
    ),
  );
  fetchCdcFundingTrendAccounts.mockResolvedValue({
    scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    accounts: [
      {
        federal_account_symbol: "075-2000",
        federal_account_name: "Alpha Prevention Account",
        first_fiscal_year: 2021,
        last_fiscal_year: 2026,
      },
      {
        federal_account_symbol: "075-UNMAPPED",
        federal_account_name: null,
        first_fiscal_year: 2022,
        last_fiscal_year: 2025,
      },
    ],
  });
}

function readBlobText(blob) {
  if (typeof blob?.text === "function") return blob.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result ?? "")));
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsText(blob);
  });
}

async function renderOverview() {
  render(<CdcFundingOverview />);
  await screen.findByRole("tab", { name: "Annual Funding" });
  await openTab("Annual Funding");
  await screen.findByRole("heading", { name: "Executive summary" });
}

async function openTab(name) {
  fireEvent.click(screen.getByRole("tab", { name }));
  await waitFor(() =>
    expect(screen.getByRole("tab", { name })).toHaveAttribute(
      "aria-selected",
      "true",
    ),
  );
}

describe("CdcFundingOverview redesign", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.pushState({}, "", "/cdc-funding");
    mockHappyApi();
  });

  it("opens Trends by default with permanent filters, chart data, and all FY2022-present years", async () => {
    render(<CdcFundingOverview />);

    expect(await screen.findByRole("heading", { name: "Funding trends" })).toBeVisible();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Trends",
      "Annual Funding",
      "Account Details",
    ]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByLabelText("Fiscal year")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Filters/ })).toBeVisible();
    await screen.findByTestId("trend-series-2026");
    expect(screen.getByRole("heading", { name: "Chart data" })).toBeVisible();
    expect(document.querySelector(".cdc-filter-panel").tagName).toBe("SECTION");
    expect(document.querySelector(".cdc-trend-data").tagName).toBe("SECTION");
    [2022, 2023, 2024, 2025, 2026].forEach((year) =>
      expect(screen.getByTestId(`trend-series-${year}`)).toBeVisible(),
    );
    expect(screen.queryByTestId("trend-series-2021")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /FY2025 · Sep/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: /FY2026 · Sep/ })).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: /Fiscal years shown 5 fiscal years selected/,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(screen.queryByTestId("trend-series-2026")).not.toBeInTheDocument();
    expect(screen.getByText("No funding activity matches these trend filters.")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Chart data" })).toBeVisible();
  });

  it("switches to stored outlays and disables obligation-only deobligation filtering", async () => {
    render(<CdcFundingOverview />);
    await screen.findByTestId("trend-series-2026");

    fireEvent.change(screen.getByLabelText("Funding measure"), {
      target: { value: "outlays" },
    });

    await waitFor(() =>
      expect(fetchCdcFundingObligationTrends).toHaveBeenLastCalledWith(
        expect.objectContaining({ measure: "outlays", excludeDeobligations: false }),
      ),
    );
    expect(screen.getByLabelText("Exclude deobligations")).toBeDisabled();
    expect(screen.getByText("Deobligation filtering applies to obligations only.")).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "Monthly outlay activity" })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "Cumulative fiscal-year-to-date outlays" })).toBeVisible();
    expect(window.location.search).toContain("trend_funding_measure=outlays");
  });

  it("keeps the legacy overview tab URL mapped to Annual Funding", async () => {
    window.history.pushState({}, "", "/cdc-funding?tab=overview&fiscal_year=2025");
    render(<CdcFundingOverview />);

    expect(await screen.findByRole("heading", { name: "Executive summary" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Annual Funding" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Fiscal year")).toHaveValue("2025");
  });

  it("loads the latest YTD overview with compact values and exact-value access", async () => {
    await renderOverview();

    expect(screen.getByRole("heading", { name: "CDC Funding" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Annual Funding" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText(/FY2026 through Mar/)).toBeVisible();
    expect(screen.getByText("$1K")).toHaveAttribute("title", "$1,000.00");
    expect(screen.getByText(/same point/)).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Funding composition" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Top federal funding accounts" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("link", { name: "Methodology" }));
    expect(screen.getByText(/Monthly trends show the funding activity/)).toBeVisible();
    expect(screen.getByText(/July 18, 2026.*July 10, 2026/)).toBeVisible();
    expect(window.location.search).toContain("fiscal_year=2026");
    expect(fetchCdcFundingAccounts).toHaveBeenCalledWith(
      2025,
      expect.objectContaining({ scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS }),
    );
    expect(fetchCdcFundingCategories).not.toHaveBeenCalled();
  });

  it("labels a complete fiscal year and shows valid annual comparisons", async () => {
    window.history.pushState({}, "", "/cdc-funding?fiscal_year=2025");
    await renderOverview();

    expect(screen.getByText(/FY2025 · all federal accounts/)).toBeVisible();
    expect(screen.queryByText(/FY2025 through/)).not.toBeInTheDocument();
    expect(screen.getByText("Unchanged from FY2024")).toBeVisible();
    expect(
      screen.getByRole("columnheader", { name: "Year-over-year" }),
    ).toBeVisible();
  });

  it("uses accessible keyboard tabs and stores the selected tab in the URL", async () => {
    await renderOverview();
    const overviewTab = screen.getByRole("tab", { name: "Annual Funding" });

    fireEvent.keyDown(overviewTab, { key: "ArrowLeft" });
    expect(
      await screen.findByRole("heading", { name: "Funding trends" }),
    ).toBeVisible();
    expect(screen.getByRole("tab", { name: "Trends" })).toHaveFocus();
    expect(window.location.search).not.toContain("tab=");

    fireEvent.keyDown(screen.getByRole("tab", { name: "Trends" }), {
      key: "End",
    });
    expect(
      await screen.findByRole("heading", { name: "Federal account details" }),
    ).toBeVisible();
    expect(screen.getByRole("tab", { name: "Account Details" })).toHaveFocus();
  });

  it("restores fiscal-year and tab state and responds to browser navigation", async () => {
    window.history.pushState(
      {},
      "",
      "/cdc-funding?fiscal_year=2023&tab=accounts",
    );
    render(<CdcFundingOverview />);

    expect(
      await screen.findByRole("heading", { name: "Federal account details" }),
    ).toBeVisible();
    expect(screen.getByLabelText("Fiscal year")).toHaveValue("2023");

    window.history.pushState(
      {},
      "",
      "/cdc-funding?fiscal_year=2025&tab=trends",
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Trends" })).toHaveAttribute("aria-selected", "true"),
    );
    expect(screen.queryByLabelText("Fiscal year")).not.toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Funding trends" }),
    ).toBeVisible();
  });

  it("updates annual data without losing the selected workspace", async () => {
    await renderOverview();
    await openTab("Account Details");

    fireEvent.change(screen.getByLabelText("Fiscal year"), {
      target: { value: "2023" },
    });

    await waitFor(() =>
      expect(fetchCdcFundingOverview).toHaveBeenCalledWith(
        2023,
        expect.objectContaining({ scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS }),
      ),
    );
    expect(
      screen.getByRole("tab", { name: "Account Details" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(window.location.search).toContain("fiscal_year=2023");
  });

  it("handles zero annual totals without percentages or misleading comparisons", async () => {
    fetchCdcFundingOverview.mockImplementation((year) =>
      Promise.resolve({
        ...overviewPayload(year),
        total_obligations: "0.00",
        classifications: overviewPayload(year).classifications.map((row) => ({
          ...row,
          obligations: "0.00",
          percent_of_total: null,
        })),
        totals: {
          emergency: "0.00",
          nonemergency: "0.00",
          grants: "0.00",
          contracts: "0.00",
        },
        reconciliation: { classification_sum: "0.00", difference: "0.00" },
      }),
    );
    fetchCdcFundingAccounts.mockImplementation((year) =>
      Promise.resolve(
        accountsPayload(year, {
          total_accounts: 1,
          accounts: [accountsPayload(year).accounts[2]],
          reconciliation: {
            account_total: "0.00",
            overview_total: "0.00",
            difference: "0.00",
          },
        }),
      ),
    );
    fetchCdcFundingObligationTrends.mockImplementation(() => {
      const payload = trendPayload();
      payload.series
        .filter((series) => [2025, 2026].includes(series.fiscal_year))
        .forEach((series) => {
          series.points.forEach((point) => {
            if (!point.available) return;
            point.period_amount = "0.00";
            point.cumulative_amount = "0.00";
          });
          series.reconciliation.latest_available_cumulative = "0.00";
          series.reconciliation.annual_or_current_ytd_total = "0.00";
        });
      return Promise.resolve(payload);
    });

    await renderOverview();

    expect(screen.getAllByTitle("$0.00").length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        /Percentages are omitted because zero or negative net values/,
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("option", { name: "Share of total" }),
    ).toBeDisabled();
    expect(screen.queryByText(/from FY2025/)).not.toBeInTheDocument();
  });

  it("renders the supplemental adjustment callout and a zero-centered chart", async () => {
    fetchCdcFundingOverview.mockImplementation((year) =>
      Promise.resolve(negativeOverviewPayload(year)),
    );
    fetchCdcFundingAccounts.mockImplementation((year) =>
      Promise.resolve(negativeAccountsPayload(year)),
    );

    await renderOverview();

    expect(
      screen.getByRole("heading", {
        name: /Supplemental adjustments reduced net obligations by \$200/,
      }),
    ).toBeVisible();
    expect(
      screen.getByText(/They may include deobligations, corrections/),
    ).toBeVisible();
    expect(
      screen.getByRole("img", {
        name: "Diverging funding classification chart centered on zero",
      }),
    ).toBeVisible();
    expect(
      screen.getByText(
        /Percentages are omitted because zero or negative net values/,
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("option", { name: "Share of total" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByText("View classification details"));
    expect(
      screen.getByRole("table", {
        name: "Funding type by award type",
      }),
    ).toBeVisible();
  });

  it("supports account ranking controls and links to all accounts", async () => {
    await renderOverview();

    fireEvent.change(screen.getByLabelText("Account metric"), {
      target: { value: "share" },
    });
    expect(screen.getAllByText("60.0%").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByLabelText("Exclude largest account"));
    expect(
      screen.queryByText("Alpha Prevention Account"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View all accounts" }));
    expect(
      await screen.findByRole("heading", { name: "Federal account details" }),
    ).toBeVisible();
    expect(window.location.search).toContain("tab=accounts");
  });

  it("uses concise account names while preserving the official title", async () => {
    const officialName =
      "Alpha Prevention Account, Centers for Disease Control and Prevention, Health and Human Services";
    fetchCdcFundingAccounts.mockImplementation((year) => {
      const payload = accountsPayload(year);
      payload.accounts[0].federal_account_name = officialName;
      return Promise.resolve(payload);
    });
    await renderOverview();

    expect(screen.getByText("Alpha Prevention Account")).toHaveAttribute(
      "title",
      officialName,
    );
    fireEvent.click(screen.getByRole("button", { name: "View all accounts" }));
    fireEvent.click(screen.getAllByRole("button", { name: "View details" })[0]);
    expect(
      await screen.findByRole("dialog", { name: "Alpha Prevention Account" }),
    ).toBeVisible();
    expect(screen.getAllByText(officialName).length).toBeGreaterThan(0);
  });

  it("shows FY2022 through the latest fiscal year by default", async () => {
    await renderOverview();
    await openTab("Trends");

    expect(await screen.findByTestId("trend-series-2026")).toBeVisible();
    expect(screen.getByTestId("trend-series-2025")).toBeVisible();
    expect(screen.getByTestId("trend-series-2024")).toBeVisible();
    expect(screen.getByTestId("trend-series-2023")).toBeVisible();
    expect(screen.getByTestId("trend-series-2022")).toBeVisible();
    expect(screen.queryByTestId("trend-series-2021")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Reporting period")).toHaveValue("month");
    expect(screen.getByLabelText("Funding measure")).toHaveValue("obligations");
    expect(screen.getByLabelText("Trend display")).toHaveValue("cumulative");
    expect(
      screen.getByRole("button", {
        name: /Fiscal years shown 5 fiscal years selected/,
      }),
    ).toBeVisible();
    expect(
      screen.getByRole("region", {
        name: "Scrollable obligation trend chart",
      }),
    ).toHaveAttribute("tabindex", "0");
  });

  it("removes one visible year and preserves exact always-visible chart data", async () => {
    await renderOverview();
    await openTab("Trends");
    await screen.findByTestId("trend-series-2026");

    fireEvent.click(
      screen.getByRole("button", { name: /Fiscal years shown/ }),
    );
    fireEvent.click(screen.getByLabelText("FY2025"));
    expect(screen.queryByTestId("trend-series-2025")).not.toBeInTheDocument();
    expect(window.location.search).toContain("trend_years=2022%2C2023%2C2024%2C2026");

    const table = screen.getByRole("table", {
      name: /Cumulative obligation values for the selected fiscal years/,
    });
    expect(table).toBeVisible();
    expect(table).toHaveTextContent("October-November");
    expect(table).toHaveTextContent("$200.00");
    expect(table).toHaveTextContent("Not available");
  });

  it("supports arbitrary visible years and keeps FY2021 rules consistent", async () => {
    await renderOverview();
    await openTab("Trends");
    await screen.findByTestId("trend-series-2026");

    fireEvent.click(
      screen.getByRole("button", { name: /Fiscal years shown/ }),
    );
    expect(screen.queryByLabelText("FY2021")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("FY2024"));

    expect(screen.getByTestId("trend-series-2025")).toBeVisible();
    expect(screen.queryByTestId("trend-series-2024")).not.toBeInTheDocument();
    expect(window.location.search).toContain("trend_years=");

    fireEvent.click(screen.getByLabelText("Include FY2021"));
    expect(screen.getByTestId("trend-series-2021")).toBeVisible();

    fireEvent.click(screen.getByLabelText("Include FY2021"));
    expect(screen.queryByTestId("trend-series-2021")).not.toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get("trend_years")).not.toContain("2021");
  });

  it("excludes deobligations across the request, narrative, table, chip, and clear filters", async () => {
    await renderOverview();
    await openTab("Trends");
    await screen.findByTestId("trend-series-2026");

    const checkbox = screen.getByLabelText("Exclude deobligations");
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);

    await waitFor(() =>
      expect(fetchCdcFundingObligationTrends).toHaveBeenLastCalledWith(
        expect.objectContaining({ excludeDeobligations: true }),
      ),
    );
    expect(window.location.search).toContain(
      "trend_exclude_deobligations=true",
    );
    expect(screen.getByText(/excluding deobligations/)).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: /Deobligations excluded.*Remove filter/,
      }),
    ).toBeVisible();

    expect(
      screen.getByRole("table", {
        name: /Cumulative obligation values/,
      }),
    ).toHaveTextContent("$280.00");

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByLabelText("Exclude deobligations")).not.toBeChecked();
    expect(window.location.search).not.toContain(
      "trend_exclude_deobligations",
    );
    await waitFor(() =>
      expect(fetchCdcFundingObligationTrends).toHaveBeenLastCalledWith(
        expect.objectContaining({ excludeDeobligations: false }),
      ),
    );
  });

  it("highlights and cycles overlapping chart series without another request", async () => {
    await renderOverview();
    await openTab("Trends");
    await screen.findByTestId("trend-series-2026");
    const calls = fetchCdcFundingObligationTrends.mock.calls.length;
    const marchPoint = screen.getByRole("button", {
      name: /FY2026 · Mar.*Activate to highlight FY2026/,
    });
    const chart = screen.getByRole("img", {
      name: /Cumulative CDC obligations by fiscal year/,
    });
    chart.getBoundingClientRect = () => ({
      left: 0,
      top: 0,
      width: 980,
      height: 400,
      right: 980,
      bottom: 400,
      x: 0,
      y: 0,
      toJSON: () => {},
    });
    fireEvent.click(document.querySelector(".cdc-chart-hit-target"), {
      clientX: Number(marchPoint.getAttribute("cx")),
      clientY: Number(marchPoint.getAttribute("cy")),
    });
    expect(screen.getByTestId("trend-series-2026")).toHaveAttribute(
      "data-highlighted",
      "true",
    );
    fireEvent.keyDown(
      screen.getByRole("region", {
        name: "Scrollable obligation trend chart",
      }),
      { key: "Escape" },
    );

    fireEvent.click(marchPoint);
    expect(screen.getByTestId("trend-series-2026")).toHaveAttribute(
      "data-highlighted",
      "true",
    );
    expect(screen.getByText(/5 overlapping series at Mar/)).toBeInTheDocument();

    fireEvent.click(marchPoint);
    expect(screen.getByTestId("trend-series-2025")).toHaveAttribute(
      "data-highlighted",
      "true",
    );
    expect(fetchCdcFundingObligationTrends).toHaveBeenCalledTimes(calls);

    fireEvent.keyDown(
      screen.getByRole("region", {
        name: "Scrollable obligation trend chart",
      }),
      { key: "Escape" },
    );
    expect(screen.getByTestId("trend-series-2025")).toHaveAttribute(
      "data-highlighted",
      "false",
    );

    expect(fetchCdcFundingObligationTrends).toHaveBeenCalledTimes(calls);
  });

  it("uses negative bars and a zero baseline for mixed period activity", async () => {
    fetchCdcFundingObligationTrends.mockImplementation((options) => {
      const payload = trendPayload({ period: options?.period ?? "month" });
      const selected = payload.series.find(
        (series) => series.fiscal_year === 2026,
      );
      selected.points[1].period_amount = "-50.00";
      return Promise.resolve(payload);
    });
    await renderOverview();
    await openTab("Trends");
    await screen.findByTestId("trend-series-2026");

    fireEvent.change(screen.getByLabelText("Trend display"), {
      target: { value: "activity" },
    });

    expect(screen.getByRole("button", { name: /Monthly obligation activity: -\$50.00/ })).toBeVisible();
    expect(document.querySelector(".cdc-trend-zero")).toBeInTheDocument();
  });

  it("switches trend period and display while preserving annual data", async () => {
    await renderOverview();
    await openTab("Trends");
    await screen.findByTestId("trend-series-2026");
    const annualCalls = fetchCdcFundingOverview.mock.calls.length;
    const beforeDisplay = fetchCdcFundingObligationTrends.mock.calls.length;

    fireEvent.change(screen.getByLabelText("Trend display"), {
      target: { value: "activity" },
    });
    expect(
      screen.getByRole("img", {
        name: /^CDC obligation activity by reporting period/,
      }),
    ).toHaveAttribute("data-display", "activity");
    expect(fetchCdcFundingObligationTrends).toHaveBeenCalledTimes(
      beforeDisplay,
    );

    fireEvent.change(screen.getByLabelText("Reporting period"), {
      target: { value: "quarter" },
    });
    await waitFor(() =>
      expect(fetchCdcFundingObligationTrends).toHaveBeenLastCalledWith(
        expect.objectContaining({ period: "quarter" }),
      ),
    );
    expect(screen.getAllByText("Q4").length).toBeGreaterThan(0);
    expect(fetchCdcFundingOverview).toHaveBeenCalledTimes(annualCalls);
    expect(window.location.search).toContain("trend_period=quarter");
  });

  it("adds FY2021 as chart context without refetching trend data", async () => {
    await renderOverview();
    await openTab("Trends");
    await screen.findByTestId("trend-series-2026");
    const calls = fetchCdcFundingObligationTrends.mock.calls.length;

    fireEvent.click(screen.getByLabelText("Include FY2021"));

    expect(await screen.findByTestId("trend-series-2021")).toBeVisible();
    expect(fetchCdcFundingObligationTrends).toHaveBeenCalledTimes(calls);
    expect(window.location.search).toContain("trend_include_fy2021=true");
  });

  it("applies advanced filters, exposes removable chips, and preserves URL state", async () => {
    await renderOverview();
    await openTab("Trends");
    await screen.findByTestId("trend-series-2026");

    fireEvent.change(screen.getByLabelText("Funding type"), {
      target: { value: "nonemergency" },
    });
    fireEvent.change(screen.getByLabelText("Award type"), {
      target: { value: "grant" },
    });
    fireEvent.change(screen.getByLabelText("Federal account"), {
      target: { value: "075-2000" },
    });

    await waitFor(() =>
      expect(fetchCdcFundingObligationTrends).toHaveBeenLastCalledWith(
        expect.objectContaining({
          view: "federal_account",
          federalAccountSymbol: "075-2000",
          emergencyStatus: "nonemergency",
          awardType: "grant",
        }),
      ),
    );
    expect(screen.getByLabelText("Active trend filters")).toBeVisible();
    expect(window.location.search).toContain("trend_account=075-2000");
    fireEvent.click(
      screen.getByRole("button", { name: /Non-supplemental.*Remove filter/ }),
    );
    expect(window.location.search).toContain("trend_emergency=all");
  });

  it("opens legacy trend deep links, restores new state, and removes the legacy measure", async () => {
    window.history.pushState(
      {},
      "",
      "/cdc-funding?fiscal_year=2025&trend_period=quarter&trend_display=activity&trend_compare=none&trend_measure=outlays&trend_include_fy2021=true",
    );
    render(<CdcFundingOverview />);

    expect(await screen.findByTestId("trend-series-2021")).toBeVisible();
    expect(screen.getByLabelText("Reporting period")).toHaveValue("quarter");
    expect(screen.getByLabelText("Trend display")).toHaveValue("activity");
    expect(
      screen.getByRole("button", {
        name: /Fiscal years shown FY2021, FY2025|Fiscal years shown 2 fiscal years selected/,
      }),
    ).toBeVisible();
    expect(screen.queryByTestId("trend-series-2024")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(window.location.search).not.toContain("trend_measure"),
    );
    expect(fetchCdcFundingQuarterlyTrends).not.toHaveBeenCalled();
  });

  it("searches accounts, exports only filtered rows, and escapes CSV values", async () => {
    let capturedBlob = null;
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    URL.createObjectURL = vi.fn((blob) => {
      capturedBlob = blob;
      return "blob:cdc-funding";
    });
    URL.revokeObjectURL = vi.fn();
    await renderOverview();
    await openTab("Account Details");

    fireEvent.change(screen.getByLabelText("Sort accounts"), {
      target: { value: "account_name:asc" },
    });
    const accountTable = screen.getByRole("table", {
      name: "Federal funding account obligations for fiscal year 2026",
    });
    expect(accountTable.querySelector("tbody tr")).toHaveTextContent(
      "075-UNMAPPED",
    );

    fireEvent.change(screen.getByLabelText("Account search"), {
      target: { value: "beta" },
    });
    expect(
      screen.getAllByText('Beta, "Quoted" Account').length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByText("Alpha Prevention Account"),
    ).not.toBeInTheDocument();

    const downloadButtons = screen.getAllByRole("button", {
      name: "Download CSV",
    });
    fireEvent.click(downloadButtons[downloadButtons.length - 1]);
    expect(clickSpy).toHaveBeenCalled();
    const csv = await readBlobText(capturedBlob);
    expect(csv).toContain(
      '2026,"Beta, ""Quoted"" Account",075-3000,0.00,0.00,0.00,200.00,200.00,400.00,400.00,0.0000',
    );
    expect(csv).not.toContain("075-2000");
  });

  it("opens a focus-managed detail drawer and returns focus on Escape", async () => {
    await renderOverview();
    await openTab("Account Details");
    const trigger = screen.getAllByRole("button", { name: "View details" })[0];

    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", {
      name: "Alpha Prevention Account",
    });
    expect(dialog).toBeVisible();
    expect(screen.getByLabelText("Close account details")).toHaveFocus();
    expect(screen.getByText("Treasury account symbol")).toHaveTextContent(
      "075-2000",
    );
    expect(
      await screen.findByRole("img", {
        name: "FY2026 monthly cumulative obligations for Alpha Prevention Account",
      }),
    ).toBeVisible();
    fireEvent.click(screen.getByText("View exact monthly account data"));
    expect(
      screen.getByRole("table", {
        name: "FY2026 monthly account activity and cumulative obligations",
      }),
    ).toBeVisible();
    expect(fetchCdcFundingObligationTrends).toHaveBeenLastCalledWith(
      expect.objectContaining({
        period: "month",
        view: "federal_account",
        federalAccountSymbol: "075-2000",
      }),
    );
    expect(
      screen.getByRole("button", { name: "Download this account" }),
    ).toBeVisible();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("opens account-specific trend analysis from the detail drawer", async () => {
    await renderOverview();
    await openTab("Account Details");
    fireEvent.click(screen.getAllByRole("button", { name: "View details" })[0]);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Analyze this account in Trends",
      }),
    );

    expect(
      await screen.findByRole("heading", { name: "Funding trends" }),
    ).toBeVisible();
    expect(window.location.search).not.toContain("tab=");
    expect(window.location.search).toContain("trend_view=federal_account");
    expect(window.location.search).toContain("trend_account=075-2000");
    await waitFor(() =>
      expect(fetchCdcFundingObligationTrends).toHaveBeenLastCalledWith(
        expect.objectContaining({
          view: "federal_account",
          federalAccountSymbol: "075-2000",
        }),
      ),
    );
  });

  it("shows explicit unavailable-year and reconciliation errors", async () => {
    window.history.pushState({}, "", "/cdc-funding?fiscal_year=1999");
    const { unmount } = render(<CdcFundingOverview />);
    expect(
      await screen.findByText(
        "CDC funding data are not available for fiscal year 1999.",
      ),
    ).toBeVisible();
    expect(fetchCdcFundingOverview).not.toHaveBeenCalled();
    unmount();

    window.history.pushState({}, "", "/cdc-funding");
    mockHappyApi();
    fetchCdcFundingAccounts.mockImplementation((year) =>
      Promise.resolve(
        accountsPayload(year, {
          reconciliation: {
            account_total: "999.00",
            overview_total: "1000.00",
            difference: "1.00",
          },
        }),
      ),
    );
    render(<CdcFundingOverview />);
    expect(
      await screen.findByText("The account reconciliation did not balance."),
    ).toBeVisible();
  });

  it("explains an unavailable backend API without falling back", async () => {
    fetchCdcFundingFiscalYears.mockRejectedValue(
      Object.assign(new Error("Not Found"), { status: 404 }),
    );
    render(<CdcFundingOverview />);

    expect(
      await screen.findByText(
        /CDC Funding API v1 was not found on the active backend/,
      ),
    ).toBeVisible();
    expect(fetchCdcFundingOverview).not.toHaveBeenCalled();
  });
});
