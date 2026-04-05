import { useEffect, useMemo, useReducer, useState } from "react";
import Header from "../components/Header";
import {
  archiveFundingModel,
  buildFundingModel,
  cloneFundingModel,
  createFundingModel,
  fetchFundingModelFieldCatalog,
  fetchFundingModel,
  fetchFundingModels,
  previewFundingModel,
  publishFundingModel,
  lockFundingModel,
  updateFundingModel,
} from "../api/fundingModels";
import { API_BASE } from "../config/apiBase";
import { isFundingModelBuilderEnabled } from "../utils/fundingModelBuilderAccess";
import {
  builderReducer,
  buildDraftFromModel,
  createEmptyDraft,
  DATA_SOURCE_OPTIONS,
  OPTION_LABELS,
} from "../utils/fundingModelBuilderState";
import "./FundingModelBuilder.css";

const FIELD_GROUP_LABELS = {
  common: "Common",
  assistance: "Assistance Only",
  contract: "Contract Only",
  legacy_curated: "Legacy Curated",
};

const DEFAULT_RULE_OPERATORS = ["equals", "not_equals", "in", "not_in", "contains", "not_contains", "starts_with", "ends_with", "greater_than", "less_than", "is_null", "is_not_null"];

function firstDefined(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined) return value;
  }
  return null;
}

function draftToApiPayload(draft, { statusOverride, fieldCatalogMap = new Map() } = {}) {
  return {
    ...draft,
    status: statusOverride ?? draft.status ?? "draft",
    chip_methodology_version: String(draft.chip_methodology_version ?? "").trim(),
    display_name: String(draft.display_name ?? "").trim(),
    internal_model_id: String(draft.internal_model_id ?? "").trim(),
    funding_mode_key: String(draft.funding_mode_key ?? "").trim(),
    slug: String(draft.slug ?? "").trim(),
    description: String(draft.description ?? "").trim(),
    chip_state_profile_source_version: String(draft.chip_state_profile_source_version ?? "").trim(),
    chip_normalization_source_version: String(draft.chip_normalization_source_version ?? "").trim(),
    definition: {
      ...draft.definition,
      advanced_sql_override: String(draft.definition.advanced_sql_override ?? "").trim() || null,
      aggregation: {
        ...draft.definition.aggregation,
        default_fiscal_year: Number.isFinite(Number(draft.definition.aggregation.default_fiscal_year))
          ? Number(draft.definition.aggregation.default_fiscal_year)
          : null,
      },
      include_group: normalizeGroupForApi(draft.definition.include_group, fieldCatalogMap),
      exclude_group: normalizeGroupForApi(draft.definition.exclude_group, fieldCatalogMap),
    },
  };
}

function normalizeGroupForApi(group, fieldCatalogMap) {
  return {
    id: group.id,
    combinator: group.combinator,
    children: Array.isArray(group.children)
      ? group.children.map((child) => (
        child.children
          ? normalizeGroupForApi(child, fieldCatalogMap)
          : {
            ...child,
            value: normalizeRuleValue(child, fieldCatalogMap),
          }
      ))
      : [],
  };
}

