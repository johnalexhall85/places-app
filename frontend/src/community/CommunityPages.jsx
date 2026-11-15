import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "../config/apiBase";
import pdoMark from "../assets/brand/pdo-observatory-mark.png";
import Footer from "../components/Footer";
import "./community.css";

const SHOWCASE = [
  { geoid: "37145", name: "Person County", state: "North Carolina", note: "A small county with seven tracts" },
  { geoid: "54039", name: "Kanawha County", state: "West Virginia", note: "A mid-size Appalachian county" },
  { geoid: "06019", name: "Fresno County", state: "California", note: "A large county with urban and agricultural areas" },
];

const TOPICS = [
  { slug: "health-conditions", title: "Health conditions", copy: "Chronic disease and mental health estimates as releases become available.", map: "/area/places-2025" },
  { slug: "prevention-and-access", title: "Prevention and access", copy: "Dental visits and insurance coverage for the populations surveyed.", map: "/area/places-2025" },
  { slug: "health-care-resources", title: "Health care resources", copy: "Workforce, hospitals, health centers, and nursing homes.", map: "/area/ahrf" },
  { slug: "community-conditions", title: "Community conditions", copy: "Income, housing, broadband, and transportation context.", map: "/area/clh" },
  { slug: "food-environment", title: "Food environment", copy: "Published food access and outlet measures, each with its own year.", map: "/area/usda-fea" },
  { slug: "environment", title: "Environment", copy: "Annual air quality summaries and TRI reporting facilities.", map: "/area/epa-aqi" },
  { slug: "medicare-use-and-spending", title: "Medicare use and spending", copy: "Original Medicare beneficiaries, use, spending, and readmissions.", map: "/area/cms-gv" },
];

const MAP_ROUTES = {
  places: "/area/places-2025",
  acs: "/area/acs-2024",
  ahrf: "/area/ahrf",
  clh: "/area/clh",
  cms_gv: "/area/cms-gv",
  epa_aqi: "/area/epa-aqi",
  usda_fea: "/area/usda-fea",
};

export function CommunityShell({ children }) {
  return (
    <div className="community-app">
      <a className="community-skip" href="#main">Skip to main content</a>
      <header className="community-header">
        <a className="community-brand" href="/" aria-label="CHIP home">
          <img src={pdoMark} alt="" width="44" height="44" />
          <span><strong>PUBLIC DATA OBSERVATORY</strong><small>CHIP · Community Health Intelligence Platform</small></span>
        </a>
        <nav aria-label="Main navigation">
          <a href="/">Home</a>
          <a href="/#topics-heading">Topics</a>
          <a href="/compare">Compare</a>
          <a href="/explore/map">Explore data</a>
          <a href="/cdc-funding">Funding</a>
        </nav>
      </header>
      <main id="main">{children}</main>
      <Footer />
    </div>
  );
}

function CountySearch({ label = "Find a county" }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      setStatus("");
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`${API_BASE}/community/search?q=${encodeURIComponent(query)}&limit=8`, { signal: controller.signal });
        if (!response.ok) throw new Error("Search is unavailable right now.");
        const matches = await response.json();
        setResults(matches);
        setStatus(matches.length ? `${matches.length} counties found` : "No counties found");
      } catch (error) {
        if (error.name !== "AbortError") setStatus(error.message);
      }
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query]);

  function submit(event) {
    event.preventDefault();
    const geoid = /^\d{5}$/.test(query.trim()) ? query.trim() : results[0]?.county_fips;
    if (geoid) window.location.assign(`/community/county/${geoid}`);
  }

  return (
    <div className="community-search">
      <form onSubmit={submit} role="search">
        <label htmlFor="community-county-query">{label}</label>
        <div className="community-search-row">
          <input id="community-county-query" value={query} onChange={(event) => setQuery(event.target.value)}
            autoComplete="off" placeholder="County name, state, or five-digit FIPS" />
          <button type="submit">View profile</button>
        </div>
      </form>
      <p className="community-search-status" aria-live="polite">{status}</p>
      {results.length > 0 && (
        <ul className="community-search-results" aria-label="County matches">
          {results.map((result) => <li key={result.county_fips}>
            <a href={`/community/county/${result.county_fips}`}>{result.name} County, {result.state_abbr} <span>{result.county_fips}</span></a>
          </li>)}
        </ul>
      )}
    </div>
  );
}

