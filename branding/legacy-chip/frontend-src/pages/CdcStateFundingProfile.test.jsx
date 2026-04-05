import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CdcStateFundingProfile from "./CdcStateFundingProfile";

vi.mock("../components/Header", () => ({
  default: function HeaderMock() {
    return <div data-testid="header-mock">Header</div>;
  },
}));

vi.mock("../api/cdcFunding", () => ({
  fetchCdcFundingProfileDetails: vi.fn(),
  fetchCdcFundingProfileOverview: vi.fn(),
}));

const {
  fetchCdcFundingProfileDetails,
  fetchCdcFundingProfileOverview,
} = await import("../api/cdcFunding");

function pushProfileUrl() {
  window.history.pushState(
    {},
    "",
    "/cdc-funding/state/AL?fiscal_year=2025&metric=funding_per_capita&funding_type=emergency_response&funding_mode=chip_normalized&cdc_center=public_health_preparedness_and_response&mechanism=cooperative_agreements&recipient_type=state_governments&time_aggregation=single_fiscal_year"
  );
}

function pushShortProfileUrl() {
  window.history.pushState(
    {},
    "",
    "/cdc-funding/state/AL?fy=2022&metric=total_funding&funding_type=total_cdc_funding&mode=raw_total"
  );
}

function buildSummaryPayload() {
  return {
    state_code: "AL",
    state_name: "Alabama",
    fiscal_year: 2025,
    timeframe_label: "FY2025",
    legend_title: "FY2025 CDC Funding Per Capita",
    total_funding: 111111,
    selected_metric: "funding_per_capita",
    selected_metric_label: "CDC Funding Per Capita",
    selected_metric_value: 245.72,
    award_count: 1,
    contract_award_count: 0,
    population: 10,
    funding_per_capita: 999.99,
    funding_mode_label: "CHIP normalized funding",
    normalization_note: "Normalized from the funding-scope layer.",
    profile: {
      geography_type: "state",
      geography_id: "AL",
      geography_name: "Alabama",
      state_code: "AL",
      state_name: "Alabama",
      fiscal_year: 2025,
      time_aggregation: "single_fiscal_year",
      timeframe_label: "FY2025",
      funding_mode_requested: "chip_normalized",
      funding_mode_effective: "chip_normalized",
      funding_mode_label: "CHIP normalized funding",
      total_funding: 1234567,
      raw_total_funding: 2345678,
      chip_normalized_funding: 1234567,
      funding_per_capita: 245.72,
      funding_per_100k: 24572000,
      national_share: 4.2,
      awards_total: 1000000,
      subawards_total: 200000,
      contracts_total: 34567,
      award_count: 12,
      subaward_count: 2,
      contract_award_count: 1,
      population: 5024279,
      normalization_supported: true,
      normalization_applied: true,
      normalization_note: "Normalized from the funding-scope layer.",
      methodology_version: "profile_scope_v5",
      profile_version: "funding_profile_result_v1",
      funding_model_version: "cdc_funding_mode_v1",
      metadata: {
        metric_context: {
          funding_type_label: "Emergency Response Funding",
          funding_mode_label: "CHIP normalized funding",
          cdc_center_label: "Public Health Preparedness and Response",
          mechanism_label: "Cooperative Agreements",
          recipient_type_label: "State Governments",
          time_aggregation_label: "Single Fiscal Year",
          legend_title: "FY2025 CDC Funding Per Capita",
        },
      },
    },
    grouping: {
      category_method: "TAGGS effective CDC program-area enrichment by ALN/CFDA number, with CDC center-name fallback when no TAGGS match is available.",
      subcategory_method: "TAGGS effective program-name enrichment by ALN/CFDA number, with USAspending program-title fallback when no TAGGS match is available.",
    },
    filter_context: {
      funding_type_label: "Emergency Response Funding",
      funding_mode_label: "CHIP normalized funding",
      cdc_center_label: "Public Health Preparedness and Response",
      mechanism_label: "Cooperative Agreements",
      recipient_type_label: "State Governments",
      time_aggregation_label: "Single Fiscal Year",
      legend_title: "FY2025 CDC Funding Per Capita",
    },
    methodology_notes: [
      "State profile totals use the same CDC funding mode and filter model as the map.",
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

function buildOverviewPayload() {
  return {
    summary: buildSummaryPayload(),
    categories: buildCategoryPayload(),
    subcategories: buildSubcategoryPayload(),
  };
}

function buildDetailsPayload(overrides = {}) {
  return {
    state_code: "AL",
    funding_mode: "chip_normalized",
    fiscal_year: 2025,
    page: 1,
    page_size: 25,
    total_rows: 60,
    sort_by: "amount",
    sort_dir: "desc",
    rows: [
      {
        line_number: 1,
        record_id: "award-1",
        record_type: "award",
        fain: "NU90TP000001",
        category: "Public Health Preparedness and Response",
        subcategory: "Public Health Emergency Preparedness",
        project_title: "Preparedness Award Alpha",
        grantee_name: "Alabama Department of Public Health",
        city: "Montgomery",
        county: "Montgomery County",
        amount: 500000,
        latest_action_date: "2025-06-30",
        usaspending_permalink: "https://example.test/award-1",
      },
    ],
    ...overrides,
  };
}

describe("CdcStateFundingProfile", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    pushProfileUrl();
    fetchCdcFundingProfileOverview.mockResolvedValue(buildOverviewPayload());
    fetchCdcFundingProfileDetails.mockResolvedValue(buildDetailsPayload());
  });

  it("renders the unified CDC funding profile content with the selected funding mode", async () => {
    render(<CdcStateFundingProfile stateCode="AL" />);

    expect(await screen.findByText("CDC State Funding Profile")).toBeInTheDocument();
    expect(screen.getByText("Alabama")).toBeInTheDocument();
    expect(screen.getByTestId("cdc-profile-mode-badge")).toHaveTextContent("CHIP normalized funding");
    expect(screen.getByText("Normalized from the funding-scope layer.")).toBeInTheDocument();
    expect(screen.getAllByText("$1,234,567.00").length).toBeGreaterThan(0);
    expect(screen.getByText("5,024,279")).toBeInTheDocument();
    expect(screen.getByText("$245.72 per person")).toBeInTheDocument();
    expect(screen.getAllByText("Public Health Preparedness and Response").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Public Health Emergency Preparedness").length).toBeGreaterThan(0);
    expect(screen.getByText("Preparedness Award Alpha")).toBeInTheDocument();
    expect(screen.getByText(/USAspending supplies award, subaward, and contract transactions/i)).toBeInTheDocument();
  });

  it("renders the overview before the detailed table resolves", async () => {
    let resolveDetails;
    fetchCdcFundingProfileDetails.mockImplementation(
      () => new Promise((resolve) => {
        resolveDetails = resolve;
      })
    );

    render(<CdcStateFundingProfile stateCode="AL" />);

    expect(await screen.findByText("Public Health Emergency Preparedness")).toBeInTheDocument();
    expect(screen.getByText("Loading detailed awards table...")).toBeInTheDocument();

    await waitFor(() => {
      expect(resolveDetails).toBeTypeOf("function");
    });
    resolveDetails(buildDetailsPayload());
    expect(await screen.findByText("Preparedness Award Alpha")).toBeInTheDocument();
  });

  it("requests the overview and detail APIs with the funding_mode contract", async () => {
    render(<CdcStateFundingProfile stateCode="AL" />);

    await waitFor(() => {
      expect(fetchCdcFundingProfileOverview).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          fiscal_year: 2025,
          metric: "funding_per_capita",
          funding_type: "emergency_response",
          funding_mode: "chip_normalized",
          cdc_center: "public_health_preparedness_and_response",
          mechanism: "cooperative_agreements",
          recipient_type: "state_governments",
          time_aggregation: "single_fiscal_year",
        })
      );
    });

    await waitFor(() => {
      expect(fetchCdcFundingProfileDetails).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          fiscal_year: 2025,
          funding_mode: "chip_normalized",
          page: 1,
          page_size: 25,
          sort_by: "amount",
          sort_dir: "desc",
        })
      );
    });
  });

  it("accepts the short fy and mode route params used by the CDC map button", async () => {
    pushShortProfileUrl();
    render(<CdcStateFundingProfile stateCode="AL" />);

    await waitFor(() => {
      expect(fetchCdcFundingProfileOverview).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          fiscal_year: 2022,
          funding_mode: "raw_total",
        })
      );
    });

    await waitFor(() => {
      expect(fetchCdcFundingProfileDetails).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          fiscal_year: 2022,
          funding_mode: "raw_total",
        })
      );
    });
  });

  it("paginates the detail table with a separate follow-up request", async () => {
    fetchCdcFundingProfileDetails
      .mockResolvedValueOnce(
        buildDetailsPayload({
          page: 1,
          rows: [
            {
              ...buildDetailsPayload().rows[0],
              record_id: "award-1",
              project_title: "Preparedness Award Alpha",
            },
          ],
        })
      )
      .mockResolvedValueOnce(
        buildDetailsPayload({
          page: 2,
          rows: [
            {
              ...buildDetailsPayload().rows[0],
              line_number: 26,
              record_id: "award-26",
              project_title: "Preparedness Award Beta",
            },
          ],
        })
      );

    render(<CdcStateFundingProfile stateCode="AL" />);

    expect(await screen.findByText("Preparedness Award Alpha")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => {
      expect(fetchCdcFundingProfileDetails).toHaveBeenLastCalledWith(
        expect.objectContaining({
          state: "AL",
          fiscal_year: 2025,
          funding_mode: "chip_normalized",
          page: 2,
          page_size: 25,
        })
      );
    });

    expect(await screen.findByText("Preparedness Award Beta")).toBeInTheDocument();
  });
});
