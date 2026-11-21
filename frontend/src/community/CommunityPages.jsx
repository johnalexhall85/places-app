import { Fragment, useEffect, useMemo, useState } from "react";
import { API_BASE } from "../config/apiBase";
import SiteHeader from "../components/SiteHeader";
import PlaceSearch from "../components/PlaceSearch";
import Footer from "../components/Footer";
import TractPatternMap from "./TractPatternMap";
import { IndicatorChart, SectionChartLegend } from "./charts/IndicatorChart";
import { chartRowMap } from "./charts/scale";
import { useCharts } from "./charts/useCharts";
import SviQuartileBar, {
  SVI_RANGE_TEXT,
  SVI_THEMES,
  sviFormatValue,
  sviIsMissing,
  sviLevel,
} from "../components/SviQuartileBar";
import "./community.css";

const SHOWCASE = [
  { geoid: "37", name: "North Carolina", state: "State profile", note: "Direct BRFSS state survey estimates alongside Census and Medicare", type: "state" },
  { geoid: "37145", name: "Person County", state: "North Carolina", note: "A small county with seven tracts" },
  { geoid: "54039", name: "Kanawha County", state: "West Virginia", note: "A mid-size Appalachian county" },
  { geoid: "06019", name: "Fresno County", state: "California", note: "A large county with urban and agricultural areas" },
];

const TOPICS = [
  { slug: "health-conditions", title: "Health conditions", copy: "Modeled PLACES county estimates and direct BRFSS state survey results.", map: "/area/places-2025" },
  { slug: "prevention-and-access", title: "Prevention and access", copy: "Published prevention measures and distinct Census, PLACES, and BRFSS insurance estimates.", map: "/area/places-2025" },
  { slug: "health-care-resources", title: "Health care resources", copy: "Workforce, hospitals, health centers, and nursing homes.", map: "/area/ahrf" },
  { slug: "community-conditions", title: "Community conditions", copy: "Income, housing, broadband, and transportation context.", map: "/area/clh" },
  { slug: "food-environment", title: "Food environment", copy: "Published food access and outlet measures, each with its own year.", map: "/area/usda-fea" },
  { slug: "environment", title: "Environment", copy: "Annual air quality summaries and TRI reporting facilities.", map: "/area/epa-aqi" },
  { slug: "medicare-use-and-spending", title: "Medicare use and spending", copy: "Original Medicare beneficiaries, use, spending, and readmissions.", map: "/area/cms-gv" },
];

export const MAP_ROUTES = {
  brfss: "/area/brfss",
  places: "/area/places-2025",
  acs: "/area/acs-2024",
  acs_profile: "/area/acs-community",
  ahrf: "/area/ahrf",
  clh: "/area/clh",
  cms_gv: "/area/cms-gv",
  epa_aqi: "/area/epa-aqi",
  usda_fea: "/area/usda-fea",
  cdc_svi: "/area/svi",
  fema_nri: "/area/fema-nri",
};

export const HAZARD_PRODUCTS = new Set(["cdc_svi", "fema_nri"]);

