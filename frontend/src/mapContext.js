/**
 * @typedef {Object} MapContext
 * @property {string} dataSource
 * @property {"county" | "tract" | "place" | "zcta"} geoLevel
 * @property {{
 *   countyFips?: string,
 *   tractGeoid?: string,
 *   name?: string,
 *   stateAbbr?: string
 * }} selectedArea
 * @property {{
 *   hpsaDomain?: "pc" | "mh" | "dh",
 *   placesMeasureId?: string,
 *   placesYear?: number,
 *   placesValueTypeId?: string,
 *   cmsMeasureId?: string,
 *   cmsYear?: number,
 *   cmsAgeLevel?: string,
 *   acsVariable?: string,
 *   acsYearWindow?: string,
 *   acsDataValueTypeId?: string,
 *   sviTheme?: string,
 *   sviMeasureId?: string,
 *   sviYear?: number
 * }} selection
 * @property {{
 *   zoom?: number,
 *   bbox?: [number, number, number, number]
 * }} mapState
 * @property {string | undefined} asOfDate
 */

function hasText(value) {
  return value != null && String(value).trim().length > 0;
}

function normalizeDataSource(value) {
  const token = String(value ?? "").trim().toLowerCase();
  if (token === "places") return "PLACES";
  if (token === "acs_nmf" || token === "acs-nmf" || token === "acs") return "ACS";
  if (token === "svi") return "SVI";
  if (token === "hpsa") return "HPSA";
  if (token === "cms") return "CMS";
  return String(value ?? "").trim().toUpperCase() || "UNKNOWN";
}

function normalizeBbox(value) {
  if (Array.isArray(value) && value.length === 4) {
    const numeric = value.map((entry) => Number(entry));
    if (numeric.every((entry) => Number.isFinite(entry))) {
      return /** @type {[number, number, number, number]} */ (numeric);
    }
  }

  if (typeof value === "string") {
    const parts = value.split(",").map((entry) => Number(entry.trim()));
    if (parts.length === 4 && parts.every((entry) => Number.isFinite(entry))) {
      return /** @type {[number, number, number, number]} */ (parts);
    }
  }

  return undefined;
}

function removeUndefined(value) {
  if (Array.isArray(value)) {
    return value.map((item) => removeUndefined(item));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, entry]) => entry !== undefined)
        .map(([key, entry]) => [key, removeUndefined(entry)])
    );
  }
  return value;
}

/**
 * @param {{
 *   dataSource: string,
 *   geoLevel: string,
 *   selectedArea: {
 *     countyFips?: string | null,
 *     tractGeoid?: string | null,
 *     name?: string | null,
 *     stateAbbr?: string | null
 *   },
 *   selection: {
 *     hpsaDomain?: string | null,
 *     placesMeasureId?: string | null,
 *     placesYear?: number | null,
 *     placesValueTypeId?: string | null,
 *     cmsMeasureId?: string | null,
 *     cmsYear?: number | null,
 *     cmsAgeLevel?: string | null,
 *     acsVariable?: string | null,
 *     acsYearWindow?: string | null,
 *     acsDataValueTypeId?: string | null,
 *     sviTheme?: string | null,
 *     sviMeasureId?: string | null,
 *     sviYear?: number | null
 *   },
 *   mapState?: {
 *     zoom?: number | null,
 *     bbox?: string | number[] | null
 *   },
 *   asOfDate?: string | null
 * }} input
 * @returns {MapContext}
 */
export function buildMapContext(input) {
  const geoLevel = String(input?.geoLevel ?? "").trim().toLowerCase() || "county";
  const normalizedGeoLevel = (
    geoLevel === "county"
    || geoLevel === "tract"
    || geoLevel === "place"
    || geoLevel === "zcta"
  ) ? geoLevel : "county";

  const selectedArea = {
    countyFips: hasText(input?.selectedArea?.countyFips)
      ? String(input.selectedArea.countyFips).trim()
      : undefined,
    tractGeoid: hasText(input?.selectedArea?.tractGeoid)
      ? String(input.selectedArea.tractGeoid).trim()
      : undefined,
    name: hasText(input?.selectedArea?.name)
      ? String(input.selectedArea.name).trim()
      : undefined,
    stateAbbr: hasText(input?.selectedArea?.stateAbbr)
      ? String(input.selectedArea.stateAbbr).trim().toUpperCase()
      : undefined,
  };

  const selection = {
    hpsaDomain: hasText(input?.selection?.hpsaDomain)
      ? String(input.selection.hpsaDomain).trim().toLowerCase()
      : undefined,
    placesMeasureId: hasText(input?.selection?.placesMeasureId)
      ? String(input.selection.placesMeasureId).trim()
      : undefined,
    placesYear: Number.isFinite(Number(input?.selection?.placesYear))
      ? Number(input.selection.placesYear)
      : undefined,
    placesValueTypeId: hasText(input?.selection?.placesValueTypeId)
      ? String(input.selection.placesValueTypeId).trim()
      : undefined,
    cmsMeasureId: hasText(input?.selection?.cmsMeasureId)
      ? String(input.selection.cmsMeasureId).trim()
      : undefined,
    cmsYear: Number.isFinite(Number(input?.selection?.cmsYear))
      ? Number(input.selection.cmsYear)
      : undefined,
    cmsAgeLevel: hasText(input?.selection?.cmsAgeLevel)
      ? String(input.selection.cmsAgeLevel).trim()
      : undefined,
    acsVariable: hasText(input?.selection?.acsVariable)
      ? String(input.selection.acsVariable).trim()
      : undefined,
    acsYearWindow: hasText(input?.selection?.acsYearWindow)
      ? String(input.selection.acsYearWindow).trim()
      : undefined,
    acsDataValueTypeId: hasText(input?.selection?.acsDataValueTypeId)
      ? String(input.selection.acsDataValueTypeId).trim()
      : undefined,
    sviTheme: hasText(input?.selection?.sviTheme)
      ? String(input.selection.sviTheme).trim()
      : undefined,
    sviMeasureId: hasText(input?.selection?.sviMeasureId)
      ? String(input.selection.sviMeasureId).trim()
      : undefined,
    sviYear: Number.isFinite(Number(input?.selection?.sviYear))
      ? Number(input.selection.sviYear)
      : undefined,
  };

  const mapState = {
    zoom: Number.isFinite(Number(input?.mapState?.zoom))
      ? Number(input.mapState.zoom)
      : undefined,
    bbox: normalizeBbox(input?.mapState?.bbox ?? null),
  };

  /** @type {MapContext} */
  const payload = {
    dataSource: normalizeDataSource(input?.dataSource ?? ""),
    geoLevel: normalizedGeoLevel,
    selectedArea,
    selection,
    mapState,
    asOfDate: hasText(input?.asOfDate) ? String(input.asOfDate).trim() : undefined,
  };

  return /** @type {MapContext} */ (removeUndefined(payload));
}
