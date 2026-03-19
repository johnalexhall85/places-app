import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchCdcFundingMap,
  fetchCdcFundingMethodologySummary,
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

  it("builds the new CDC funding map query without normalize", async () => {
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
      expect(url).toContain("cdc_center=public_health_preparedness_and_response");
      expect(url).toContain("geography_level=state");
      expect(url).not.toContain("normalize=");
      expect(url).not.toContain("basis=");
      expect(url).not.toContain("display_mode=");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("builds the new CDC funding profile summary query without normalize", async () => {
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
        cdc_center: "all",
        mechanism: "grants",
      });

      const url = String(fetchMock.mock.calls[0][0]);
      expect(url).toContain("/api/cdc/funding/profile/summary?");
      expect(url).toContain("state=AL");
      expect(url).toContain("fiscal_year=2025");
      expect(url).toContain("metric=total_funding");
      expect(url).toContain("funding_type=total_cdc_funding");
      expect(url).toContain("mechanism=grants");
      expect(url).not.toContain("normalize=");
      expect(url).not.toContain("basis=");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
