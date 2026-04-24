import { API_BASE as DEFAULT_API_BASE } from "../config/apiBase";

const DEMO_ACCESS_BASE_PATH = "/api/demo-access";

function buildDemoAccessUrl(apiBase, path) {
  const base = String(apiBase ?? DEFAULT_API_BASE).trim().replace(/\/+$/, "");
  const normalizedPath = `/${String(path ?? "").trim().replace(/^\/+/, "")}`;
  const routePath = `${DEMO_ACCESS_BASE_PATH}${normalizedPath === "/" ? "" : normalizedPath}`;
  const effectiveBase = /\/api$/i.test(base) && routePath.startsWith("/api/")
    ? base.slice(0, -4)
    : base;
  return new URL(`${effectiveBase}${routePath}`);
}

async function parseJsonOrThrow(response, fallbackMessage) {
  if (response.ok) {
    return response.json();
  }
  const text = await response.text().catch(() => "");
  let body = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = text ? { detail: text } : {};
  }
  const detail = typeof body?.detail === "string" ? body.detail : fallbackMessage;
  throw new Error(detail || fallbackMessage);
}

function jsonOptions(method, body, signal, adminSecret) {
  const headers = { "Content-Type": "application/json" };
  if (adminSecret) {
    headers["X-Demo-Admin-Secret"] = adminSecret;
  }
  return {
    method,
    credentials: "include",
    headers,
    body: JSON.stringify(body ?? {}),
    signal,
  };
}

function adminGetOptions(signal, adminSecret) {
  return {
    credentials: "include",
    signal,
    headers: adminSecret ? { "X-Demo-Admin-Secret": adminSecret } : {},
  };
}

export function installDemoAccessFetchCredentials(apiBase = DEFAULT_API_BASE) {
  if (typeof window === "undefined" || typeof window.fetch !== "function") {
    return;
  }
  if (window.fetch.__chipDemoAccessCredentialsInstalled) {
    return;
  }

  const originalFetch = window.fetch.bind(window);
  const apiUrl = new URL(apiBase, window.location.origin);
  const apiOrigin = apiUrl.origin;
  const apiPathPrefix = apiUrl.pathname.replace(/\/+$/, "");

  function shouldIncludeCredentials(input) {
    const rawUrl = typeof input === "string" || input instanceof URL
      ? String(input)
      : input?.url;
    if (!rawUrl) return false;
    const url = new URL(rawUrl, window.location.origin);
    if (url.origin !== apiOrigin) return false;
    if (!apiPathPrefix || apiPathPrefix === "/") return true;
    return url.pathname === apiPathPrefix || url.pathname.startsWith(`${apiPathPrefix}/`);
  }

  window.fetch = (input, init = {}) => {
    if (init?.credentials || !shouldIncludeCredentials(input)) {
      return originalFetch(input, init);
    }
    return originalFetch(input, { ...init, credentials: "include" });
  };
  window.fetch.__chipDemoAccessCredentialsInstalled = true;
}

export async function fetchDemoAccessSession({ apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(buildDemoAccessUrl(apiBase, "/session"), {
    credentials: "include",
    signal,
  });
  return parseJsonOrThrow(response, "Failed to check demo access session.");
}

export async function validateDemoAccessCode(accessCode, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    buildDemoAccessUrl(apiBase, "/validate"),
    jsonOptions("POST", { access_code: accessCode }, signal)
  );
  return parseJsonOrThrow(response, "Invalid or expired access code.");
}

export async function logoutDemoAccess({ apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    buildDemoAccessUrl(apiBase, "/logout"),
    jsonOptions("POST", {}, signal)
  );
  return parseJsonOrThrow(response, "Failed to clear demo access.");
}

export async function fetchDemoAccessCodes(adminSecret, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    buildDemoAccessUrl(apiBase, "/admin/codes"),
    adminGetOptions(signal, adminSecret)
  );
  return parseJsonOrThrow(response, "Failed to load access codes.");
}

export async function createDemoAccessCode(body, adminSecret, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    buildDemoAccessUrl(apiBase, "/admin/codes"),
    jsonOptions("POST", body, signal, adminSecret)
  );
  return parseJsonOrThrow(response, "Failed to create access code.");
}

export async function updateDemoAccessCode(codeId, body, adminSecret, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    buildDemoAccessUrl(apiBase, `/admin/codes/${encodeURIComponent(codeId)}`),
    jsonOptions("PATCH", body, signal, adminSecret)
  );
  return parseJsonOrThrow(response, "Failed to update access code.");
}

export async function fetchDemoAccessEvents(adminSecret, { apiBase = DEFAULT_API_BASE, signal, limit = 100 } = {}) {
  const url = buildDemoAccessUrl(apiBase, "/admin/events");
  url.searchParams.set("limit", String(limit));
  const response = await fetch(url, adminGetOptions(signal, adminSecret));
  return parseJsonOrThrow(response, "Failed to load access events.");
}