function normalizeRuleValue(rule, fieldCatalogMap) {
  const operator = String(rule?.operator ?? "").trim().toLowerCase();
  const field = String(rule?.field ?? "").trim();
  const rawValue = rule?.value;
  if (operator === "is_null" || operator === "is_not_null") {
    return null;
  }
  if (operator === "in" || operator === "not_in") {
    return String(rawValue ?? "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => coerceFieldValue(field, item, fieldCatalogMap));
  }
  return coerceFieldValue(field, rawValue, fieldCatalogMap);
}

function coerceFieldValue(field, value, fieldCatalogMap = new Map()) {
  const fieldType = fieldCatalogMap.get(field)?.type ?? "text";
  if (fieldType === "number") {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : value;
  }
  if (fieldType === "boolean") {
    if (value === true || value === "true") return true;
    if (value === false || value === "false") return false;
  }
  return value;
}

function validateDraft(draft) {
  const errors = [];
  if (!String(draft.display_name ?? "").trim()) {
    errors.push("Display name is required.");
  }
  if (!String(draft.internal_model_id ?? "").trim()) {
    errors.push("Internal model ID is required.");
  }
  if (!String(draft.chip_methodology_version ?? "").trim()) {
    errors.push("Methodology version is required.");
  }
  if (draft.status !== "draft") {
    if (!String(draft.chip_state_profile_source_version ?? "").trim()) {
      errors.push("State profile source version is required before locking.");
    }
    if (!String(draft.chip_normalization_source_version ?? "").trim()) {
      errors.push("Normalization source version is required before locking.");
    }
  }
  return errors;
}

function StatusBadge({ status }) {
  return <span className={`funding-model-status funding-model-status-${status}`}>{status}</span>;
}

function RuleValueField({ rule, disabled, onChange, fieldMeta }) {
  const operator = String(rule.operator ?? "").trim().toLowerCase();
  if (operator === "is_null" || operator === "is_not_null") {
    return <div className="funding-model-rule-value-disabled">No value needed</div>;
  }
  if (fieldMeta?.type === "boolean") {
    return (
      <select value={String(rule.value ?? "")} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }
  const inputType = operator === "in" || operator === "not_in"
    ? "text"
    : fieldMeta?.type === "number"
      ? "number"
      : fieldMeta?.type === "date"
        ? "date"
        : "text";
  return (
    <input
      type={inputType}
      value={String(rule.value ?? "")}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
      placeholder={operator === "in" || operator === "not_in" ? "comma,separated,values" : "Value"}
    />
  );
}

function RuleFieldPicker({ disabled, availableFields, rule, onChange }) {
  const [query, setQuery] = useState("");
  const normalizedQuery = String(query ?? "").trim().toLowerCase();
  const filteredFields = useMemo(() => {
    if (!normalizedQuery) return availableFields;
    return availableFields.filter((item) => (
      String(item.label ?? "").toLowerCase().includes(normalizedQuery)
      || String(item.raw_key ?? "").toLowerCase().includes(normalizedQuery)
      || String(item.key ?? "").toLowerCase().includes(normalizedQuery)
    ));
  }, [availableFields, normalizedQuery]);

  const groupedFields = useMemo(() => {
    const groups = new Map();
    filteredFields.forEach((item) => {
      const group = item.group ?? "common";
      if (!groups.has(group)) {
        groups.set(group, []);
      }
      groups.get(group).push(item);
    });
    return groups;
  }, [filteredFields]);

  const selectedField = availableFields.find((item) => item.key === rule.field) ?? null;

  return (
    <div className="funding-model-field-picker">
      <input
        value={query}
        disabled={disabled}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search fields"
      />
      <select value={rule.field} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        {filteredFields.length === 0 ? <option value={rule.field}>No matching fields</option> : null}
        {Array.from(groupedFields.entries()).map(([group, items]) => (
          <optgroup key={group} label={FIELD_GROUP_LABELS[group] ?? group}>
            {items.map((field) => (
              <option key={field.key} value={field.key}>
                {field.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {selectedField ? (
        <div className="funding-model-field-meta">
          <small>{selectedField.raw_key}</small>
        </div>
      ) : null}
    </div>
  );
}

function RuleConditionEditor({ root, rule, disabled, dispatch, availableFields, fieldCatalogMap }) {
  const fieldMeta = fieldCatalogMap.get(rule.field) ?? availableFields[0] ?? { key: rule.field, operators: DEFAULT_RULE_OPERATORS, type: "text" };
  const operators = Array.isArray(fieldMeta.operators) && fieldMeta.operators.length > 0
    ? fieldMeta.operators
    : DEFAULT_RULE_OPERATORS;

  return (
    <div className="funding-model-rule-row" key={rule.id}>
      <RuleFieldPicker
        disabled={disabled}
        availableFields={availableFields}
        rule={rule}
        onChange={(nextField) => {
          const nextMeta = fieldCatalogMap.get(nextField) ?? availableFields.find((item) => item.key === nextField) ?? null;
          dispatch({
            type: "rule-field",
            root,
            nodeId: rule.id,
            value: nextField,
            operator: nextMeta?.operators?.[0] ?? "equals",
            ruleValue: nextMeta?.type === "boolean" ? "true" : "",
          });
        }}
      />
      <select
        value={operators.includes(rule.operator) ? rule.operator : operators[0]}
        disabled={disabled}
        onChange={(event) => dispatch({ type: "rule-change", root, nodeId: rule.id, field: "operator", value: event.target.value })}
      >
        {operators.map((operator) => (
          <option key={operator} value={operator}>{operator}</option>
        ))}
      </select>
      <RuleValueField
        rule={rule}
        fieldMeta={fieldMeta}
        disabled={disabled}
        onChange={(value) => dispatch({ type: "rule-change", root, nodeId: rule.id, field: "value", value })}
      />
      <div className="funding-model-inline-actions">
        <button type="button" className="chip-secondary-btn" disabled={disabled} onClick={() => dispatch({ type: "duplicate-node", root, nodeId: rule.id })}>
          Duplicate
        </button>
        <button type="button" className="chip-secondary-btn" disabled={disabled} onClick={() => dispatch({ type: "delete-node", root, nodeId: rule.id })}>
          Delete
        </button>
      </div>
    </div>
  );
}

function RuleGroupEditor({ title, root, group, disabled, dispatch, availableFields, fieldCatalogMap }) {
  return (
    <section className="funding-model-section">
      <div className="funding-model-section-header">
        <h3>{title}</h3>
        <div className="funding-model-inline-actions">
          <select
            value={group.combinator}
            disabled={disabled}
            onChange={(event) => dispatch({ type: "group-combinator", root, value: event.target.value })}
          >
            <option value="ALL">ALL</option>
            <option value="ANY">ANY</option>
          </select>
          <button type="button" className="chip-secondary-btn" disabled={disabled} onClick={() => dispatch({ type: "add-rule", root, groupId: group.id })}>
            Add Rule
          </button>
          <button type="button" className="chip-secondary-btn" disabled={disabled} onClick={() => dispatch({ type: "add-group", root, groupId: group.id })}>
            Add Group
          </button>
        </div>
      </div>
      <RuleGroupNode
        root={root}
        group={group}
        disabled={disabled}
        dispatch={dispatch}
        depth={0}
        availableFields={availableFields}
        fieldCatalogMap={fieldCatalogMap}
      />
    </section>
  );
}

function RuleGroupNode({ root, group, disabled, dispatch, depth, availableFields, fieldCatalogMap }) {
  return (
    <div className="funding-model-rule-group" data-depth={depth}>
      {group.children.length === 0 ? (
        <div className="funding-model-empty-state">No rules in this group yet.</div>
      ) : null}
      {group.children.map((child) => (
        child.children ? (
          <div key={child.id} className="funding-model-rule-branch">
            <div className="funding-model-rule-branch-header">
              <strong>Group</strong>
              <span>{child.combinator}</span>
              <div className="funding-model-inline-actions">
                <button type="button" className="chip-secondary-btn" disabled={disabled} onClick={() => dispatch({ type: "add-rule", root, groupId: child.id })}>
                  Add Rule
                </button>
                <button type="button" className="chip-secondary-btn" disabled={disabled} onClick={() => dispatch({ type: "add-group", root, groupId: child.id })}>
                  Add Group
                </button>
                <button type="button" className="chip-secondary-btn" disabled={disabled} onClick={() => dispatch({ type: "duplicate-node", root, nodeId: child.id })}>
                  Duplicate
                </button>
                <button type="button" className="chip-secondary-btn" disabled={disabled} onClick={() => dispatch({ type: "delete-node", root, nodeId: child.id })}>
                  Delete
                </button>
              </div>
            </div>
            <div className="funding-model-inline-actions">
              <label>
                Logic
                <select
                  value={child.combinator}
                  disabled={disabled}
                  onChange={(event) => dispatch({ type: "rule-change", root, nodeId: child.id, field: "combinator", value: event.target.value })}
                >
                  <option value="ALL">ALL</option>
                  <option value="ANY">ANY</option>
                </select>
              </label>
            </div>
            <RuleGroupNode
              root={root}
              group={child}
              disabled={disabled}
              dispatch={dispatch}
              depth={depth + 1}
              availableFields={availableFields}
              fieldCatalogMap={fieldCatalogMap}
            />
          </div>
        ) : (
          <RuleConditionEditor
            key={child.id}
            root={root}
            rule={child}
            disabled={disabled}
            dispatch={dispatch}
            availableFields={availableFields}
            fieldCatalogMap={fieldCatalogMap}
          />
        )
      ))}
    </div>
  );
}

export default function FundingModelBuilder() {
  const [draft, dispatch] = useReducer(builderReducer, undefined, createEmptyDraft);
  const [models, setModels] = useState([]);
  const [fieldCatalog, setFieldCatalog] = useState([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [selectedModel, setSelectedModel] = useState(null);
  const [preview, setPreview] = useState(null);
  const [activeAction, setActiveAction] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const enabled = isFundingModelBuilderEnabled();
  const validationErrors = useMemo(() => validateDraft(draft), [draft]);
  const isDraftEditable = !selectedModel || selectedModel.status === "draft";
  const currentStatus = selectedModel?.status ?? draft.status ?? "draft";
  const currentVersionNumber = selectedModel?.current_version?.version_number ?? null;
  const selectedSourceKeys = useMemo(
    () => Object.entries(draft.definition.data_sources ?? {}).filter(([, value]) => Boolean(value)).map(([key]) => key),
    [draft.definition.data_sources]
  );
  const availableFieldItems = useMemo(
    () => fieldCatalog.filter((item) => Array.isArray(item.applies_to_sources) && item.applies_to_sources.some((sourceKey) => selectedSourceKeys.includes(sourceKey))),
    [fieldCatalog, selectedSourceKeys]
  );
  const fieldCatalogMap = useMemo(
    () => new Map(fieldCatalog.map((item) => [item.key, item])),
    [fieldCatalog]
  );

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    fetchFundingModels({ apiBase: API_BASE, signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setModels(Array.isArray(payload) ? payload : []);
      })
      .catch((fetchError) => {
        if (controller.signal.aborted) return;
        setError(fetchError.message ?? "Failed to load funding models.");
      });
    return () => controller.abort();
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    fetchFundingModelFieldCatalog({ apiBase: API_BASE, signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setFieldCatalog(Array.isArray(payload?.items) ? payload.items : []);
      })
      .catch((fetchError) => {
        if (controller.signal.aborted) return;
        setError(fetchError.message ?? "Failed to load funding model field catalog.");
      });
    return () => controller.abort();
  }, [enabled]);

  async function loadModel(modelId) {
    setActiveAction("load");
    setError("");
    try {
      const payload = await fetchFundingModel(modelId, { apiBase: API_BASE });
      setSelectedModel(payload);
      setSelectedModelId(String(payload.id));
      dispatch({ type: "replace", value: buildDraftFromModel(payload) });
      setPreview(null);
      setMessage(`Loaded ${payload.display_name}.`);
    } catch (loadError) {
      setError(loadError.message ?? "Failed to load funding model.");
    } finally {
      setActiveAction("");
    }
  }

  async function handlePreview() {
    setActiveAction("preview");
    setError("");
    try {
      const payload = await previewFundingModel(
        {
          ...draftToApiPayload(draft, { fieldCatalogMap }),
          preview_fiscal_year: Number.isFinite(Number(draft.definition.aggregation.default_fiscal_year))
            ? Number(draft.definition.aggregation.default_fiscal_year)
            : null,
          preview_geography_level: draft.definition.aggregation.default_geography || "state",
        },
        { apiBase: API_BASE }
      );
      setPreview(payload);
      setMessage("Preview refreshed.");
    } catch (previewError) {
      setError(previewError.message ?? "Preview failed.");
    } finally {
      setActiveAction("");
    }
  }

  async function handleSave() {
    setActiveAction("save");
    setError("");
    try {
      const payload = draftToApiPayload(draft, { fieldCatalogMap });
      const result = selectedModel
        ? await updateFundingModel(selectedModel.id, payload, { apiBase: API_BASE })
        : await createFundingModel(payload, { apiBase: API_BASE });
      setSelectedModel(result);
      setSelectedModelId(String(result.id));
      setModels((current) => {
        const remainder = current.filter((item) => item.id !== result.id);
        return [result, ...remainder];
      });
      dispatch({ type: "replace", value: buildDraftFromModel(result) });
      setMessage("Draft saved.");
    } catch (saveError) {
      setError(saveError.message ?? "Failed to save draft.");
    } finally {
      setActiveAction("");
    }
  }

  async function handleLock() {
    if (!selectedModel || !window.confirm("Lock this version? Locked versions are immutable.")) return;
    setActiveAction("lock");
    setError("");
    try {
      const result = await lockFundingModel(selectedModel.id, { version_number: currentVersionNumber }, { apiBase: API_BASE });
      setSelectedModel(result);
      setModels((current) => current.map((item) => (item.id === result.id ? result : item)));
      dispatch({ type: "replace", value: buildDraftFromModel(result) });
      setMessage("Version locked.");
    } catch (lockError) {
      setError(lockError.message ?? "Failed to lock version.");
    } finally {
      setActiveAction("");
    }
  }

  async function handleBuild() {
    if (!selectedModel) return;
    setActiveAction("build");
    setError("");
    try {
      const result = await buildFundingModel(selectedModel.id, { version_number: currentVersionNumber }, { apiBase: API_BASE });
      const model = result?.model ?? result;
      setSelectedModel(model);
      setModels((current) => current.map((item) => (item.id === model.id ? model : item)));
      dispatch({ type: "replace", value: buildDraftFromModel(model) });
      setMessage("Backend layer built.");
    } catch (buildError) {
      setError(buildError.message ?? "Build failed.");
    } finally {
      setActiveAction("");
    }
  }

  async function handlePublish() {
    if (!selectedModel || !window.confirm("Publish this funding mode to the CDC map?")) return;
    setActiveAction("publish");
    setError("");
    try {
      const result = await publishFundingModel(
        selectedModel.id,
        {
          version_number: currentVersionNumber,
          label: draft.display_name,
        },
        { apiBase: API_BASE }
      );
      setSelectedModel(result);
      setModels((current) => current.map((item) => (item.id === result.id ? result : item)));
      dispatch({ type: "replace", value: buildDraftFromModel(result) });
      setMessage("Funding mode published.");
    } catch (publishError) {
      setError(publishError.message ?? "Publish failed.");
    } finally {
      setActiveAction("");
    }
  }

  async function handleClone() {
    if (!selectedModel) return;
    setActiveAction("clone");
    setError("");
    try {
      const result = await cloneFundingModel(
        selectedModel.id,
        {
          version_number: currentVersionNumber,
          version_label: draft.version_label || "",
        },
        { apiBase: API_BASE }
      );
      setSelectedModel(result);
      setModels((current) => current.map((item) => (item.id === result.id ? result : item)));
      dispatch({ type: "replace", value: buildDraftFromModel(result) });
      setMessage("New draft version created from the locked artifact.");
    } catch (cloneError) {
      setError(cloneError.message ?? "Clone failed.");
    } finally {
      setActiveAction("");
    }
  }

  async function handleArchive() {
    if (!selectedModel || !window.confirm("Archive this model? It will be hidden from normal selection.")) return;
    setActiveAction("archive");
    setError("");
    try {
      const result = await archiveFundingModel(selectedModel.id, { apiBase: API_BASE });
      setSelectedModel(result);
      setModels((current) => current.map((item) => (item.id === result.id ? result : item)));
      dispatch({ type: "replace", value: buildDraftFromModel(result) });
      setMessage("Model archived.");
    } catch (archiveError) {
      setError(archiveError.message ?? "Archive failed.");
    } finally {
      setActiveAction("");
    }
  }

  if (!enabled) {
    return (
      <div className="funding-model-page">
        <Header />
        <main className="funding-model-builder-main">
          <div className="funding-model-alert funding-model-alert-error">
            Funding Model Builder is not enabled in this environment.
          </div>
        </main>
      </div>
    );
  }

  const methodologySummary = firstDefined(
    preview?.plain_language_summary,
    selectedModel?.current_version?.plain_language_summary,
    "Build a governed funding methodology and preview the resulting state and national totals."
  );
  const generatedSql = firstDefined(preview?.generated_sql, selectedModel?.current_version?.generated_sql, "");

  return (
    <div className="funding-model-page">
      <Header />
      <main className="funding-model-builder-main">
        <header className="funding-model-builder-hero">
          <div>
            <div className="funding-model-kicker">Governed methodology tooling</div>
            <h1>Funding Model Builder</h1>
            <p>
              Draft, version, preview, lock, build, and publish funding methodology profiles as structured JSON.
            </p>
          </div>
          <div className="funding-model-hero-actions">
            <label>
              Load saved model
              <select
                value={selectedModelId}
                onChange={(event) => {
                  setSelectedModelId(event.target.value);
                }}
              >
                <option value="">New model draft</option>
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="chip-secondary-btn"
              disabled={!selectedModelId || activeAction === "load"}
              onClick={() => loadModel(selectedModelId)}
            >
              {activeAction === "load" ? "Loading..." : "Load"}
            </button>
            <button
              type="button"
              className="chip-secondary-btn"
              onClick={() => {
                setSelectedModel(null);
                setSelectedModelId("");
                setPreview(null);
                dispatch({ type: "reset" });
                setMessage("New draft ready.");
                setError("");
              }}
            >
              New Draft
            </button>
          </div>
        </header>

        {message ? <div className="funding-model-alert">{message}</div> : null}
        {error ? <div className="funding-model-alert funding-model-alert-error">{error}</div> : null}

        <div className="funding-model-builder-layout">
          <aside className="funding-model-sidebar">
            <section className="funding-model-section">
              <div className="funding-model-section-header">
                <h2>Model Metadata</h2>
                <StatusBadge status={currentStatus} />
              </div>
              <div className="funding-model-form-grid">
                <label>
                  Display Name
                  <input
                    data-testid="metadata-display-name"
                    value={draft.display_name}
                    disabled={!isDraftEditable}
                    onChange={(event) => dispatch({ type: "metadata", field: "display_name", value: event.target.value })}
                  />
                  <small>Human-facing umbrella name shown to analysts and in the Funding Mode dropdown.</small>
                </label>
                <label>
                  Internal Model ID
                  <input
                    value={draft.internal_model_id}
                    disabled={!isDraftEditable}
                    onChange={(event) => dispatch({ type: "metadata", field: "internal_model_id", value: event.target.value })}
                  />
                  <small>Machine-safe internal identifier used for governance and scripted builds.</small>
                </label>
                <label>
                  Methodology Version
                  <input
                    value={draft.chip_methodology_version}
                    disabled={!isDraftEditable}
                    onChange={(event) => dispatch({ type: "metadata", field: "chip_methodology_version", value: event.target.value })}
                  />
                  <small>Human-readable methodology version such as `v1.1`.</small>
                </label>
                <label>
                  Funding Mode Key
                  <input
                    value={draft.funding_mode_key}
                    disabled={!isDraftEditable}
                    onChange={(event) => dispatch({ type: "metadata", field: "funding_mode_key", value: event.target.value })}
                  />
                  <small>Registry key that later resolves to the built funding mode.</small>
                </label>
                <label>
                  Slug
                  <input
                    value={draft.slug}
                    disabled={!isDraftEditable}
                    onChange={(event) => dispatch({ type: "metadata", field: "slug", value: event.target.value })}
                  />
                  <small>Editable URL-safe slug derived from the display name.</small>
                </label>
                <label>
                  Description
                  <textarea
                    rows={4}
                    value={draft.description}
                    disabled={!isDraftEditable}
                    onChange={(event) => dispatch({ type: "metadata", field: "description", value: event.target.value })}
                  />
                </label>
                <label>
                  State Profile Source Version
                  <input
                    value={draft.chip_state_profile_source_version}
                    disabled={!isDraftEditable}
                    onChange={(event) => dispatch({ type: "metadata", field: "chip_state_profile_source_version", value: event.target.value })}
                  />
                  <small>Built backend asset used for the state profile layer.</small>
                </label>
                <label>
                  Normalization Source Version
                  <input
                    value={draft.chip_normalization_source_version}
                    disabled={!isDraftEditable}
                    onChange={(event) => dispatch({ type: "metadata", field: "chip_normalization_source_version", value: event.target.value })}
                  />
                  <small>Built backend asset used for the published funding mode source.</small>
                </label>
                <label>
                  Version Label
                  <input
                    value={draft.version_label}
                    disabled={!isDraftEditable}
                    onChange={(event) => dispatch({ type: "metadata", field: "version_label", value: event.target.value })}
                  />
                </label>
              </div>
            </section>

            <section className="funding-model-section">
              <div className="funding-model-section-header">
                <h2>Data Source Selection</h2>
              </div>
              <div className="funding-model-checkbox-grid">
                {DATA_SOURCE_OPTIONS.map(({ key, label }) => (
                  <label key={key} className="funding-model-checkbox">
                    <input
                      type="checkbox"
                      checked={Boolean(draft.definition.data_sources?.[key])}
                      disabled={!isDraftEditable}
                      onChange={(event) => dispatch({ type: "data-source", field: key, value: event.target.checked })}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
              <div className="funding-model-checkbox-grid">
                {Object.entries(draft.definition.options).map(([key, value]) => (
                  <label key={key} className="funding-model-checkbox">
                    <input
                      type="checkbox"
                      checked={Boolean(value)}
                      disabled={!isDraftEditable}
                      onChange={(event) => dispatch({ type: "option", field: key, value: event.target.checked })}
                    />
                    <span>{OPTION_LABELS[key] ?? key}</span>
                  </label>
                ))}
              </div>
            </section>

            <section className="funding-model-section">
              <div className="funding-model-section-header">
                <h2>Validation Summary</h2>
              </div>
              {validationErrors.length === 0 ? (
                <div className="funding-model-empty-state">Required metadata is currently satisfied.</div>
              ) : (
                <ul className="funding-model-list">
                  {validationErrors.map((item) => <li key={item}>{item}</li>)}
                </ul>
              )}
            </section>
          </aside>

          <section className="funding-model-main">
            <RuleGroupEditor
              title="Include Rules"
              root="include"
              group={draft.definition.include_group}
              disabled={!isDraftEditable}
              dispatch={dispatch}
              availableFields={availableFieldItems}
              fieldCatalogMap={fieldCatalogMap}
            />
            <RuleGroupEditor
              title="Exclude Rules"
              root="exclude"
              group={draft.definition.exclude_group}
              disabled={!isDraftEditable}
              dispatch={dispatch}
              availableFields={availableFieldItems}
              fieldCatalogMap={fieldCatalogMap}
            />

            <section className="funding-model-section">
              <div className="funding-model-section-header">
                <h2>Advanced SQL</h2>
              </div>
              <p className="funding-model-warning">
                Advanced SQL is optional, read-only, and intended for internal users who need a guarded narrowing layer on top of the visual methodology definition.
              </p>
              <label className="funding-model-checkbox">
                <input
                  type="checkbox"
                  checked={Boolean(draft.definition.advanced_sql_enabled)}
                  disabled={!isDraftEditable}
                  onChange={(event) => dispatch({ type: "advanced-enabled", value: event.target.checked })}
                />
                <span>Enable advanced SQL narrowing</span>
              </label>
              <textarea
                rows={7}
                value={draft.definition.advanced_sql_override}
                disabled={!isDraftEditable || !draft.definition.advanced_sql_enabled}
                onChange={(event) => dispatch({ type: "advanced-sql", value: event.target.value })}
                placeholder="SELECT record_key FROM analytics.funding_model_builder_base_v1 WHERE ..."
              />
            </section>

            <section className="funding-model-section">
              <div className="funding-model-section-header">
                <h2>Preview Results</h2>
                <div className="funding-model-inline-actions">
                  <label>
                    Fiscal year
                    <input
                      type="number"
                      value={draft.definition.aggregation.default_fiscal_year}
                      disabled={!isDraftEditable && !selectedModel}
                      onChange={(event) => dispatch({ type: "aggregation", field: "default_fiscal_year", value: event.target.value })}
                    />
                  </label>
                  <label>
                    Geography
                    <select
                      value={draft.definition.aggregation.default_geography}
                      onChange={(event) => dispatch({ type: "aggregation", field: "default_geography", value: event.target.value })}
                    >
                      <option value="state">state</option>
                      <option value="county">county</option>
                      <option value="nation">nation</option>
                    </select>
                  </label>
                  <button type="button" className="chip-primary-btn" onClick={handlePreview} disabled={activeAction === "preview"}>
                    {activeAction === "preview" ? "Refreshing..." : "Refresh Preview"}
                  </button>
                </div>
              </div>
              <div className="funding-model-preview-grid">
                <article className="funding-model-preview-card">
                  <div className="funding-model-preview-label">Included rows</div>
                  <div className="funding-model-preview-value">{Number(preview?.included_record_count ?? 0).toLocaleString("en-US")}</div>
                </article>
                <article className="funding-model-preview-card">
                  <div className="funding-model-preview-label">Excluded rows</div>
                  <div className="funding-model-preview-value">{Number(preview?.excluded_record_count ?? 0).toLocaleString("en-US")}</div>
                </article>
                <article className="funding-model-preview-card">
                  <div className="funding-model-preview-label">National FY rows</div>
                  <div className="funding-model-preview-value">{Array.isArray(preview?.national_totals_by_fiscal_year) ? preview.national_totals_by_fiscal_year.length : 0}</div>
                </article>
              </div>
              {Array.isArray(preview?.warnings) && preview.warnings.length > 0 ? (
                <div className="funding-model-warning-list">
                  {preview.warnings.map((warning) => (
                    <span key={warning} className="funding-model-warning-pill">{warning}</span>
                  ))}
                </div>
              ) : null}
              <div className="funding-model-two-column">
                <div className="funding-model-table-wrap">
                  <h4>National total by fiscal year</h4>
                  <table className="funding-model-table">
                    <thead>
                      <tr>
                        <th>Fiscal year</th>
                        <th>Total</th>
                        <th>Rows</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(preview?.national_totals_by_fiscal_year ?? []).map((row) => (
                        <tr key={`national-${row.fiscal_year}`}>
                          <td>{row.fiscal_year}</td>
                          <td>{Number(row.total_amount ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 })}</td>
                          <td>{Number(row.row_count ?? 0).toLocaleString("en-US")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="funding-model-table-wrap">
                  <h4>State totals for preview year</h4>
                  <table className="funding-model-table">
                    <thead>
                      <tr>
                        <th>State</th>
                        <th>Total</th>
                        <th>Rows</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(preview?.state_totals_for_fiscal_year ?? []).map((row) => (
                        <tr key={`state-${row.state_code}`}>
                          <td>{row.state_name || row.state_code}</td>
                          <td>{Number(row.total_amount ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 })}</td>
                          <td>{Number(row.row_count ?? 0).toLocaleString("en-US")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <section className="funding-model-section">
              <div className="funding-model-section-header">
                <h2>Methodology Summary</h2>
              </div>
              <p>{methodologySummary}</p>
            </section>

            <section className="funding-model-section">
              <div className="funding-model-section-header">
                <h2>Generated SQL</h2>
              </div>
              <pre className="funding-model-generated-sql">{generatedSql || "Preview SQL will appear here after refresh."}</pre>
            </section>
          </section>

          <aside className="funding-model-actions">
            <section className="funding-model-section">
              <div className="funding-model-section-header">
                <h2>Governance Actions</h2>
              </div>
              <div className="funding-model-action-stack">
                <button type="button" className="chip-primary-btn" onClick={handleSave} disabled={!isDraftEditable || activeAction === "save"}>
                  {activeAction === "save" ? "Saving..." : "Save Draft"}
                </button>
                <button
                  type="button"
                  className="chip-secondary-btn"
                  onClick={handleLock}
                  disabled={!selectedModel || currentStatus !== "draft" || validationErrors.length > 0 || activeAction === "lock"}
                >
                  {activeAction === "lock" ? "Locking..." : "Lock Version"}
                </button>
                <button
                  type="button"
                  className="chip-secondary-btn"
                  onClick={handleBuild}
                  disabled={!selectedModel || !["locked", "built", "published"].includes(currentStatus) || activeAction === "build"}
                >
                  {activeAction === "build" ? "Building..." : "Build Backend Layer"}
                </button>
                <button
                  type="button"
                  className="chip-secondary-btn"
                  onClick={handlePublish}
                  disabled={!selectedModel || !["built", "published"].includes(currentStatus) || activeAction === "publish"}
                >
                  {activeAction === "publish" ? "Publishing..." : "Publish to Funding Mode"}
                </button>
                <button
                  type="button"
                  className="chip-secondary-btn"
                  onClick={handleClone}
                  disabled={!selectedModel || activeAction === "clone"}
                >
                  {activeAction === "clone" ? "Cloning..." : "Clone Version"}
                </button>
                <button
                  type="button"
                  className="chip-secondary-btn"
                  onClick={handleArchive}
                  disabled={!selectedModel || currentStatus === "archived" || activeAction === "archive"}
                >
                  {activeAction === "archive" ? "Archiving..." : "Archive"}
                </button>
              </div>
            </section>

            <section className="funding-model-section">
              <div className="funding-model-section-header">
                <h2>Version History</h2>
              </div>
              {Array.isArray(selectedModel?.versions) && selectedModel.versions.length > 0 ? (
                <ul className="funding-model-version-list">
                  {selectedModel.versions.map((version) => (
                    <li key={version.id}>
                      <div>
                        <strong>v{version.version_number}</strong>
                        {version.version_label ? ` - ${version.version_label}` : ""}
                      </div>
                      <div className="funding-model-version-meta">
                        <StatusBadge status={version.status} />
                        {version.build_status ? <span>build: {version.build_status}</span> : null}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="funding-model-empty-state">Saved versions will appear here after the first draft save.</div>
              )}
            </section>
          </aside>
        </div>
      </main>
    </div>
  );
}
