import { useCallback, useEffect, useId, useRef, useState } from "react";
import "./MobileMapPanels.css";

const HINT_KEY = "chip-mobile-map-panels-hint-seen";
const MOBILE_QUERY = "(max-width: 768px)";

function hintSeen() {
  try { return window.localStorage.getItem(HINT_KEY) === "1"; } catch { return false; }
}

export default function MobileMapPanels({ children, mapSurfaceRef, onVisibilityChange, className = "" }) {
  const id = useId().replaceAll(":", "");
  const rootRef = useRef(null);
  const touchStart = useRef(null);
  const [isMobile, setIsMobile] = useState(() => typeof window !== "undefined" && window.matchMedia?.(MOBILE_QUERY).matches);
  const [open, setOpen] = useState(false);
  const [showHint, setShowHint] = useState(() => !hintSeen());

  const rememberHint = useCallback(() => {
    setShowHint(false);
    try { window.localStorage.setItem(HINT_KEY, "1"); } catch { /* Private browsing can deny storage. */ }
  }, []);
  const show = useCallback(() => { setOpen(true); rememberHint(); }, [rememberHint]);

  useEffect(() => {
    const media = window.matchMedia?.(MOBILE_QUERY);
    if (!media) return undefined;
    const update = () => { setIsMobile(media.matches); if (!media.matches) setOpen(false); };
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);

  useEffect(() => {
    if (!open || !isMobile) return undefined;
    const onKey = (event) => { if (event.key === "Escape") setOpen(false); };
    const outside = (event) => { if (!rootRef.current?.contains(event.target)) setOpen(false); };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", outside);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("pointerdown", outside); };
  }, [open, isMobile]);

  useEffect(() => {
    if (!isMobile) return undefined;
    const surface = mapSurfaceRef?.current;
    if (!surface) return undefined;
    const start = (event) => {
      const point = event.touches[0];
      touchStart.current = point && point.clientX <= 24 ? { x: point.clientX, y: point.clientY } : null;
    };
    const end = (event) => {
      const origin = touchStart.current;
      touchStart.current = null;
      const point = event.changedTouches[0];
      if (origin && point && point.clientX - origin.x > 60 && Math.abs(point.clientY - origin.y) < 60) show();
    };
    surface.addEventListener("touchstart", start, { passive: true });
    surface.addEventListener("touchend", end, { passive: true });
    return () => { surface.removeEventListener("touchstart", start); surface.removeEventListener("touchend", end); };
  }, [isMobile, mapSurfaceRef, show]);

  useEffect(() => {
    if (!isMobile) return undefined;
    onVisibilityChange?.();
    const timer = window.setTimeout(() => onVisibilityChange?.(), 300);
    return () => window.clearTimeout(timer);
  }, [open, isMobile, onVisibilityChange]);

  const onDrawerTouchStart = (event) => {
    const point = event.touches[0];
    touchStart.current = point ? { x: point.clientX, y: point.clientY } : null;
  };
  const onDrawerTouchEnd = (event) => {
    const origin = touchStart.current;
    touchStart.current = null;
    const point = event.changedTouches[0];
    if (origin && point && origin.x - point.clientX > 60 && Math.abs(point.clientY - origin.y) < 60) setOpen(false);
  };

  return <div className={`mobile-map-panels ${className}`} ref={rootRef}>
    <button type="button" className="mobile-map-panels-button" aria-controls={id} aria-expanded={open}
      onClick={() => open ? setOpen(false) : show()}>Panels</button>
    {showHint && <div className="mobile-map-panels-hint" role="status">
      <span>Tap Panels or swipe from the left to see legends and filters</span>
      <button type="button" aria-label="Dismiss map panels hint" onClick={rememberHint}>×</button>
    </div>}
    <div className={`mobile-map-panels-drawer ${open ? "is-open" : ""}`} id={id}
      role={isMobile ? "region" : undefined} aria-label={isMobile ? "Map panels" : undefined}
      aria-hidden={isMobile && !open ? "true" : undefined}
      onTouchStart={onDrawerTouchStart} onTouchEnd={onDrawerTouchEnd}>
      <div className="mobile-map-panels-head">
        <strong>Map panels</strong>
        <button type="button" aria-label="Close panels" onClick={() => setOpen(false)}>×</button>
      </div>
      {children}
    </div>
  </div>;
}
