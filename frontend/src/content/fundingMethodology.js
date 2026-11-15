// CDC funding methodology text, moved unchanged from the former header pop-up.
export const FUNDING_METHODOLOGY_INTRO =
  "Each indicator and funding view is tied to a documented source and method. CHIP surfaces derived estimates, reconstruction logic, and confidence context so analytical interpretation remains transparent and reproducible.";

export const FUNDING_METHODOLOGY_SECTIONS = [
  {
    title: "TAGGS CAN Mapping",
    paragraphs: [
      "CHIP uses CDC Funding Profiles FY2020-FY2023 as a reference dataset to identify the most likely program, category, and sub-category behind TAGGS Common Accounting Numbers (CANs).",
      "Profile rows are matched deterministically to TAGGS award records using fiscal year, state, grantee, title, amount, and related metadata. Exact project or award identifiers are used when they are available, while raw TAGGS rows remain unchanged.",
    ],
    bullets: [
      "CDC Funding Profiles FY2020-FY2023 are ingested as the reference side of the matcher.",
      "The TAGGS state CSV exports currently loaded in CHIP begin in FY2021, so direct TAGGS-to-profile matching occurs for FY2021-FY2023 when matching evidence is available.",
      "Each CAN is stored with evidence, confidence, and mapping method so CHIP can distinguish profile-assisted mappings from fallback inference or unresolved CANs.",
    ],
  },
  {
    title: "Later-Year Estimation",
    paragraphs: [
      "For FY2024-FY2026, CHIP reuses CAN mappings learned from FY2021-FY2023 whenever a CAN was observed in the profile-assisted dictionary.",
      "If a later-year CAN is new or remains unmatched, CHIP falls back to deterministic inference using TAGGS metadata such as Program Office, ALN, Assistance Listing Title, and award text.",
    ],
    bullets: [
      "FY2024-FY2026 values are profile-informed estimates rather than official CDC Funding Profile totals.",
      "Low-confidence CANs can remain in unknown or unclassified buckets instead of being forced into a program category.",
    ],
  },
  {
    title: "Verified vs Inferred",
    paragraphs: [
      "A CAN mapping can be manually verified, CDC-profile-assisted, fallback-inferred, or unresolved. The selected method is exposed in TAGGS metadata so researchers can audit how a grouping was produced.",
      "Raw TAGGS data is immutable in this workflow. The mapping only affects derived classifications, normalized TAGGS outputs, and state funding profile rollups built on top of the raw tables.",
    ],
  },
  {
    title: "Funding Scope Framework",
    paragraphs: [
      "TAGGS, USAspending, and CDC Funding Profiles measure related but different funding views, so their raw state totals do not align automatically.",
      "CHIP classifies observed federal accounts into funding scopes such as core public health funding, emergency public health funding, federal health financing transfers, procurement support, special transfers, other public health, biomedical research, and international health assistance.",
      "The verified federal account mapping CSV now overrides fallback agency and ratio heuristics whenever an account has been manually reviewed. Unmapped accounts still fall back to the deterministic rule pipeline.",
      "This matters because not every CDC-awarded or CDC-associated transaction represents the same funding concept. Core CDC program accounts, emergency response funding, Medicaid-like transfers, biomedical research funding, and international assistance should not be interpreted as equivalent.",
      "When Normalize Data is on, CHIP reconstructs a conservative CDC Funding Profiles reporting scope from public federal data, then compares the reconstructed state totals against observed CDC Funding Profiles for FY2020-FY2023.",
      "That reconstruction uses funding-scope classification together with appropriation-related and emergency or disaster coding rather than rewriting raw source records.",
      "Some USAspending rows list multiple federal accounts in a single raw field. CHIP distinguishes single-account rows, multi-account same-scope rows, and multi-account mixed-scope rows in the derived interpretation layer.",
      "When the raw source does not provide an exact per-account split for a mixed-account row, CHIP preserves the raw dollars unchanged and handles the normalized interpretation conservatively instead of fabricating precise splits.",
      "The normalized view keeps raw source tables unchanged. It only adds derived profile-scope classifications, reconciliation diagnostics, and normalized state totals built from the reconstruction layer.",
      "Current normalization version: profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics_calibration_v1 (March 16, 2026). Current TAGGS CAN mapping version: taggs_cdc_profile_can_mapping_v2026_03_13 (March 13, 2026).",
    ],
    bullets: [
      "Funding-scope categories used by CHIP include core public health, emergency public health, federal health financing transfers, procurement support, special transfers, other public health, biomedical research, international health assistance, and unknown.",
      "The normalized CDC public health view focuses primarily on core public health funding and selectively includes other scopes only where the methodology rules support them.",
      "Medicaid-like federal health financing transfers are not treated as core CDC public health investment and do not inflate normalized CDC totals.",
      "Procurement support enters the core model only in rule-supported cases such as conservative Vaccines for Children procurement matches.",
      "Other public health, biomedical research, and international health assistance remain visible in diagnostics and component metadata but do not inflate the domestic CDC core public health map.",
      "Verified federal account mappings override fallback logic for explicitly reviewed accounts, while unmapped accounts still use the additive rule-based classifier.",
      "Multi-account USAspending rows are normalized into deterministic ordered account combinations and then classified from the linked scope set instead of treating the whole raw string as one unknown account.",
      "Mixed-account rows stay conservative when the public source does not provide an exact account-level split, and rows containing unknown scopes can be flagged for manual review.",
      "Calibration does not force equality. CHIP measures residuals between reconstructed public-data totals and observed CDC Funding Profiles, then preserves those gaps for review.",
      "FY2020-FY2023 use observed CDC Funding Profiles totals as calibration references. FY2024-FY2026 reuse the same profile-scope rules and are estimates rather than official CDC Funding Profile totals.",
      "Residual differences can remain because CDC Funding Profiles are curated accounting products and may reflect internal timing, emergency treatment, transfer handling, procurement treatment, or other classification choices not fully visible in public data.",
      "Recipient geography follows grantee or recipient address conventions in the source systems, and some later-year or special funding streams can remain imperfectly classified.",
    ],
  },
  {
    title: "Caveats",
    paragraphs: [
      "Recipient geography follows the grantee or recipient address used in the source systems, which may differ from where services are ultimately delivered.",
      "Normalized values are derived reconstructed totals designed to align with CDC Funding Profiles scope. They should not be interpreted as copied CDC profile amounts or as changes to the raw TAGGS or USAspending records.",
    ],
    bullets: [
      "Cross-year comparisons remain imperfect because CDC profile categories and methodology can shift across years.",
      "Raw source tables remain unchanged. Calibration diagnostics are additive and reviewable.",
    ],
  },
];
