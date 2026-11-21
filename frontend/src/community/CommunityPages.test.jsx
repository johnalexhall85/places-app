import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import {
  CommunityCounty,
  formatIndicatorValue,
  formatNriPercentile,
  formatNriValue,
  formatSviRank,
  uncertaintyText,
} from "./CommunityPages";
import { CommunityState } from "./CommunityState";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("community indicator display", () => {
  it("keeps missing, true zero, and published percentages distinct", () => {
    expect(formatIndicatorValue({ value: null, status_text: "Suppressed by the source" })).toBe("Suppressed by the source");
    expect(formatIndicatorValue({ value: 0, status: "true_zero", unit: "percent" })).toBe("0%");
    expect(formatIndicatorValue({ value: 12.3, unit: "percent" })).toBe("12.3%");
  });

  it("converts CMS stored proportions for display only", () => {
    const row = { value: 0.1863, storage_scale: "proportion_0_1", unit: "proportion" };
    expect(formatIndicatorValue(row)).toBe("18.63%");
    expect(row.value).toBe(0.1863);
  });

  it("formats published ACS dollars and CLH percentages from their source units", () => {
    expect(formatIndicatorValue({ value: 63300, unit: "2024 inflation-adjusted USD" })).toBe("$63,300");
    expect(formatIndicatorValue({ value: 87.52, unit: "%" })).toBe("87.52%");
  });

  it("shows the Census Bureau's controlled population margin label", () => {
    expect(uncertaintyText({ uncertainty: { kind: "moe90", moe: null, label: "No sampling margin: the estimate is controlled to official population totals" } }))
      .toContain("controlled to official population totals");
  });

  it("formats SVI ranks and NRI scores, dollars, and missing status text without showing zero", () => {
    expect(formatSviRank({ value: 0.686, status: "available" })).toBe("0.686");
    expect(formatSviRank({ value: 0, status: "true_zero" })).toBe("0.00");
    expect(formatSviRank({ value: null, status: "not_available", status_text: "Not ranked by CDC (−999 in the source file)" }))
      .toBe("Not ranked by CDC (−999 in the source file)");
    expect(formatNriValue({ value: 81.44, kind: "score" })).toBe("81.4");
    expect(formatNriValue({ value: 38142500.4, kind: "currency", storage_scale: "dollars_per_year" })).toBe("$38,142,500");
    expect(formatNriValue({ value: 1.123, kind: "factor", storage_scale: "multiplier" })).toBe("1.12");
    expect(formatNriValue({ value: null, status_text: "Not published by FEMA for this area (Data Unavailable)" }))
      .toBe("Not published by FEMA for this area (Data Unavailable)");
    expect(formatNriPercentile({ value: 89.0 })).toBe("89.0");
    expect(formatNriPercentile({ value: null, status_text: "Not published by FEMA for this area" }))
      .toBe("Not published by FEMA for this area");
    expect(formatNriPercentile(null)).toBe("—");
  });
});

const SAMPLE_COUNTY_PROFILE = {
  area: {
    geoid: "37063",
    name: "Durham",
    state_geoid: "37",
    state_name: "North Carolina",
    boundary_vintage: "TIGER/Line 2024",
    bbox: [-79.0, 35.9, -78.7, 36.2],
  },
  values: [
    {
      product: "epa_aqi",
      measure_id: "median_aqi",
      geoid: "37063",
      level: "county",
      label: "Median Air Quality Index",
      value: 42,
      unit: "AQI",
      period: "2024",
      population: "Reporting days",
      status: "available",
      status_text: "Published value",
      uncertainty: { kind: "none" },
      source_release_id: "EPA AQI 2024",
      source: { publisher: "EPA", product_name: "EPA AQI" },
    },
    {
      product: "cms_gv",
      measure_id: "standardized_per_capita_cost",
      geoid: "37063",
      level: "county",
      label: "Medicare standardized per capita spending",
      value: 11400,
      unit: "US dollars",
      kind: "currency",
      period: "2023",
      population: "Original Medicare beneficiaries",
      status: "available",
      status_text: "Published value",
      uncertainty: { kind: "none" },
      source_release_id: "CMS GV 2023",
      source: { publisher: "CMS", product_name: "CMS Geographic Variation" },
    },
    // Present in profile.values on staging; must NOT be dumped into Community conditions
    {
      product: "cdc_svi",
      measure_id: "rpl_themes",
      geoid: "37063",
      level: "county",
      label: "Overall social vulnerability (percentile rank)",
      value: 0.686,
      unit: "percentile rank (0–1)",
      period: "2018–2022",
      population: "All U.S. counties",
      status: "available",
      status_text: "Published value",
      uncertainty: { kind: "none" },
      source_release_id: "SVI 2022",
      source: { publisher: "CDC/ATSDR", product_name: "CDC SVI" },
    },
  ],
  state_values: [],
  survey_companions: {},
  facilities: { health_centers: null, nursing_homes: null, tri_facilities: null },
  limitations: ["Test limitation"],
};

