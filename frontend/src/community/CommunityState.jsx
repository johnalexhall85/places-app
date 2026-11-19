import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "../config/apiBase";
import { getStateCodeForFips } from "../utils/stateFundingMap";
import { CommunityShell, FacilityBlock, Indicator } from "./CommunityPages";
import { SectionChartLegend } from "./charts/IndicatorChart";
import { chartRowMap } from "./charts/scale";
import { useCharts } from "./charts/useCharts";

const PREVENTION = new Set([
  "current_smoking", "routine_checkup", "uninsured_18_64", "dental_visit",
  "binge_drinking", "no_leisure_physical_activity", "cost_barrier_to_care",
]);

const SECTIONS = [
  { key: "people", title: "Who lives here", intro: "Census Bureau ACS estimates for income and community characteristics. The ACS uninsured measure covers all ages." },
  { key: "health", title: "Health conditions and status", intro: "Direct state survey estimates from CDC BRFSS for the named adult populations. These are crude prevalence estimates." },
  { key: "prevention", title: "Prevention and access", intro: "Direct state survey estimates from CDC BRFSS. Insurance here covers adults aged 18–64; it differs from the all-age ACS measure and modeled PLACES county measure." },
  { key: "medicare", title: "Medicare use and spending", intro: "These values describe Original Medicare beneficiaries, not all residents." },
];

function sectionFor(row) {
  if (row.product === "acs" || row.product === "acs_profile") return "people";
  if (row.product === "cms_gv") return "medicare";
  return PREVENTION.has(row.measure_id) ? "prevention" : "health";
}

export function CommunityState({ geoid }) {
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState("");
  const charts = useCharts("state", geoid, !!profile);
  useEffect(() => {
    const controller = new AbortController();
    setProfile(null);
    setError("");
    fetch(`${API_BASE}/community/state/${geoid}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 404 ? "State not found." : "This profile is unavailable right now.");
        return response.json();
      })
      .then((body) => { setProfile(body); document.title = `${body.area.name} | CHIP`; })
      .catch((failure) => { if (failure.name !== "AbortError") setError(failure.message); });
    return () => controller.abort();
  }, [geoid]);

  const bySection = useMemo(() => {
    const groups = Object.fromEntries(SECTIONS.map((section) => [section.key, []]));
    for (const row of profile?.values || []) groups[sectionFor(row)].push(row);
    return groups;
  }, [profile]);
  const chartRows = useMemo(() => chartRowMap(charts), [charts]);
  const fundingCode = getStateCodeForFips(geoid);
  const counties = profile?.counties || [];
  const districts = profile?.districts || [];

  return <CommunityShell><div className="community-wrap community-profile community-state-profile">
    <a className="community-back" href="/">← Find another place</a>
    {error && <p className="community-message" role="alert">{error}</p>}
    {!profile && !error && <p className="community-message" role="status">Loading state profile…</p>}
    {profile && <>
      <header className="community-profile-head" data-testid="profile-ready">
        <p className="community-eyebrow">State profile · {profile.area.boundary_vintage}</p>
        <h1>{profile.area.name}</h1>
        <p>Published state indicators and mapped facility locations for state GEOID {profile.area.geoid}. Each indicator keeps its own period, population, uncertainty, source, and release.</p>
        <div className="community-actions">
          <a href={`${API_BASE}/community/state/${geoid}/csv`} download>Download indicator CSV</a>
          <a href={`${API_BASE}/community/state/${geoid}/pdf`} download>Download PDF briefing</a>
          <button type="button" onClick={() => navigator.clipboard?.writeText(window.location.href)}>Copy link</button>
          {fundingCode && <a href={`/cdc-funding/state/${fundingCode}`}>State funding profile</a>}
        </div>
      </header>
      <nav className="community-section-nav" aria-label="Profile sections">
        {SECTIONS.filter((section) => bySection[section.key].length).map((section) => <a href={`#${section.key}`} key={section.key}>{section.title}</a>)}
        <a href="#facilities">Facilities</a><a href="#places">Places in this state</a><a href="#limitations">What this data cannot tell you</a>
      </nav>
      {SECTIONS.map((section) => {
        if (!bySection[section.key].length) return null;
        const sectionChartRows = bySection[section.key]
          .map((row) => chartRows.get(`${row.product}:${row.measure_id}`))
          .filter(Boolean);
        return <section className="community-profile-section" id={section.key} key={section.key}>
          <div className="community-section-heading">
            <h2>{section.title}</h2>
            <p>{section.intro}</p>
            <SectionChartLegend rows={sectionChartRows} areaLabel={profile.area.name} stateLabel={profile.area.name} />
          </div>
          <div className="community-indicator-grid">{bySection[section.key].map((row) => <Indicator key={`${row.product}:${row.measure_id}`} row={row} chart={chartRows.get(`${row.product}:${row.measure_id}`)} areaLabel={profile.area.name} stateLabel={profile.area.name} />)}</div>
        </section>;
      })}
      <section className="community-profile-section" id="facilities">
        <div className="community-section-heading"><h2>Mapped facility locations</h2><p>Source-listed locations within the state boundary. Counts do not measure capacity, access, exposure, or quality.</p></div>
        <div className="community-facility-grid">
          <FacilityBlock title="HRSA health center sites" block={profile.facilities.health_centers} />
          <FacilityBlock title="CMS nursing homes" block={profile.facilities.nursing_homes} />
          <FacilityBlock title="TRI reporting facilities" block={profile.facilities.tri_facilities} />
        </div>
      </section>
      <section className="community-profile-section" id="places">
        <div className="community-section-heading"><h2>Places in this state</h2><p>County profiles and congressional district briefings use their own published estimates. They are not combined into state values.</p></div>
        <details><summary>Browse {counties.length} counties</summary>
          <ul className="community-state-places">{counties.map((item) => <li key={item.geoid}><a href={`/community/county/${item.geoid}`}>{item.name} County</a></li>)}</ul>
        </details>
        <details><summary>Browse {districts.length} congressional districts</summary>
          <ul className="community-state-places">{districts.map((item) => <li key={item.geoid}><a href={`/district/cd/${item.geoid}`}>{item.name}</a></li>)}</ul>
        </details>
        {fundingCode && <p><a href={`/cdc-funding/state/${fundingCode}`}>Explore the {profile.area.name} funding profile →</a></p>}
      </section>
      <section className="community-profile-section community-limits" id="limitations">
        <h2>What this data cannot tell you</h2>
        <ul>{profile.limitations.map((limit) => <li key={limit}>{limit}</li>)}</ul>
        <p>BRFSS is a direct state survey. PLACES county values are modeled estimates; the state figures are not computed from counties. Missing, suppressed, and not published are distinct from a published zero.</p>
      </section>
    </>}
  </div></CommunityShell>;
}
