import { API_BASE as DEFAULT_API_BASE } from "../config/apiBase";

async function parseJsonOrThrow(response, fallbackMessage) {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(body || fallbackMessage);
  }
  return response.json();
}

function buildJsonOptions(method, body, signal) {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
    signal,
  };
}

export async function fetchFundingModels({ apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(new URL(`${apiBase}/api/funding-models`), { signal });
  return parseJsonOrThrow(response, "Failed to load funding models.");
}

export async function fetchFundingModelFieldCatalog({ apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(new URL(`${apiBase}/api/funding-models/field-catalog`), { signal });
  return parseJsonOrThrow(response, "Failed to load funding model field catalog.");
}

export async function fetchFundingModel(modelId, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(new URL(`${apiBase}/api/funding-models/${encodeURIComponent(modelId)}`), { signal });
  return parseJsonOrThrow(response, "Failed to load funding model.");
}

export async function createFundingModel(body, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    new URL(`${apiBase}/api/funding-models`),
    buildJsonOptions("POST", body, signal)
  );
  return parseJsonOrThrow(response, "Failed to create funding model.");
}

export async function updateFundingModel(modelId, body, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    new URL(`${apiBase}/api/funding-models/${encodeURIComponent(modelId)}`),
    buildJsonOptions("PUT", body, signal)
  );
  return parseJsonOrThrow(response, "Failed to update funding model.");
}

export async function createFundingModelVersion(modelId, body, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    new URL(`${apiBase}/api/funding-models/${encodeURIComponent(modelId)}/versions`),
    buildJsonOptions("POST", body, signal)
  );
  return parseJsonOrThrow(response, "Failed to create funding model version.");
}

export async function previewFundingModel(body, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    new URL(`${apiBase}/api/funding-models/preview`),
    buildJsonOptions("POST", body, signal)
  );
  return parseJsonOrThrow(response, "Failed to preview funding model.");
}

export async function previewSavedFundingModel(modelId, body, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    new URL(`${apiBase}/api/funding-models/${encodeURIComponent(modelId)}/preview`),
    buildJsonOptions("POST", body, signal)
  );
  return parseJsonOrThrow(response, "Failed to preview saved funding model.");
}

export async function lockFundingModel(modelId, body = {}, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    new URL(`${apiBase}/api/funding-models/${encodeURIComponent(modelId)}/lock`),
    buildJsonOptions("POST", body, signal)
  );
  return parseJsonOrThrow(response, "Failed to lock funding model.");
}

export async function buildFundingModel(modelId, body = {}, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    new URL(`${apiBase}/api/funding-models/${encodeURIComponent(modelId)}/build`),
    buildJsonOptions("POST", body, signal)
  );
  return parseJsonOrThrow(response, "Failed to build funding model.");
}

export async function publishFundingModel(modelId, body = {}, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    new URL(`${apiBase}/api/funding-models/${encodeURIComponent(modelId)}/publish`),
    buildJsonOptions("POST", body, signal)
  );
  return parseJsonOrThrow(response, "Failed to publish funding model.");
}

export async function cloneFundingModel(modelId, body = {}, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    new URL(`${apiBase}/api/funding-models/${encodeURIComponent(modelId)}/clone`),
    buildJsonOptions("POST", body, signal)
  );
  return parseJsonOrThrow(response, "Failed to clone funding model version.");
}

export async function archiveFundingModel(modelId, { apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(
    new URL(`${apiBase}/api/funding-models/${encodeURIComponent(modelId)}/archive`),
    buildJsonOptions("POST", {}, signal)
  );
  return parseJsonOrThrow(response, "Failed to archive funding model.");
}

export async function fetchFundingModeRegistry({ apiBase = DEFAULT_API_BASE, signal } = {}) {
  const response = await fetch(new URL(`${apiBase}/api/funding-modes`), { signal });
  return parseJsonOrThrow(response, "Failed to load funding modes.");
}
