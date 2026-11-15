import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Header from "./Header";

describe("Header", () => {
  it("links to the funding overview and the home-page destinations", () => {
    render(<Header />);

    const link = screen.getByRole("link", { name: "Funding" });
    expect(link).toHaveAttribute("href", "/cdc-funding");
    for (const name of ["Home", "Topics", "Compare", "Districts", "Explore data", "About"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: "Help" })).not.toBeInTheDocument();
  });
});
