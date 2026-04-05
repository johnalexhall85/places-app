import { useEffect, useState } from "react";
import { fetchCdcFundingMethodologySummary as defaultFetchSummary } from "../api/cdcFunding";
import { API_BASE as DEFAULT_API_BASE } from "../config/apiBase";
import "./CdcFundingMethodologyControl.css";

function toCountValue(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.round(numeric) : null;
}

function readText(value, fallback = "Not available") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function formatCount(value) {
  return value == null ? "Not available" : value.toLocaleString("en-US");
}

function formatFamilyName(value) {
  const text = String(value ?? "").trim();
  if (!text) return "Not available";
  if (/^[A-Za-z]{2,4}$/.test(text)) {
    return text.toUpperCase();
  }
  return text
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function normalizeMethodologySummary(payload) {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const frontendSummary = payload.frontend_summary && typeof payload.frontend_summary === "object"
    ? payload.frontend_summary
    : {};
  const counts = frontendSummary.counts && typeof frontendSummary.counts === "object"
    ? frontendSummary.counts
    : {};

  const familyRows = Array.isArray(payload.top_fy2021_review_families)
    ? payload.top_fy2021_review_families
    : Array.isArray(frontendSummary.top_review_families)
      ? frontendSummary.top_review_families
      : [];

  const topReviewFamilies = familyRows
    .map((row, index) => ({
      id: `${String(row?.award_family ?? "family").trim() || "family"}-${index}`,
      name: formatFamilyName(row?.award_family),
      rowCount: toCountValue(row?.row_count),
    }))
    .filter((row) => row.name !== "Not available");

  const directManualReviewFlag = payload.manual_review_exceptions_applied_in_production;
  const fallbackManualReviewFlag = frontendSummary.production_exceptions_applied;

  return {
    version: readText(payload.current_frozen_version ?? frontendSummary.version),
    verifiedAccountCount: toCountValue(payload.verified_account_count ?? counts.verified_accounts),
    fallbackAccountCount: toCountValue(payload.fallback_account_count ?? counts.fallback_accounts),
    singleAccountRowCount: toCountValue(payload.total_single_account_rows ?? counts.single_account_rows),
    multiAccountSameScopeRowCount: toCountValue(
      payload.total_multi_account_same_scope_rows ?? counts.multi_account_same_scope_rows
    ),
    multiAccountMixedScopeRowCount: toCountValue(
      payload.total_multi_account_mixed_scope_rows ?? counts.multi_account_mixed_scope_rows
    ),
    conservativeMixedAccountExplanation: readText(
      payload.conservative_mixed_account_handling_explanation,
      "Mixed-account awards stay conservative when the public record does not show an exact split by federal account."
    ),
    whyFy2021Differs: readText(
      payload.why_fy2021_differs,
      "FY2021 includes unusually large mixed-account awards that are harder to reconcile cleanly from public reporting alone."
    ),
    topReviewFamilies,
    manualReviewExceptionsAppliedInProduction:
      typeof directManualReviewFlag === "boolean"
        ? directManualReviewFlag
        : typeof fallbackManualReviewFlag === "boolean"
          ? fallbackManualReviewFlag
          : null,
  };
}

function MethodologyStat({ label, value }) {
  return (
    <div className="cdc-methodology-stat-card">
      <div className="cdc-methodology-stat-label">{label}</div>
      <div className="cdc-methodology-stat-value">{value}</div>
    </div>
  );
}

export function CdcFundingMethodologyPanel({
  isOpen,
  onClose,
  summary,
  isLoading,
  errorMessage,
}) {
  useEffect(() => {
    if (!isOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const manualReviewNote = summary?.manualReviewExceptionsAppliedInProduction
    ? "Manual review exceptions are currently applied in production for this version."
    : "Manual review exceptions are not applied in production for this frozen public version.";

  return (
    <div
      className="chip-nav-modal-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="chip-nav-modal cdc-methodology-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cdc-methodology-heading"
      >
        <div className="chip-nav-modal-header cdc-methodology-modal-header">
          <div>
            <div className="cdc-methodology-eyebrow">CDC Funding</div>
            <h2 id="cdc-methodology-heading">Methodology</h2>
          </div>
          <button
            type="button"
            className="chip-nav-modal-close"
            onClick={onClose}
            aria-label="Close methodology panel"
          >
            Close
          </button>
        </div>

        <div className="cdc-methodology-modal-body">
          {isLoading ? (
            <div className="cdc-methodology-state" role="status">
              Loading methodology summary...
            </div>
          ) : errorMessage ? (
            <div className="cdc-methodology-state is-error" role="alert">
              Unable to load the methodology summary right now. {errorMessage}
            </div>
          ) : !summary ? (
            <div className="cdc-methodology-state" role="status">
              Methodology summary is unavailable right now.
            </div>
          ) : (
            <>
              <section className="cdc-methodology-hero">
                <div className="cdc-methodology-eyebrow">Frozen Production Methodology</div>
                <h3>Public CDC funding methodology summary</h3>
                <p className="cdc-methodology-hero-copy">
                  This map uses a frozen, profile-aligned methodology built from publicly reported
                  award and account data rather than internal CDC accounting systems.
                </p>
                <div className="cdc-methodology-chip-row" aria-label="Methodology status">
                  <span className="cdc-methodology-chip is-success">Verified methodology</span>
                  <span className="cdc-methodology-chip is-neutral">
                    {`${formatCount(summary.verifiedAccountCount)} verified accounts`}
                  </span>
                  <span className="cdc-methodology-chip is-neutral">
                    {summary.fallbackAccountCount === 0
                      ? "No fallback accounts"
                      : `${formatCount(summary.fallbackAccountCount)} fallback accounts`}
                  </span>
                </div>
                <dl className="cdc-methodology-version-card">
                  <dt>Methodology version</dt>
                  <dd>{summary.version}</dd>
                </dl>
              </section>

              <section className="cdc-methodology-section">
                <h3>Core summary metrics</h3>
                <div className="cdc-methodology-stat-grid">
                  <MethodologyStat
                    label="Verified accounts"
                    value={formatCount(summary.verifiedAccountCount)}
                  />
                  <MethodologyStat
                    label="Fallback accounts"
                    value={formatCount(summary.fallbackAccountCount)}
                  />
                  <MethodologyStat
                    label="Single-account rows"
                    value={formatCount(summary.singleAccountRowCount)}
                  />
                  <MethodologyStat
                    label="Multi-account same-scope rows"
                    value={formatCount(summary.multiAccountSameScopeRowCount)}
                  />
                  <MethodologyStat
                    label="Multi-account mixed-scope rows"
                    value={formatCount(summary.multiAccountMixedScopeRowCount)}
                  />
                </div>
              </section>

              <section className="cdc-methodology-explainer-grid">
                <article className="cdc-methodology-explainer-card">
                  <h3>Conservative mixed-account handling</h3>
                  <p>{summary.conservativeMixedAccountExplanation}</p>
                </article>
                <article className="cdc-methodology-explainer-card">
                  <h3>Why FY2021 differs</h3>
                  <p>{summary.whyFy2021Differs}</p>
                </article>
              </section>

              {summary.topReviewFamilies.length > 0 ? (
                <section className="cdc-methodology-section">
                  <h3>FY2021 review families</h3>
                  <p className="cdc-methodology-section-copy">
                    The largest FY2021 public-data review families in this frozen summary are shown
                    here because they account for much of the remaining difference.
                  </p>
                  <div className="cdc-methodology-family-grid">
                    {summary.topReviewFamilies.slice(0, 2).map((family) => (
                      <div key={family.id} className="cdc-methodology-family-card">
                        <div className="cdc-methodology-family-name">{family.name}</div>
                        <div className="cdc-methodology-family-meta">
                          {family.rowCount == null
                            ? "Highlighted FY2021 family"
                            : `${formatCount(family.rowCount)} FY2021 rows`}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}

              <section className="cdc-methodology-section">
                <h3>Why totals may differ</h3>
                <ul className="cdc-methodology-list">
                  <li>This model uses publicly reported award and account data.</li>
                  <li>
                    Mixed-account awards are handled conservatively when the public source does not
                    show an exact split by account.
                  </li>
                  <li>
                    Some published totals may come from internal accounting systems and can differ
                    from this public-data reconstruction.
                  </li>
                </ul>
              </section>

              <section className="cdc-methodology-production-note">
                <h3>Production note</h3>
                <p>{manualReviewNote}</p>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function CdcFundingMethodologyControl({
  apiBase = DEFAULT_API_BASE,
  fetchSummary = defaultFetchSummary,
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [summary, setSummary] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let isActive = true;

    setIsLoading(true);
    setErrorMessage("");

    fetchSummary({
      apiBase,
      signal: controller.signal,
    })
      .then((payload) => {
        if (!isActive || controller.signal.aborted) return;
        const normalizedSummary = normalizeMethodologySummary(payload);
        if (!normalizedSummary) {
          throw new Error("Methodology summary is unavailable.");
        }
        setSummary(normalizedSummary);
      })
      .catch((error) => {
        if (!isActive || controller.signal.aborted) return;
        setSummary(null);
        setErrorMessage(error?.message ?? "Failed to load methodology summary.");
      })
      .finally(() => {
        if (!isActive || controller.signal.aborted) return;
        setIsLoading(false);
      });

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [apiBase, fetchSummary]);

  return (
    <>
      <div className="cdc-methodology-control">
        <div className="cdc-methodology-trigger-row">
          <button
            type="button"
            className="chip-secondary-btn"
            aria-haspopup="dialog"
            onClick={() => setIsOpen(true)}
          >
            Methodology
          </button>
          {!isLoading && !errorMessage && summary ? (
            <div className="cdc-methodology-chip-row">
              <span className="cdc-methodology-chip is-success">Verified methodology</span>
              <span className="cdc-methodology-chip is-neutral">
                {`${formatCount(summary.verifiedAccountCount)} verified accounts`}
              </span>
              <span className="cdc-methodology-chip is-neutral">
                {summary.fallbackAccountCount === 0
                  ? "No fallback accounts"
                  : `${formatCount(summary.fallbackAccountCount)} fallback accounts`}
              </span>
            </div>
          ) : null}
        </div>
        <div className="cdc-methodology-trigger-copy">
          See how public CDC funding totals are constructed and why they may differ from simpler
          dashboards.
        </div>
      </div>

      <CdcFundingMethodologyPanel
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        summary={summary}
        isLoading={isLoading}
        errorMessage={errorMessage}
      />
    </>
  );
}
