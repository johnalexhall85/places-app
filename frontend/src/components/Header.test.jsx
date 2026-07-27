import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Header from "./Header";

describe("Header", () => {
  it("links to the CDC funding overview page", () => {
    render(<Header />);

    const link = screen.getByRole("link", { name: "CDC Funding" });
    expect(link).toHaveAttribute("href", "/cdc-funding");
  });
});
