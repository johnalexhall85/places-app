export const APP_NAME = "CHIP by Public Data Observatory";
export const PRODUCT_NAME = "CHIP";
export const PRIMARY_BRAND = "Public Data Observatory";
export const APP_DESCRIPTION =
  "CHIP by Public Data Observatory is a nonpartisan geospatial data platform for modeled and administrative public health analysis, planning, and transparent reporting.";

export const BRAND_FOOTER = {
  description:
    "Public Data Observatory is a nonpartisan organization that publishes source-aware data products for public analysis and planning.",
  transparency:
    "CHIP combines modeled indicators and public administrative records. Measures should be interpreted with the cited source, geography, and methodology context.",
  sources:
    "Source acknowledgments vary by view and may include CDC PLACES, ACS, SVI, HRSA HPSA, CMS, USDA, FEMA, USAspending, and TAGGS.",
};

export const PDO_TOKENS = {
  primary: "#3576BA",
  secondary: "#9ABBDD",
  accent: "#FFD5B0",
  background: "#F2F6FB",
  text: "#123247",
  legacyNavy: "#0F2D46",
  legacySlate: "#2C5F8A",
  legacyTeal: "#178B8B",
};

export function applyDocumentBranding() {
  if (typeof document === "undefined") return;
  document.title = APP_NAME;

  let metaDescription = document.querySelector('meta[name="description"]');
  if (!metaDescription) {
    metaDescription = document.createElement("meta");
    metaDescription.setAttribute("name", "description");
    document.head.appendChild(metaDescription);
  }
  metaDescription.setAttribute("content", APP_DESCRIPTION);
}
