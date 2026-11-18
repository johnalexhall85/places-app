import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import CommunityAI from "./CommunityAI";

afterEach(() => { vi.unstubAllGlobals(); });

describe("AI connector page", () => {
  it("shows the live URL, copies it, and limits catalog coverage to published public products", async () => {
    const copy = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText: copy } });
    const fetchCatalog = vi.fn(async () => ({
      ok: true,
      json: async () => ({ products: [
        { product: "places", name: "CDC PLACES live", published: true, levels: ["county", "tract"] },
        { product: "ahrf", name: "AHRF workforce", published: true, levels: ["county"] },
        { product: "epa_aqi", name: "Unpublished AQI", published: false, levels: ["county"] },
      ] }),
    }));
    vi.stubGlobal("fetch", fetchCatalog);

    render(<CommunityAI />);
    expect(screen.getByRole("heading", { name: "Use CHIP in your AI assistant" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Use CHIP with AI" })).toHaveAttribute("href", "/ai");
    expect(screen.getByText("https://mcp.publicdataobservatory.org")).toBeInTheDocument();
    expect(screen.queryByText(/also answers at/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("CDC PLACES live")).toBeInTheDocument());
    expect(fetchCatalog).toHaveBeenCalledWith(expect.stringContaining("/community/catalog"), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByText(/counties, census tracts/)).toBeInTheDocument();
    expect(screen.queryByText("AHRF workforce")).not.toBeInTheDocument();
    expect(screen.queryByText("Unpublished AQI")).not.toBeInTheDocument();
    expect(screen.getByText(/AHRF is not available through the AI connector/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy connector URL" }));
    await waitFor(() => expect(copy).toHaveBeenCalledWith("https://mcp.publicdataobservatory.org"));
    expect(screen.getByRole("status")).toHaveTextContent("Connector URL copied.");
  });

  it("keeps the eight public products visible when the protected catalog requires sign-in", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 401 })));
    render(<CommunityAI />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.getByText("CDC PLACES")).toBeInTheDocument();
    expect(screen.getByText("USDA Food Environment Atlas")).toBeInTheDocument();
    expect(document.querySelectorAll(".community-ai-products li")).toHaveLength(8);
  });
});
