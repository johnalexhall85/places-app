import ProfileReport from "./ProfileReport";

function normalizeCountyFips(value) {
  const digits = String(value ?? "").replace(/[^0-9]/g, "");
  if (!digits) return null;
  if (digits.length === 5) return digits;
  if (digits.length < 5) return digits.padStart(5, "0");
  return digits.slice(0, 5);
}

export default function ProfileCounty({ countyFips }) {
  const normalized = normalizeCountyFips(countyFips);
  if (!normalized) {
    return <div style={{ padding: 24 }}>Invalid county FIPS.</div>;
  }
  return <ProfileReport geography="county" geoId={normalized} />;
}
