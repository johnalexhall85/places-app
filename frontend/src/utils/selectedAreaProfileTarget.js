function firstDefined(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined) {
      return value;
    }
  }
  return null;
}

function asTrimmedText(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

function normalizeCountyFips(value) {
  const digits = asTrimmedText(value).replace(/[^0-9]/g, "");
  if (!digits) return null;
  if (digits.length === 5) return digits;
  if (digits.length < 5) return digits.padStart(5, "0");
  if (digits.length > 5) return digits.slice(0, 5);
  return null;
}

function normalizeTractGeoid(value) {
  const digits = asTrimmedText(value).replace(/[^0-9]/g, "");
  if (!digits) return null;
  if (digits.length === 11) return digits;
  if (digits.length > 11) return digits.slice(-11);
  return null;
}

export function resolveSelectedAreaProfileTarget({ selectedFeatureProps, tractsActive }) {
  const selected = selectedFeatureProps && typeof selectedFeatureProps === "object"
    ? selectedFeatureProps
    : null;
  if (!selected) {
    return {
      enabled: false,
      reason: "Select a county or tract first",
      geography: null,
      id: null,
      href: null,
    };
  }

  const explicitLevel = asTrimmedText(firstDefined(selected.geo_level, selected.level)).toLowerCase();
  let inferredLevel = explicitLevel;
  if (!inferredLevel) {
    if (tractsActive) {
      inferredLevel = "tract";
    } else {
      const fallbackIdDigits = asTrimmedText(firstDefined(selected.state_fips, selected.id)).replace(/[^0-9]/g, "");
      const hasCountySignals = Boolean(
        firstDefined(selected.county_fips, selected.location_id, selected.locationid, selected.geoid)
      );
      inferredLevel = !hasCountySignals && fallbackIdDigits.length === 2 ? "state" : "county";
    }
  }
  const isTract = inferredLevel === "tract";
  const isState = inferredLevel === "state";

  if (isTract) {
    const tractGeoid = normalizeTractGeoid(
      firstDefined(selected.locationid, selected.location_id, selected.geoid, selected.id)
    );
    if (!tractGeoid) {
      return {
        enabled: false,
        reason: "Select a county or tract first",
        geography: null,
        id: null,
        href: null,
      };
    }
    return {
      enabled: true,
      reason: "",
      geography: "tract",
      id: tractGeoid,
      href: `/profile/tract/${encodeURIComponent(tractGeoid)}`,
    };
  }

  if (isState) {
    return {
      enabled: false,
      reason: "Zoom in to select a county or tract",
      geography: null,
      id: null,
      href: null,
    };
  }

  const countyFips = normalizeCountyFips(
    firstDefined(selected.county_fips, selected.location_id, selected.locationid, selected.geoid, selected.id)
  );
  if (!countyFips) {
    return {
      enabled: false,
      reason: "Select a county or tract first",
      geography: null,
      id: null,
      href: null,
    };
  }
  return {
    enabled: true,
    reason: "",
    geography: "county",
    id: countyFips,
    href: `/profile/county/${encodeURIComponent(countyFips)}`,
  };
}
