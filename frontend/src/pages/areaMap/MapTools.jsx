import { BASE_MAP_OPTIONS } from "../../branding/baseMaps";

// The legacy map's "Map Tools" bar for the /area maps. "Analyze this area" is not carried over:
// the assistant reads the legacy datasets, not the release-pinned values shown here.
export default function MapTools({
  map, home, hasSelection, zoomToSelectedLabel = "Zoom to selected area", onZoomToSelected, onClearSelection,
  profileHref, profileLabel = "Open profile", profileDisabledReason = "Select a county, state, or district first",
  baseMapId, onBaseMapChange,
}) {
  return (
    <div className="pilot-tools-row" role="group" aria-label="Map tools">
      <button type="button" className="chip-secondary-btn" disabled={!map} onClick={() => map?.setView(home.center, home.zoom)}>Home</button>
      <button type="button" className="chip-secondary-btn" disabled={!map} onClick={() => map?.zoomIn()}>Zoom In</button>
      <button type="button" className="chip-secondary-btn" disabled={!map} onClick={() => map?.zoomOut()}>Zoom Out</button>
      <button type="button" className={`chip-secondary-btn ${hasSelection ? "" : "is-disabled"}`} disabled={!hasSelection} onClick={onZoomToSelected}>{zoomToSelectedLabel}</button>
      <button type="button" className={`chip-secondary-btn ${hasSelection ? "" : "is-disabled"}`} disabled={!hasSelection} onClick={onClearSelection}>Clear Selection (Esc)</button>
      {profileHref
        ? <a className="chip-secondary-btn" href={profileHref}>{profileLabel}</a>
        : <button type="button" className="chip-secondary-btn is-disabled" disabled aria-disabled="true" title={profileDisabledReason}>{profileLabel}</button>}
      <label className="pilot-tools-basemap">
        <span>Base map</span>
        <select value={baseMapId} onChange={(event) => onBaseMapChange(event.target.value)} aria-label="Select base map">
          {BASE_MAP_OPTIONS.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
      </label>
    </div>
  );
}
