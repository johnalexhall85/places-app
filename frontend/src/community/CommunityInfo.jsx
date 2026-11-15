import { useEffect, useState } from "react";
import { API_BASE } from "../config/apiBase";
import { CommunityShell } from "./CommunityPages";
import { FUNDING_METHODOLOGY_INTRO, FUNDING_METHODOLOGY_SECTIONS } from "../content/fundingMethodology";

export function CommunityAbout() {
  useEffect(() => { document.title = "About CHIP | CHIP"; }, []);
  return <CommunityShell><div className="community-wrap community-info">
    <p className="community-eyebrow">About the project</p>
    <h1>Public data for a clearer view of communities</h1>
    <p className="community-info-lede">CHIP, the Community Health Intelligence Platform, brings published health, community, environment, and public funding data together around a place or question.</p>
    <div className="community-info-grid">
      <section><h2>Start with a county</h2><p>Find a county to see each available indicator with its source, observation period, population, published uncertainty, and release. Open the source map to explore its geography, compare up to four counties, or export a cited briefing.</p></section>
      <section><h2>Explore a topic</h2><p>Seven topic views group related measures without turning unlike sources into one score. A topic links to source maps and states what the measures and mapped locations cannot establish.</p></section>
      <section><h2>Use the evidence carefully</h2><p>CHIP displays source-published values. It keeps missing and suppressed values distinct from a published zero. Different measures may describe different people and years; a mapped facility location does not establish access or service capacity.</p></section>
    </div>
    <p><a href="/methodology">Read how CHIP selects, displays, and cites data →</a></p>
  </div></CommunityShell>;
}

export function CommunityMethodology() {
  const [catalog, setCatalog] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    document.title = "Data methodology | CHIP";
    const controller = new AbortController();
    fetch(`${API_BASE}/community/catalog`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Current source releases are unavailable right now.");
        return response.json();
      })
      .then(setCatalog)
      .catch((failure) => { if (failure.name !== "AbortError") setError(failure.message); });
    return () => controller.abort();
  }, []);
  return <CommunityShell><div className="community-wrap community-info">
    <p className="community-eyebrow">Data transparency</p>
    <h1>How CHIP uses published data</h1>
    <p className="community-info-lede">The county profile reads the active, reviewed release of each source. Every indicator carries its own source, period, population, status, uncertainty, and release ID. Exports use the same published profile values.</p>
    <section><h2>Values and comparisons</h2><p>CHIP does not fill gaps, calculate county values from tracts, or average unlike measures. A comparison places the same published measure alongside selected counties without a rank or composite score. State estimates appear only when the source publishes them.</p></section>
    <section><h2>Missing values and uncertainty</h2><p>A published zero is shown as zero. Missing, suppressed, not covered, and not published values keep the source or release status text. PLACES displays its published 95% confidence interval; ACS displays its 90% margin of error. Other sources may publish no uncertainty for these measures.</p></section>
    <section><h2>Maps and mapped locations</h2><p>County and tract shapes are shown at their source's boundary vintage. A tract pattern map shows individual published tract estimates; its colors compare values only within the selected county. Health center, nursing home, and TRI locations show records mapped inside a boundary. Their counts and positions do not measure access, capacity, exposure, or quality.</p></section>
    <section><h2>Current source releases</h2>
      {error && <p role="alert">{error}</p>}
      {!catalog && !error && <p role="status">Loading release information…</p>}
      {catalog && <ul className="community-release-list">{catalog.products.map((product) => <li key={product.product}>
        <strong>{product.name}</strong> · {product.publisher} · {product.published ? `active source release ${product.release.source_release_id}` : "no active published release"}
        {product.landing_page && <> · <a href={product.landing_page}>Source page</a></>}
      </li>)}</ul>}
    </section>
    <section id="funding-methodology"><h2>CDC funding methodology</h2>
      <p>The <a href="/cdc-funding">funding pages</a> follow their own methods, separate from the release-pinned indicators above. {FUNDING_METHODOLOGY_INTRO}</p>
      {FUNDING_METHODOLOGY_SECTIONS.map((section) => <div className="community-funding-method" key={section.title}>
        <h3>{section.title}</h3>
        {(section.paragraphs || []).map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
        {section.bullets?.length > 0 && <ul>{section.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}</ul>}
      </div>)}
    </section>
    <p>Check each indicator's source line for its period and population. <a href="/topics">Explore topics →</a></p>
  </div></CommunityShell>;
}
