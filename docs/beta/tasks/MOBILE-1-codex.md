# Task MOBILE-1 (Codex): mobile viewport for the header menu and map pages

Assigned by Claude, 2026-11-17, at John's request. Branch `codex/mobile-1` (checked out). Owned paths: `frontend/**` only. Same rules as before: no commits, pushes, deploys, or sudo; record facts in `docs/mcp/status/codex.md` and stop.

**Scope: mobile viewport only** (use one shared breakpoint, e.g. `max-width: 768px`). Desktop layout and behaviour must not change.

## 1. Menu

- Both headers (`components/SiteHeader.jsx` and `components/Header.jsx`, plus any page-specific nav) show a single menu button (hamburger, accessible label "Menu", `aria-expanded`, `aria-controls`) **in the top-right corner** on mobile.
- Tapping it opens the **full** menu (every link the desktop nav has) as a full-width panel or sheet; tapping again, tapping a link, pressing Escape, or tapping outside closes it. No horizontal page scroll at 360px width.

## 2. Map pages

Find every page with a map plus legends/panels (e.g. `pages/Places2025Pilot.jsx`, `community/TractPatternMap.jsx`, the CDC funding maps, and the facility overlays). Today on mobile the legends and panels cover the map entirely.

- On mobile, the page opens showing **only the map**; legends, filters, info and side panels are hidden.
- One floating button (e.g. "Panels", top-left of the map, ≥44px tap target) shows **all** the panels together in a drawer that slides in from the left. Tap the button again, tap a close control, or swipe the drawer back to the left to hide it.
- A swipe right starting from the left edge of the map opens the drawer. Don't break map panning: only an edge swipe (first ~24px) opens it.
- First visit on mobile: show a small dismissible hint near the button ("Tap Panels or swipe from the left to see legends and filters"). Hide it after the first open or dismissal; remember that in `localStorage` wrapped in try/catch.
- Build this as one reusable component (e.g. `components/MobileMapPanels.jsx` + CSS) and apply it to each map page instead of per-page hacks. Map must resize correctly (call the map's resize/invalidateSize) when the drawer opens/closes if needed.
- Follow the PDO brand rules in `docs/beta/EXECUTION_PLAN.md` ("Visual identity") and the existing token CSS.

## Verify

Add tests in the existing frontend test style (menu toggle, drawer toggle, hint dismissal, desktop unaffected). Run `npm test` and `npm run build`. If a headless browser is available, check 375×812 screenshots of the home page and two map pages. Report in five lines or fewer, listing the pages changed.
