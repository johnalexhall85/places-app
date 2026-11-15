import { useEffect, useId, useState } from "react";
import { API_BASE } from "../config/apiBase";

export function placeProfileHref(place) {
  return place.type === "state" ? `/community/state/${place.geoid}` : `/community/county/${place.geoid}`;
}

function normalize(result) {
  return result.type === "state"
    ? { type: "state", geoid: result.state_geoid || result.geoid, name: result.name, label: `${result.name} · State` }
    : { type: "county", geoid: result.county_fips, name: result.name, label: `${result.name} County, ${result.state_abbr}` };
}

// The home-page place search. By default a choice opens the profile; a map passes onSelect to zoom instead.
export default function PlaceSearch({ label = "Find a county or state", submitLabel = "View profile", onSelect, variant = "hero" }) {
  const inputId = useId();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      setStatus("");
      return undefined;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`${API_BASE}/community/search?q=${encodeURIComponent(query)}&limit=8`, { signal: controller.signal });
        if (!response.ok) throw new Error("Search is unavailable right now.");
        const matches = (await response.json()).map(normalize);
        setResults(matches);
        setStatus(matches.length ? `${matches.length} places found` : "No places found");
      } catch (error) {
        if (error.name !== "AbortError") setStatus(error.message);
      }
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query]);

  function choose(place, event) {
    if (!place) return;
    if (!onSelect) {
      if (!event || event.type === "submit") window.location.assign(placeProfileHref(place));
      return;
    }
    event?.preventDefault();
    setQuery(place.label.replace(" · State", ""));
    setResults([]);
    setStatus("");
    onSelect(place);
  }

  function submit(event) {
    event.preventDefault();
    const value = query.trim();
    const state = /^\d{2}$/.test(value) ? { type: "state", geoid: value, name: value, label: value } : null;
    const county = /^\d{5}$/.test(value) ? { type: "county", geoid: value, name: value, label: value } : null;
    choose(state || county || results[0], event);
  }

  return (
    <div className={`community-search community-search-${variant}`}>
      <form onSubmit={submit} role="search">
        <label htmlFor={inputId}>{label}</label>
        <div className="community-search-row">
          <input id={inputId} value={query} onChange={(event) => setQuery(event.target.value)}
            autoComplete="off" placeholder="State or county name, or FIPS code" />
          <button type="submit">{submitLabel}</button>
        </div>
      </form>
      <p className="community-search-status" aria-live="polite">{status}</p>
      {results.length > 0 && (
        <ul className="community-search-results" aria-label="Place matches">
          {results.map((place) => <li key={`${place.type}:${place.geoid}`}>
            <a href={placeProfileHref(place)} onClick={(event) => choose(place, event)}>
              {place.type === "state" ? `${place.name} · ${onSelect ? "State" : "State profile"}` : place.label} <span>{place.geoid}</span>
            </a>
          </li>)}
        </ul>
      )}
    </div>
  );
}
