import { useEffect, useLayoutEffect, useState } from "react";
import "./MapLoading.css";

const STAR_A = [[75, 208], [118, 177], [147, 203], [183, 156]];
const STAR_B = [[205, 79], [247, 107], [240, 147], [299, 153]];
// Data blocks in the dome, bottom row first so the "chart" builds upward.
const BLOCKS = [[186, 291], [236, 291], [285, 291], [335, 291], [186, 256], [236, 256], [285, 256], [236, 222]];
const line = (points) => `M${points.map((p) => p.join(" ")).join(" L")}`;

/** The Public Data Observatory mark, drawn as SVG so its parts can move. Matches pdo-observatory-mark.png. */
export function ObservatoryMark({ animated = true, size = 104 }) {
  return <svg className={`pdo-mark ${animated ? "is-animated" : ""}`} viewBox="0 0 580 580" width={size} height={size} aria-hidden="true" focusable="false">
    <defs><clipPath id="pdo-mark-clip"><circle cx="290" cy="290" r="290" /></clipPath></defs>
    <circle cx="290" cy="290" r="290" fill="#3576ba" />
    <g clipPath="url(#pdo-mark-clip)" fill="none" stroke="#fff" strokeWidth="7" strokeLinejoin="round" strokeLinecap="round">
      <g className="pdo-mark-sky" stroke="#ffd5b0" strokeWidth="5">
        <path className="pdo-mark-path" d={line(STAR_A)} pathLength="1" />
        <path className="pdo-mark-path pdo-mark-path-b" d={line(STAR_B)} pathLength="1" />
        {[...STAR_A, ...STAR_B].map(([cx, cy], i) => <circle key={`${cx}-${cy}`} className="pdo-mark-star" cx={cx} cy={cy} r="10" fill="#ffd5b0" stroke="none" style={{ "--i": i }} />)}
      </g>
      <g className="pdo-mark-scope">
        <g transform="translate(438 172) rotate(35)">
          <rect x="-25" y="16" width="50" height="110" fill="#3576ba" />
          <rect x="-38" y="-19" width="76" height="38" rx="12" fill="#3576ba" />
        </g>
      </g>
      <path d="M146 332 A150.5 152 0 0 1 447 332 Z" fill="#3576ba" />
      <path d="M262 183 C340 190 393 240 393 332" />
      {BLOCKS.map(([x, y], i) => <rect key={`${x}-${y}`} className="pdo-mark-block" x={x} y={y} width="37" height="24" fill="#ffd5b0" stroke="none" style={{ "--i": i }} />)}
      <path d="M146 358 V459 M447 358 V459 M40 459 H540 M270 459 V422 A26.5 26.5 0 0 1 323 422 V459" />
      <rect x="130" y="332" width="329" height="27" rx="13.5" fill="#3576ba" />
    </g>
  </svg>;
}

/** Full-map overlay for the first load of a map page. Fades out, then unmounts. */
export function MapLoadingOverlay({ active, title = "Loading map", detail }) {
  const [mounted, setMounted] = useState(active);
  useEffect(() => {
    if (active) { setMounted(true); return undefined; }
    const timer = setTimeout(() => setMounted(false), 450);
    return () => clearTimeout(timer);
  }, [active]);
  if (!mounted) return null;
  return <div className={`map-loading-overlay ${active ? "" : "is-leaving"}`} role="status" aria-live="polite" data-testid="map-loading-overlay">
    <div className="map-loading-card">
      <div className="map-loading-mark"><span className="map-loading-ring" aria-hidden="true" /><ObservatoryMark /></div>
      <p className="map-loading-title">{active ? title : "Map ready"}<span className="map-loading-dots" aria-hidden="true"><i /><i /><i /></span></p>
      {detail && <p className="map-loading-detail">{detail}</p>}
    </div>
  </div>;
}

/**
 * Small progress pill for later loads (zoom, pan, measure change). Sits under `anchor` (the Map Tools strip)
 * on wide screens and just above it when the strip is docked at the bottom.
 */
export function MapLoadingStrip({ active, label, anchor, container, watch = [] }) {
  const [place, setPlace] = useState(null);
  useLayoutEffect(() => {
    if (!active || !anchor || !container) return undefined;
    const update = () => {
      const a = anchor.getBoundingClientRect();
      const c = container.getBoundingClientRect();
      const docked = a.top - c.top > c.height / 2;
      setPlace({ left: a.left - c.left + a.width / 2, ...(docked ? { bottom: c.bottom - a.top + 10 } : { top: a.bottom - c.top + 10 }) });
    };
    update();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(anchor);
    if (anchor.parentElement) observer?.observe(anchor.parentElement);
    window.addEventListener("resize", update);
    return () => { observer?.disconnect(); window.removeEventListener("resize", update); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, anchor, container, ...watch]);
  if (!active) return null;
  return <div className="map-loading-strip" role="status" aria-live="polite" data-testid="map-loading-strip"
    style={place ? place : { top: 16, left: "50%" }}>
    <span className="map-loading-strip-mark"><ObservatoryMark size={22} /></span>
    <span>{label}</span>
    <span className="map-loading-strip-bar" aria-hidden="true" />
  </div>;
}

/** Shimmering placeholder rows for the legend while its classes load. */
export function LegendSkeleton({ rows = 5, label = "Loading legend…" }) {
  return <div className="legend-skeleton" role="status">
    <span className="visually-hidden">{label}</span>
    {Array.from({ length: rows }, (_, i) => <span key={i} className="legend-skeleton-row" style={{ "--i": i }} aria-hidden="true"><i /><b /></span>)}
  </div>;
}
