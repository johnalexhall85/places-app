import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FundingModelBuilder from "./FundingModelBuilder";

vi.mock("../components/Header", () => ({
  default: function HeaderMock() {
    return <div data-testid="header-mock">Header</div>;
  },
}));

vi.mock("../api/fundingModels", () => ({
  archiveFundingModel: vi.fn(),
  buildFundingModel: vi.fn(),
  cloneFundingModel: vi.fn(),
  createFundingModel: vi.fn(),
  fetchFundingModelFieldCatalog: vi.fn(),
  fetchFundingModel: vi.fn(),
  fetchFundingModels: vi.fn(),
  previewFundingModel: vi.fn(),
  publishFundingModel: vi.fn(),
  lockFundingModel: vi.fn(),
  updateFundingModel: vi.fn(),
}));

const {
  fetchFundingModelFieldCatalog,
  fetchFundingModel,
  fetchFundingModels,
  previewFundingModel,
} = await import("../api/fundingModels");

const FIELD_CATALOG_ITEMS = [
  {
    key: "fiscal_year",
    label: "Fiscal Year",
    raw_key: "action_date_fiscal_year | fiscal_year",
    type: "number",
    group: "common",
    applies_to_sources: ["usaspending_awards", "usaspending_assistance_transactions", "usaspending_contract_transactions", "taggs"],
    operators: ["equals", "not_equals", "greater_than", "less_than", "in", "not_in", "is_null", "is_not_null"],
  },
  {
    key: "funding_subagency_name",
    label: "Funding Subagency Name",
    raw_key: "funding_sub_agency_name",
    type: "text",
    group: "common",
    applies_to_sources: ["usaspending_awards", "usaspending_subawards", "usaspending_assistance_transactions", "usaspending_contract_transactions"],
    operators: ["equals", "not_equals", "contains", "starts_with", "ends_with", "in", "not_in", "is_null", "is_not_null"],
  },
  {
    key: "assistance.award_id_fain",
    label: "Award ID FAIN",
    raw_key: "award_id_fain",
    type: "text",
    group: "assistance",
    applies_to_sources: ["usaspending_assistance_transactions"],
    operators: ["equals", "not_equals", "contains", "starts_with", "ends_with", "in", "not_in", "is_null", "is_not_null"],
  },
  {
    key: "contract.product_or_service_code",
    label: "Product Or Service Code",
    raw_key: "product_or_service_code",
    type: "text",
    group: "contract",
    applies_to_sources: ["usaspending_contract_transactions"],
    operators: ["equals", "not_equals", "contains", "starts_with", "ends_with", "in", "not_in", "is_null", "is_not_null"],
  },
];

function buildSavedModel(overrides = {}) {
  return {
    id: 3,
    display_name: "CHIP v1.1 Emergency Classification",
    internal_model_id: "v1_1_emergency_classification",
    slug: "chip-v1-1-emergency-classification",
    description: "Governed funding methodology.",
    chip_methodology_version: "v1.1",
    funding_mode_key: "chip_v1_1_emergency",
    status: "draft",
    current_version_id: 33,
    current_version: {
      id: 33,
      version_number: 1,
      version_label: "Initial draft",
      definition_json: {
        display_name: "CHIP v1.1 Emergency Classification",
        internal_model_id: "v1_1_emergency_classification",
        chip_methodology_version: "v1.1",
        funding_mode_key: "chip_v1_1_emergency",
        slug: "chip-v1-1-emergency-classification",
        chip_state_profile_source_version: "chip_state_profile_v1_1_emergency_classification",
        chip_normalization_source_version: "chip_normalized_v1_1_emergency_classification",
        status: "draft",
        definition: {
          data_sources: {
            usaspending_awards: true,
            usaspending_subawards: false,
            usaspending_assistance_transactions: true,
            usaspending_contract_transactions: true,
            taggs: true,
          },
          options: {
            include_finalized_only: true,
            include_deobligations: false,
            include_negative_adjustments: false,
            include_pass_through_records: false,
          },
          include_group: { id: "include-root", combinator: "ALL", children: [] },
          exclude_group: { id: "exclude-root", combinator: "ANY", children: [] },
          advanced_sql_enabled: false,
          advanced_sql_override: null,
          aggregation: {
            default_metric: "normalized_total",
            supported_geographies: ["nation", "state", "county"],
            default_geography: "state",
            default_fiscal_year: 2025,
          },
        },
      },
      generated_sql: "SELECT * FROM analytics.funding_model_builder_base_v1",
      plain_language_summary: "Summary text",
      chip_state_profile_source_version: "chip_state_profile_v1_1_emergency_classification",
      chip_normalization_source_version: "chip_normalized_v1_1_emergency_classification",
      notes: null,
    },
    versions: [
      {
        id: 33,
        version_number: 1,
        version_label: "Initial draft",
        status: "draft",
        build_status: null,
      },
    ],
    ...overrides,
  };
}

