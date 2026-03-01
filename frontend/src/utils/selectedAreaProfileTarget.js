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

  const inferredLevel = asTrimmedText(
    firstDefined(selected.geo_level, tractsActive ? "tract" : "county")
  ).toLowerCase();
  const isTract = inferredLevel === "tract";

  if (isTract) {
    const tractGeoid = normalizeTractGeoid(
      firstDefined(selected.locationid, selected.location_id, selected.geoid)
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

  const countyFips = normalizeCountyFips(
    firstDefined(selected.county_fips, selected.location_id, selected.locationid, selected.geoid)
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
