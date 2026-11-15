import assert from 'node:assert/strict';
import { mkdirSync, readFileSync } from 'node:fs';
import { chromium } from 'playwright';

const base = (process.env.CHIP_BETA_URL || 'http://127.0.0.1:8080').replace(/\/$/, '');
const codeFile = process.env.CHIP_BETA_CODE_FILE || '/home/john/.local/share/chip/staging-beta-access-code';
const districtGeoid = process.env.CHIP_BETA_DISTRICT_GEOID;
const screenshotDir = process.env.CHIP_BETA_SCREENSHOT_DIR;
const showcase = ['37145', '54039', '06019'];
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1365, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
if (screenshotDir) mkdirSync(screenshotDir, { recursive: true });
async function screenshot(name, fullPage = false) {
  if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/${name}.png`, fullPage });
}

async function visit(path, heading) {
  const response = await page.goto(`${base}${path}`, { waitUntil: 'domcontentloaded' });
  assert.equal(response.status(), 200, `${path} HTTP status`);
  if (heading) await page.getByRole('heading', { name: heading, exact: true }).waitFor();
  assert.deepEqual(errors, [], `${path} browser errors`);
}

try {
  const anonymous = await browser.newContext();
  const protectedResponse = await anonymous.request.get(`${base}/api/community/catalog`);
  assert.equal(protectedResponse.status(), 401, 'anonymous community API');
  await anonymous.close();

  const code = readFileSync(codeFile, 'utf8').trim();
  const auth = await context.request.post(`${base}/api/demo-access/validate`, { data: { access_code: code } });
  assert.equal(auth.status(), 200, 'staging access code validation');
  await visit('/', 'Start with a place. Follow the evidence.');
  assert.equal(await page.locator('.community-topic').count(), 7, 'landing topics');
  await screenshot('landing', true);
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement?.className), 'community-skip', 'keyboard skip link');
  await page.getByLabel('Find a county').fill('Person');
  await page.getByRole('link', { name: /Person County, NC/ }).first().click();
  await page.getByRole('heading', { name: 'Person County, North Carolina' }).waitFor();
  assert.ok(await page.locator('.community-indicator').count() >= 28, 'Person profile indicators');
  await page.locator('.community-tract-map .leaflet-interactive').first().waitFor();
  assert.equal(await page.locator('.community-tract-map .leaflet-interactive').count(), 7, 'Person ACS tracts');
  await screenshot('person-profile', true);
  const pdf = await context.request.get(`${base}/api/community/county/37145/pdf`);
  assert.equal(pdf.status(), 200, 'PDF briefing');
  assert.equal((await pdf.body()).subarray(0, 4).toString(), '%PDF', 'PDF file signature');
  console.log('Landing, search, profile, seven ACS tracts, and PDF: passed');

  await visit('/compare?counties=37145,54039,06019', 'Compare published indicators');
  await page.getByText('Fresno County', { exact: false }).first().waitFor();
  assert.ok(await page.locator('.community-compare-table tbody tr').count() >= 28, 'comparison rows');
  await screenshot('three-county-comparison');
  console.log('Three-county comparison: passed');

  await visit('/topics', 'Community health topics');
  await page.locator('.community-topic').first().waitFor();
  assert.equal(await page.locator('.community-topic').count(), 7, 'topic list');
  await visit('/topics/food-environment', 'Food environment');
  await page.locator('.community-topic-measures article').first().waitFor();
  assert.ok(await page.locator('.community-topic-measures article').count() >= 6, 'food measures');
  await screenshot('food-topic', true);
  const mapHref = await page.locator('.community-topic-measures article a').first().getAttribute('href');
  await visit(mapHref);
  const selected = await page.locator('select').filter({ has: page.locator('option[value="low_income_low_access_pct"]') }).inputValue();
  assert.equal(selected, 'low_income_low_access_pct', 'source map measure preselection');
  await page.getByRole('button', { name: 'Copy map link' }).waitFor();
  await page.waitForFunction(() => ['lat', 'lon', 'zoom'].every(key => new URLSearchParams(location.search).has(key)));
  const sharedMapUrl = page.url();
  await page.goto(sharedMapUrl);
  assert.equal(await page.locator('select').filter({ has: page.locator('option[value="low_income_low_access_pct"]') }).inputValue(), 'low_income_low_access_pct', 'shared map selection');
  console.log('Topics, preselected source map, and shareable map view: passed');

  for (const geoid of showcase) {
    await visit(`/community/county/${geoid}`);
    await page.locator('.community-indicator').first().waitFor();
    assert.ok(await page.locator('.community-indicator').count() >= 28, `${geoid} published indicator rows`);
  }
  await visit('/about', 'Public data for a clearer view of communities');
  await visit('/methodology', 'How CHIP uses published data');
  await page.locator('.community-release-list li').first().waitFor();
  console.log('Three showcase profiles, About, and methodology: passed');

  for (const path of ['/explore/map', '/area/places-2025', '/area/acs-2024', '/area/ahrf', '/area/clh', '/area/epa-aqi', '/area/cms-gv', '/area/usda-fea', '/cdc-funding']) {
    await visit(path);
    await page.locator('main, #root').first().waitFor();
  }
  console.log('Legacy map, seven area pages, and funding page: loaded without browser errors');

  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ['/', '/topics/food-environment', '/community/county/37145', '/compare?counties=37145,54039,06019', '/methodology']) {
    await visit(path);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${path} mobile overflow`);
    if (path === '/community/county/37145') await screenshot('person-profile-mobile');
  }
  console.log('Mobile layout: no document overflow on five key routes');

  if (districtGeoid) {
    await visit(`/district/cd/${districtGeoid}`);
    console.log(`District ${districtGeoid}: loaded`);
  } else {
    console.log('District briefing: pending C3 published district release');
  }
  assert.deepEqual(errors, [], 'browser errors');
} finally {
  await browser.close();
}
