// Shape tolerance sent to the map APIs: about one screen pixel at the current zoom, in degrees.
// The server snaps shapes to a grid of this size, which keeps neighbouring borders identical,
// so areas fit together at every zoom while detail grows as the map zooms in.
export function gridForZoom(zoom, { min = 0.00005, max = 0.1 } = {}) {
  const level = Math.max(0, Math.floor(Number.isFinite(zoom) ? zoom : 4));
  const degreesPerPixel = 360 / (256 * 2 ** level);
  return Number(Math.min(max, Math.max(min, degreesPerPixel)).toPrecision(3));
}