export function useHazards(level, geoid, ready) {
  const [hazards, setHazards] = useState(null);
  useEffect(() => {
    setHazards(null);
    if (!ready) return;
    const controller = new AbortController();
    fetch(`${API_BASE}/community/${level}/${geoid}/hazards`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        if (body && typeof body === "object") setHazards(body);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [level, geoid, ready]);
  return hazards;
}

export function formatSviRank(cell) {
  if (!cell) return "Not available";
  if (sviIsMissing(cell.value, cell.status)) return cell.status_text || "Not available";
  return sviFormatValue(cell.value);
}

export function formatNriValue(row) {
  if (!row) return "Not available";
  if (row.value == null) return row.status_text || "Not published by FEMA for this area";
  if (row.kind === "currency" || row.storage_scale === "dollars_per_year") {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(row.value);
  }
  if (row.kind === "factor" || row.storage_scale === "multiplier") {
    return Number(row.value).toFixed(2);
  }
  return Number(row.value).toFixed(1);
}

export function formatNriPercentile(cell) {
  if (!cell) return "—";
  if (cell.value == null) return cell.status_text || "Not published by FEMA for this area";
  return Number(cell.value).toFixed(1);
}

function SviRankRow({ label, cell, measureId }) {
  const missing = !cell || sviIsMissing(cell.value, cell.status);
  const level = missing ? null : sviLevel(cell.value, cell.status);
  return (
    <div className="community-svi-row">
      <div className="community-svi-row-head">
        <span className="community-svi-row-label">{label}</span>
        {!missing && (
          <span className="community-svi-row-value">
            <strong>{sviFormatValue(cell.value)}</strong>
            {level && <span className="community-svi-row-phrase"> ({level.phrase})</span>}
          </span>
        )}
      </div>
      {missing ? (
        <p className="community-svi-missing">{cell?.status_text || "Not available"}</p>
      ) : (
        <SviQuartileBar value={cell.value} status={cell.status} measureId={measureId} />
      )}
    </div>
  );
}

export function CountySviSection({ geoid, stateGeoid, stateName, rows, source }) {
  if (!rows?.length) return null;
  const rowsById = new Map(rows.map((row) => [row.measure_id, row]));
  const orderedCards = SVI_THEMES
    .map((theme) => ({ theme, row: rowsById.get(theme.baseId) }))
    .filter(({ row }) => Boolean(row));
  if (!orderedCards.length) return null;
  const stateLabel = stateName ? `Within ${stateName}` : "Within state";
  const resolvedStateGeoid = stateGeoid || (String(geoid || "").length >= 2 ? String(geoid).slice(0, 2) : "");
  const citation = source?.citation || rows[0]?.citation;
  return <section className="community-profile-section community-hazard-section" id="svi">
    <div className="community-section-heading">
      <h2>Social vulnerability (CDC/ATSDR SVI 2022)</h2>
      <p>A rank of 0.85 means 85% of counties in the nation (or state) are less vulnerable.</p>
    </div>
    <div className="community-svi-grid">
      {orderedCards.map(({ theme, row }) => {
        const nationalMapUrl = `/area/svi?measure_id=${encodeURIComponent(theme.baseId)}&scope=us&focus=county:${encodeURIComponent(geoid)}`;
        const stateMapUrl = resolvedStateGeoid
          ? `/area/svi?measure_id=${encodeURIComponent(theme.stateId)}&scope=state&state=${encodeURIComponent(resolvedStateGeoid)}&focus=county:${encodeURIComponent(geoid)}`
          : null;
        return (
          <article className="community-svi-card" key={theme.baseId}>
            <h3>{theme.title}</h3>
            <SviRankRow label="Among all U.S. counties" cell={row.us} measureId={theme.baseId} />
            <SviRankRow label={stateLabel} cell={row.state} measureId={theme.baseId} />
            <footer className="community-svi-card-footer">
              <p className="community-svi-range">{SVI_RANGE_TEXT}</p>
              <div className="community-svi-links">
                <a className="community-map-link" href={nationalMapUrl}>View on map</a>
                {stateMapUrl && (
                  <a className="community-map-link" href={stateMapUrl}>View within {stateName || "state"}</a>
                )}
              </div>
            </footer>
          </article>
        );
      })}
    </div>
    {citation && <p className="community-source community-svi-source">
      {citation}
      {source?.landing_page && <> · <a href={source.landing_page} target="_blank" rel="noreferrer">CDC/ATSDR documentation</a></>}
    </p>}
  </section>;
}

export const NRI_RISK_SPCTL_NOTE =
  "FEMA's v1.20 file repeats the national risk score in its risk state-percentile field for every county and tract, so CHIP does not show a within-state percentile for the overall risk score.";

export function NriSection({ level, geoid, rows, source }) {
  if (!rows?.length) return null;
  const isState = level === "state";
  const citation = source?.citation || rows[0]?.citation;
  const mapUrl = `/area/fema-nri?focus=${encodeURIComponent(level)}:${encodeURIComponent(geoid)}`;
  const hasRiskNoSpctl = !isState && rows.some((row) => row.measure_id === "risk_score" && !row.state_percentile);
  return <section className="community-profile-section community-hazard-section" id="fema-nri">
    <div className="community-section-heading">
      <h2>Natural hazard risk (FEMA NRI)</h2>
      {isState ? <>
        <p>FEMA publishes no state-level risk score; see county and tract values on the map.</p>
        <p className="community-hazard-direction">Expected annual loss score runs from 0 to 100 among states; higher values mean greater modeled natural-hazard loss.</p>
      </> : <p>Scores and percentiles run from 0 to 100. Higher community resilience is better; for all other measures, a higher value means greater modeled natural-hazard risk, loss, or vulnerability.</p>}
    </div>
    <div className="community-hazard-card">
      <table className="community-hazard-table">
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th scope="col">{isState ? "Score / Dollars" : "Score (0–100)"}</th>
            <th scope="col">FEMA rating</th>
            {!isState && <th scope="col">Within-state percentile</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const valueMissing = row.value == null;
            const spctlMissing = row.state_percentile != null && row.state_percentile.value == null;
            const isRiskNoSpctl = !isState && row.measure_id === "risk_score" && !row.state_percentile;
            return <tr key={row.measure_id}>
              <th scope="row">
                {row.label}
                {row.direction === "higher_better" && <span className="community-hazard-badge">higher is better</span>}
              </th>
              <td data-label={isState ? "Score / Dollars" : "Score (0–100)"} className={valueMissing ? "community-hazard-missing" : "community-hazard-num"}>
                {formatNriValue(row)}
              </td>
              <td data-label="FEMA rating">{row.rating || "—"}</td>
              {!isState && <td
                data-label="Within-state percentile"
                className={spctlMissing ? "community-hazard-missing" : "community-hazard-num"}
                aria-describedby={isRiskNoSpctl ? "nri-risk-spctl-note" : undefined}
              >
                {formatNriPercentile(row.state_percentile)}
                {isRiskNoSpctl && <sup className="community-hazard-footnote-mark" aria-hidden="true">*</sup>}
              </td>}
            </tr>;
          })}
        </tbody>
      </table>
      {hasRiskNoSpctl && <p id="nri-risk-spctl-note" className="community-hazard-footnote">
        <span aria-hidden="true">* </span>{NRI_RISK_SPCTL_NOTE}
      </p>}
      {citation && <p className="community-source">
        {citation}
        {source?.landing_page && <> · <a href={source.landing_page} target="_blank" rel="noreferrer">FEMA OpenFEMA data</a></>}
      </p>}
      <p className="community-hazard-actions">
        <a className="community-map-link" href={mapUrl}>Explore FEMA NRI on the map →</a>
      </p>
    </div>
  </section>;
}

