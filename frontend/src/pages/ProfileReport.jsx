import { useEffect, useMemo, useState } from "react";
import Footer from "../components/Footer";
import Header from "../components/Header";
import { API_BASE } from "../config/apiBase";
import "./ProfileReport.css";
const CHART_PAGE_SIZE = 10;

function toFiniteNumber(value) {
  if (value === null || value === undefined) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatValue(value, unit, precision = 1) {
  const numeric = toFiniteNumber(value);
  if (numeric == null) return "Not available";
  const normalizedUnit = String(unit ?? "").trim().toLowerCase();
  if (["%", "percent", "percentage", "pct"].includes(normalizedUnit)) {
    return `${numeric.toFixed(precision)}%`;
  }
  return `${numeric.toFixed(precision)}${unit ? ` ${unit}` : ""}`;
}

function formatCi(low, high, unit) {
  const lowValue = toFiniteNumber(low);
  const highValue = toFiniteNumber(high);
  if (lowValue == null || highValue == null) return "Not available";
  return `${formatValue(lowValue, unit)} to ${formatValue(highValue, unit)}`;
}

function formatTimestampLabel(value) {
  const text = String(value ?? "").trim();
  if (!text) return "Not available";
  return text.replace("T", " ").replace("Z", "").slice(0, 19);
}

function compareBarData(local, state, us) {
  const points = [
    { key: "local", label: "Local", value: toFiniteNumber(local), color: "#3576ba" },
    { key: "state", label: "State", value: toFiniteNumber(state), color: "#5b90c7" },
    { key: "us", label: "U.S.", value: toFiniteNumber(us), color: "#123247" },
  ];
  const valid = points.filter((point) => point.value != null);
  const max = valid.length > 0 ? Math.max(...valid.map((point) => Math.abs(point.value))) : 0;
  return points.map((point) => ({
    ...point,
    width: point.value == null || max <= 0 ? 0 : (Math.abs(point.value) / max) * 100,
  }));
}

function ComparisonBars({ local, state, us, unit }) {
  const bars = compareBarData(local, state, us);
  return (
    <div className="profile-bars">
      {bars.map((bar) => (
        <div key={bar.key} className="profile-bars-row">
          <div className="profile-bars-label">{bar.label}</div>
          <div className="profile-bars-track">
            <div
              className="profile-bars-fill"
              style={{ width: `${bar.width}%`, background: bar.color }}
            />
          </div>
          <div className="profile-bars-value">{formatValue(bar.value, unit)}</div>
        </div>
      ))}
    </div>
  );
}

function SectionHeading({ title, subtitle }) {
  return (
    <div className="profile-section-heading">
      <h2>{title}</h2>
      {subtitle ? <p>{subtitle}</p> : null}
    </div>
  );
}

function PlacesTable({ measures }) {
  return (
    <div className="profile-table-wrap">
      <table className="profile-table">
        <thead>
          <tr>
            <th>Measure</th>
            <th>Category</th>
            <th>Local</th>
            <th>95% CI</th>
            <th>State</th>
            <th>U.S.</th>
          </tr>
        </thead>
        <tbody>
          {measures.map((measure) => (
            <tr key={measure.measure_id}>
              <td>{measure.short_question_text || measure.measure || measure.measure_id}</td>
              <td>{measure.category || "Uncategorized"}</td>
              <td>{formatValue(measure.local?.value, measure.unit)}</td>
              <td>
                {formatCi(
                  measure.local?.low_confidence_limit,
                  measure.local?.high_confidence_limit,
                  measure.unit
                )}
              </td>
              <td>{formatValue(measure.comparisons?.state?.value, measure.unit)}</td>
              <td>{formatValue(measure.comparisons?.us?.value, measure.unit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProfileReport({ geography, geoId }) {
  const [bundle, setBundle] = useState(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [placesSearch, setPlacesSearch] = useState("");
  const [placesSort, setPlacesSort] = useState("local-desc");
  const [categoryPage, setCategoryPage] = useState({});

  useEffect(() => {
    const controller = new AbortController();
    const endpoint = `${API_BASE}/api/profiles/${geography}/${encodeURIComponent(geoId)}`;
    setIsLoading(true);
    setError("");
    fetch(endpoint, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          const text = await response.text();
          throw new Error(`Profile request failed (${response.status}): ${text}`);
        }
        return response.json();
      })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setBundle(payload);
      })
      .catch((fetchError) => {
        if (controller.signal.aborted) return;
        setError(fetchError?.message ?? "Failed to load profile report.");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setIsLoading(false);
      });
    return () => controller.abort();
  }, [geography, geoId]);

  const geo = bundle?.geo ?? {};
  const places = bundle?.places ?? { measures: [], top_concerns: [], categories: [] };
  const acs = bundle?.acs ?? { factors: [], top_context_tiles: [] };
  const svi = bundle?.svi ?? { themes: [] };
  const hpsa = bundle?.hpsa ?? {};
  const narrative = bundle?.narrative?.executive_summary ?? {};
  const methodology = bundle?.methodology ?? {};
  const dataNotes = Array.isArray(bundle?.data_notes) ? bundle.data_notes : [];
  const primaryIndicator = (Array.isArray(places.top_concerns) ? places.top_concerns : [])[0] ?? null;
  const profileTimestamp = formatTimestampLabel(
    bundle?.generated_at ?? bundle?.updated_at ?? bundle?.last_updated ?? geo?.as_of_date ?? ""
  );
  const profileVersionLabel = String(bundle?.version_label ?? "PDO analytical profile").trim();
  const dataSources = [
    Array.isArray(places.measures) && places.measures.length > 0
      ? "CDC PLACES modeled estimates"
      : null,
    Array.isArray(acs.factors) && acs.factors.length > 0
      ? "American Community Survey contextual indicators"
      : null,
    svi?.overall
      ? "CDC/ATSDR Social Vulnerability Index"
      : null,
    hpsa?.available
      ? "HRSA Health Professional Shortage Area data"
      : null,
  ].filter(Boolean);

  const filteredPlacesMeasures = useMemo(() => {
    const measures = Array.isArray(places.measures) ? [...places.measures] : [];
    const token = placesSearch.trim().toLowerCase();
    const filtered = token
      ? measures.filter((measure) => {
          const label = `${measure.short_question_text ?? ""} ${measure.measure ?? ""} ${
            measure.measure_id ?? ""
          } ${measure.category ?? ""}`.toLowerCase();
          return label.includes(token);
        })
      : measures;

    filtered.sort((left, right) => {
      if (placesSort === "measure-asc") {
        return String(left.short_question_text || left.measure || left.measure_id || "")
          .localeCompare(String(right.short_question_text || right.measure || right.measure_id || ""));
      }
      const leftValue = toFiniteNumber(left.local?.value);
      const rightValue = toFiniteNumber(right.local?.value);
      if (leftValue == null && rightValue == null) return 0;
      if (leftValue == null) return 1;
      if (rightValue == null) return -1;
      return placesSort === "local-asc" ? leftValue - rightValue : rightValue - leftValue;
    });
    return filtered;
  }, [places.measures, placesSearch, placesSort]);

  const placesByCategory = useMemo(() => {
    const groups = new Map();
    filteredPlacesMeasures.forEach((measure) => {
      const category = String(measure.category || "Uncategorized");
      if (!groups.has(category)) {
        groups.set(category, []);
      }
      groups.get(category).push(measure);
    });
    return Array.from(groups.entries()).map(([category, measures]) => ({ category, measures }));
  }, [filteredPlacesMeasures]);

  const title = `${geo?.name ?? geoId} Profile`;
  const subheader = geo?.state_abbr
    ? `${geo?.level === "tract" ? "Tract" : "County"}, ${geo.state_abbr}`
    : geo?.level === "tract"
      ? "Tract"
      : "County";
  const pdfHref = `${API_BASE}/api/profiles/${geography}/${encodeURIComponent(geoId)}/pdf`;

  const isReady = !isLoading && !error && Boolean(bundle);

  return (
    <div className="profile-report-page">
      <Header />
      <main className="profile-report-main" data-testid={isReady ? "profile-ready" : undefined}>
        <header className="profile-report-header">
          <div className="profile-report-header-copy">
            <div className="profile-report-kicker">CHIP by Public Data Observatory</div>
            <h1>{title}</h1>
            <p>{subheader}</p>
            <div className="profile-report-meta-strip">
              <span>Last Updated: {profileTimestamp}</span>
              <span>Version: {profileVersionLabel}</span>
              <span>Data Source: Multi-source analytical profile</span>
            </div>
          </div>
          <div className="profile-report-actions">
            <a className="chip-primary-btn profile-action-link" href={pdfHref} target="_blank" rel="noreferrer">
              Download PDF
            </a>
            <a className="chip-secondary-btn profile-action-link" href="/">
              Back to Map
            </a>
          </div>
        </header>

        {isLoading ? <div className="profile-status">Loading PDO location report...</div> : null}
        {error ? <div className="profile-status profile-status-error">{error}</div> : null}

        {isReady ? (
          <>
            <section className="profile-section">
              <SectionHeading
                title="Analytical Summary"
                subtitle="Modeled and administrative indicators summarized for analytical review and planning."
              />
              <div className="profile-grid profile-grid-2">
                <article className="profile-card profile-card-hero">
                  <div className="profile-card-eyebrow">Key indicator</div>
                  <h3>
                    {primaryIndicator?.short_question_text
                      || primaryIndicator?.measure
                      || primaryIndicator?.measure_id
                      || "Primary indicator not available"}
                  </h3>
                  <div className="profile-card-hero-value">
                    {primaryIndicator ? formatValue(primaryIndicator.local?.value, primaryIndicator.unit) : "Not available"}
                  </div>
                  <div className="profile-card-note">
                    State: {primaryIndicator ? formatValue(primaryIndicator.comparisons?.state?.value, primaryIndicator.unit) : "Not available"}
                    {" • "}
                    U.S.: {primaryIndicator ? formatValue(primaryIndicator.comparisons?.us?.value, primaryIndicator.unit) : "Not available"}
                  </div>
                </article>
                <article className="profile-card">
                  <div className="profile-card-eyebrow">Context</div>
                  <h3>Interpretation notes</h3>
                  <p className="profile-paragraph">
                    {narrative.how_factors_connect
                      || "This location brief summarizes available indicators for comparative review. Values may reflect modeled estimates and should be interpreted alongside the cited source and methodology notes."}
                  </p>
                </article>
              </div>
              <ul className="profile-list">
                {(Array.isArray(narrative.key_takeaways) ? narrative.key_takeaways : []).map((bullet) => (
                  <li key={bullet}>{bullet}</li>
                ))}
              </ul>
            </section>

            <section className="profile-section profile-page-break">
              <SectionHeading title="Key Indicators" subtitle="Selected charts and benchmark context for the current geography." />
              <div className="profile-grid profile-grid-2">
                <article className="profile-card">
                  <h3>PLACES Top Concerns vs Benchmarks</h3>
                  {(Array.isArray(places.top_concerns) ? places.top_concerns : []).slice(0, 8).map((measure) => (
                    <div className="profile-card-row" key={`top-${measure.measure_id}`}>
                      <div className="profile-card-row-title">
                        {measure.short_question_text || measure.measure || measure.measure_id}
                      </div>
                      <ComparisonBars
                        local={measure.local?.value}
                        state={measure.comparisons?.state?.value}
                        us={measure.comparisons?.us?.value}
                        unit={measure.unit}
                      />
                    </div>
                  ))}
                </article>

                <article className="profile-card">
                  <h3>SVI</h3>
                  {svi.overall ? (
                    <div className="profile-pill-grid">
                      <div className="profile-pill">
                        <div className="profile-pill-label">Overall Percentile</div>
                        <div className="profile-pill-value">{formatValue(svi.overall.value, null, 3)}</div>
                      </div>
                      {(Array.isArray(svi.themes) ? svi.themes : []).map((theme) => (
                        <div className="profile-pill" key={theme.measure_id}>
                          <div className="profile-pill-label">{theme.measure_name || theme.measure_id}</div>
                          <div className="profile-pill-value">{formatValue(theme.value, null, 3)}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="profile-muted">SVI not available for this geography.</div>
                  )}
                </article>
              </div>

              <div className="profile-grid profile-grid-2">
                <article className="profile-card">
                  <h3>HPSA</h3>
                  {hpsa.available ? (
                    <div className="profile-pill-grid">
                      {Object.values(hpsa.domains ?? {}).map((domain) => (
                        <div className="profile-pill" key={domain.domain}>
                          <div className="profile-pill-label">{domain.domain_label}</div>
                          <div className="profile-pill-value">
                            {domain.designated ? "Designated" : "Not designated"}
                          </div>
                          <div className="profile-pill-note">
                            Score: {formatValue(domain.score_max, null)}
                            {domain.tier_label ? ` · ${domain.tier_label}` : ""}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="profile-muted">
                      {hpsa.not_available_message || "HPSA details are not available for this geography."}
                    </div>
                  )}
                </article>

                <article className="profile-card">
                  <h3>ACS Context (Top 6)</h3>
                  {(Array.isArray(acs.top_context_tiles) ? acs.top_context_tiles : []).slice(0, 6).map((factor) => (
                    <div className="profile-card-row" key={`acs-top-${factor.measure_id}`}>
                      <div className="profile-card-row-title">{factor.measure || factor.measure_id}</div>
                      <ComparisonBars
                        local={factor.local?.value}
                        state={factor.comparisons?.state?.value}
                        us={factor.comparisons?.us?.value}
                        unit={factor.unit}
                      />
                    </div>
                  ))}
                </article>
              </div>
            </section>

            <section className="profile-section profile-page-break">
              <SectionHeading
                title="PLACES Measure Catalog"
                subtitle="All available measures for the selected geography and the default PLACES release snapshot."
              />
              <div className="profile-tools">
                <label>
                  Search measures
                  <input
                    value={placesSearch}
                    onChange={(event) => setPlacesSearch(event.target.value)}
                    placeholder="Filter by measure or category"
                  />
                </label>
                <label>
                  Sort
                  <select value={placesSort} onChange={(event) => setPlacesSort(event.target.value)}>
                    <option value="local-desc">Local value (high to low)</option>
                    <option value="local-asc">Local value (low to high)</option>
                    <option value="measure-asc">Measure name (A-Z)</option>
                  </select>
                </label>
              </div>
              <PlacesTable measures={filteredPlacesMeasures} />

              <div className="profile-accordion-list">
                {placesByCategory.map(({ category, measures }) => {
                  const pageIndex = Number(categoryPage[category] ?? 0);
                  const pageStart = pageIndex * CHART_PAGE_SIZE;
                  const pageMeasures = measures.slice(pageStart, pageStart + CHART_PAGE_SIZE);
                  const maxPages = Math.max(1, Math.ceil(measures.length / CHART_PAGE_SIZE));
                  return (
                    <details className="profile-accordion" key={`category-${category}`} open>
                      <summary>
                        <span>{category}</span>
                        <span>{measures.length} measures</span>
                      </summary>
                      <div className="profile-category-tools">
                        <button
                          type="button"
                          className="chip-secondary-btn"
                          disabled={pageIndex <= 0}
                          onClick={() => setCategoryPage((prev) => ({ ...prev, [category]: Math.max(0, pageIndex - 1) }))}
                        >
                          Previous
                        </button>
                        <span>
                          Page {pageIndex + 1} / {maxPages}
                        </span>
                        <button
                          type="button"
                          className="chip-secondary-btn"
                          disabled={pageIndex + 1 >= maxPages}
                          onClick={() => setCategoryPage((prev) => ({ ...prev, [category]: Math.min(maxPages - 1, pageIndex + 1) }))}
                        >
                          Next
                        </button>
                      </div>
                      {pageMeasures.map((measure) => (
                        <div className="profile-card-row" key={`chart-${category}-${measure.measure_id}`}>
                          <div className="profile-card-row-title">
                            {measure.short_question_text || measure.measure || measure.measure_id}
                          </div>
                          <ComparisonBars
                            local={measure.local?.value}
                            state={measure.comparisons?.state?.value}
                            us={measure.comparisons?.us?.value}
                            unit={measure.unit}
                          />
                        </div>
                      ))}
                    </details>
                  );
                })}
              </div>
            </section>

            <section className="profile-section profile-page-break">
              <SectionHeading
                title="ACS Contextual Indicators"
                subtitle="Local ACS factors with state and national comparison points where available."
              />
              <div className="profile-grid profile-grid-2">
                {(Array.isArray(acs.factors) ? acs.factors : []).map((factor) => (
                  <article className="profile-card" key={`acs-factor-${factor.measure_id}`}>
                    <h3>{factor.measure || factor.measure_id}</h3>
                    <ComparisonBars
                      local={factor.local?.value}
                      state={factor.comparisons?.state?.value}
                      us={factor.comparisons?.us?.value}
                      unit={factor.unit}
                    />
                    <div className="profile-muted">MOE: {formatValue(factor.local?.moe, factor.unit)}</div>
                  </article>
                ))}
              </div>
            </section>

            <section className="profile-section profile-page-break">
              <SectionHeading
                title="SVI"
                subtitle="Higher percentile values indicate higher relative social vulnerability."
              />
              {svi.overall ? (
                <div className="profile-grid profile-grid-2">
                  <article className="profile-card">
                    <h3>{svi.overall.measure_name || "Overall SVI"}</h3>
                    <div className="profile-metric-row">
                      <span>National percentile</span>
                      <strong>{formatValue(svi.overall.value, null, 3)}</strong>
                    </div>
                    <div className="profile-metric-row">
                      <span>State percentile (optional)</span>
                      <strong>
                        {formatValue(svi.overall.comparisons?.state?.state_percentile, null, 3)}
                      </strong>
                    </div>
                  </article>
                  {(Array.isArray(svi.themes) ? svi.themes : []).map((theme) => (
                    <article className="profile-card" key={`svi-theme-${theme.measure_id}`}>
                      <h3>{theme.measure_name || theme.measure_id}</h3>
                      <div className="profile-metric-row">
                        <span>National percentile</span>
                        <strong>{formatValue(theme.value, null, 3)}</strong>
                      </div>
                      <div className="profile-metric-row">
                        <span>State percentile (optional)</span>
                        <strong>
                          {formatValue(theme.comparisons?.state?.state_percentile, null, 3)}
                        </strong>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="profile-muted">SVI data were unavailable for this geography.</div>
              )}
            </section>

            <section className="profile-section profile-page-break">
              <SectionHeading title="HRSA HPSA" subtitle="Provider access designations and shortage severity context for this geography." />
              {hpsa.available ? (
                <div className="profile-grid profile-grid-3">
                  {Object.values(hpsa.domains ?? {}).map((domain) => (
                    <article className="profile-card" key={`hpsa-${domain.domain}`}>
                      <h3>{domain.domain_label}</h3>
                      <div className="profile-metric-row">
                        <span>Designated</span>
                        <strong>{domain.designated ? "Yes" : "No"}</strong>
                      </div>
                      <div className="profile-metric-row">
                        <span>Score / Tier</span>
                        <strong>
                          {formatValue(domain.score_max, null)}
                          {domain.tier_label ? ` · ${domain.tier_label}` : ""}
                        </strong>
                      </div>
                      <div className="profile-metric-row">
                        <span>Ratio / Goal</span>
                        <strong>
                          {domain.hpsa_formal_ratio || "Not available"} / {domain.provider_ratio_goal || "Not available"}
                        </strong>
                      </div>
                      <div className="profile-metric-row">
                        <span>FTE</span>
                        <strong>{formatValue(domain.fte, null, 2)}</strong>
                      </div>
                      <div className="profile-metric-row">
                        <span>Coverage / Population Covered</span>
                        <strong>
                          {formatValue(domain.coverage_pct, "%")} / {domain.population_covered?.toLocaleString?.() ?? "Not available"}
                        </strong>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="profile-muted">
                  {hpsa.not_available_message || "HPSA designations are not available for this profile."}
                </div>
              )}

              {hpsa.methodology ? (
                <details className="profile-notes-accordion">
                  <summary>HPSA Data Notes</summary>
                  <div className="profile-note-list">
                    <div>Source: {hpsa.methodology.source || "Not available"}</div>
                    <div>As-of date: {hpsa.methodology.as_of_date || "Not available"}</div>
                    <div>Calculation: {hpsa.methodology.calculation || "Not available"}</div>
                    <div>See Data Notes for consolidated caveats and overlap interpretation.</div>
                  </div>
                </details>
              ) : null}
            </section>

            <section className="profile-section profile-page-break">
              <SectionHeading title="Data Sources" subtitle="Primary sources represented in this profile." />
              {dataSources.length > 0 ? (
                <ul className="profile-list">
                  {dataSources.map((source) => (
                    <li key={source}>{source}</li>
                  ))}
                </ul>
              ) : (
                <div className="profile-muted">Source metadata were not available in this response.</div>
              )}
            </section>

            <section className="profile-section profile-page-break">
              <SectionHeading title="Methodology" subtitle="Short structured methods summary by data source." />
              {["places", "acs", "svi", "hpsa"].map((key) => (
                <article className="profile-card" key={`method-${key}`}>
                  <h3>{key.toUpperCase()}</h3>
                  <ul className="profile-list">
                    {(Array.isArray(methodology[key]) ? methodology[key] : []).map((line) => (
                      <li key={`${key}-${line}`}>{line}</li>
                    ))}
                  </ul>
                </article>
              ))}
            </section>

            <section className="profile-section profile-page-break">
              <SectionHeading title="Data Notes" subtitle="Consolidated caveats and interpretation limits." />
              <ul className="profile-list">
                {dataNotes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </section>
          </>
        ) : null}
      </main>
      <Footer />
    </div>
  );
}

export default ProfileReport;
