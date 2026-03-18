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
  fetchCdcFundingProfileDetails: vi.fn(),
}));

const {
  fetchCdcFundingProfileSummary,
  fetchCdcFundingProfileCategories,
  fetchCdcFundingProfileSubcategories,
  fetchCdcFundingProfileDetails,
} = await import("../api/cdcFunding");

function pushProfileUrl(normalized = false) {
  window.history.pushState(
    {},
    "",
    `/cdc-funding/state/AL?basis=prime&fy=2025&normalized=${normalized ? "true" : "false"}`
  );
}

function buildSummaryPayload(normalized = false) {
  return {
    state_code: "AL",
    state_name: "Alabama",
    fiscal_year: 2025,
    timeframe_label: "Fiscal Year 2025",
    appropriation_type_label: "All funding",
    total_funding: normalized ? 2469134 : 1234567,
    award_count: 12,
    category_count: 3,
    population: 5024279,
    population_source: "Census population estimate",
    funding_per_capita: normalized ? 491.44 : 245.72,
    normalization_requested: normalized,
    normalization_applied: normalized,
    data_mode_label: normalized ? "Normalized data" : "Raw obligations",
    normalization_note: normalized
      ? "Normalized values are calibrated to CHIP's CDC funding profile benchmark."
      : null,
    methodology_notes: [
      normalized
        ? "This page summarizes normalized CDC funding obligations for Alabama using CHIP's CDC funding pipeline."
        : "This page summarizes CDC funding obligations for Alabama using CHIP's CDC funding pipeline.",
    ],
    grouping: {
      category_label: "Derived category",
      category_method: "Derived from CDC center metadata.",
      subcategory_label: "Derived sub-category",
      subcategory_method: "Derived from CDC office metadata.",
    },
  };
}

function buildCategoryPayload(normalized = false) {
  return {
    rows: [
      {
        category: "Immunization Services",
        amount: normalized ? 1800000 : 900000,
        share_pct: 72.9,
        award_count: 7,
      },
    ],
  };
}

function buildSubcategoryPayload(normalized = false) {
  return {
    rows: [
      {
        category: "Immunization Services",
        subcategory: "Vaccines for Children",
        amount: normalized ? 1000000 : 500000,
        share_total_pct: 40.5,
        share_category_pct: 55.6,
        award_count: 4,
      },
    ],
  };
}

function buildDetailsPayload(normalized = false) {
  return {
    total_rows: 1,
    rows: [
      {
        line_number: 1,
        record_id: "PRIME-1",
        fain: "NU66IP000001",
        category: "Immunization Services",
        subcategory: "Vaccines for Children",
        project_title: "Childhood vaccination coordination",
        grantee_name: "Alabama Department of Public Health",
        city: "Montgomery",
        county: "Montgomery",
        amount: normalized ? 1000000 : 500000,
        latest_action_date: "2025-10-01",
      },
    ],
  };
}

describe("CdcStateFundingProfile", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    pushProfileUrl(false);
    fetchCdcFundingProfileSummary.mockImplementation(async ({ normalize }) => buildSummaryPayload(Boolean(normalize)));
    fetchCdcFundingProfileCategories.mockImplementation(async ({ normalize }) => buildCategoryPayload(Boolean(normalize)));
    fetchCdcFundingProfileSubcategories.mockImplementation(async ({ normalize }) => buildSubcategoryPayload(Boolean(normalize)));
    fetchCdcFundingProfileDetails.mockImplementation(async ({ normalize }) => buildDetailsPayload(Boolean(normalize)));
  });

  it("renders summary cards, category totals, and detail rows", async () => {
    render(<CdcStateFundingProfile stateCode="AL" />);

    expect(await screen.findByText("CDC State Funding Profile")).toBeInTheDocument();
    expect(screen.getByText("Alabama")).toBeInTheDocument();
    expect(screen.getAllByText("$1,234,567.00").length).toBeGreaterThan(0);
    expect(screen.getByTestId("cdc-profile-mode-badge")).toHaveTextContent("Raw obligations");

    expect((await screen.findAllByText("Immunization Services")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Vaccines for Children").length).toBeGreaterThan(0);
    expect(screen.getByText("Childhood vaccination coordination")).toBeInTheDocument();
    expect(screen.getByText("Alabama Department of Public Health")).toBeInTheDocument();
  });

  it("requests the CDC profile APIs with the routed state code and normalized=false", async () => {
    render(<CdcStateFundingProfile stateCode="AL" />);

    await waitFor(() => {
      expect(fetchCdcFundingProfileSummary).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          fy: 2025,
          basis: "prime",
          normalize: false,
        })
      );
    });
    await waitFor(() => {
      expect(fetchCdcFundingProfileDetails).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          page: 1,
          sort_by: "amount",
          sort_dir: "desc",
          normalize: false,
        })
      );
    });
  });

  it("reads normalized=true from the URL, requests normalized data, and updates the mode badge", async () => {
    pushProfileUrl(true);

    render(<CdcStateFundingProfile stateCode="AL" />);

    expect(await screen.findByTestId("cdc-profile-mode-badge")).toHaveTextContent("Normalized data");
    expect(screen.getAllByText("$2,469,134.00").length).toBeGreaterThan(0);
    expect(screen.getByText("$1,800,000.00")).toBeInTheDocument();
    expect(screen.getAllByText("$1,000,000.00").length).toBeGreaterThan(0);

    await waitFor(() => {
      expect(fetchCdcFundingProfileSummary).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          normalize: true,
        })
      );
    });
    await waitFor(() => {
      expect(fetchCdcFundingProfileCategories).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          normalize: true,
        })
      );
    });
    await waitFor(() => {
      expect(fetchCdcFundingProfileSubcategories).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          normalize: true,
        })
      );
    });
    await waitFor(() => {
      expect(fetchCdcFundingProfileDetails).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "AL",
          normalize: true,
        })
      );
    });
  });
});