export function CommunityLanding() {
  useEffect(() => { document.title = "CHIP | Find a community"; }, []);
  return <CommunityShell>
    <section className="community-hero">
      <div className="community-wrap">
        <p className="community-eyebrow">CHIP · Public Data Observatory</p>
        <h1>Start with a place. Follow the evidence.</h1>
        <p className="community-lede">Explore published health, community, environment, and federal funding data with the source, period, and limits beside every indicator.</p>
        <CountySearch />
      </div>
    </section>
    <section className="community-wrap community-section" aria-labelledby="topics-heading">
      <div className="community-section-heading"><p className="community-eyebrow">Explore a question</p><h2 id="topics-heading">Seven ways to explore a community</h2></div>
      <div className="community-topic-grid">
        {TOPICS.map((topic, index) => <a className="community-topic" href={topic.map} key={topic.slug}>
          <span className="community-topic-index">{String(index + 1).padStart(2, "0")}</span>
          <h3>{topic.title}</h3><p>{topic.copy}</p><span className="community-topic-cta">Open data map →</span>
        </a>)}
      </div>
    </section>
    <section className="community-wrap community-section" aria-labelledby="examples-heading">
      <div className="community-section-heading"><p className="community-eyebrow">Places to start</p><h2 id="examples-heading">See a county profile</h2></div>
      <div className="community-example-grid">
        {SHOWCASE.map((place) => <a className="community-example" href={`/community/county/${place.geoid}`} key={place.geoid}>
          <span>{place.state}</span><h3>{place.name}</h3><p>{place.note}</p><strong>View profile →</strong>
        </a>)}
      </div>
      <p className="community-caveat">CHIP shows source-published values. Missing, suppressed, and unavailable values remain visible; no overall health score is calculated.</p>
    </section>
  </CommunityShell>;
}

function sectionFor(row) {
  const id = row.measure_id.toLowerCase();
  if (row.product === "acs") return "people";
  if (row.product === "ahrf") return "care";
  if (row.product === "clh") return id.includes("sogs") ? "food" : "conditions";
  if (row.product === "usda_fea") return "food";
  if (row.product === "epa_aqi") return "environment";
  if (row.product === "cms_gv") return "medicare";
  if (row.product === "places") return id.includes("dental") || id.includes("access2") || id.includes("checkup") ? "prevention" : "health";
  return "conditions";
}

export function formatIndicatorValue(row) {
  if (row.value == null) return row.status_text || "No published value";
  const value = row.storage_scale === "proportion_0_1" ? row.value * 100 : row.value;
  if (row.kind === "currency" || /\bUSD\b|US dollars/i.test(row.unit || "")) return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
  const formatted = new Intl.NumberFormat("en-US", { maximumFractionDigits: Number.isInteger(value) ? 0 : 2 }).format(value);
  if (row.kind === "percent" || row.unit === "percent" || row.unit === "%" || row.storage_scale === "proportion_0_1") return `${formatted}%`;
  return formatted;
}

export function unitText(row) {
  if (row.storage_scale === "proportion_0_1") return "Percent of acute hospital stays";
  if (row.unit === "percent" || row.unit === "%") return null;
  return row.unit;
}

export function uncertaintyText(row) {
  const uncertainty = row.uncertainty || {};
  if (uncertainty.kind === "ci95") return uncertainty.low != null && uncertainty.high != null
    ? `95% confidence interval: ${uncertainty.low}–${uncertainty.high}${row.unit === "percent" ? "%" : ""}`
    : "95% confidence interval unavailable";
  if (uncertainty.kind === "moe90") return uncertainty.moe != null
    ? `90% margin of error: ±${/\bUSD\b|US dollars/i.test(row.unit || "") ? "$" : ""}${new Intl.NumberFormat("en-US").format(uncertainty.moe)}`
    : "90% margin of error unavailable";
  return "No uncertainty published";
}

function Indicator({ row, stateRow }) {
  const hasValue = row.value != null;
  const mapUrl = MAP_ROUTES[row.product];
  return <article className={`community-indicator ${hasValue ? "" : "is-missing"}`}>
    <h3>{row.label}</h3>
    <p className="community-value">{formatIndicatorValue(row)}</p>
    {hasValue && unitText(row) && <p className="community-unit">{unitText(row)}</p>}
    {row.status === "true_zero" && <p className="community-indicator-note">Published zero</p>}
    <p className="community-indicator-note">{uncertaintyText(row)}</p>
    {stateRow && <p className="community-state-value">State estimate: {formatIndicatorValue(stateRow)} <span>({stateRow.period}; {stateRow.population})</span></p>}
    <p className="community-source">Source: {row.source?.publisher} · {row.source?.product_name} · {row.period} · {row.source_release_id}<br />Population: {row.population}</p>
    {row.notes?.estimate_annotation && <p className="community-indicator-note">Source annotation: {row.notes.estimate_annotation}</p>}
    {mapUrl && <a className="community-map-link" href={mapUrl}>Open source map →</a>}
  </article>;
}

function FacilityBlock({ title, block }) {
  if (!block) return null;
  return <div className="community-facility">
    <h3>{title}</h3>
    <p className="community-facility-count">{block.published ? new Intl.NumberFormat("en-US").format(block.count) : "No published release"}</p>
    <p>{block.method}</p>
    <details><summary>See listed locations{block.truncated ? " (first 200)" : ""}</summary>
      <ul>{block.rows.map((item) => <li key={item.site_id || item.ccn || item.facility_id || item.trifd || item.name}>{item.name}{item.city ? ` · ${item.city}` : ""}</li>)}</ul>
    </details>
    {block.limitations?.map((limit) => <p className="community-indicator-note" key={limit}>{limit}</p>)}
  </div>;
}

