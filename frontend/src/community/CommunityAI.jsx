import { useEffect, useState } from "react";
import { API_BASE } from "../config/apiBase";
import { CommunityShell } from "./CommunityPages";
import "./CommunityAI.css";

const CONNECTOR_URL = "https://mcp.publicdataobservatory.org";
const PUBLIC_PRODUCTS = new Set(["places", "acs", "acs_profile", "brfss", "clh", "cms_gv", "epa_aqi", "usda_fea"]);
const LEVEL_NAMES = { state: "states", county: "counties", tract: "census tracts", cd: "119th Congress districts" };

const FALLBACK_PRODUCTS = [
  { product: "places", name: "CDC PLACES", levels: ["county", "tract"] },
  { product: "acs", name: "ACS median household income", levels: ["state", "county", "tract"] },
  { product: "acs_profile", name: "ACS community characteristics", levels: ["state", "county", "tract", "cd"] },
  { product: "brfss", name: "CDC BRFSS", levels: ["state"] },
  { product: "clh", name: "AHRQ Community-Level Health", levels: ["county", "tract"] },
  { product: "cms_gv", name: "CMS Original Medicare geographic variation", levels: ["state", "county"] },
  { product: "epa_aqi", name: "EPA annual Air Quality Index", levels: ["county"] },
  { product: "usda_fea", name: "USDA Food Environment Atlas", levels: ["county"] },
];

const EXAMPLES = [
  "What is the published PLACES diabetes estimate and confidence interval for Person County, North Carolina?",
  "Compare median household income in Person, Kanawha, and Fresno counties. Show each source period and margin of error.",
  "Which published community measures are available for West Virginia's 1st congressional district?",
  "Show the PLACES diabetes estimate for every Alabama county, including counties without a value.",
  "Which Alabama counties have a reported annual median AQI, and which have no reported value?",
];

const RULES = [
  "Values describe exactly the named area. Do not add or average them across areas, or make a composite score.",
  "Missing, suppressed, and not-published values are not zero. Read the status text.",
  "Check each measure's period, population, and source before comparing it with another.",
  "Medicare measures describe Original Medicare beneficiaries, not all residents.",
  "TRI locations are facilities that report to EPA. A location alone does not establish a release, violation, or health risk.",
  "Each measure has one published period in CHIP; the connector does not provide a time series.",
];

export default function CommunityAI() {
  const [catalogProducts, setCatalogProducts] = useState(null);
  const [copyMessage, setCopyMessage] = useState("");

  useEffect(() => {
    document.title = "Use CHIP in your AI assistant | CHIP";
    const controller = new AbortController();
    fetch(`${API_BASE}/community/catalog`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Catalog unavailable");
        return response.json();
      })
      .then((catalog) => {
        if (!Array.isArray(catalog?.products)) throw new Error("Catalog unavailable");
        setCatalogProducts(catalog.products.filter((product) => PUBLIC_PRODUCTS.has(product.product) && product.published));
      })
      .catch(() => {}); // The eight public products below remain available as static guidance.
    return () => controller.abort();
  }, []);

  const products = catalogProducts ?? FALLBACK_PRODUCTS;

  async function copyUrl() {
    try {
      await navigator.clipboard.writeText(CONNECTOR_URL);
      setCopyMessage("Connector URL copied.");
    } catch {
      setCopyMessage("Copy failed. Select the URL above to copy it.");
    }
  }

  return <CommunityShell>
    <div className="community-wrap community-info community-ai">
      <p className="community-eyebrow">Use CHIP with AI</p>
      <h1>Use CHIP in your AI assistant</h1>
      <p className="community-info-lede">AI assistants such as Claude and ChatGPT can look up CHIP’s published public-health data directly and cite the source for each value.</p>

      <section aria-labelledby="ai-connector-heading">
        <h2 id="ai-connector-heading">Connector URL</h2>
        <div className="community-ai-url">
          <code>{CONNECTOR_URL}</code>
          <button type="button" onClick={copyUrl} aria-label="Copy connector URL">Copy</button>
        </div>
        <p className="community-ai-feedback" role="status">{copyMessage}</p>
      </section>

      <section aria-labelledby="ai-setup-heading">
        <h2 id="ai-setup-heading">Set it up</h2>
        <div className="community-ai-setup">
          <div><h3>Claude</h3><p>Settings → Connectors → Add custom connector. Paste the URL and leave OAuth blank. Custom connectors are available on all plans; the free plan allows one.</p></div>
          <div><h3>ChatGPT</h3><p>Settings → Apps &amp; Connectors → Advanced → turn on Developer mode. Create a connector with the URL and choose “No authentication.” This requires a paid plan; the connector is read-only.</p></div>
          <div><h3>Other MCP clients</h3><p>Use the URL with Streamable HTTP transport and no authentication.</p></div>
        </div>
      </section>

      <section aria-labelledby="ai-examples-heading">
        <h2 id="ai-examples-heading">Questions to try</h2>
        <ul>{EXAMPLES.map((question) => <li key={question}>{question}</li>)}</ul>
      </section>

      <section aria-labelledby="ai-coverage-heading">
        <h2 id="ai-coverage-heading">What it covers</h2>
        <p>CHIP serves published data at the source’s available geographic levels. Each measure has one published period.</p>
        <ul className="community-ai-products">{products.map((product) => <li key={product.product}>
          <strong>{product.name}</strong> · {(product.levels || []).map((level) => LEVEL_NAMES[level] || level).join(", ")}
        </li>)}</ul>
        <p><strong>AHRF is not available through the AI connector.</strong> Its health workforce and hospital measures remain on the CHIP website.</p>
      </section>

      <section aria-labelledby="ai-reading-heading">
        <h2 id="ai-reading-heading">How to read answers</h2>
        <ul>{RULES.map((rule) => <li key={rule}>{rule}</li>)}</ul>
      </section>

      <section aria-labelledby="ai-limits-heading">
        <h2 id="ai-limits-heading">Limits</h2>
        <p>The connector is read-only and rate-limited. It uses the same published releases as this site. Check each answer’s citation, status, period, population, and uncertainty before using a number.</p>
      </section>
    </div>
  </CommunityShell>;
}