describe("FundingModelBuilder", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    fetchFundingModels.mockResolvedValue([buildSavedModel()]);
    fetchFundingModelFieldCatalog.mockResolvedValue({ items: FIELD_CATALOG_ITEMS });
    previewFundingModel.mockResolvedValue({
      generated_sql: "SELECT * FROM analytics.funding_model_builder_base_v1",
      plain_language_summary: "This model includes USAspending awards for FY2025.",
      warnings: ["Advanced SQL override is enabled."],
      included_record_count: 11,
      excluded_record_count: 2,
      national_totals_by_fiscal_year: [{ fiscal_year: 2025, total_amount: 1000, row_count: 11 }],
      state_totals_for_fiscal_year: [{ state_code: "AL", state_name: "Alabama", total_amount: 250, row_count: 3 }],
    });
    window.confirm = vi.fn(() => true);
  });

  it("renders the metadata form and action controls", async () => {
    render(<FundingModelBuilder />);

    expect(await screen.findByText("Funding Model Builder")).toBeInTheDocument();
    expect(screen.getByTestId("metadata-display-name")).toBeInTheDocument();
    expect(screen.getByText("USAspending assistance transactions")).toBeInTheDocument();
    expect(screen.getByText("USAspending contract transactions")).toBeInTheDocument();
    expect(screen.getByText("Save Draft")).toBeInTheDocument();
    expect(screen.getByText("Lock Version")).toBeDisabled();
  });

  it("adds an include rule from the visual rule builder", async () => {
    render(<FundingModelBuilder />);

    await screen.findByText("Funding Model Builder");
    fireEvent.click(screen.getAllByText("Add Rule")[0]);

    expect(screen.getAllByDisplayValue("Fiscal Year").length).toBeGreaterThan(0);
    expect(screen.getAllByDisplayValue("equals").length).toBeGreaterThan(0);
    expect(screen.getByText("Funding Subagency Name")).toBeInTheDocument();
  });

  it("runs the preview flow and renders returned totals", async () => {
    render(<FundingModelBuilder />);

    await screen.findByText("Funding Model Builder");
    fireEvent.change(screen.getByTestId("metadata-display-name"), { target: { value: "My Emergency Model" } });
    fireEvent.change(screen.getByLabelText(/Methodology Version/i), { target: { value: "v1.1" } });
    fireEvent.change(screen.getByLabelText(/Internal Model ID/i), { target: { value: "my_emergency_model" } });
    fireEvent.click(screen.getByText("Refresh Preview"));

    await waitFor(() => {
      expect(previewFundingModel).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText("Alabama")).toBeInTheDocument();
    expect(screen.getByText("This model includes USAspending awards for FY2025.")).toBeInTheDocument();
  });

  it("enables locking after a draft model is loaded", async () => {
    fetchFundingModel.mockResolvedValue(buildSavedModel());

    render(<FundingModelBuilder />);

    await screen.findByText("Funding Model Builder");
    fireEvent.change(screen.getByLabelText("Load saved model"), { target: { value: "3" } });
    fireEvent.click(screen.getByText("Load"));

    await waitFor(() => {
      expect(fetchFundingModel).toHaveBeenCalledWith("3", expect.any(Object));
    });
    expect(await screen.findByText("Loaded CHIP v1.1 Emergency Classification.")).toBeInTheDocument();
    expect(screen.getByText("Lock Version")).toBeEnabled();
  });

  it("shows the selected field raw key helper text", async () => {
    render(<FundingModelBuilder />);

    await screen.findByText("Funding Model Builder");
    fireEvent.click(screen.getAllByText("Add Rule")[0]);

    expect(screen.getByText("action_date_fiscal_year | fiscal_year")).toBeInTheDocument();
  });

  it("filters contract-only fields when the contract source is disabled", async () => {
    render(<FundingModelBuilder />);

    await screen.findByText("Funding Model Builder");
    fireEvent.click(screen.getAllByText("Add Rule")[0]);

    expect(screen.getByText("Product Or Service Code")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("USAspending contract transactions"));

    await waitFor(() => {
      expect(screen.queryByText("Product Or Service Code")).not.toBeInTheDocument();
    });
  });
});
