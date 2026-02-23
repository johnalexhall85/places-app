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

  if (!open) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        right: 0,
        height: "100vh",
        width: "min(460px, 92vw)",
        background: "#ffffff",
        borderLeft: "1px solid #e2e8f0",
        boxShadow: "-10px 0 24px rgba(15, 23, 42, 0.18)",
        zIndex: 2400,
        display: "grid",
        gridTemplateRows: "auto 1fr",
      }}
    >
      <div
        style={{
          borderBottom: "1px solid #e2e8f0",
          padding: "14px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Full profile</div>
          <div style={{ fontSize: 12, color: "#475569" }}>
            {location?.name ?? profileId} ({location?.state_abbr ?? "Not available"})
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <a
            href={`${apiBase}/profiles/${profileId}.pdf`}
            target="_blank"
            rel="noreferrer"
            style={{
              padding: "8px 10px",
              borderRadius: 6,
              border: "1px solid #1d4ed8",
              background: "#eff6ff",
              color: "#1e40af",
              fontWeight: 600,
              fontSize: 12,
              textDecoration: "none",
            }}
          >
            Download PDF
          </a>
          <button
            type="button"
            onClick={onClose}
            style={{
              padding: "8px 10px",
              borderRadius: 6,
              border: "1px solid #cbd5e1",
              background: "#f8fafc",
              color: "#0f172a",
              fontWeight: 600,
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Close
          </button>
        </div>
      </div>

      <div style={{ overflowY: "auto", padding: 16, display: "grid", gap: 16 }}>
        {isLoading ? <div style={{ color: "#64748b", fontSize: 12 }}>Loading profile...</div> : null}
        {error ? <div style={{ color: "#b91c1c", fontSize: 12 }}>{error}</div> : null}
        {!isLoading && !error && profile ? (
          <>
            <div style={{ fontSize: 13, color: "#334155", lineHeight: 1.5 }}>
              {summary || "Summary unavailable."}
            </div>

            <div>
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>Key stats</div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <tbody>
                  <tr>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>Measure</td>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>
                      {places?.short_question_text ?? places?.measure ?? places?.measure_id ?? "Not available"}
                    </td>
                  </tr>
                  <tr>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>Year</td>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>
                      {places?.year ?? "Not available"}
                    </td>
                  </tr>
                  <tr>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>Location value</td>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>
                      {formatValue(places?.location_value, "%")}
                    </td>
                  </tr>
                  <tr>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>US percentile</td>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>
                      {`${ordinal(references?.us_percentile)} percentile`}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div>
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>Comparisons</div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr>
                    <th style={{ border: "1px solid #e2e8f0", padding: 6, textAlign: "left" }}>Metric</th>
                    <th style={{ border: "1px solid #e2e8f0", padding: 6, textAlign: "left" }}>Location</th>
                    <th style={{ border: "1px solid #e2e8f0", padding: 6, textAlign: "left" }}>State</th>
                    <th style={{ border: "1px solid #e2e8f0", padding: 6, textAlign: "left" }}>US</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>PLACES</td>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>
                      {formatValue(placesComparison?.location_value, "%")}
                    </td>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>
                      {formatValue(placesComparison?.state_mean, "%")}
                    </td>
                    <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>
                      {formatValue(placesComparison?.us_mean, "%")}
                    </td>
                  </tr>
                  {acsPrimary && typeof acsPrimary === "object" ? (
                    <tr>
                      <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>
                        {acsPrimary?.measure ?? acsPrimary?.measure_id ?? "ACS"}
                      </td>
                      <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>
                        {formatValue(acsPrimary?.location_value)}
                      </td>
                      <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>
                        {formatValue(acsPrimary?.state_mean)}
                      </td>
                      <td style={{ border: "1px solid #e2e8f0", padding: 6 }}>
                        {formatValue(acsPrimary?.us_mean)}
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>

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
                      style={{ width: "100%", border: "1px solid #e2e8f0", borderRadius: 6 }}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ color: "#64748b", fontSize: 12 }}>No charts available for this profile.</div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