const SECTIONS = [
  { key: "people", title: "Who lives here", intro: "Published population and household estimates." },
  { key: "health", title: "Health conditions and status", intro: "CDC PLACES estimates describe the named adult population." },
  { key: "prevention", title: "Prevention and access", intro: "Preventive care and insurance coverage for the named populations." },
  { key: "care", title: "Access to care and resources", intro: "Workforce and hospital counts from HRSA, with mapped facility locations below." },
  { key: "conditions", title: "Community conditions", intro: "Housing, broadband, transportation, and other community measures." },
  { key: "food", title: "Food environment", intro: "Published measures have different observation years; read each source line." },
  { key: "environment", title: "Environment", intro: "Annual AQI summarizes monitoring reports; no report is not clean air." },
  { key: "medicare", title: "Medicare use and spending", intro: "These values describe Original Medicare beneficiaries, not all residents." },
];

export function CommunityCounty({ geoid }) {
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setProfile(null);
    setError("");
    fetch(`${API_BASE}/community/county/${geoid}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 404 ? "County not found." : "This profile is unavailable right now.");
        return response.json();
      })
      .then((body) => { setProfile(body); document.title = `${body.area.name} County | CHIP`; })
      .catch((failure) => { if (failure.name !== "AbortError") setError(failure.message); });
    return () => controller.abort();
  }, [geoid]);

  const bySection = useMemo(() => {
    const groups = Object.fromEntries(SECTIONS.map((section) => [section.key, []]));
    for (const row of profile?.values || []) groups[sectionFor(row)].push(row);
    return groups;
  }, [profile]);
  const stateValues = useMemo(() => new Map((profile?.state_values || []).map((row) => [`${row.product}:${row.measure_id}`, row])), [profile]);

  return <CommunityShell>
    <div className="community-wrap community-profile">
      <a className="community-back" href="/">← Find another place</a>
      {error && <div className="community-message" role="alert">{error}</div>}
      {!profile && !error && <div className="community-message" role="status">Loading county profile…</div>}
      {profile && <>
        <header className="community-profile-head" data-testid="profile-ready">
          <p className="community-eyebrow">County profile · {profile.area.boundary_vintage}</p>
          <h1>{profile.area.name} County, {profile.area.state_name}</h1>
          <p>Published indicators and facility locations for county GEOID {profile.area.geoid}. Each indicator keeps its own period, population, source, and release.</p>
          <div className="community-actions">
            <a href={`${API_BASE}/community/county/${geoid}/csv`} download>Download indicator CSV</a>
            <a href={`${API_BASE}/community/county/${geoid}/pdf`} download>Download PDF briefing</a>
            <button type="button" onClick={() => navigator.clipboard?.writeText(window.location.href)}>Copy link</button>
            <a href={`/compare?counties=${geoid}`}>Compare counties</a>
          </div>
        </header>
        <nav className="community-section-nav" aria-label="Profile sections">
          {SECTIONS.filter((section) => bySection[section.key]?.length).map((section) => <a href={`#${section.key}`} key={section.key}>{section.title}</a>)}
          <a href="#facilities">Facilities</a><a href="#limitations">What this data cannot tell you</a>
        </nav>
        {SECTIONS.map((section) => bySection[section.key]?.length > 0 && <section className="community-profile-section" id={section.key} key={section.key}>
          <div className="community-section-heading"><h2>{section.title}</h2><p>{section.intro}</p></div>
          <div className="community-indicator-grid">{bySection[section.key].map((row) => <Indicator key={`${row.product}:${row.measure_id}`} row={row} stateRow={stateValues.get(`${row.product}:${row.measure_id}`)} />)}</div>
        </section>)}
        <section className="community-profile-section" id="facilities">
          <div className="community-section-heading"><h2>Mapped facility locations</h2><p>These are source-listed locations inside the county boundary, not a measure of access, capacity, exposure, or quality.</p></div>
          <div className="community-facility-grid">
            <FacilityBlock title="HRSA health center sites" block={profile.facilities.health_centers} />
            <FacilityBlock title="CMS nursing homes" block={profile.facilities.nursing_homes} />
            <FacilityBlock title="TRI reporting facilities" block={profile.facilities.tri_facilities} />
          </div>
        </section>
        <section className="community-profile-section community-limits" id="limitations">
          <h2>What this data cannot tell you</h2>
          <ul>{profile.limitations.map((limit) => <li key={limit}>{limit}</li>)}</ul>
          <p>Some sources do not publish a value for every county. Missing, suppressed, and not published are distinct from a published zero.</p>
          <p>Older SVI, FEMA NRI, and HPSA layers are available as <a href="/explore/map">additional context on the legacy map</a>; they are not part of this release-pinned indicator table.</p>
          <p>Explore <a href="/cdc-funding">public-health funding</a> separately. The funding view is state-level and follows its own methodology.</p>
        </section>
      </>}
    </div>
  </CommunityShell>;
}