const SAMPLE_COUNTY_HAZARDS = {
  level: "county",
  geoid: "37063",
  name: "Durham",
  state: { geoid: "37", name: "North Carolina" },
  svi: [
    {
      measure_id: "rpl_themes",
      label: "Overall social vulnerability",
      us: { value: 0.686, status: "available", status_text: "Published value", citation: "Source: CDC/ATSDR · CDC Social Vulnerability Index · 2018–2022" },
      state: { value: 0.596, status: "available", status_text: "Published value", citation: "Source: CDC/ATSDR · CDC Social Vulnerability Index · 2018–2022" },
      status: "available",
      status_text: "Published value",
      citation: "Source: CDC/ATSDR · CDC Social Vulnerability Index · 2018–2022",
    },
    {
      measure_id: "rpl_theme1",
      label: "Socioeconomic status",
      us: { value: null, status: "not_available", status_text: "Not ranked by CDC (−999 in the source file)" },
      state: { value: null, status: "not_available", status_text: "Not ranked by CDC (−999 in the source file)" },
      status: "not_available",
      status_text: "Not ranked by CDC (−999 in the source file)",
      citation: "Source: CDC/ATSDR · CDC Social Vulnerability Index · 2018–2022",
    },
    {
      measure_id: "rpl_theme2",
      label: "Household characteristics",
      us: { value: 0.25, status: "available", status_text: "Published value" },
      state: { value: 0.2501, status: "available", status_text: "Published value" },
      status: "available",
      status_text: "Published value",
      citation: "Source: CDC/ATSDR · CDC Social Vulnerability Index · 2018–2022",
    },
    {
      measure_id: "rpl_theme3",
      label: "Racial and ethnic minority status",
      us: { value: 0.75, status: "available", status_text: "Published value" },
      state: { value: 0.7501, status: "available", status_text: "Published value" },
      status: "available",
      status_text: "Published value",
      citation: "Source: CDC/ATSDR · CDC Social Vulnerability Index · 2018–2022",
    },
    {
      measure_id: "rpl_theme4",
      label: "Housing type and transportation",
      us: { value: 0.5, status: "available", status_text: "Published value" },
      state: { value: 0.5001, status: "available", status_text: "Published value" },
      status: "available",
      status_text: "Published value",
      citation: "Source: CDC/ATSDR · CDC Social Vulnerability Index · 2018–2022",
    },
  ],
  nri: [
    {
      measure_id: "risk_score",
      label: "National Risk Index score",
      kind: "score",
      value: 81.4,
      status: "available",
      status_text: "Published value",
      rating: "Relatively Moderate",
      direction: "higher_worse",
      state_percentile: { value: 89.0, status: "available", status_text: "Published value" },
      citation: "Source: FEMA · FEMA National Risk Index · NRI v1.20 (December 2025)",
    },
    {
      measure_id: "eal_valt",
      label: "Expected annual loss, total ($ per year)",
      kind: "currency",
      storage_scale: "dollars_per_year",
      value: 38142500,
      status: "available",
      status_text: "Published value",
      rating: null,
      direction: "higher_worse",
      state_percentile: null,
      citation: "Source: FEMA · FEMA National Risk Index · NRI v1.20 (December 2025)",
    },
    {
      measure_id: "sovi_score",
      label: "Social vulnerability score (as used by NRI)",
      kind: "score",
      value: null,
      status: "not_available",
      status_text: "Not published by FEMA for this area (Data Unavailable)",
      rating: "Data Unavailable",
      direction: "higher_worse",
      state_percentile: { value: null, status: "not_available", status_text: "Not published by FEMA for this area" },
      citation: "Source: FEMA · FEMA National Risk Index · NRI v1.20 (December 2025)",
    },
    {
      measure_id: "resl_score",
      label: "Community resilience score",
      kind: "score",
      value: 72.1,
      status: "available",
      status_text: "Published value",
      rating: "Relatively High",
      direction: "higher_better",
      state_percentile: { value: 84.0, status: "available", status_text: "Published value" },
      citation: "Source: FEMA · FEMA National Risk Index · NRI v1.20 (December 2025)",
    },
  ],
  sources: {
    cdc_svi: {
      citation: "Source: CDC/ATSDR · CDC Social Vulnerability Index · 2018–2022",
      landing_page: "https://www.atsdr.cdc.gov/place-health/php/svi/svi-data-documentation-download.html",
    },
    fema_nri: {
      citation: "Source: FEMA · FEMA National Risk Index · NRI v1.20 (December 2025)",
      landing_page: "https://www.fema.gov/about/openfema/data-sets/national-risk-index-data",
    },
  },
  limitations: { cdc_svi: [], fema_nri: [] },
};

