import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
  CDC_FUNDING_PROFILE_SCOPE,
  fetchCdcFundingAccounts,
  fetchCdcFundingCategories,
  fetchCdcFundingFiscalYears,
  fetchCdcFundingObligationTrends,
  fetchCdcFundingOverview,
  fetchCdcFundingQuarterlyTrends,
  fetchCdcFundingTrendAccounts,
} from "./cdcFundingOverview";

describe("cdcFundingOverview API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requests all-account overview page endpoints with explicit scope", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ ok: true }),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock;

    try {
      await fetchCdcFundingFiscalYears({
        apiBase: "https://example.test/api",
        scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
      });
      await fetchCdcFundingOverview(2026, {
        apiBase: "https://example.test/api",
        scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
      });
      await fetchCdcFundingAccounts(2026, {
        apiBase: "https://example.test/api",
        scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
      });

      const urls = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(urls).toEqual([
        "https://example.test/api/cdc-funding/v1/fiscal-years?scope=all_accounts",
        "https://example.test/api/cdc-funding/v1/overview?fiscal_year=2026&scope=all_accounts",
        "https://example.test/api/cdc-funding/v1/accounts?fiscal_year=2026&scope=all_accounts",
      ]);
      urls.forEach((url) => {
        expect(url).not.toContain("/api/cdc/funding/map");
        expect(url).not.toContain("/funding/");
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("still supports the mapped categories helper", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ ok: true }),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock;

    try {
      await fetchCdcFundingCategories(2026, {
        apiBase: "https://example.test/api",
        scope: CDC_FUNDING_PROFILE_SCOPE,
      });

      expect(String(fetchMock.mock.calls[0][0])).toBe(
        "https://example.test/api/cdc-funding/v1/categories?fiscal_year=2026&scope=cdc_funding_profiles",
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("serializes funding measure and trend filters with cross-year account options", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ ok: true }),
    });

    try {
      await fetchCdcFundingObligationTrends({
        apiBase: "https://example.test/api",
        scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
        period: "month",
        view: "federal_account",
        federalAccountSymbol: "075-0943",
        emergencyStatus: "emergency",
        awardType: "grant",
        measure: "outlays",
      });
      await fetchCdcFundingTrendAccounts({
        apiBase: "https://example.test/api",
        scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
      });

      expect(String(globalThis.fetch.mock.calls[0][0])).toBe(
        "https://example.test/api/cdc-funding/v1/obligation-trends" +
          "?scope=all_accounts&period=month&view=federal_account" +
          "&federal_account_symbol=075-0943&emergency_status=emergency&award_type=grant" +
          "&measure=outlays",
      );
      expect(String(globalThis.fetch.mock.calls[1][0])).toBe(
        "https://example.test/api/cdc-funding/v1/quarterly-trends/accounts?scope=all_accounts",
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("keeps the legacy quarterly trend client available for compatibility", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ ok: true }),
    });

    try {
      await fetchCdcFundingQuarterlyTrends({
        apiBase: "https://example.test/api",
        scope: CDC_FUNDING_SCOPE_ALL_ACCOUNTS,
        measure: "outlays",
      });

      expect(String(globalThis.fetch.mock.calls[0][0])).toBe(
        "https://example.test/api/cdc-funding/v1/quarterly-trends?scope=all_accounts&measure=outlays",
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("preserves unscoped all-account API requests by default", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ ok: true }),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock;

    try {
      await fetchCdcFundingFiscalYears({ apiBase: "https://example.test/api" });
      await fetchCdcFundingOverview(2026, {
        apiBase: "https://example.test/api",
      });
      await fetchCdcFundingAccounts(2026, {
        apiBase: "https://example.test/api",
      });
      await fetchCdcFundingCategories(2026, {
        apiBase: "https://example.test/api",
      });

      const urls = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(urls).toEqual([
        "https://example.test/api/cdc-funding/v1/fiscal-years",
        "https://example.test/api/cdc-funding/v1/overview?fiscal_year=2026",
        "https://example.test/api/cdc-funding/v1/accounts?fiscal_year=2026",
        "https://example.test/api/cdc-funding/v1/categories?fiscal_year=2026",
      ]);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("surfaces API detail messages", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      text: vi.fn().mockResolvedValue(
        JSON.stringify({
          detail: {
            message: "CDC funding data are not available for fiscal year 1999.",
          },
        }),
      ),
    });

    try {
      await expect(
        fetchCdcFundingOverview(1999, { apiBase: "https://example.test" }),
      ).rejects.toThrow(
        "CDC funding data are not available for fiscal year 1999.",
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("attaches HTTP status to fetch errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      text: vi.fn().mockResolvedValue("Not Found"),
    });

    try {
      await expect(
        fetchCdcFundingFiscalYears({ apiBase: "https://example.test" }),
      ).rejects.toMatchObject({ status: 404, message: "Not Found" });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
