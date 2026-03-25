function uid(prefix = "id") {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

export function slugifyFundingModelName(value) {
  const token = String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return token || "funding-model";
}

export function machineFundingModelId(value) {
  let token = String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!token) return "funding_model";
  if (!/^[a-z]/.test(token)) {
    token = `m_${token}`;
  }
  return token;
}

export function defaultFundingModeKey(internalModelId) {
  return machineFundingModelId(internalModelId);
}

export function createRule() {
  return {
    id: uid("rule"),
    field: "fiscal_year",
    operator: "equals",
    value: "",
  };
}

export function createGroup(combinator = "ALL") {
  return {
    id: uid("group"),
    combinator,
    children: [],
  };
}

export function createEmptyDraft() {
  return {
    display_name: "",
    internal_model_id: "",
    chip_methodology_version: "",
    funding_mode_key: "",
    slug: "",
    description: "",
    chip_state_profile_source_version: "",
    chip_normalization_source_version: "",
    status: "draft",
    version_label: "",
    notes: "",
    definition: {
      data_sources: {
        usaspending_awards: true,
        usaspending_subawards: false,
        usaspending_assistance_transactions: true,
        usaspending_contract_transactions: true,
        taggs: true,
      },
      options: {
        include_finalized_only: true,
        include_deobligations: false,
        include_negative_adjustments: false,
        include_pass_through_records: false,
      },
      include_group: { id: "include-root", combinator: "ALL", children: [] },
      exclude_group: { id: "exclude-root", combinator: "ANY", children: [] },
      advanced_sql_enabled: false,
      advanced_sql_override: "",
      aggregation: {
        default_metric: "normalized_total",
        supported_geographies: ["nation", "state", "county"],
        default_geography: "state",
        default_fiscal_year: "",
      },
    },
  };
}

export function builderReducer(state, action) {
  switch (action.type) {
    case "replace":
      return { ...action.value };
    case "reset":
      return createEmptyDraft();
    case "metadata":
      return applyMetadataChange(state, action.field, action.value);
    case "data-source":
      return {
        ...state,
        definition: {
          ...state.definition,
          data_sources: {
            ...state.definition.data_sources,
            [action.field]: Boolean(action.value),
          },
        },
      };
    case "option":
      return {
        ...state,
        definition: {
          ...state.definition,
          options: {
            ...state.definition.options,
            [action.field]: Boolean(action.value),
          },
        },
      };
    case "aggregation":
      return {
        ...state,
        definition: {
          ...state.definition,
          aggregation: {
            ...state.definition.aggregation,
            [action.field]: action.value,
          },
        },
      };
    case "advanced-sql":
      return {
        ...state,
        definition: {
          ...state.definition,
          advanced_sql_override: action.value,
        },
      };
    case "advanced-enabled":
      return {
        ...state,
        definition: {
          ...state.definition,
          advanced_sql_enabled: Boolean(action.value),
        },
      };
    case "group-combinator":
      return updateRootGroup(state, action.root, (group) => ({ ...group, combinator: action.value }));
    case "add-rule":
      return updateRootGroup(state, action.root, (group) => ({
        ...group,
        children: [...group.children, createRule()],
      }), action.groupId);
    case "add-group":
      return updateRootGroup(state, action.root, (group) => ({
        ...group,
        children: [...group.children, createGroup(action.combinator ?? "ALL")],
      }), action.groupId);
    case "delete-node":
      return updateRootGroup(state, action.root, (group) => removeNode(group, action.nodeId));
    case "duplicate-node":
      return updateRootGroup(state, action.root, (group) => duplicateNode(group, action.nodeId));
    case "rule-change":
      return updateRootGroup(state, action.root, (group) => updateNode(group, action.nodeId, (node) => ({
        ...node,
        [action.field]: action.value,
      })));
    case "rule-field":
      return updateRootGroup(state, action.root, (group) => updateNode(group, action.nodeId, (node) => ({
        ...node,
        field: action.value,
        operator: action.operator ?? "equals",
        value: action.ruleValue ?? "",
      })));
    default:
      return state;
  }
}

function applyMetadataChange(state, field, value) {
  const next = {
    ...state,
    [field]: value,
  };
  if (field === "display_name" && !String(state.slug ?? "").trim()) {
    next.slug = slugifyFundingModelName(value);
  }
  if (field === "display_name" && !String(state.internal_model_id ?? "").trim()) {
    const internalModelId = machineFundingModelId(value);
    next.internal_model_id = internalModelId;
    next.funding_mode_key = defaultFundingModeKey(internalModelId);
  }
  if (field === "internal_model_id" && !String(state.funding_mode_key ?? "").trim()) {
    next.funding_mode_key = defaultFundingModeKey(value);
  }
  return next;
}

function updateRootGroup(state, root, transform, targetGroupId = null) {
  const key = root === "exclude" ? "exclude_group" : "include_group";
  const currentGroup = state.definition[key];
  return {
    ...state,
    definition: {
      ...state.definition,
      [key]: targetGroupId
        ? updateGroupById(currentGroup, targetGroupId, transform)
        : transform(currentGroup),
    },
  };
}

