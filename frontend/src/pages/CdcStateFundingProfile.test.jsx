import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CdcStateFundingProfile from "./CdcStateFundingProfile";

vi.mock("../components/Header", () => ({
  default: function HeaderMock() {
    return <div data-testid="header-mock">Header</div>;
  },
}));

vi.mock("../api/cdcFunding", () => ({
  fetchCdcFundingProfileSummary: vi.fn(),
  fetchCdcFundingProfileCategories: vi.fn(),
  fetchCdcFundingProfileSubcategories: vi.fn(),
}));

const {
  fetchCdcFundingProfileSummary,
  fetchCdcFundingProfileCategories,
  fetchCdcFundingProfileSubcategories,
} = await import("../api/cdcFunding");

function pushProfileUrl() {
  window.history.pushState(
    {},
    "",
    "/cdc-funding/state/AL?fiscal_year=2025&metric=funding_per_capita&funding_type=emergency_response&cdc_center=public_health_preparedness_and_response&mechanism=cooperative_agreements&recipient_type=state_governments&time_aggregation=single_fiscal_year"
  );
}

function buildSummaryPayload() {
  return {
    state_code: "AL",
    state_name: "Alabama",
    fiscal_year: 2025,
    timeframe_label: "FY2025",
    legend_title: "FY2025 CDC Funding Per Capita",
    total_funding: 1234567,
    selected_metric: "funding_per_capita",
    selected_metric_label: "CDC Funding Per Capita",
    selected_metric_value: 245.72,
    award_count: 12,
    contract_award_count: 1,
    population: 5024279,
    funding_per_capita: 245.72,
    grouping: {
      category_method: "TAGGS effective CDC program-area enrichment by ALN/CFDA number, with CDC center-name fallback when no TAGGS match is available.",
      subcategory_method: "TAGGS effective program-name enrichment by ALN/CFDA number, with USAspending program-title fallback when no TAGGS match is available.",
    },
    filter_context: {
      funding_type_label: "Emergency Response Funding",
      cdc_center_label: "Public Health Preparedness and Response",
      mechanism_label: "Cooperative Agreements",
      recipient_type_label: "State Governments",
      time_aggregation_label: "Single Fiscal Year",
      legend_title: "FY2025 CDC Funding Per Capita",
    },
    methodology_notes: [
      "State profile totals use the same CHIP funding filter model as the map.",
    ],
  };
}

function buildCategoryPayload() {
  return {
    rows: [
      {
        category: "Public Health Preparedness and Response",
        category_value: "public_health_preparedness_and_response",
        amount: 900000,
        share_pct: 72.9,
        award_count: 7,
        subcategory_count: 3,
      },
    ],
  };
}

function buildSubcategoryPayload() {
  return {
    rows: [
      {
        category: "Public Health Preparedness and Response",
        category_value: "public_health_preparedness_and_response",
        subcategory: "Public Health Emergency Preparedness",
        amount: 500000,
        share_total_pct: 40.5,
        share_category_pct: 55.6,
        award_count: 4,
      },
    ],
  };
}

describe("CdcStateFundingProfile", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    pushProfileUrl();
    fetchCdcFundingProfileSummary.mockResolvedValue(buildSummaryPayload());
    fetchCdcFundingProfileCategories.mockResolvedValue(buildCategoryPayload());
    fetchCdcFundingProfileSubcategories.mockResolvedValue(buildSubcategoryPayload());
  });

  it("renders the unified CHIP funding profile content", async () => {
    render(<CdcStateFundingProfile stateCode="AL" />);

    expect(await screen.findByText("CDC State Funding Profile")).toBeInTheDocument();
    expect(screen.getByText("Alabama")).toBeInTheDocument();
    expect(screen.getByTestId("cdc-profile-mode-badge")).toHaveTextContent("CHIP funding model");
    expect(screen.getAllByText("$1,234,567.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Public Health Preparedness and Response").length).toBeGreaterThan(0);
    expect(screen.getByText("Public Health Emergency Preparedness")).toBeInTheDocument();
    expect(screen.getByText(/USAspending supplies award, subaward, and contract transactions/i)).toBeInTheDocument();
  });

  it("requests the profile APIs with the new filter contract", async () => {
    render(<CdcStateFundingProfile stateCode="AL" />);

    await waitFor(() => {
      expect(fetchCdcFundingProfileSummary).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          fiscal_year: 2025,
          metric: "funding_per_capita",
          funding_type: "emergency_response",
          cdc_center: "public_health_preparedness_and_response",
          mechanism: "cooperative_agreements",
          recipient_type: "state_governments",
          time_aggregation: "single_fiscal_year",
        })
      );
    });

    await waitFor(() => {
      expect(fetchCdcFundingProfileCategories).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          fiscal_year: 2025,
          funding_type: "emergency_response",
        })
      );
    });

    await waitFor(() => {
      expect(fetchCdcFundingProfileSubcategories).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          fiscal_year: 2025,
          funding_type: "emergency_response",
        })
      );
    });
  });
});
