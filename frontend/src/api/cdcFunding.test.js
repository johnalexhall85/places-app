import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchCdcFundingMethodologySummary } from "./cdcFunding";

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
});