describe("county and state profile hazard sections", () => {
  it("renders county SVI and NRI sections after Environment with citations, links, and missing status text", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      if (String(url).endsWith("/community/county/37063")) return { ok: true, json: async () => SAMPLE_COUNTY_PROFILE };
      if (String(url).endsWith("/community/county/37063/hazards")) return { ok: true, json: async () => SAMPLE_COUNTY_HAZARDS };
      if (String(url).endsWith("/community/catalog")) return { ok: true, json: async () => ({ measures: [] }) };
      return { ok: false, status: 404 };
    }));

    const { container } = render(<CommunityCounty geoid="37063" />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Social vulnerability (CDC/ATSDR SVI 2022)" })).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Natural hazard risk (FEMA NRI)" })).toBeInTheDocument();

    // Section order: environment -> svi -> fema-nri -> medicare, and no Community conditions dump
    const sectionIds = Array.from(container.querySelectorAll("section.community-profile-section")).map((el) => el.id);
    expect(sectionIds.indexOf("environment")).toBeLessThan(sectionIds.indexOf("svi"));
    expect(sectionIds.indexOf("svi")).toBeLessThan(sectionIds.indexOf("fema-nri"));
    expect(sectionIds.indexOf("fema-nri")).toBeLessThan(sectionIds.indexOf("medicare"));
    expect(sectionIds).not.toContain("conditions");

    const sviSection = container.querySelector("#svi");
    expect(within(sviSection).getByText("A rank of 0.85 means 85% of counties in the nation (or state) are less vulnerable.")).toBeInTheDocument();
    const cardTitles = Array.from(sviSection.querySelectorAll(".community-svi-card h3")).map((h) => h.textContent);
    expect(cardTitles).toEqual([
      "Overall SVI",
      "Socioeconomic Status",
      "Household Characteristics",
      "Racial & Ethnic Minority Status",
      "Housing Type & Transportation",
    ]);

    // Overall SVI card: two rows with quartile bars, phrases, footer, and map links
    const overallCard = sviSection.querySelectorAll(".community-svi-card")[0];
    expect(within(overallCard).getByText("Among all U.S. counties")).toBeInTheDocument();
    expect(within(overallCard).getByText("Within North Carolina")).toBeInTheDocument();
    expect(within(overallCard).getByText("0.686")).toBeInTheDocument();
    expect(within(overallCard).getByText("0.596")).toBeInTheDocument();
    expect(within(overallCard).getByRole("img", { name: "Rank 0.686 of 1, medium to high vulnerability" })).toBeInTheDocument();
    expect(within(overallCard).getByRole("img", { name: "Rank 0.596 of 1, medium to high vulnerability" })).toBeInTheDocument();
    expect(within(overallCard).getByText("Possible ranks range from 0 (lowest vulnerability) to 1 (highest vulnerability).")).toBeInTheDocument();
    expect(within(overallCard).getByRole("link", { name: "View on map" }))
      .toHaveAttribute("href", "/area/svi?measure_id=rpl_themes&scope=us&focus=county:37063");
    expect(within(overallCard).getByRole("link", { name: "View within North Carolina" }))
      .toHaveAttribute("href", "/area/svi?measure_id=rpl_themes_state&scope=state&state=37&focus=county:37063");

    // Socioeconomic Status card (-999 missing): shows status_text, NEVER renders a quartile bar or dot at 0
    const missingCard = sviSection.querySelectorAll(".community-svi-card")[1];
    expect(within(missingCard).getAllByText("Not ranked by CDC (−999 in the source file)")).toHaveLength(2);
    expect(missingCard.querySelector("svg")).toBeNull();
    expect(missingCard.querySelector("[data-testid='svi-quartile-dot']")).toBeNull();

    // Boundary checks on cards 2 and 3: 0.25 -> low, 0.2501 -> low to medium, 0.75 -> medium to high, 0.7501 -> high
    expect(within(sviSection).getByRole("img", { name: "Rank 0.25 of 1, low vulnerability" })).toBeInTheDocument();
    expect(within(sviSection).getByRole("img", { name: "Rank 0.2501 of 1, low to medium vulnerability" })).toBeInTheDocument();
    expect(within(sviSection).getByRole("img", { name: "Rank 0.75 of 1, medium to high vulnerability" })).toBeInTheDocument();
    expect(within(sviSection).getByRole("img", { name: "Rank 0.7501 of 1, high vulnerability" })).toBeInTheDocument();

    expect(within(sviSection).getByText(/Source: CDC\/ATSDR/)).toBeInTheDocument();

    const nriSection = container.querySelector("#fema-nri");
    expect(within(nriSection).getByText(/Higher community resilience is better/)).toBeInTheDocument();
    expect(within(nriSection).getByText("$38,142,500")).toBeInTheDocument();
    expect(within(nriSection).getByText("Relatively Moderate")).toBeInTheDocument();
    expect(within(nriSection).getByText("89.0")).toBeInTheDocument();
    expect(within(nriSection).getByText("Not published by FEMA for this area (Data Unavailable)")).toBeInTheDocument();
    expect(within(nriSection).getByText("Not published by FEMA for this area")).toBeInTheDocument();
    expect(within(nriSection).getByText("higher is better")).toBeInTheDocument();
    expect(within(nriSection).getByText(/Source: FEMA/)).toBeInTheDocument();
    expect(within(nriSection).getByRole("link", { name: /Explore FEMA NRI on the map/ })).toHaveAttribute("href", "/area/fema-nri?focus=county:37063");
  });

  it("keeps the county profile intact when /hazards fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      if (String(url).endsWith("/community/county/37063")) return { ok: true, json: async () => SAMPLE_COUNTY_PROFILE };
      if (String(url).endsWith("/community/county/37063/hazards")) throw new Error("network down");
      if (String(url).endsWith("/community/catalog")) return { ok: true, json: async () => ({ measures: [] }) };
      return { ok: false, status: 404 };
    }));

    render(<CommunityCounty geoid="37063" />);
    await waitFor(() => expect(screen.getByTestId("profile-ready")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Environment" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Social vulnerability (CDC/ATSDR SVI 2022)" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders the state NRI section with the required state-level note and no SVI section", async () => {
    const stateProfile = {
      area: { geoid: "37", name: "North Carolina", state_geoid: "37", state_name: "North Carolina", boundary_vintage: "TIGER/Line 2024" },
      values: [
        {
          product: "fema_nri",
          measure_id: "eal_score",
          geoid: "37",
          level: "state",
          label: "Expected annual loss score",
          value: 89.3,
          unit: "score (0–100)",
          period: "NRI v1.20 (December 2025)",
          population: "All U.S. states",
          status: "available",
          status_text: "Published value",
          uncertainty: { kind: "none" },
          source_release_id: "NRI v1.20",
          source: { publisher: "FEMA", product_name: "FEMA NRI" },
        },
      ],
      facilities: { health_centers: null, nursing_homes: null, tri_facilities: null },
      counties: [],
      districts: [],
      limitations: ["State limitation"],
    };
    const stateHazards = {
      level: "state",
      geoid: "37",
      name: "North Carolina",
      state: { geoid: "37", name: "North Carolina" },
      nri: [
        {
          measure_id: "eal_score",
          label: "Expected annual loss score",
          kind: "score",
          value: 89.3,
          status: "available",
          status_text: "Published value",
          rating: "Relatively High",
          direction: "higher_worse",
          state_percentile: null,
          citation: "Source: FEMA · FEMA National Risk Index · NRI v1.20 (December 2025)",
        },
        {
          measure_id: "eal_valt",
          label: "Expected annual loss, total ($ per year)",
          kind: "currency",
          storage_scale: "dollars_per_year",
          value: 3210450124,
          status: "available",
          status_text: "Published value",
          rating: null,
          direction: "higher_worse",
          state_percentile: null,
          citation: "Source: FEMA · FEMA National Risk Index · NRI v1.20 (December 2025)",
        },
      ],
      sources: {
        fema_nri: {
          citation: "Source: FEMA · FEMA National Risk Index · NRI v1.20 (December 2025)",
          landing_page: "https://www.fema.gov/about/openfema/data-sets/national-risk-index-data",
        },
      },
      limitations: { fema_nri: [] },
    };

    vi.stubGlobal("fetch", vi.fn(async (url) => {
      if (String(url).endsWith("/community/state/37")) return { ok: true, json: async () => stateProfile };
      if (String(url).endsWith("/community/state/37/hazards")) return { ok: true, json: async () => stateHazards };
      return { ok: false, status: 404 };
    }));

    const { container } = render(<CommunityState geoid="37" />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Natural hazard risk (FEMA NRI)" })).toBeInTheDocument());

    expect(screen.queryByRole("heading", { name: "Social vulnerability (CDC/ATSDR SVI 2022)" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Health conditions and status" })).not.toBeInTheDocument();
    const nriSection = container.querySelector("#fema-nri");
    expect(within(nriSection).getByText("FEMA publishes no state-level risk score; see county and tract values on the map.")).toBeInTheDocument();
    expect(within(nriSection).getByText("89.3")).toBeInTheDocument();
    expect(within(nriSection).getByText("Relatively High")).toBeInTheDocument();
    expect(within(nriSection).getByText("$3,210,450,124")).toBeInTheDocument();
    expect(within(nriSection).getByRole("link", { name: /Explore FEMA NRI on the map/ })).toHaveAttribute("href", "/area/fema-nri?focus=state:37");
  });
});
