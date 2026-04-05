import { useEffect, useMemo, useState } from "react";

const BULLET_PREFIX_RE = /^\s*bullet[\s:.-]*/i;

function asNumber(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function formatValue(value, suffix = "") {
  const parsed = asNumber(value);
  if (parsed == null) return "Not available";
  return `${parsed.toFixed(1)}${suffix}`;
}

function formatPercent(value) {
  const parsed = asNumber(value);
  if (parsed == null) return "Not available";
  return `${parsed.toFixed(3)}%`;
}

function formatInt(value) {
  const parsed = asNumber(value);
  if (parsed == null) return "Not available";
  return Math.round(parsed).toLocaleString();
}

function ordinal(value) {
  const parsed = asNumber(value);
  if (parsed == null) return "Not available";
  const rounded = Math.round(parsed);
  const absValue = Math.abs(rounded);
  let suffix = "th";
  if (absValue % 100 < 11 || absValue % 100 > 13) {
    suffix = { 1: "st", 2: "nd", 3: "rd" }[absValue % 10] ?? "th";
  }
  return `${rounded}${suffix}`;
}

function normalizeBulletLine(line) {
  if (line == null) return { text: "", isBulletPrefixed: false };
  const raw = String(line).trim();
  if (!raw) return { text: "", isBulletPrefixed: false };
  const isBulletPrefixed = BULLET_PREFIX_RE.test(raw);
  let cleaned = raw.replace(BULLET_PREFIX_RE, "").trim();
  if (cleaned.startsWith("- ")) cleaned = cleaned.slice(2).trim();
  if (cleaned.startsWith("* ")) cleaned = cleaned.slice(2).trim();
  return { text: cleaned, isBulletPrefixed };
}

function normalizeSection(section) {
  if (!section || typeof section !== "object") return null;
  const paragraphLines = [];
  const bullets = [];

  if (typeof section.paragraph === "string") {
    section.paragraph
      .split(/\r?\n/)
      .map((line) => normalizeBulletLine(line))
      .forEach(({ text, isBulletPrefixed }) => {
        if (!text) return;
        if (isBulletPrefixed) {
          bullets.push(text);
        } else {
          paragraphLines.push(text);
        }
      });
  } else if (section.paragraph != null) {
    const normalized = String(section.paragraph).trim();
    if (normalized) paragraphLines.push(normalized);
  }

  const rawBullets = Array.isArray(section.bullets)
    ? section.bullets
    : section.bullets == null
      ? []
      : [section.bullets];

  rawBullets.forEach((rawBullet) => {
    const lines = typeof rawBullet === "string" ? rawBullet.split(/\r?\n/) : [rawBullet];
    lines
      .map((line) => normalizeBulletLine(line))
      .forEach(({ text }) => {
        if (text) bullets.push(text);
      });
  });

  const seen = new Set();
  const dedupedBullets = bullets.filter((item) => {
    if (seen.has(item)) return false;
    seen.add(item);
    return true;
  });

  return {
    ...section,
    title: (section?.title && String(section.title).trim()) || "Section",
    paragraph: paragraphLines.join(" ").trim(),
    bullets: dedupedBullets,
  };
}

export default function FullProfilePanel({
  apiBase,
  profileId,
  open,
  onClose,
}) {
  const [profile, setProfile] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [pdfTemplate, setPdfTemplate] = useState("full");

  useEffect(() => {
    if (!open || !profileId) {
      return;
    }

    const controller = new AbortController();
    setIsLoading(true);
    setError(null);

    fetch(`${apiBase}/profiles/${profileId}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.text().catch(() => "No body");
          throw new Error(`Profile request failed (${response.status}): ${body}`);
        }
        return response.json();
      })
      .then((data) => {
        if (controller.signal.aborted) return;
        setProfile(data);
      })
      .catch((fetchError) => {
        if (controller.signal.aborted) return;
        setProfile(null);
        setError(fetchError.message ?? "Failed to load profile.");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setIsLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [apiBase, open, profileId]);

  useEffect(() => {
    if (!open) return;
    setPdfTemplate("full");
  }, [open, profileId]);

  const chartEntries = useMemo(() => {
    const charts = profile?.charts;
    if (!charts || typeof charts !== "object") return [];
    return Object.entries(charts)
      .map(([name, config]) => {
        const url = config?.url;
        if (!url) return null;
        return {
          name,
          url: `${apiBase}${url}`,
        };
      })
      .filter(Boolean);
  }, [apiBase, profile]);

  const location = profile?.location ?? {};
  const places = profile?.places_measure ?? {};
  const references = profile?.reference_stats ?? {};
  const comparisons = profile?.comparisons ?? {};
  const narrative = profile?.narrative ?? {};
  const summary = narrative?.summary_paragraph ?? narrative?.summary_text ?? "";
  const hpsa = profile?.hpsa && typeof profile.hpsa === "object" ? profile.hpsa : null;
  const hpsaMethodologyFromProfile = profile?.methodology?.hpsa;
  const hpsaMethodologyFromNarrative = narrative?.methodology?.hpsa;
  const hpsaMethodology = (
    hpsaMethodologyFromProfile && typeof hpsaMethodologyFromProfile === "object"
      ? hpsaMethodologyFromProfile
      : hpsaMethodologyFromNarrative && typeof hpsaMethodologyFromNarrative === "object"
        ? hpsaMethodologyFromNarrative
        : null
  );
  const hpsaCaveat = Array.isArray(hpsaMethodology?.caveats) && hpsaMethodology.caveats.length > 0
    ? hpsaMethodology.caveats[0]
    : null;
  const sections = useMemo(() => {
    const sourceSections = Array.isArray(narrative?.plain_language_sections)
      ? narrative.plain_language_sections
      : Array.isArray(narrative?.sections)
        ? narrative.sections
        : [];
    const normalizedSections = sourceSections
      .map((section) => normalizeSection(section))
      .filter(Boolean);
    const technicalSection = normalizeSection(narrative?.technical_methods_section);
    if (!technicalSection) return normalizedSections;

    const hasEquivalentTechnicalSection = normalizedSections.some((section) => {
      const existingId = String(section?.section_id ?? "").trim();
      const technicalId = String(technicalSection?.section_id ?? "").trim();
      if (existingId && technicalId) return existingId === technicalId;
      return section?.title === technicalSection?.title;
    });
    if (hasEquivalentTechnicalSection) return normalizedSections;
    return [...normalizedSections, technicalSection];
  }, [narrative]);
  const placesComparison = comparisons?.places ?? {};
  const acsPrimary = comparisons?.acs_primary ?? null;
  const pdfHref = `${apiBase}/profiles/${profileId}.pdf${pdfTemplate === "brief" ? "?template=brief" : ""}`;

  if (!open) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        right: 0,
        height: "100%",
        width: "min(460px, 92vw)",
        background: "#ffffff",
        borderLeft: "1px solid #D7E2EE",
        boxShadow: "-12px 0 30px rgba(18, 50, 71, 0.09)",
        zIndex: 2400,
        display: "grid",
        gridTemplateRows: "auto 1fr",
      }}
    >
      <div
        style={{
          borderBottom: "1px solid #D7E2EE",
          padding: "16px 18px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "#3576BA" }}>
            PDO location brief
          </div>
          <div style={{ fontSize: 15, fontWeight: 700, marginTop: 2 }}>CHIP by Public Data Observatory</div>
          <div style={{ fontSize: 12, color: "#627A90", marginTop: 2 }}>
            {location?.name ?? profileId} ({location?.state_abbr ?? "Not available"})
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            value={pdfTemplate}
            onChange={(event) => setPdfTemplate(event.target.value)}
            style={{
              padding: "9px 10px",
              borderRadius: 12,
              border: "1px solid #BFD0E1",
              background: "#ffffff",
              color: "#123247",
              fontWeight: 600,
              fontSize: 12,
            }}
          >
            <option value="full">Full Profile (PDF)</option>
            <option value="brief">PDO Brief (PDF)</option>
          </select>
          <a
            href={pdfHref}
            target="_blank"
            rel="noreferrer"
            className="chip-primary-link"
            style={{
              padding: "8px 12px",
              borderRadius: 999,
              fontWeight: 600,
              fontSize: 12,
              textDecoration: "none",
              whiteSpace: "nowrap",
            }}
          >
            Download
          </a>
          <button
            type="button"
            onClick={onClose}
            className="chip-secondary-btn"
            style={{
              padding: "8px 12px",
              borderRadius: 999,
              fontWeight: 600,
              fontSize: 12,
            }}
          >
            Close
          </button>
        </div>
      </div>

      <div style={{ overflowY: "auto", padding: 18, display: "grid", gap: 16 }}>
        {isLoading ? <div style={{ color: "#627A90", fontSize: 12 }}>Loading location brief...</div> : null}
        {error ? <div style={{ color: "#b91c1c", fontSize: 12 }}>{error}</div> : null}
        {!isLoading && !error && profile ? (
          <>
            <div style={{ fontSize: 13, color: "#334155", lineHeight: 1.6 }}>
              {summary || "Summary unavailable."}
            </div>

            <div>
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>Key indicators</div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <tbody>
                  <tr>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6, background: "#F7FAFD" }}>Measure</td>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                      {places?.short_question_text ?? places?.measure ?? places?.measure_id ?? "Not available"}
                    </td>
                  </tr>
                  <tr>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6, background: "#F7FAFD" }}>Last Updated</td>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                      {places?.year ?? "Not available"}
                    </td>
                  </tr>
                  <tr>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6, background: "#F7FAFD" }}>Location value</td>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                      {formatValue(places?.location_value, "%")}
                    </td>
                  </tr>
                  <tr>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6, background: "#F7FAFD" }}>National percentile</td>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                      {`${ordinal(references?.us_percentile)} percentile`}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div>
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>Benchmark comparisons</div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr>
                    <th style={{ border: "1px solid #E5EDF5", padding: 6, textAlign: "left", background: "#F7FAFD" }}>Metric</th>
                    <th style={{ border: "1px solid #E5EDF5", padding: 6, textAlign: "left", background: "#F7FAFD" }}>Local</th>
                    <th style={{ border: "1px solid #E5EDF5", padding: 6, textAlign: "left", background: "#F7FAFD" }}>State</th>
                    <th style={{ border: "1px solid #E5EDF5", padding: 6, textAlign: "left", background: "#F7FAFD" }}>U.S.</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>PLACES</td>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                      {formatValue(placesComparison?.location_value, "%")}
                    </td>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                      {formatValue(placesComparison?.state_mean, "%")}
                    </td>
                    <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                      {formatValue(placesComparison?.us_mean, "%")}
                    </td>
                  </tr>
                  {acsPrimary && typeof acsPrimary === "object" ? (
                    <tr>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                        {acsPrimary?.measure ?? acsPrimary?.measure_id ?? "ACS"}
                      </td>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                        {formatValue(acsPrimary?.location_value)}
                      </td>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                        {formatValue(acsPrimary?.state_mean)}
                      </td>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                        {formatValue(acsPrimary?.us_mean)}
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>

            {hpsa ? (
              <div>
                <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>
                  HPSA coverage
                </div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr>
                      <th style={{ border: "1px solid #E5EDF5", padding: 6, textAlign: "left", background: "#F7FAFD" }}>
                        Type
                      </th>
                      <th style={{ border: "1px solid #E5EDF5", padding: 6, textAlign: "left", background: "#F7FAFD" }}>
                        Coverage
                      </th>
                      <th style={{ border: "1px solid #E5EDF5", padding: 6, textAlign: "left", background: "#F7FAFD" }}>
                        Population covered
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>Primary Care</td>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                        {formatPercent(hpsa?.primary_care?.coverage_pct)}
                      </td>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                        {formatInt(hpsa?.primary_care?.population_covered)}
                      </td>
                    </tr>
                    <tr>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>Mental Health</td>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                        {formatPercent(hpsa?.mental_health?.coverage_pct)}
                      </td>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                        {formatInt(hpsa?.mental_health?.population_covered)}
                      </td>
                    </tr>
                    <tr>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>Dental</td>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                        {formatPercent(hpsa?.dental?.coverage_pct)}
                      </td>
                      <td style={{ border: "1px solid #E5EDF5", padding: 6 }}>
                        {formatInt(hpsa?.dental?.population_covered)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            ) : null}

            {hpsaMethodology ? (
              <details>
                <summary style={{ cursor: "pointer", fontWeight: 700, fontSize: 13 }}>
                  Data Notes
                </summary>
                <div
                  style={{
                    marginTop: 6,
                    display: "grid",
                    gap: 4,
                    color: "#334155",
                    fontSize: 12,
                    lineHeight: 1.4,
                  }}
                >
                  <div>Source: {hpsaMethodology.source ?? "HRSA HPSA Data Mart"}</div>
                  <div>As-of date: {hpsaMethodology.as_of_date ?? "Not available"}</div>
                  <div>{hpsaCaveat ?? "Coverage is computed conservatively; overlapping designations may exist."}</div>
                </div>
              </details>
            ) : null}

            {sections.map((section, index) => (
              <div key={`profile-section-${index}`} style={{ display: "grid", gap: 6 }}>
                <div style={{ fontWeight: 700, fontSize: 13 }}>{section?.title ?? "Section"}</div>
                {section?.paragraph ? (
                  <div style={{ fontSize: 12, color: "#334155", lineHeight: 1.5 }}>
                    {section.paragraph}
                  </div>
                ) : null}
                {Array.isArray(section?.bullets) && section.bullets.length > 0 ? (
                  <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4, fontSize: 12 }}>
                    {section.bullets.map((bullet, bulletIndex) => (
                      <li key={`profile-bullet-${index}-${bulletIndex}`}>{bullet}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}

            {chartEntries.length > 0 ? (
              <div style={{ display: "grid", gap: 10 }}>
                <div style={{ fontWeight: 700, fontSize: 13 }}>Charts</div>
                {chartEntries.map((chart) => (
                  <div key={chart.name} style={{ display: "grid", gap: 4 }}>
                            <div style={{ fontSize: 12, color: "#334155" }}>
                      {chart.name.replaceAll("_", " ")}
                    </div>
                    <img
                      src={chart.url}
                      alt={chart.name}
                      style={{ width: "100%", border: "1px solid #E5EDF5", borderRadius: 12 }}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ color: "#627A90", fontSize: 12 }}>No charts are available for this location brief.</div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
