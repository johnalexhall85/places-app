import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchCdcFundingFilters,
  fetchCdcFundingMap,
  fetchCdcFundingMethodologySummary,
  fetchCdcFundingProfileDetails,
  fetchCdcFundingProfileOverview,
  fetchCdcFundingProfileSummary,
} from "./cdcFunding";

describe("fetchCdcFundingMethodologySummary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requests the methodology summary endpoint", async () => {
    const payload = { current_frozen_version: "profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics_calibration_v1" };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(payload),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock;

    try {
      const result = await fetchCdcFundingMethodologySummary({
        apiBase: "https://example.test",
      });

      expect(result).toEqual(payload);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(String(fetchMock.mock.calls[0][0])).toBe(
        "https://example.test/api/cdc/funding/methodology/summary"
      );
      expect(fetchMock.mock.calls[0][1]).toEqual({ signal: undefined });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("builds the CDC funding map query with explicit funding_mode", async () => {
    const payload = { type: "FeatureCollection", features: [] };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(payload),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock;

    try {
      await fetchCdcFundingMap({
        apiBase: "https://example.test",
        fiscal_year: 2025,
        metric: "funding_per_capita",
        funding_type: "emergency_response",
        funding_mode: "raw_total",
        cdc_center: "public_health_preparedness_and_response",
        mechanism: "cooperative_agreements",
        recipient_type: "state_governments",
        geography_level: "state",
        time_aggregation: "single_fiscal_year",
      });

      const url = String(fetchMock.mock.calls[0][0]);
      expect(url).toContain("/api/cdc/funding/map?");
      expect(url).toContain("fiscal_year=2025");
      expect(url).toContain("metric=funding_per_capita");
      expect(url).toContain("funding_type=emergency_response");
      expect(url).toContain("funding_mode=raw_total");
      expect(url).toContain("cdc_center=public_health_preparedness_and_response");
      expect(url).toContain("geography_level=state");
      expect(url).not.toContain("normalize=");
      expect(url).not.toContain("basis=");
      expect(url).not.toContain("display_mode=");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("preserves published custom funding mode options from the filters response", async () => {
    const payload = {
      funding_mode_options: [
        { value: "chip_normalized_v1_1", label: "CHIP Normalized Funding v1.1" },
        { value: "chip_v1_1_emergency", label: "CHIP v1.1 Emergency Classification" },
      ],
      default_funding_mode: "chip_normalized_v1_1",
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(payload),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock;

    try {
      const result = await fetchCdcFundingFilters({
        apiBase: "https://example.test",
      });

      expect(result.funding_mode_options[1]).toEqual({
        value: "chip_v1_1_emergency",
        label: "CHIP v1.1 Emergency Classification",
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("defaults the CDC funding map geography to state", async () => {
    const payload = { type: "FeatureCollection", features: [] };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(payload),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock;

    try {
      await fetchCdcFundingMap({
        apiBase: "https://example.test",
      });

      const url = String(fetchMock.mock.calls[0][0]);
      expect(url).toContain("geography_level=state");
      expect(url).toContain("funding_mode=chip_normalized_v1_1");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("builds the CDC funding profile summary query with explicit funding_mode", async () => {
    const payload = { state_code: "AL" };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(payload),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock;

    try {
      await fetchCdcFundingProfileSummary({
        apiBase: "https://example.test",
        state: "AL",
        fiscal_year: 2025,
        metric: "total_funding",
        funding_type: "total_cdc_funding",
        funding_mode: "chip_normalized",
        cdc_center: "all",
        mechanism: "grants",
      });

      const url = String(fetchMock.mock.calls[0][0]);
      expect(url).toContain("/api/cdc/funding/profile/summary?");
      expect(url).toContain("state=AL");
      expect(url).toContain("fiscal_year=2025");
      expect(url).toContain("metric=total_funding");
      expect(url).toContain("funding_type=total_cdc_funding");
      expect(url).toContain("funding_mode=chip_normalized");
      expect(url).toContain("mechanism=grants");
      expect(url).not.toContain("normalize=");
      expect(url).not.toContain("basis=");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("builds the CDC funding profile overview query with fiscal year and funding mode", async () => {
    const payload = { summary: {}, categories: {}, subcategories: {} };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(payload),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock;

    try {
      await fetchCdcFundingProfileOverview({
        apiBase: "https://example.test",
        state: "AL",
        fiscal_year: 2024,
        metric: "funding_per_capita",
        funding_type: "emergency_response",
        funding_mode: "chip_normalized",
        mechanism: "cooperative_agreements",
      });

      const url = String(fetchMock.mock.calls[0][0]);
      expect(url).toContain("/api/cdc/funding/profile/overview?");
      expect(url).toContain("state=AL");
      expect(url).toContain("fiscal_year=2024");
      expect(url).toContain("metric=funding_per_capita");
      expect(url).toContain("funding_type=emergency_response");
      expect(url).toContain("funding_mode=chip_normalized");
      expect(url).toContain("mechanism=cooperative_agreements");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("falls back to the legacy profile endpoints when overview is not available", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        text: vi.fn().mockResolvedValue('{"detail":"Not Found"}'),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({ state_code: "AL" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({ rows: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({ rows: [] }),
      });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock;

    try {
      const result = await fetchCdcFundingProfileOverview({
        apiBase: "https://example.test",
        state: "AL",
        fiscal_year: 2025,
        metric: "funding_per_capita",
        funding_type: "emergency_response",
        funding_mode: "chip_normalized",
      });

      expect(result).toEqual({
        summary: { state_code: "AL" },
        categories: { rows: [] },
        subcategories: { rows: [] },
      });
      expect(fetchMock).toHaveBeenCalledTimes(4);
      expect(String(fetchMock.mock.calls[0][0])).toContain("/api/cdc/funding/profile/overview?");
      expect(String(fetchMock.mock.calls[1][0])).toContain("/api/cdc/funding/profile/summary?");
      expect(String(fetchMock.mock.calls[2][0])).toContain("/api/cdc/funding/profile/categories?");
      expect(String(fetchMock.mock.calls[3][0])).toContain("/api/cdc/funding/profile/subcategories?");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("builds the CDC funding profile details query with pagination and sorting", async () => {
    const payload = { rows: [], total_rows: 0 };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(payload),
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock;

    try {
      await fetchCdcFundingProfileDetails({
        apiBase: "https://example.test",
        state: "AL",
        fiscal_year: 2025,
        funding_mode: "raw_total",
        page: 2,
        page_size: 50,
        sort_by: "category",
        sort_dir: "asc",
        q: "preparedness",
      });

      const url = String(fetchMock.mock.calls[0][0]);
      expect(url).toContain("/api/cdc/funding/profile/details?");
      expect(url).toContain("state=AL");
      expect(url).toContain("fiscal_year=2025");
      expect(url).toContain("funding_mode=raw_total");
      expect(url).toContain("page=2");
      expect(url).toContain("page_size=50");
      expect(url).toContain("sort_by=category");
      expect(url).toContain("sort_dir=asc");
      expect(url).toContain("q=preparedness");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
