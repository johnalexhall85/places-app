import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CdcFundingOverview from "./CdcFundingOverview";

vi.mock("../components/Header", () => ({
  default: function HeaderMock() {
    return <div data-testid="header-mock">Header</div>;
  },
}));

vi.mock("../components/Footer", () => ({
  default: function FooterMock() {
    return <div data-testid="footer-mock">Footer</div>;
  },
}));

vi.mock("../api/cdcFundingOverview", () => ({
  CDC_FUNDING_SCOPE_ALL_ACCOUNTS: "all_accounts",
  fetchCdcFundingAccounts: vi.fn(),
  fetchCdcFundingCategories: vi.fn(),
  fetchCdcFundingFiscalYears: vi.fn(),
  fetchCdcFundingOverview: vi.fn(),
}));

const {
  CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
  fetchCdcFundingAccounts,
  fetchCdcFundingCategories,
  fetchCdcFundingFiscalYears,
  fetchCdcFundingOverview,
} = await import("../api/cdcFundingOverview");

function fiscalYearsPayload() {
  return {
    scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    fiscal_years: [
      { fiscal_year: 2026, is_latest: true },
      { fiscal_year: 2025, is_latest: false },
      { fiscal_year: 2024, is_latest: false },
      { fiscal_year: 2023, is_latest: false },
      { fiscal_year: 2022, is_latest: false },
      { fiscal_year: 2021, is_latest: false },
    ],
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
    reconciliation: {
      classification_sum: "1000.00",
      difference: "0.00",
    },
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

function mockHappyApi() {
  fetchCdcFundingFiscalYears.mockResolvedValue(fiscalYearsPayload());
  fetchCdcFundingOverview.mockImplementation((year) => Promise.resolve(overviewPayload(year)));
  fetchCdcFundingAccounts.mockImplementation((year) => Promise.resolve(accountsPayload(year)));
  fetchCdcFundingCategories.mockImplementation(() => {
    throw new Error("The page should not call category data.");
  });
}

function readBlobText(blob) {
  if (typeof blob?.text === "function") {
    return blob.text();
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result ?? "")));
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsText(blob);
  });
}

