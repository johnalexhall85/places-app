import { spawn } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendDir = path.resolve(__dirname, "..");
const outputDir = path.resolve(frontendDir, "figma-export");
const requestedPort = Number(process.env.FIGMA_EXPORT_PORT ?? 4173);
const serverBootTimeoutMs = 40_000;

const transparentPngBase64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Y8KsAAAAASUVORK5CYII=";
const transparentPngBuffer = Buffer.from(transparentPngBase64, "base64");

function rectanglePolygon(west, south, east, north) {
  return [
    [
      [west, south],
      [east, south],
      [east, north],
      [west, north],
      [west, south],
    ],
  ];
}

function createCountyFeatures() {
  return [
    {
      type: "Feature",
      properties: {
        locationid: "01001",
        county_name: "Autauga County",
        state_abbr: "AL",
        value: 11.8,
        data_value: 11.8,
        low_confidence_limit: 10.4,
        high_confidence_limit: 13.2,
        age_adjusted_data_value: 11.1,
        age_adjusted_low_confidence_limit: 9.9,
        age_adjusted_high_confidence_limit: 12.6,
        measure: "Current asthma among adults aged >=18 years",
        measure_id: "CASTHMA",
        year: 2023,
        data_value_type_id: "CrdPrv",
        population: 43510,
        location_name: "Autauga County, AL",
        lat: 32.63,
        lng: -86.68,
      },
      geometry: {
        type: "Polygon",
        coordinates: rectanglePolygon(-87.9, 31.5, -85.8, 33.1),
      },
    },
    {
      type: "Feature",
      properties: {
        locationid: "13121",
        county_name: "Fulton County",
        state_abbr: "GA",
        value: 9.4,
        data_value: 9.4,
        low_confidence_limit: 8.2,
        high_confidence_limit: 10.7,
        age_adjusted_data_value: 8.9,
        age_adjusted_low_confidence_limit: 7.8,
        age_adjusted_high_confidence_limit: 10.2,
        measure: "Current asthma among adults aged >=18 years",
        measure_id: "CASTHMA",
        year: 2023,
        data_value_type_id: "CrdPrv",
        population: 829492,
        location_name: "Fulton County, GA",
        lat: 33.81,
        lng: -84.39,
      },
      geometry: {
        type: "Polygon",
        coordinates: rectanglePolygon(-85.1, 33.2, -83.8, 34.4),
      },
    },
  ];
}

function createTractFeatures() {
  return [
    {
      type: "Feature",
      properties: {
        locationid: "13121010100",
        geoid: "13121010100",
        location_name: "Census Tract 010100, Fulton County",
        state_abbr: "GA",
        value: 12.3,
        data_value: 12.3,
        moe: 1.1,
        data_value_type_id: "Percent",
        year_window: "2019-2023",
        measure_id: "NO_VEHICLE",
        measure: "Households with no vehicle available",
        population: 4123,
      },
      geometry: {
        type: "Polygon",
        coordinates: rectanglePolygon(-84.55, 33.7, -84.45, 33.8),
      },
    },
  ];
}

function createStateBoundaryFeatures() {
  return [
    {
      type: "Feature",
      properties: { name: "Alabama" },
      geometry: {
        type: "Polygon",
        coordinates: rectanglePolygon(-88.5, 30.1, -84.6, 35.1),
      },
    },
    {
      type: "Feature",
      properties: { name: "Georgia" },
      geometry: {
        type: "Polygon",
        coordinates: rectanglePolygon(-85.7, 30.3, -80.8, 35.1),
      },
    },
  ];
}

function asFeatureCollection(features) {
  return { type: "FeatureCollection", features };
}

function jsonFulfill(route, payload, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

async function waitForHttpReady(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const ok = await new Promise((resolve) => {
      const req = http.get(url, (res) => {
        res.resume();
        resolve(res.statusCode >= 200 && res.statusCode < 500);
      });
      req.on("error", () => resolve(false));
      req.setTimeout(1200, () => {
        req.destroy();
        resolve(false);
      });
    });
    if (ok) return;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`Timed out waiting for dev server at ${url}`);
}

