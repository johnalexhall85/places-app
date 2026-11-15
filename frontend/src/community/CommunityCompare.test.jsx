import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import CommunityCompare from "./CommunityCompare";

afterEach(() => { vi.unstubAllGlobals(); });

describe("county comparison", () => {
  it("aligns the same released measure without ranking or filling a missing value", async () => {
    window.history.replaceState(null, "", "/compare?counties=37145,54039");
    const response = {
      areas: [{ geoid: "37145", name: "Person", state_name: "North Carolina" },
              { geoid: "54039", name: "Kanawha", state_name: "West Virginia" }],
      values: [
        { product: "places", measure_id: "dental_crudeprev", geoid: "37145", label: "Dental visit",
          value: 57.8, status: "available", unit: "percent", population: "adults", period: "2022",
          source_release_id: "2025-12-12", source: { publisher: "CDC", product_name: "PLACES" },
          uncertainty: { kind: "ci95", low: 53.7, high: 61.7 } },
        { product: "places", measure_id: "dental_crudeprev", geoid: "54039", label: "Dental visit",
          value: null, status: "suppressed", status_text: "Suppressed by the source", unit: "percent",
          population: "adults", period: "2022", source_release_id: "2025-12-12",
          source: { publisher: "CDC", product_name: "PLACES" }, uncertainty: { kind: "ci95" } },
      ],
      survey_companions: {
        "37": { dental_crudeprev: { value: 61.2, period: "2022", population: "adults", unit: "percent",
          uncertainty: { kind: "ci95", low: 59.8, high: 62.6 }, source_release_id: "BRFSS 2022",
          source: { publisher: "CDC", product_name: "BRFSS state survey estimates" } } },
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => response })));
    render(<CommunityCompare />);
    await waitFor(() => expect(screen.getByText("2 counties · 1 published indicator")).toBeTruthy());
    const table = screen.getByRole("table");
    expect(table.textContent).toContain("57.8%");
    expect(table.textContent).toContain("Suppressed by the source");
    expect(table.textContent).toContain("Release 2025-12-12");
    expect(table.textContent).toContain("State survey estimate (BRFSS)");
    expect(table.textContent).toContain("95% confidence interval: 59.8–62.6%");
    expect(table.textContent).not.toContain("rank");
  });
});
