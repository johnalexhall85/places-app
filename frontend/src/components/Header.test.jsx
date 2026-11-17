import { fireEvent, render, screen } from "@testing-library/react";
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

  it("opens the complete mobile menu and closes on a link, Escape, or an outside tap", () => {
    render(<Header />);
    const button = screen.getByRole("button", { name: "Menu" });
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(button).toHaveAttribute("aria-controls", nav.id);
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(nav).toHaveClass("is-open");
    for (const name of ["Home", "Topics", "Compare", "Districts", "Explore data", "Funding", "Use CHIP with AI", "About"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    const topics = screen.getByRole("link", { name: "Topics" });
    topics.addEventListener("click", (event) => event.preventDefault(), { once: true });
    fireEvent.click(topics);
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    fireEvent.pointerDown(document.body);
    expect(button).toHaveAttribute("aria-expanded", "false");
  });
});