function updateGroupById(group, targetGroupId, transform) {
  if (group.id === targetGroupId) {
    return transform(group);
  }
  return {
    ...group,
    children: group.children.map((child) => (
      child.children ? updateGroupById(child, targetGroupId, transform) : child
    )),
  };
}

function updateNode(group, nodeId, transform) {
  return {
    ...group,
    children: group.children.map((child) => {
      if (child.id === nodeId) {
        return transform(child);
      }
      if (child.children) {
        return updateNode(child, nodeId, transform);
      }
      return child;
    }),
  };
}

function removeNode(group, nodeId) {
  return {
    ...group,
    children: group.children
      .filter((child) => child.id !== nodeId)
      .map((child) => (child.children ? removeNode(child, nodeId) : child)),
  };
}

function duplicateNode(group, nodeId) {
  return {
    ...group,
    children: group.children.flatMap((child) => {
      if (child.id === nodeId) {
        return [child, cloneNode(child)];
      }
      if (child.children) {
        return [duplicateNode(child, nodeId)];
      }
      return [child];
    }),
  };
}

function cloneNode(node) {
  if (node.children) {
    return {
      ...node,
      id: uid("group"),
      children: node.children.map((child) => cloneNode(child)),
    };
  }
  return {
    ...node,
    id: uid("rule"),
  };
}

export const DATA_SOURCE_OPTIONS = [
  { key: "usaspending_awards", label: "USAspending awards" },
  { key: "usaspending_subawards", label: "USAspending subawards" },
  { key: "usaspending_assistance_transactions", label: "USAspending assistance transactions" },
  { key: "usaspending_contract_transactions", label: "USAspending contract transactions" },
  { key: "taggs", label: "TAGGS" },
];

export const OPTION_LABELS = {
  include_finalized_only: "Include finalized obligations only",
  include_deobligations: "Include deobligations",
  include_negative_adjustments: "Include negative adjustments",
  include_pass_through_records: "Include subrecipient / pass-through records",
};

export function buildDraftFromModel(model) {
  const definitionJson = model?.current_version?.definition_json ?? {};
  const definition = definitionJson?.definition ?? {};
  return {
    ...createEmptyDraft(),
    display_name: definitionJson.display_name ?? model?.display_name ?? "",
    internal_model_id: definitionJson.internal_model_id ?? model?.internal_model_id ?? "",
    chip_methodology_version: definitionJson.chip_methodology_version ?? model?.chip_methodology_version ?? "",
    funding_mode_key: definitionJson.funding_mode_key ?? model?.funding_mode_key ?? "",
    slug: definitionJson.slug ?? model?.slug ?? "",
    description: definitionJson.description ?? model?.description ?? "",
    chip_state_profile_source_version: definitionJson.chip_state_profile_source_version ?? model?.current_version?.chip_state_profile_source_version ?? "",
    chip_normalization_source_version: definitionJson.chip_normalization_source_version ?? model?.current_version?.chip_normalization_source_version ?? "",
    status: model?.status ?? definitionJson.status ?? "draft",
    version_label: model?.current_version?.version_label ?? "",
    notes: model?.current_version?.notes ?? "",
    definition: {
      ...createEmptyDraft().definition,
      ...definition,
      data_sources: normalizeDataSources(definition.data_sources),
      options: {
        ...createEmptyDraft().definition.options,
        ...(definition.options ?? {}),
      },
      include_group: normalizeGroup(definition.include_group, "include-root", "ALL"),
      exclude_group: normalizeGroup(definition.exclude_group, "exclude-root", "ANY"),
      aggregation: {
        ...createEmptyDraft().definition.aggregation,
        ...(definition.aggregation ?? {}),
        default_fiscal_year: definition?.aggregation?.default_fiscal_year ?? "",
      },
      advanced_sql_override: definition.advanced_sql_override ?? "",
      advanced_sql_enabled: Boolean(definition.advanced_sql_enabled),
    },
  };
}

function normalizeDataSources(value) {
  const sourceData = value && typeof value === "object" ? { ...value } : {};
  if ("usaspending_transactions" in sourceData) {
    const legacyEnabled = Boolean(sourceData.usaspending_transactions);
    delete sourceData.usaspending_transactions;
    if (!("usaspending_assistance_transactions" in sourceData)) {
      sourceData.usaspending_assistance_transactions = legacyEnabled;
    }
    if (!("usaspending_contract_transactions" in sourceData)) {
      sourceData.usaspending_contract_transactions = legacyEnabled;
    }
  }
  return {
    ...createEmptyDraft().definition.data_sources,
    ...sourceData,
  };
}

function normalizeGroup(value, fallbackId, fallbackCombinator) {
  const group = value && typeof value === "object" ? value : {};
  return {
    id: group.id ?? fallbackId,
    combinator: group.combinator ?? fallbackCombinator,
    children: Array.isArray(group.children)
      ? group.children.map((child) => (
        child?.children
          ? normalizeGroup(child, uid("group"), "ALL")
          : {
            id: child?.id ?? uid("rule"),
            field: child?.field ?? "fiscal_year",
            operator: child?.operator ?? "equals",
            value: child?.value ?? "",
          }
      ))
      : [],
  };
}
