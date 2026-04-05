import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import CdcFundingMethodologyControl from "./CdcFundingMethodologyControl";

const SUMMARY_PAYLOAD = {
  current_frozen_version: "profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics_calibration_v1",
  verified_account_count: 29,
  fallback_account_count: 0,
  total_single_account_rows: 89660,
  total_multi_account_same_scope_rows: 31683,
  total_multi_account_mixed_scope_rows: 118806,
  conservative_mixed_account_handling_explanation:
    "When a public source row mixes multiple federal accounts and does not provide an exact account-level split, CHIP leaves the raw dollars unchanged but avoids crediting the full row to core CDC public health funding.",
  why_fy2021_differs:
    "FY2021 contains unusually large mixed_program_transfer assistance awards, especially in immunization and ELC, where core CDC accounts appear alongside federal transfer accounts without a defensible public split.",
  top_fy2021_review_families: [
    {
      award_family: "immunization",
      row_count: 1149,
      raw_amount: "8937365937.69",
      residual_contribution_estimate: "8780142556.03",
    },
    {
      award_family: "ELC",
      row_count: 2050,
      raw_amount: "29693207832.51",
      residual_contribution_estimate: "701652501.00",
    },
  ],
  manual_review_exceptions_applied_in_production: false,
  manual_review_exceptions_production_note:
    "Manual-review candidates are surfaced for analyst review only. No exception rows are applied to frozen production normalization outputs in this version.",
  review_overlay_summary: {
    candidate_recommendation_count: 2,
    production_change_recommended: false,
  },
};

function createDeferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("CdcFundingMethodologyControl", () => {
  it("shows a loading state and then renders the methodology summary with zero fallback handling", async () => {
    const deferred = createDeferred();
    const fetchSummary = vi.fn().mockImplementation(() => deferred.promise);

    render(
      <CdcFundingMethodologyControl
        apiBase="https://example.test"
        fetchSummary={fetchSummary}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Methodology" }));

    expect(screen.getByText("Loading methodology summary...")).toBeInTheDocument();
    expect(fetchSummary).toHaveBeenCalledTimes(1);
    expect(fetchSummary).toHaveBeenCalledWith(
      expect.objectContaining({
        apiBase: "https://example.test",
        signal: expect.any(AbortSignal),
      })
    );

    deferred.resolve(SUMMARY_PAYLOAD);

    const dialog = await screen.findByRole("dialog", { name: "Methodology" });
    expect(within(dialog).getByText("profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics_calibration_v1")).toBeInTheDocument();
    expect(within(dialog).getByText("29 verified accounts")).toBeInTheDocument();
    expect(within(dialog).getByText("No fallback accounts")).toBeInTheDocument();
    expect(within(dialog).getByText("89,660")).toBeInTheDocument();
    expect(within(dialog).getByText("118,806")).toBeInTheDocument();
  });

  it("shows only public-facing FY2021 details and hides analyst-only review fields", async () => {
    const fetchSummary = vi.fn().mockResolvedValue(SUMMARY_PAYLOAD);

    render(<CdcFundingMethodologyControl fetchSummary={fetchSummary} />);

    fireEvent.click(screen.getByRole("button", { name: "Methodology" }));

    const dialog = await screen.findByRole("dialog", { name: "Methodology" });
    expect(within(dialog).getByText("Immunization")).toBeInTheDocument();
    expect(within(dialog).getByText("ELC")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Manual review exceptions are not applied in production for this frozen public version.")
    ).toBeInTheDocument();
    expect(within(dialog).queryByText(/candidate/i)).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/manual_review_only/i)).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/production_change_recommended/i)).not.toBeInTheDocument();
  });

  it("shows an error state when the methodology summary request fails", async () => {
    const fetchSummary = vi.fn().mockRejectedValue(new Error("503 unavailable"));

    render(<CdcFundingMethodologyControl fetchSummary={fetchSummary} />);

    fireEvent.click(screen.getByRole("button", { name: "Methodology" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Unable to load the methodology summary right now.");
    expect(alert).toHaveTextContent("503 unavailable");
  });
});