describe("CdcFundingOverview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.pushState({}, "", "/cdc-funding");
    mockHappyApi();
  });

  it("defaults to the latest fiscal year from the API and replaces the URL", async () => {
    render(<CdcFundingOverview />);

    expect(await screen.findByRole("heading", { name: "FY2026 Overview" })).toBeInTheDocument();
    expect(window.location.search).toBe("?fiscal_year=2026");
    expect(fetchCdcFundingFiscalYears).toHaveBeenCalledWith(expect.objectContaining({
      scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    }));
    expect(fetchCdcFundingOverview).toHaveBeenCalledWith(2026, expect.objectContaining({
      scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    }));
    expect(fetchCdcFundingAccounts).toHaveBeenCalledWith(2026, expect.objectContaining({
      scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    }));
    expect(fetchCdcFundingCategories).not.toHaveBeenCalled();
    expect(screen.getAllByText("$1,000.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Emergency Grants").length).toBeGreaterThan(0);
    expect(screen.getByText("This page includes all federal accounts in the ingested CDC-awarded funding dataset.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Funding by Federal Account" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Federal Funding Account Details" })).toBeInTheDocument();
    expect(screen.getAllByText("Alpha Prevention Account").length).toBeGreaterThan(0);
    expect(screen.getAllByText("075-2000").length).toBeGreaterThan(0);
    expect(screen.getAllByText("075-UNMAPPED").length).toBeGreaterThan(0);
    expect(screen.queryByText("Alpha Prevention Category")).not.toBeInTheDocument();
  });

  it("respects an explicit FY2023 query parameter", async () => {
    window.history.pushState({}, "", "/cdc-funding?fiscal_year=2023");

    render(<CdcFundingOverview />);

    expect(await screen.findByRole("heading", { name: "FY2023 Overview" })).toBeInTheDocument();
    expect(window.location.search).toBe("?fiscal_year=2023");
    expect(fetchCdcFundingOverview).toHaveBeenCalledWith(2023, expect.objectContaining({
      scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    }));
  });

  it("updates the URL and data when the fiscal-year selector changes", async () => {
    render(<CdcFundingOverview />);
    await screen.findByRole("heading", { name: "FY2026 Overview" });

    fireEvent.change(screen.getByLabelText("Fiscal year"), { target: { value: "2023" } });

    expect(await screen.findByRole("heading", { name: "FY2023 Overview" })).toBeInTheDocument();
    expect(window.location.search).toBe("?fiscal_year=2023");
    expect(fetchCdcFundingAccounts).toHaveBeenCalledWith(2023, expect.objectContaining({
      scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
    }));
    expect(fetchCdcFundingCategories).not.toHaveBeenCalled();
  });

  it("responds to browser popstate changes", async () => {
    render(<CdcFundingOverview />);
    await screen.findByRole("heading", { name: "FY2026 Overview" });

    window.history.pushState({}, "", "/cdc-funding?fiscal_year=2023");
    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(await screen.findByRole("heading", { name: "FY2023 Overview" })).toBeInTheDocument();
  });

  it("shows a fiscal-year error without falling back when a requested year is unavailable", async () => {
    window.history.pushState({}, "", "/cdc-funding?fiscal_year=1999");

    render(<CdcFundingOverview />);

    expect(await screen.findByText("CDC funding data are not available for fiscal year 1999.")).toBeInTheDocument();
    expect(fetchCdcFundingOverview).not.toHaveBeenCalled();
    expect(fetchCdcFundingAccounts).not.toHaveBeenCalled();
  });

  it("supports account search, symbol search, expansion, chart toggles, and CSV export for filtered accounts", async () => {
    let capturedDownload = "";
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function handleClick() {
      capturedDownload = this.download;
    });
    let capturedBlob = null;
    URL.createObjectURL = vi.fn((blob) => {
      capturedBlob = blob;
      return "blob:cdc-funding";
    });
    URL.revokeObjectURL = vi.fn();

    render(<CdcFundingOverview />);
    await screen.findByRole("heading", { name: "FY2026 Overview" });

    fireEvent.change(screen.getByLabelText("Account search"), { target: { value: "beta" } });
    expect(screen.getAllByText('Beta, "Quoted" Account').length).toBeGreaterThan(0);
    expect(screen.getAllByText("075-3000").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("Alpha Prevention Account")).toHaveLength(0);

    fireEvent.change(screen.getByLabelText("Account search"), { target: { value: "075-2000" } });
    expect(screen.getAllByText("Alpha Prevention Account").length).toBeGreaterThan(0);
    expect(screen.getAllByText("075-2000").length).toBeGreaterThan(0);
    expect(screen.queryAllByText('Beta, "Quoted" Account')).toHaveLength(0);

    fireEvent.change(screen.getByLabelText("Account search"), { target: { value: "beta" } });

    fireEvent.change(screen.getByLabelText("View"), { target: { value: "share" } });
    expect(screen.getAllByText("0.0%").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByText("Nonemergency contracts")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Download CSV" }));
    expect(clickSpy).toHaveBeenCalled();
    expect(capturedDownload).toBe("cdc-funding-accounts-fy2026.csv");
    const csv = await readBlobText(capturedBlob);
    expect(csv).toContain("Fiscal Year,Federal Account Name,Federal Account Symbol,Emergency Grants");
    expect(csv).toContain('2026,"Beta, ""Quoted"" Account",075-3000,0.00,0.00,0.00,200.00,200.00,400.00,400.00,0.0000');
    expect(csv).not.toContain("075-2000");
    expect(csv).not.toContain("Alpha Prevention Account");
  });

  it("shows a page-level data error when reconciliation fails", async () => {
    fetchCdcFundingAccounts.mockImplementation((year) => Promise.resolve(accountsPayload(year, {
      reconciliation: {
        account_total: "999.00",
        overview_total: "1000.00",
        difference: "1.00",
      },
    })));

    render(<CdcFundingOverview />);

    expect(await screen.findByText("The account reconciliation did not balance.")).toBeInTheDocument();
  });

  it("rejects overview responses that do not use the all-account scope", async () => {
    fetchCdcFundingOverview.mockImplementation((year) => Promise.resolve({
      ...overviewPayload(year),
      scope: "cdc_funding_profiles",
    }));

    render(<CdcFundingOverview />);

    expect(await screen.findByText("The CDC funding overview response did not use the requested all-account scope."))
      .toBeInTheDocument();
  });

  it("rejects account responses that do not use the all-account scope", async () => {
    fetchCdcFundingAccounts.mockImplementation((year) => Promise.resolve({
      ...accountsPayload(year),
      scope: "cdc_funding_profiles",
    }));

    render(<CdcFundingOverview />);

    expect(await screen.findByText("The CDC funding account response did not use the requested all-account scope."))
      .toBeInTheDocument();
  });

  it("rejects fiscal-year responses that do not use the all-account scope", async () => {
    fetchCdcFundingFiscalYears.mockResolvedValue({
      ...fiscalYearsPayload(),
      scope: "cdc_funding_profiles",
    });

    render(<CdcFundingOverview />);

    expect(await screen.findByText(/fiscal-year response did not use the requested all-account scope/))
      .toBeInTheDocument();
    expect(fetchCdcFundingOverview).not.toHaveBeenCalled();
    expect(fetchCdcFundingAccounts).not.toHaveBeenCalled();
  });

  it("shows an empty fiscal-years state", async () => {
    fetchCdcFundingFiscalYears.mockResolvedValue({
      scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
      fiscal_years: [],
      latest_fiscal_year: null,
    });

    render(<CdcFundingOverview />);

    expect(await screen.findByText("No fiscal years available")).toBeInTheDocument();
  });

  it("explains when the active backend does not expose CDC Funding API v1", async () => {
    fetchCdcFundingFiscalYears.mockRejectedValue(Object.assign(new Error("Not Found"), { status: 404 }));

    render(<CdcFundingOverview />);

    expect(await screen.findByText(/CDC Funding API v1 was not found on the active backend/)).toBeInTheDocument();
  });
});
