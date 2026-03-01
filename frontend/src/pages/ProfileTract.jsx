import ProfileReport from "./ProfileReport";

function normalizeTractGeoid(value) {
  const digits = String(value ?? "").replace(/[^0-9]/g, "");
  if (!digits) return null;
  if (digits.length === 11) return digits;
  if (digits.length > 11) return digits.slice(-11);
  return null;
}

export default function ProfileTract({ tractGeoid }) {
  const normalized = normalizeTractGeoid(tractGeoid);
  if (!normalized) {
    return <div style={{ padding: 24 }}>Invalid tract GEOID.</div>;
  }
  return <ProfileReport geography="tract" geoId={normalized} />;
}
