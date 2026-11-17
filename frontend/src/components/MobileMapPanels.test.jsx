import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MobileMapPanels from "./MobileMapPanels";

function Harness({ onVisibilityChange }) {
  const mapSurfaceRef = createRef();
  return <div>
    <div ref={mapSurfaceRef} data-testid="map-surface">Map</div>
    <MobileMapPanels mapSurfaceRef={mapSurfaceRef} onVisibilityChange={onVisibilityChange}>
      <div>Legend and filters</div>
    </MobileMapPanels>
  </div>;
}

describe("MobileMapPanels", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("opens all panels, closes by button or swipe, and remembers the hint dismissal", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    const resize = vi.fn();
    render(<Harness onVisibilityChange={resize} />);
    const button = screen.getByRole("button", { name: "Panels" });
    const drawer = document.getElementById(button.getAttribute("aria-controls"));
    expect(drawer).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText(/Tap Panels or swipe/)).toBeInTheDocument();
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(drawer).toHaveClass("is-open");
    expect(drawer).toHaveTextContent("Legend and filters");
    expect(screen.queryByText(/Tap Panels or swipe/)).not.toBeInTheDocument();
    expect(window.localStorage.getItem("chip-mobile-map-panels-hint-seen")).toBe("1");
    expect(resize).toHaveBeenCalled();
    fireEvent.click(button);
    expect(drawer).toHaveAttribute("aria-hidden", "true");
    fireEvent.touchStart(screen.getByTestId("map-surface"), { touches: [{ clientX: 8, clientY: 100 }] });
    fireEvent.touchEnd(screen.getByTestId("map-surface"), { changedTouches: [{ clientX: 90, clientY: 104 }] });
    expect(drawer).toHaveClass("is-open");
    fireEvent.touchStart(drawer, { touches: [{ clientX: 130, clientY: 100 }] });
    fireEvent.touchEnd(drawer, { changedTouches: [{ clientX: 30, clientY: 106 }] });
    expect(drawer).toHaveAttribute("aria-hidden", "true");
  });

  it("ignores map swipes outside the left edge and keeps desktop panels visible", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    const { unmount } = render(<Harness />);
    const surface = screen.getByTestId("map-surface");
    fireEvent.touchStart(surface, { touches: [{ clientX: 80, clientY: 100 }] });
    fireEvent.touchEnd(surface, { changedTouches: [{ clientX: 200, clientY: 100 }] });
    expect(screen.getByRole("button", { name: "Panels" })).toHaveAttribute("aria-expanded", "false");
    unmount();
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    render(<Harness />);
    // Desktop keeps the normal panels in the document, with no hidden state.
    expect(screen.getByText("Legend and filters")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Map panels" })).not.toBeInTheDocument();
  });

  it("dismisses the first-visit hint without opening the drawer", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    const { unmount } = render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss map panels hint" }));
    expect(screen.queryByText(/Tap Panels or swipe/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Panels" })).toHaveAttribute("aria-expanded", "false");
    unmount();
    render(<Harness />);
    expect(screen.queryByText(/Tap Panels or swipe/)).not.toBeInTheDocument();
  });
});