function appUrlForPort(portValue) {
  return `http://127.0.0.1:${portValue}/`;
}

async function isPortFree(portValue) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.on("error", () => resolve(false));
    server.listen({ host: "127.0.0.1", port: portValue }, () => {
      server.close(() => resolve(true));
    });
  });
}

async function findAvailablePort(startPort, attempts = 20) {
  for (let offset = 0; offset < attempts; offset += 1) {
    const candidate = startPort + offset;
    // eslint-disable-next-line no-await-in-loop
    const free = await isPortFree(candidate);
    if (free) return candidate;
  }
  throw new Error(`Unable to find a free port starting from ${startPort}`);
}

function startViteServer(portValue) {
  const child = spawn(
    "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(portValue), "--strictPort"],
    {
      cwd: frontendDir,
      stdio: ["ignore", "pipe", "pipe"],
      detached: true,
    }
  );

  child.stdout.on("data", (chunk) => {
    process.stdout.write(`[vite] ${chunk}`);
  });
  child.stderr.on("data", (chunk) => {
    process.stderr.write(`[vite] ${chunk}`);
  });

  return child;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function terminateProcessGroup(child) {
  if (!child || !child.pid) return;
  if (child.exitCode !== null || child.signalCode !== null) return;

  const tryKill = (signal) => {
    try {
      process.kill(-child.pid, signal);
      return true;
    } catch (_err) {
      return false;
    }
  };

  if (!tryKill("SIGTERM")) {
    child.kill("SIGTERM");
  }

  await Promise.race([once(child, "exit"), sleep(2_000)]);
  if (child.exitCode === null && child.signalCode === null) {
    if (!tryKill("SIGKILL")) {
      child.kill("SIGKILL");
    }
    await Promise.race([once(child, "exit"), sleep(1_000)]);
  }
}

function buildHistorySeries() {
  return [2018, 2019, 2020, 2021, 2022, 2023].map((year, index) => ({
    year,
    value: Number((10.4 + index * 0.5).toFixed(1)),
  }));
}

function mockCountySearchResults(query) {
  const q = String(query ?? "").toLowerCase();
  const results = [
    {
      county_fips: "13121",
      name: "Fulton County",
      state_abbr: "GA",
      centroid: { lat: 33.81, lon: -84.39 },
      bbox: {
        min_lat: 33.2,
        max_lat: 34.4,
        min_lon: -85.1,
        max_lon: -83.8,
      },
    },
    {
      county_fips: "01001",
      name: "Autauga County",
      state_abbr: "AL",
      centroid: { lat: 32.63, lon: -86.68 },
      bbox: {
        min_lat: 31.5,
        max_lat: 33.1,
        min_lon: -87.9,
        max_lon: -85.8,
      },
    },
  ];
  if (!q) return results;
  return results.filter((item) => `${item.name}, ${item.state_abbr}`.toLowerCase().includes(q));
}

async function installPageRoutes(page) {
  await page.route("**://localhost:8000/**", async (route) => {
    const requestUrl = new URL(route.request().url());
    const pathname = requestUrl.pathname;

    if (pathname === "/measures") {
      return jsonFulfill(route, [
        {
          measure_id: "CASTHMA",
          measure: "Current asthma among adults aged >=18 years",
          short_question_text: "Current asthma among adults",
          source: "places",
        },
        {
          measure_id: "BPHIGH",
          measure: "High blood pressure among adults aged >=18 years",
          short_question_text: "High blood pressure among adults",
          source: "places",
        },
      ]);
    }
    if (pathname === "/meta/years") {
      return jsonFulfill(route, { years: [2023, 2022, 2021, 2020] });
    }
    if (pathname === "/counties/boundaries/geojson/estimates") {
      return jsonFulfill(route, asFeatureCollection(createCountyFeatures()));
    }
    if (pathname === "/counties/boundaries/geojson") {
      return jsonFulfill(route, asFeatureCollection(createCountyFeatures()));
    }
    if (pathname === "/states/boundaries/geojson") {
      return jsonFulfill(route, asFeatureCollection(createStateBoundaryFeatures()));
    }
    if (pathname === "/geojson/tracts") {
      return jsonFulfill(route, asFeatureCollection(createTractFeatures()));
    }
    if (pathname === "/history") {
      return jsonFulfill(route, {
        measure_id: "CASTHMA",
        measure: "Current asthma among adults aged >=18 years",
        data_value_type_id: "CrdPrv",
        data_value_type: "CrdPrv",
        series: buildHistorySeries(),
      });
    }
    if (pathname === "/search/counties") {
      const query = requestUrl.searchParams.get("q") ?? "";
      return jsonFulfill(route, mockCountySearchResults(query));
    }
    if (pathname === "/assistant/query") {
      return jsonFulfill(route, {
        answer_markdown: "Fulton County has a lower modeled asthma prevalence than Autauga County.",
        actions: [
          { type: "MAP_FLY_TO", lat: 33.81, lng: -84.39, zoom: 9 },
          { type: "MAP_HIGHLIGHT", level: "county", geoid: "13121" },
        ],
      });
    }
    if (pathname === "/profiles/generate") {
      return jsonFulfill(route, {
        profile_id: "figma-demo-profile",
        summary_text: "Profile generated for design capture.",
      });
    }
    if (pathname === "/profiles/figma-demo-profile") {
      return jsonFulfill(route, {
        location: {
          name: "Fulton County",
          state_abbr: "GA",
        },
        places_measure: {
          short_question_text: "Current asthma among adults",
        },
        reference_stats: {
          state_rank: 13,
        },
        comparisons: {
          places: {
            national_percentile: 44,
          },
          acs_primary: null,
        },
        narrative: {
          summary_paragraph: "Fulton County has better-than-average values for this mock profile.",
          plain_language_sections: [
            {
              title: "Context",
              paragraph: "This is a deterministic payload for Figma capture.",
              bullets: ["Stable for local export", "No backend dependency"],
            },
          ],
        },
        charts: {},
      });
    }
    if (pathname.startsWith("/profiles/") && pathname.endsWith(".pdf")) {
      return route.fulfill({
        status: 200,
        contentType: "application/pdf",
        body: Buffer.from("%PDF-1.4\n%%EOF\n", "utf8"),
      });
    }
    if (pathname === "/acs-nmf/measures") {
      return jsonFulfill(route, [
        {
          measure_id: "NO_VEHICLE",
          measure: "Households with no vehicle available",
          data_value_type_ids: ["Percent"],
          year_windows: ["2019-2023", "2018-2022"],
          source: "acs",
        },
      ]);
    }
    if (pathname === "/acs-nmf/counties") {
      const features = createCountyFeatures().map((feature) => ({
        ...feature,
        properties: {
          ...feature.properties,
          value: Number((feature.properties.value / 2).toFixed(1)),
          data_value_type_id: "Percent",
          year_window: "2019-2023",
        },
      }));
      return jsonFulfill(route, asFeatureCollection(features));
    }
    if (pathname === "/acs-nmf/legend") {
      return jsonFulfill(route, {
        n: 2,
        noDataCount: 0,
        bins: [
          { min: 0, max: 4.9, colorIndex: 0, label: "0.0 - 4.9" },
          { min: 5.0, max: 7.9, colorIndex: 1, label: "5.0 - 7.9" },
          { min: 8.0, max: 9.9, colorIndex: 2, label: "8.0 - 9.9" },
          { min: 10.0, max: 12.9, colorIndex: 3, label: "10.0 - 12.9" },
          { min: 13.0, max: 20.0, colorIndex: 4, label: "13.0 - 20.0" },
        ],
      });
    }
    if (pathname === "/acs-nmf/tracts/measures") {
      return jsonFulfill(route, [
        {
          measure_id: "NO_VEHICLE",
          measure: "Households with no vehicle available",
          data_value_type_ids: ["Percent"],
          year_windows: ["2019-2023", "2018-2022"],
          source: "acs",
        },
      ]);
    }
    if (pathname === "/acs-nmf/tracts") {
      return jsonFulfill(route, asFeatureCollection(createTractFeatures()));
    }
    if (pathname === "/acs-nmf/tracts/legend") {
      return jsonFulfill(route, {
        n: 1,
        noDataCount: 0,
        bins: [{ min: 10, max: 15, colorIndex: 3, label: "10.0 - 15.0" }],
      });
    }

    return jsonFulfill(route, { detail: `No mock for ${pathname}` }, 404);
  });

  await page.route("**://nominatim.openstreetmap.org/**", async (route) => {
    return jsonFulfill(route, [
      {
        place_id: 1001,
        display_name: "Atlanta, Georgia, United States",
        lat: "33.7490",
        lon: "-84.3880",
        boundingbox: ["33.64", "33.89", "-84.55", "-84.28"],
      },
    ]);
  });

  await page.route("**://*.tile.openstreetmap.org/**", async (route) => {
    return route.fulfill({
      status: 200,
      contentType: "image/png",
      body: transparentPngBuffer,
    });
  });
}

async function captureSet(browser, appUrl, name, viewport) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();
  await installPageRoutes(page);
  await page.goto(appUrl, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);

  const shots = [];
  const capture = async (fileName) => {
    const fullPath = path.resolve(outputDir, fileName);
    await page.screenshot({ path: fullPath, fullPage: true });
    shots.push(fileName);
  };

  await capture(`01-overview-${name}.png`);

  const searchInput = page.getByRole("textbox", {
    name: /search address, zip, or county/i,
  });
  await searchInput.fill("Fulton");
  await page.waitForTimeout(700);
  await capture(`02-search-${name}.png`);

  const suggestion = page.getByRole("button", { name: /Fulton County, GA/i }).first();
  if (await suggestion.count()) {
    await suggestion.click();
    await page.waitForTimeout(600);
  }

  const polygon = page.locator(".leaflet-interactive").first();
  if (await polygon.count()) {
    const polygonBox = await polygon.boundingBox();
    if (polygonBox && polygonBox.width > 1 && polygonBox.height > 1) {
      await polygon.click({ force: true }).catch(() => {
        // Mobile viewport may not expose a clickable feature path; keep capture deterministic.
      });
      await page.waitForTimeout(500);
    }
  }
  await capture(`03-selected-${name}.png`);

  await context.close();
  return shots;
}

