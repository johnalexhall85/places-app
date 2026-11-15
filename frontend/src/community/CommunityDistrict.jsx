import { useEffect, useState } from "react";
import { API_BASE } from "../config/apiBase";
import { CommunityShell, FacilityBlock, Indicator } from "./CommunityPages";

function useJson(path) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError("");
    fetch(`${API_BASE}${path}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(response.status === 404 ? "No published area was found." : "District information is unavailable right now.");
        return response.json();
      })
      .then(setData)
      .catch(failure => { if (failure.name !== "AbortError") setError(failure.message); });
    return () => controller.abort();
  }, [path]);
  return { data, error };
}

export function CommunityDistricts() {
  const { data: states, error } = useJson("/community/districts/states");
  const [state, setState] = useState("54");
  const { data: selection, error: selectionError } = useJson(`/community/districts?state_geoid=${state}`);
  useEffect(() => { document.title = "Congressional districts | CHIP"; }, []);
  return <CommunityShell><div className="community-wrap community-districts">
    <p className="community-eyebrow">119th Congress</p>
    <h1>Find a congressional district</h1>
    <p>Choose a state to open a briefing with Census Bureau district estimates, mapped facilities, and overlapping counties.</p>
    {error && <p role="alert" className="community-message">{error}</p>}
    {!states && !error && <p role="status" className="community-message">Loading states…</p>}
    {states && <><label htmlFor="district-state">State or territory</label>
      <select id="district-state" value={state} onChange={event => setState(event.target.value)}>
        {states.map(item => <option value={item.geoid} key={item.geoid}>{item.name}</option>)}
      </select></>}
    {selectionError && <p role="alert" className="community-message">{selectionError}</p>}
    {!selection && !selectionError && <p role="status" className="community-message">Loading districts…</p>}
    {selection && <ul className="community-district-list">{selection.districts.map(item => <li key={item.geoid}>
      <a href={`/district/cd/${item.geoid}`}>{selection.state.name} · {item.name} ({item.geoid})</a>
    </li>)}</ul>}
  </div></CommunityShell>;
}

export function CommunityDistrict({ geoid }) {
  const { data, error } = useJson(`/community/district/${geoid}`);
  useEffect(() => { document.title = `${data?.area?.name || "District"} | CHIP`; }, [data]);
  const counties = data?.counties?.counties || [];
  return <CommunityShell><div className="community-wrap community-profile community-district">
    <a className="community-back" href="/districts">← Find another district</a>
    {error && <p role="alert" className="community-message">{error}</p>}
    {!data && !error && <p role="status" className="community-message">Loading district briefing…</p>}
    {data && <>
      <header className="community-profile-head" data-testid="district-ready">
        <p className="community-eyebrow">Congressional district briefing · {data.area.boundary_vintage}</p>
        <h1>{data.area.state_name} · {data.area.name}</h1>
        <p>District GEOID {data.area.geoid}. The indicators below are source-published district estimates from the Census Bureau. County links and facility locations give geographic context.</p>
        <div className="community-actions"><button type="button" onClick={() => navigator.clipboard?.writeText(window.location.href)}>Copy link</button>
          <a href={`/area/acs-community?measure_id=poverty_pct&geography=cd&focus=cd:${geoid}`}>Open district source map</a></div>
      </header>
      <section className="community-profile-section" aria-labelledby="district-estimates">
        <div className="community-section-heading"><h2 id="district-estimates">District estimates (Census Bureau)</h2><p>ACS 2020–2024 five-year subject-table estimates for the 119th Congress district boundary. Each measure has its own population and 90% margin of error where published.</p></div>
        {data.values.length ? <div className="community-indicator-grid">{data.values.map(row => <Indicator key={row.measure_id} row={row} />)}</div>
          : <p>No district estimates are published for this boundary.</p>}
      </section>
      <section className="community-profile-section" aria-labelledby="district-facilities">
        <div className="community-section-heading"><h2 id="district-facilities">Mapped facility locations inside this district</h2><p>These are published point locations, not counts of available services or measures of exposure.</p></div>
        <div className="community-facility-grid">
          <FacilityBlock title="HRSA health center sites" block={data.facilities.health_centers} />
          <FacilityBlock title="CMS nursing homes" block={data.facilities.nursing_homes} />
          <FacilityBlock title="TRI reporting facilities" block={data.facilities.tri_facilities} />
        </div>
      </section>
      <section className="community-profile-section" aria-labelledby="district-counties">
        <div className="community-section-heading"><h2 id="district-counties">Counties overlapping this district</h2><p>County profiles are context under each county's own name. Their values are never district estimates.</p></div>
        <p>{data.counties.note}</p>
        <ul className="community-district-list">{counties.map(item => <li key={item.county_geoid}>
          <a href={`/community/county/${item.county_geoid}`}>{item.county_name} County, {item.state_name}</a>
          <span>{item.county_wholly_in_district ? "Wholly inside the district" : `${Math.round(item.county_area_share_in_district * 100)}% of county area inside this district`}</span>
        </li>)}</ul>
      </section>
      <section className="community-profile-section community-limits"><h2>What this briefing cannot tell you</h2>
        <ul>{data.limitations.map(limit => <li key={limit}>{limit}</li>)}</ul>
      </section>
    </>}
  </div></CommunityShell>;
}
