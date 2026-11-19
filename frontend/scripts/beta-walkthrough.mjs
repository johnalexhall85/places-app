import assert from 'node:assert/strict';
import { mkdirSync, readFileSync } from 'node:fs';
import { chromium } from 'playwright';

const base = (process.env.CHIP_BETA_URL || 'http://127.0.0.1:8080').replace(/\/$/, '');
const codeFile = process.env.CHIP_BETA_CODE_FILE || '/home/john/.local/share/chip/staging-beta-access-code';
const districtGeoid = process.env.CHIP_BETA_DISTRICT_GEOID || '5401';
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

async function contrast(selector, backgroundSelector, minimum) {
  const ratio = await page.evaluate(([foreground, background]) => {
    const channels = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
    const luminance = value => channels(value).map(n => {
      const c = n / 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    }).reduce((sum, c, index) => sum + c * [0.2126, 0.7152, 0.0722][index], 0);
    const a = luminance(getComputedStyle(document.querySelector(foreground)).color);
    const b = luminance(getComputedStyle(document.querySelector(background)).backgroundColor);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  }, [selector, backgroundSelector]);
  assert.ok(ratio >= minimum, `${selector} contrast ${ratio.toFixed(2)} below ${minimum}`);
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
  await page.getByLabel('Find a county or state').fill('Person');
  await page.getByRole('link', { name: /Person County, NC/ }).first().click();
  await page.getByRole('heading', { name: 'Person County, North Carolina' }).waitFor();
  assert.equal(await page.locator('.community-indicator').count(), 46, 'Person profile indicators from eight products');
  await page.locator('.community-tract-map .leaflet-interactive').first().waitFor();
  assert.equal(await page.locator('.community-tract-map .leaflet-interactive').count(), 7, 'Person ACS tracts');
  await page.getByLabel('Tract measure').selectOption('places:diabetes_crudeprev');
  await page.waitForFunction(() => document.querySelectorAll('.community-tract-map .leaflet-interactive').length === 7);
  assert.equal(await page.locator('.community-tract-map .leaflet-interactive').count(), 7, 'Person PLACES diabetes tracts');
  const insurance = page.locator('.community-indicator').filter({ hasText: 'insurance' });
  assert.equal(await insurance.count(), 2, 'separate ACS and PLACES insurance measures');
  assert.ok((await page.locator('#people').innerText()).includes('all ages'), 'ACS insurance population');
  assert.ok((await page.locator('#prevention').innerText()).includes('adults aged 18-64'), 'PLACES insurance population');
  await contrast('.community-source', '.community-indicator', 4.5);
  await contrast('.community-value', '.community-indicator', 3);
  await contrast('.community-header nav a', '.community-header', 4.5);
  await screenshot('person-profile', true);
  const pdf = await context.request.get(`${base}/api/community/county/37145/pdf`);
  assert.equal(pdf.status(), 200, 'PDF briefing');
  assert.equal((await pdf.body()).subarray(0, 4).toString(), '%PDF', 'PDF file signature');
  console.log('Landing, search, profile, seven ACS tracts, and PDF: passed');

  await visit('/', 'Start with a place. Follow the evidence.');
  await page.getByLabel('Find a county or state').fill('North Carolina');
  await page.getByRole('link', { name: /North Carolina · State profile/ }).first().click();
  await page.locator('[data-testid="profile-ready"]').waitFor();
  assert.equal(await page.locator('.community-indicator').count(), 33, 'North Carolina state profile indicators');
  assert.equal(await page.locator('#health .community-indicator, #prevention .community-indicator').count(), 20, 'BRFSS state indicators');
  assert.ok(await page.getByRole('link', { name: /State funding profile/ }).count(), 'state funding link');
  await screenshot('north-carolina-state-profile', true);
  const statePdf = await context.request.get(`${base}/api/community/state/37/pdf`);
  assert.equal(statePdf.status(), 200, 'state PDF briefing');
  assert.equal((await statePdf.body()).subarray(0, 4).toString(), '%PDF', 'state PDF signature');
  await visit('/community/state/21', 'Kentucky');
  assert.equal(await page.locator('.community-indicator').count(), 33, 'Kentucky state indicators');
  assert.ok(await page.getByText(/Not published/i).count(), 'Kentucky 2023 BRFSS statuses');
  await screenshot('kentucky-state-profile', true);
  await visit('/area/brfss?measure_id=diabetes', 'BRFSS state survey estimates');
  await page.locator('.pilot-table tbody tr').first().waitFor();
  assert.equal(await page.locator('.pilot-table tbody tr').count(), 52, 'BRFSS state table');
  assert.equal(await page.locator('.leaflet-interactive').count(), 52, 'BRFSS state shapes');
  assert.equal(await page.locator('.pilot-controls select').nth(1).inputValue(), 'diabetes', 'BRFSS measure preselection');
  assert.ok((await page.locator('.pilot-table').innerText()).includes('Median of states and DC'), 'median reference label');
  await screenshot('brfss-state-map');
  console.log('State search, profiles, PDF, and BRFSS map: passed');

  await visit('/compare?counties=37145,54039,06019', 'Compare published indicators');
  await page.getByText('Fresno County', { exact: false }).first().waitFor();
  assert.equal(await page.locator('.community-compare-table tbody tr').count(), 46, 'comparison rows');
  await screenshot('three-county-comparison');
  console.log('Three-county comparison: passed');

  await visit('/topics', 'Community health topics');
  await page.locator('.community-topic').first().waitFor();
  assert.equal(await page.locator('.community-topic').count(), 7, 'topic list');
  await visit('/topics/health-conditions', 'Health conditions');
  assert.equal(await page.locator('.community-topic-measures article').count(), 22, 'published PLACES and BRFSS condition measures');
  await visit('/topics/prevention-and-access', 'Prevention and access');
  assert.equal(await page.locator('.community-topic-measures article').count(), 12, 'published prevention and three separate insurance measures');
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
    assert.equal(await page.locator('.community-indicator').count(), 46, `${geoid} published indicator rows`);
  }
  await visit('/districts', 'Find a congressional district');
  await page.locator('.community-district-list li').first().waitFor();
  assert.equal(await page.locator('.community-district-list li').count(), 2, 'West Virginia district search');
  await page.getByRole('link', { name: /Congressional District 1/ }).first().click();
  await page.locator('[data-testid="district-ready"]').waitFor();
  assert.equal(await page.locator('.community-indicator').count(), 7, 'Census-published district estimates');
  assert.equal(await page.locator('.community-district-list li').count(), 28, 'named county context links');
  assert.ok(await page.getByText(/not population shares/).count(), 'county overlap caveat');
  await screenshot('wv01-district', true);
  await visit('/area/acs-community?measure_id=poverty_pct&geography=cd&lat=38.2&lon=-81.2&zoom=7', 'ACS 2020–2024 community characteristics');
  assert.equal(await page.getByLabel('Geography').inputValue(), 'cd', 'district geography selection');
  await page.locator('.leaflet-interactive').first().waitFor();
  await screenshot('acs-district-map');
  await visit('/about', 'Public data for a clearer view of communities');
  await visit('/methodology', 'How CHIP uses published data');
  await page.locator('.community-release-list li').first().waitFor();
  console.log('Three showcase profiles, About, and methodology: passed');

  for (const path of ['/explore/map', '/area/places-2025', '/area/brfss', '/area/acs-2024', '/area/acs-community', '/area/ahrf', '/area/clh', '/area/epa-aqi', '/area/cms-gv', '/area/usda-fea', '/cdc-funding']) {
    await visit(path);
    await page.locator('main, #root').first().waitFor();
  }
  console.log('Explore map, nine area pages, and funding page: loaded without browser errors');

  // One header everywhere; the legacy map is retired and /explore/map opens the published-release map.
  await visit('/', 'Start with a place. Follow the evidence.');
  const homeNav = await page.locator('.community-header nav a').allInnerTexts();
  for (const path of ['/explore/map', '/area/ahrf', '/cdc-funding', '/cdc-funding/state/NC', '/profile/county/37145']) {
    await visit(path);
    await page.locator('.community-header nav a').first().waitFor();
    assert.deepEqual(await page.locator('.community-header nav a').allInnerTexts(), homeNav, `${path} header links match the home page`);
    await contrast('.community-header nav a', '.community-header', 4.5);
    assert.equal(await page.locator('.chip-header, .chip-brand-line').count(), 0, `${path} has no legacy header`);
  }
  await visit('/cdc-funding/state/NC');
  await page.getByRole('heading', { name: /CDC grants to recipients in North Carolina/ }).waitFor();
  await page.getByRole('heading', { name: 'Funding by budget category' }).waitFor();
  await page.getByRole('heading', { name: 'Grants' }).waitFor();
  await page.getByLabel('Funding type').waitFor();
  await visit('/cdc-funding/state/NC?award_type=all');
  await page.getByRole('heading', { name: /CDC funding to recipients in North Carolina/ }).waitFor();
  await page.getByText(/Contracts are counted in the state where the contractor is located\.\s+Vaccines for Children purchases, for example, appear in the vaccine manufacturers' states\./).waitFor();
  console.log('Rebuilt state funding profile: loaded');
  console.log('Shared header on explore map, area map, funding, and legacy profile pages: passed');
  await visit('/explore/map');
  await page.getByRole('heading', { name: /^PLACES county and tract estimates(?:, \d{4})?$/ }).waitFor();
  const sourceOptions = await page.getByLabel('Data source').locator('option').allInnerTexts();
  assert.equal(sourceOptions.length, 9, 'nine published-release map sources');
  assert.ok(!sourceOptions.some((label) => /legacy|main/i.test(label)), 'no legacy entries in the Data source menu');
  assert.equal(await page.locator('.measure-controls-panel, .legend-panel').count(), 0, 'legacy map panels gone');

  const selectedArea = page.locator('[data-testid="selected-area"]');
  const zoomParam = () => Number(new URL(page.url()).searchParams.get('zoom'));
  await visit('/community/county/37145');
  await page.locator('[data-testid="profile-ready"]').waitFor();
  await page.locator('#health .community-map-link').first().click();
  await selectedArea.getByText('Person · County 37145').waitFor();
  await selectedArea.locator('.pilot-selected-value strong').waitFor();
  assert.match(await selectedArea.locator('.pilot-selected-value strong').innerText(), /%$/, 'focused county value in legend');
  assert.ok((await selectedArea.innerText()).includes('95% confidence interval'), 'focused county uncertainty in legend');
  await page.waitForFunction(() => new URLSearchParams(location.search).get('focus') === 'county:37145' && Number(new URLSearchParams(location.search).get('zoom')) >= 8);
  assert.ok(zoomParam() < 10, 'focused county stays at county level');
  assert.equal(await page.locator('.leaflet-area-selection-pane path').count(), 2, 'selection outline (casing and line)');
  assert.ok((await page.locator('.pilot-legend').innerText()).includes('quintiles of all published county values'), 'quintile class note');
  await screenshot('map-focused-county');
  await page.mouse.move(730, 395);
  await page.mouse.move(740, 400);   // open map inside the focused county, clear of the panels
  const countyTooltip = page.locator('.pdo-map-tooltip').filter({ hasText: 'Person · County 37145' });
  await countyTooltip.waitFor();
  assert.match(await countyTooltip.innerText(), /· County \d{5}\n.+\n.+ • 2023\nModeled adult prevalence estimate from CDC PLACES\./, 'legacy-format hover tooltip');
  assert.equal(await page.locator('.leaflet-popup').count(), 0, 'no click popup');
  await page.getByRole('button', { name: 'Clear Selection (Esc)' }).click();
  assert.equal(await selectedArea.count(), 0, 'clear selection');
  await page.mouse.click(740, 400);
  await selectedArea.locator('.pilot-selected-value strong').waitFor();
  await page.keyboard.press('Escape');
  assert.equal(await selectedArea.count(), 0, 'Escape clears selection');
  assert.equal(await page.getByRole('button', { name: /Analyze/ }).count(), 0, 'no assistant button on area maps');

  await visit('/community/state/37');
  await page.locator('[data-testid="profile-ready"]').waitFor();
  await page.locator('#health .community-map-link').first().click();
  await selectedArea.getByText('North Carolina · State 37').waitFor();
  await selectedArea.locator('.pilot-selected-value strong').waitFor();
  assert.ok((await selectedArea.innerText()).includes('95% confidence interval'), 'focused state BRFSS interval');
  assert.equal(await page.getByRole('link', { name: 'Open profile' }).getAttribute('href'), '/community/state/37', 'state profile tool');
  await screenshot('map-focused-state');

  await visit(`/district/cd/${districtGeoid}`);
  await page.locator('[data-testid="district-ready"]').waitFor();
  await page.getByRole('link', { name: 'Open district source map' }).click();
  await selectedArea.getByText(`· District ${districtGeoid}`).waitFor();
  await selectedArea.locator('.pilot-selected-value strong').waitFor();
  assert.ok((await selectedArea.innerText()).includes('margin'), 'focused district margin of error');
  await screenshot('map-focused-district');

  await visit('/area/ahrf');
  await page.locator('.pilot-table tbody tr').first().waitFor();
  await page.getByLabel('Find a county or state on the map').fill('Kanawha');
  await page.getByRole('link', { name: /Kanawha County, WV/ }).first().click();
  await selectedArea.getByText('Kanawha · County 54039').waitFor();
  await selectedArea.locator('.pilot-selected-value strong').waitFor();
  assert.equal(new URL(page.url()).pathname, '/area/ahrf', 'map search stays on the map');
  await page.waitForFunction(() => Number(new URLSearchParams(location.search).get('zoom')) >= 7);
  await page.getByLabel('Find a county or state on the map').fill('District of Columbia');
  await page.getByRole('link', { name: /District of Columbia · State/ }).first().click();
  await selectedArea.getByText('District of Columbia · State 11').waitFor();
  assert.ok((await selectedArea.innerText()).includes('none is calculated'), 'state selected on a county-only map shows no derived value');
  await page.getByLabel('Select base map').selectOption('topographic');
  await visit('/explore/map?focus=county:54039');
  await selectedArea.getByText('Kanawha · County 54039').waitFor();
  console.log('Profile-to-map focus (county, state, district), tooltip, legend selection, tools, and map search: passed');

  for (const [width, height] of [[1365, 900], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await visit('/area/usda-fea?lat=38.35&lon=-81.63&zoom=10');
    if (width === 390 && await page.getByRole('button', { name: 'Panels', exact: true }).getAttribute('aria-expanded') === 'false') {
      await page.getByRole('button', { name: 'Panels', exact: true }).click();
    }
    await page.getByLabel('Show HRSA health center sites').check();
    if (width === 390) await page.getByRole('button', { name: 'Show panel', exact: true }).click();
    const detail = page.getByRole('button', { name: /Details for/ }).first();
    await detail.waitFor();
    await detail.click();
    await page.locator('.chip-sites-detail h3').first().waitFor();
    await page.waitForFunction(() => document.querySelector('.chip-sites-detail h3')?.textContent !== 'Loading site…');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${width} overlay overflow`);
  }
  console.log('HRSA table Details pointer clicks: passed at desktop and mobile widths');

  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ['/', '/topics/food-environment', '/community/county/37145', '/community/state/37', '/area/brfss', '/compare?counties=37145,54039,06019', '/district/cd/5401', '/methodology']) {
    await visit(path);
    if (path.startsWith('/community/')) await page.locator('[data-testid="profile-ready"]').waitFor();
    if (path === '/area/brfss') {
      // On a phone the table starts closed; opening it must still show every state.
      if (await page.getByRole('button', { name: 'Panels', exact: true }).getAttribute('aria-expanded') === 'false') {
        await page.getByRole('button', { name: 'Panels', exact: true }).click();
      }
      await page.locator('.pilot-table-toggle').click();
      await page.locator('.pilot-table tbody tr').first().waitFor();
    }
    if (path.startsWith('/district/')) await page.locator('[data-testid="district-ready"]').waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${path} mobile overflow`);
    if (path === '/community/county/37145') await screenshot('person-profile-mobile');
    if (path === '/community/state/37') await screenshot('north-carolina-state-profile-mobile');
  }
  console.log('Mobile layout: no document overflow on eight key routes');
  for (const width of [1365, 390, 375]) {
    await page.setViewportSize({ width, height: width === 1365 ? 900 : 844 });
    for (const [path, label] of [
      ['/community/county/01055', 'etowah-county'],
      ['/community/state/01', 'alabama-state'],
      ['/district/cd/5401', 'wv-district'],
    ]) {
      await visit(path);
      await page.locator('.indicator-chart').first().waitFor();
      assert.ok(await page.locator('.indicator-chart').count() >= 1, `${path} has at least one indicator chart at ${width}px`);
      assert.equal(await page.locator('.chart-band').count(), 0, `${path} has no chart band at ${width}px`);
      const axisLabels = await page.locator('.indicator-chart .indicator-chart-axis-label').allTextContents();
      assert.ok(axisLabels.every((text) => !/^-/.test(text.trim())), `${path} nonnegative chart axes at ${width}px`);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${path} chart overflow at ${width}px`);
      await screenshot(`${label}-charts-${width}`, true);
    }
  }
  console.log('Profile charts: desktop, 390px, and 375px layouts passed');
  await visit(`/district/cd/${districtGeoid}`);
  await page.locator('[data-testid="district-ready"]').waitFor();
  assert.equal(await page.locator('.community-indicator').count(), 7, `${districtGeoid} mobile district estimates`);
  console.log(`District ${districtGeoid}: full briefing passed`);
  assert.deepEqual(errors, [], 'browser errors');
} finally {
  await browser.close();
}