async function main() {
  await fs.mkdir(outputDir, { recursive: true });
  const port = await findAvailablePort(requestedPort);
  const appUrl = appUrlForPort(port);
  const viteServer = startViteServer(port);

  let browser = null;
  try {
    await waitForHttpReady(appUrl, serverBootTimeoutMs);
    browser = await chromium.launch({ headless: true });

    const desktopShots = await captureSet(browser, appUrl, "desktop", {
      width: 1440,
      height: 960,
    });
    const mobileShots = await captureSet(browser, appUrl, "mobile", {
      width: 390,
      height: 844,
    });

    const manifest = {
      generated_at: new Date().toISOString(),
      app_url: appUrl,
      output_dir: outputDir,
      requested_port: requestedPort,
      actual_port: port,
      screenshots: {
        desktop: desktopShots,
        mobile: mobileShots,
      },
      note:
        "Use these images directly in Figma, or import the running app URL via html.to.design for editable layers.",
    };
    await fs.writeFile(
      path.resolve(outputDir, "manifest.json"),
      JSON.stringify(manifest, null, 2),
      "utf8"
    );

    console.log(`Figma export assets generated in ${outputDir}`);
  } finally {
    if (browser) {
      await browser.close();
    }
    await terminateProcessGroup(viteServer);
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
