const FALLBACK_API_BASE = "http://localhost:8000";

function normalizeApiBase(rawApiBase) {
  if (typeof rawApiBase !== "string") {
    return FALLBACK_API_BASE;
  }

  const trimmed = rawApiBase.trim();
  if (!trimmed) {
    return FALLBACK_API_BASE;
  }

  if (trimmed.startsWith("/")) {
    const origin =
      typeof window !== "undefined" && window.location?.origin
        ? window.location.origin
        : FALLBACK_API_BASE;
    return `${origin}${trimmed}`.replace(/\/+$/, "");
  }

  return trimmed.replace(/\/+$/, "");
}

export const API_BASE = normalizeApiBase(import.meta.env.VITE_API_BASE_URL);
