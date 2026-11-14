import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StarRating, useNursingHomes } from "./NursingHomes";

function FilterHarness() {
  const homes = useNursingHomes({ bbox: "-87,32,-85,33", zoom: 9 });
  return <><button onClick={() => homes.setEnabled(true)}>Enable</button>
    {["1", "2", "3"].map((value) => <button key={value} onClick={() => homes.toggleFilter("overall", value)}>Toggle {value}</button>)}
    <span>{homes.ready ? "ready" : "pending"}</span></>;
}

afterEach(() => { vi.unstubAllGlobals(); window.sessionStorage.clear(); });

describe("CMS nursing home rating display", () => {
  it("shows published stars as an accessible count", () => {
    render(<StarRating value={3} />);
    expect(screen.getByText("3 of 5 stars")).toBeInTheDocument();
    expect(screen.getByText("★★★☆☆")).toHaveAttribute("aria-hidden", "true");
  });

  it("keeps an unrated facility distinct from zero and preserves the CMS explanation", () => {
    render(<StarRating value={null} footnote={{ code: "18", explanation: "Special focus facility program." }} />);
    expect(screen.getByText("Unrated")).toBeInTheDocument();
    expect(screen.queryByText(/0 of 5 stars/)).not.toBeInTheDocument();
    expect(screen.getByText(/CMS footnote 18: Special focus facility program/)).toBeInTheDocument();
  });

  it("coalesces rapid filter changes into one map and table request pair", async () => {
    window.sessionStorage.clear();
    const catalog = { active_release_id: "cms-debounce-test", filters: [
      { name: "provider_type", values: [{ code: "Medicare", default: true }] },
      { name: "ownership", values: [{ code: "Non profit", default: true }] },
      { name: "overall", values: ["1", "2", "3", "4", "5", "unrated"].map((code) => ({ code, default: true })) },
    ] };
    const calls = [];
    vi.stubGlobal("fetch", vi.fn(async (path) => {
      calls.push(String(path));
      const url = new URL(String(path), "http://example.test");
      const filters = Object.fromEntries(["provider_type", "ownership", "overall"].map((name) =>
        [name, (url.searchParams.get(name) || "").split(",").filter(Boolean)]));
      const base = { release_id: "cms-debounce-test", bbox: url.searchParams.get("bbox"), filters, total: 0 };
      const body = url.pathname.endsWith("/catalog") ? catalog : url.pathname.endsWith("/map")
        ? { ...base, mode: "points", points: [], clusters: [] } : { ...base, rows: [] };
      return { ok: true, json: async () => body };
    }));
    render(<FilterHarness />);
    fireEvent.click(screen.getByText("Enable"));
    await screen.findByText("ready");
    const maps = () => calls.filter((url) => url.includes("/map?"));
    expect(maps()).toHaveLength(1);
    fireEvent.click(screen.getByText("Toggle 1"));
    fireEvent.click(screen.getByText("Toggle 2"));
    fireEvent.click(screen.getByText("Toggle 3"));
    expect(maps()).toHaveLength(1);
    await waitFor(() => expect(maps()).toHaveLength(2), { timeout: 2000 });
    expect(new URL(maps()[1], "http://example.test").searchParams.get("overall")).toBe("4,5,unrated");
  });
});
