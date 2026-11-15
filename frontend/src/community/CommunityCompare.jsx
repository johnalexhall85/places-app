import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "../config/apiBase";
import { CommunityShell, SurveyCompanion, formatIndicatorValue, uncertaintyText, unitText } from "./CommunityPages";

const EXAMPLE_COUNTIES = ["37145", "54039", "06019"];

function fromUrl() {
  const query = new URLSearchParams(window.location.search).get("counties") || "";
  return [...new Set(query.split(",").map((part) => part.trim()).filter((part) => /^\d{5}$/.test(part)))].slice(0, 4);
}

function alignedRows(values) {
  const grouped = new Map();
  for (const row of values) {
    const key = `${row.product}:${row.measure_id}`;
    if (!grouped.has(key)) grouped.set(key, { key, exemplar: row, byGeoid: new Map() });
    grouped.get(key).byGeoid.set(row.geoid, row);
  }
  return [...grouped.values()];
}

export default function CommunityCompare() {
  const [selected, setSelected] = useState(fromUrl);
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState([]);
  const [searchError, setSearchError] = useState("");

  useEffect(() => { document.title = "Compare counties | CHIP"; }, []);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (selected.length) params.set("counties", selected.join(","));
    else params.delete("counties");
    window.history.replaceState(null, "", `${window.location.pathname}${params.size ? `?${params}` : ""}`);
    if (!selected.length) { setComparison(null); setError(""); return; }
    const controller = new AbortController();
    setComparison(null);
    setError("");
    fetch(`${API_BASE}/community/compare?geoids=${encodeURIComponent(selected.join(","))}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("The comparison is unavailable right now.");
        return response.json();
      })
      .then(setComparison)
      .catch((failure) => { if (failure.name !== "AbortError") setError(failure.message); });
    return () => controller.abort();
  }, [selected]);

  useEffect(() => {
    if (query.trim().length < 2) { setMatches([]); setSearchError(""); return; }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      fetch(`${API_BASE}/community/search?q=${encodeURIComponent(query)}&limit=8`, { signal: controller.signal })
        .then(async (response) => { if (!response.ok) throw new Error("County search is unavailable."); return response.json(); })
        .then(setMatches)
        .catch((failure) => { if (failure.name !== "AbortError") setSearchError(failure.message); });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query]);

  const rows = useMemo(() => alignedRows(comparison?.values || []), [comparison]);
  const maxReached = selected.length >= 4;

  function add(geoid) {
    if (!selected.includes(geoid) && !maxReached) setSelected((current) => [...current, geoid]);
    setQuery(""); setMatches([]); setSearchError("");
  }

  return <CommunityShell>
    <div className="community-wrap community-compare">
      <p className="community-eyebrow">County comparison</p>
      <h1>Compare published indicators</h1>
      <p className="community-compare-intro">View up to four counties side by side. Each row keeps the source's measure, population, period, uncertainty, and release. CHIP does not rank places or combine indicators into a score.</p>
      <div className="community-compare-controls">
        <div>
          <label htmlFor="comparison-county-search">Add a county</label>
          <input id="comparison-county-search" value={query} onChange={(event) => setQuery(event.target.value)} disabled={maxReached}
            placeholder={maxReached ? "Four counties selected" : "Search county or state"} autoComplete="off" />
          <p aria-live="polite" className="community-search-status">{searchError || (query.length >= 2 && !matches.length ? "No matches yet" : "")}</p>
          {matches.length > 0 && !maxReached && <ul className="community-compare-matches" aria-label="County matches">
            {matches.filter((match) => match.type !== "state" && !selected.includes(match.county_fips)).map((match) => <li key={match.county_fips}>
              <button type="button" onClick={() => add(match.county_fips)}>{match.name} County, {match.state_abbr} ({match.county_fips})</button>
            </li>)}
          </ul>}
        </div>
        <button type="button" className="community-compare-example" onClick={() => setSelected(EXAMPLE_COUNTIES)}>Compare three showcase counties</button>
      </div>
      {selected.length > 0 && <div className="community-selected" aria-label="Selected counties">
        {selected.map((geoid) => <button type="button" key={geoid} onClick={() => setSelected((current) => current.filter((item) => item !== geoid))}>
          {comparison?.areas.find((area) => area.geoid === geoid)?.name || geoid} <span aria-hidden="true">×</span><span className="sr-only"> remove</span>
        </button>)}
        <button type="button" onClick={() => navigator.clipboard?.writeText(window.location.href)}>Copy comparison link</button>
      </div>}
      {error && <p className="community-message" role="alert">{error}</p>}
      {!selected.length && <p className="community-message">Search for a county or choose the showcase comparison.</p>}
      {selected.length > 0 && !comparison && !error && <p className="community-message" role="status">Loading comparison…</p>}
      {comparison && <>
        <p className="community-compare-count">{comparison.areas.length} counties · {rows.length} published indicator{rows.length === 1 ? "" : "s"}</p>
        <div className="community-compare-scroll" role="region" aria-label="County indicator comparison" tabIndex="0">
          <table className="community-compare-table">
            <thead><tr><th scope="col">Indicator and source</th>
              {comparison.areas.map((area) => <th scope="col" key={area.geoid}>
                <a href={`/community/county/${area.geoid}`}>{area.name} County<br />{area.state_name}</a><small>GEOID {area.geoid}</small>
              </th>)}
            </tr></thead>
            <tbody>{rows.map(({ key, exemplar, byGeoid }) => <tr key={key}>
              <th scope="row"><strong>{exemplar.label}</strong><small>Source: {exemplar.source?.publisher} · {exemplar.source?.product_name}{exemplar.source?.credit ? ` · ${exemplar.source.credit}` : ""}</small></th>
              {comparison.areas.map((area) => {
                const row = byGeoid.get(area.geoid);
                return <td key={area.geoid}>{row && <>
                  <strong className={row.value == null ? "community-compare-missing" : ""}>{formatIndicatorValue(row)}</strong>
                  <small>{unitText(row) || "Percent"} · {row.population}</small>
                  <small>{uncertaintyText(row)}</small>
                  <small>{row.period} · Release {row.source_release_id}</small>
                  {row.product === "places" && <SurveyCompanion row={comparison.survey_companions?.[area.geoid.slice(0, 2)]?.[row.measure_id]} />}
                </>}</td>;
              })}
            </tr>)}</tbody>
          </table>
        </div>
      </>}
    </div>
  </CommunityShell>;
}
