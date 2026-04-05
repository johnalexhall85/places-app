export function isFundingModelBuilderEnabled() {
  return import.meta.env.VITE_FUNDING_MODEL_BUILDER_ENABLED !== "false";
}