export function CommunityShell({ children }) {
  return (
    <div className="community-app">
      <SiteHeader />
      <main id="main">{children}</main>
      <div className="community-meta-links"><a href="/about">About CHIP</a><a href="/methodology">Data methodology</a></div>
      <Footer />
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
        <PlaceSearch />
      </div>
    </section>
    <section className="community-wrap community-section" aria-labelledby="topics-heading">
      <div className="community-section-heading"><p className="community-eyebrow">Explore a question</p><h2 id="topics-heading">Seven ways to explore a community</h2></div>
      <div className="community-topic-grid">
        {TOPICS.map((topic, index) => <a className="community-topic" href={`/topics/${topic.slug}`} key={topic.slug}>
          <span className="community-topic-index">{String(index + 1).padStart(2, "0")}</span>
          <h3>{topic.title}</h3><p>{topic.copy}</p><span className="community-topic-cta">Explore topic →</span>
        </a>)}
      </div>
    </section>
    <section className="community-wrap community-section" aria-labelledby="examples-heading">
      <div className="community-section-heading"><p className="community-eyebrow">Places to start</p><h2 id="examples-heading">See a place profile</h2></div>
      <div className="community-example-grid">
        {SHOWCASE.map((place) => <a className="community-example" href={place.type === "state" ? `/community/state/${place.geoid}` : `/community/county/${place.geoid}`} key={place.geoid}>
          <span>{place.state}</span><h3>{place.name}</h3><p>{place.note}</p><strong>View profile →</strong>
        </a>)}
      </div>
      <p className="community-caveat">CHIP shows source-published values. Missing, suppressed, and unavailable values remain visible; no overall health score is calculated.</p>
      <p><a href="/district/cd/5401">Explore the West Virginia 1st Congressional District briefing →</a></p>
    </section>
  </CommunityShell>;
}

function sectionFor(row) {
  const id = row.measure_id.toLowerCase();
  if (row.product === "acs" || row.product === "acs_profile") return "people";
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
    : uncertainty.label || "90% margin of error unavailable";
  return "No uncertainty published";
}

export function SurveyCompanion({ row }) {
  if (!row) return null;
  return <div className="community-survey-companion">
    <strong>State survey estimate (BRFSS)</strong>
    <p>{formatIndicatorValue(row)} · {row.period} · {row.population}</p>
    <p>{uncertaintyText(row)}</p>
    <p className="community-source">Source: {row.source?.publisher} · {row.source?.product_name} · {row.period} · {row.source_release_id}</p>
    <small>Direct state survey estimate for context; the county PLACES estimate is modeled from BRFSS.</small>
  </div>;
}

// Map links from a profile open the map zoomed to that place with it outlined.
export function mapFocus(level, geoid) {
  return level && geoid ? `&focus=${level}:${geoid}` : "";
}

export function Indicator({ row, stateRow, surveyCompanion, chart, areaLabel, stateLabel }) {
  const hasValue = row.value != null;
  const mapUrl = MAP_ROUTES[row.product] ? `${MAP_ROUTES[row.product]}?measure_id=${encodeURIComponent(row.measure_id)}${row.level === "cd" ? "&geography=cd" : ""}${mapFocus(row.level, row.geoid)}` : null;
  return <article className={`community-indicator ${hasValue ? "" : "is-missing"}`}>
    <h3>{row.label}</h3>
    <p className="community-value">{formatIndicatorValue(row)}</p>
    {hasValue && unitText(row) && <p className="community-unit">{unitText(row)}</p>}
    {chart && <IndicatorChart row={chart} areaLabel={areaLabel} stateLabel={stateLabel} />}
    {row.status === "true_zero" && <p className="community-indicator-note">Published zero</p>}
    <p className="community-indicator-note">{uncertaintyText(row)}</p>
    {stateRow && <p className="community-state-value">State estimate: {formatIndicatorValue(stateRow)} <span>({stateRow.period}; {stateRow.population}; {stateRow.source?.publisher}; release {stateRow.source_release_id})</span></p>}
    {row.product === "places" && <SurveyCompanion row={surveyCompanion} />}
    <p className="community-source">Source: {row.source?.publisher} · {row.source?.product_name} · {row.period} · {row.source_release_id}<br />Population: {row.population}{row.source?.credit && <><br />{row.source.credit}</>}</p>
    {row.notes?.estimate_annotation && <p className="community-indicator-note">Source annotation: {row.notes.estimate_annotation}</p>}
    {mapUrl && <a className="community-map-link" href={mapUrl}>Open source map →</a>}
  </article>;
}

export function FacilityBlock({ title, block }) {
  if (!block) return null;
  return <div className="community-facility">
    <h3>{title}</h3>
    <p className="community-facility-count">{block.published ? new Intl.NumberFormat("en-US").format(block.count) : "No published release"}</p>
    <p>{block.method}</p>
    {block.release && <p className="community-source">Source: {title} · {block.release.source_release_id} · release {block.release.release_id}</p>}
    <details><summary>See listed locations{block.truncated ? " (first 200)" : ""}</summary>
      <ul>{block.rows.map((item) => <li key={item.site_id || item.ccn || item.facility_id || item.trifd || item.name}>{item.name}{item.city ? ` · ${item.city}` : ""}</li>)}</ul>
    </details>
    {block.limitations?.map((limit) => <p className="community-indicator-note" key={limit}>{limit}</p>)}
  </div>;
}

const SECTIONS = [
  { key: "people", title: "Who lives here", intro: "Published Census Bureau population and community estimates. The ACS uninsured estimate covers all ages; the PLACES insurance estimate covers modeled adults aged 18–64." },
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
  const [catalog, setCatalog] = useState(null);
  const [selectedTractKey, setSelectedTractKey] = useState("acs:B19013_001E");
  const [error, setError] = useState("");
  const charts = useCharts("county", geoid, !!profile);
  const hazards = useHazards("county", geoid, !!profile);
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
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/community/catalog`, { signal: controller.signal })
      .then(async (response) => response.ok ? response.json() : null)
      .then(setCatalog)
      .catch((failure) => { if (failure.name !== "AbortError") setCatalog(null); });
    return () => controller.abort();
  }, []);

  const bySection = useMemo(() => {
    const groups = Object.fromEntries(SECTIONS.map((section) => [section.key, []]));
    for (const row of profile?.values || []) {
      if (HAZARD_PRODUCTS.has(row.product)) continue;
      groups[sectionFor(row)].push(row);
    }
    return groups;
  }, [profile]);
  const stateValues = useMemo(() => new Map((profile?.state_values || []).map((row) => [`${row.product}:${row.measure_id}`, row])), [profile]);
  const chartRows = useMemo(() => chartRowMap(charts), [charts]);
  const countyLabel = profile ? (/County|Parish|Borough|Planning Region|Municipality|Census Area|City$/i.test(profile.area.name) ? profile.area.name : `${profile.area.name} County`) : "";
  const tractMeasures = useMemo(() => {
    const capable = new Set((catalog?.measures || []).filter((measure) => measure.levels?.includes("tract") && measure.published && !HAZARD_PRODUCTS.has(measure.product))
      .map((measure) => `${measure.product}:${measure.measure_id}`));
    return (profile?.values || []).filter((row) => !HAZARD_PRODUCTS.has(row.product) && capable.has(`${row.product}:${row.measure_id}`));
  }, [catalog, profile]);
  const selectedTractRow = tractMeasures.find((row) => `${row.product}:${row.measure_id}` === selectedTractKey) || tractMeasures[0];

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
          <p><a href={`/community/state/${profile.area.state_geoid}`}>Explore the {profile.area.state_name} state profile →</a></p>
          <div className="community-actions">
            <a href={`${API_BASE}/community/county/${geoid}/csv`} download>Download indicator CSV</a>
            <a href={`${API_BASE}/community/county/${geoid}/pdf`} download>Download PDF briefing</a>
            <button type="button" onClick={() => navigator.clipboard?.writeText(window.location.href)}>Copy link</button>
            <a href={`/compare?counties=${geoid}`}>Compare counties</a>
          </div>
        </header>
        <nav className="community-section-nav" aria-label="Profile sections">
          {SECTIONS.map((section) => <Fragment key={section.key}>
            {bySection[section.key]?.length > 0 && <a href={`#${section.key}`}>{section.title}</a>}
            {section.key === "environment" && <>
              {hazards?.svi?.length > 0 && <a href="#svi">Social vulnerability (CDC/ATSDR SVI 2022)</a>}
              {hazards?.nri?.length > 0 && <a href="#fema-nri">Natural hazard risk (FEMA NRI)</a>}
            </>}
          </Fragment>)}
          {tractMeasures.length > 0 && <a href="#tract-patterns">Tract patterns</a>}
          <a href="#facilities">Facilities</a><a href="#limitations">What this data cannot tell you</a>
        </nav>
        {SECTIONS.map((section) => {
          const rows = bySection[section.key] || [];
          const sectionChartRows = rows
            .map((row) => chartRows.get(`${row.product}:${row.measure_id}`))
            .filter(Boolean);
          const hazardBlocks = section.key === "environment" ? <>
            <CountySviSection geoid={geoid} stateGeoid={profile.area.state_geoid} stateName={profile.area.state_name} rows={hazards?.svi} source={hazards?.sources?.cdc_svi} />
            <NriSection level="county" geoid={geoid} rows={hazards?.nri} source={hazards?.sources?.fema_nri} />
          </> : null;
          if (!rows.length && !hazardBlocks) return null;
          return <Fragment key={section.key}>
            {rows.length > 0 && <section className="community-profile-section" id={section.key}>
              <div className="community-section-heading">
                <h2>{section.title}</h2>
                <p>{section.intro}</p>
                <SectionChartLegend rows={sectionChartRows} areaLabel={countyLabel} stateLabel={profile.area.state_name} />
              </div>
              <div className="community-indicator-grid">{rows.map((row) => <Indicator key={`${row.product}:${row.measure_id}`} row={row} stateRow={stateValues.get(`${row.product}:${row.measure_id}`)} surveyCompanion={profile.survey_companions?.[row.measure_id]} chart={chartRows.get(`${row.product}:${row.measure_id}`)} areaLabel={countyLabel} stateLabel={profile.area.state_name} />)}</div>
            </section>}
            {hazardBlocks}
          </Fragment>;
        })}
        {selectedTractRow && <section className="community-profile-section" id="tract-patterns">
          <div className="community-section-heading"><h2>Within-county tract patterns</h2><p>Each shape is a source-published tract estimate. Darker blues show higher values for the selected measure within this county.</p></div>
          <div className="community-tract-controls">
            <label htmlFor="community-tract-measure">Tract measure</label>
            <select id="community-tract-measure" value={`${selectedTractRow.product}:${selectedTractRow.measure_id}`} onChange={(event) => setSelectedTractKey(event.target.value)}>
              {tractMeasures.map((row) => <option key={`${row.product}:${row.measure_id}`} value={`${row.product}:${row.measure_id}`}>{row.label} · {row.period}</option>)}
            </select>
            <a href={`${MAP_ROUTES[selectedTractRow.product]}?measure_id=${encodeURIComponent(selectedTractRow.measure_id)}${mapFocus("county", geoid)}`}>Open full map →</a>
          </div>
          <TractPatternMap area={profile.area} row={selectedTractRow} />
        </section>}
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
          <p>Explore <a href="/cdc-funding">public-health funding</a> separately. The funding view is state-level and follows its own methodology.</p>
        </section>
      </>}
    </div>
  </CommunityShell>;
}
