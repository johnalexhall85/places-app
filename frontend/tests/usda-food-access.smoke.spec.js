import { expect, test } from "playwright/test";

test("USDA Food Environment datasource smoke", async ({ page }) => {
  const appUrl = process.env.USDA_SMOKE_APP_URL || "http://127.0.0.1:5173";
  const requestUrls = [];
  page.on("request", (request) => {
    requestUrls.push(request.url());
  });

  await page.goto(appUrl, { waitUntil: "domcontentloaded" });
  requestUrls.length = 0;

  await page.getByLabel("Data source").selectOption({ label: "USDA Food Environment" });

  const measureSelect = page.locator('label:has-text("Measure") select').first();
  await expect(measureSelect).toBeVisible();
  await expect(page.locator(".leaflet-container")).toBeVisible();

  await expect.poll(async () => {
    const optionCount = await measureSelect.locator("option").count();
    return optionCount;
  }).toBeGreaterThan(0);

  const sawVariablesRequest = requestUrls.some((url) =>
    url.includes("/api/usda/food-environment/variables")
  );
  expect(sawVariablesRequest).toBeTruthy();

  const selectedMeasureValue = await measureSelect.evaluate((element) => {
    const options = Array.from(element.options).filter((option) => {
      const label = String(option.textContent ?? "").trim().toLowerCase();
      return Boolean(option.value) && label !== "loading measures...";
    });
    if (options.length === 0) {
      return null;
    }
    const firstOption = options[0];
    element.value = firstOption.value;
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return firstOption.value;
  });
  expect(selectedMeasureValue).not.toBeNull();

  const countyOptionCount = await measureSelect.locator('option[value="PCT_LACCESS_POP19"]').count();
  if (countyOptionCount > 0) {
    await measureSelect.selectOption("PCT_LACCESS_POP19");
    await expect(page.getByText("County-level", { exact: true })).toBeVisible();
  }

  const stateOptionCount = await measureSelect.locator('option[value="PCT_SNAP22"]').count();
  if (stateOptionCount > 0) {
    await measureSelect.selectOption("PCT_SNAP22");
    await expect(page.getByText("State-level", { exact: true })).toBeVisible();
  }

  await expect.poll(
    () => requestUrls.some((url) => url.includes("/api/usda/food-environment/map"))
  ).toBeTruthy();
  await expect.poll(
    () => requestUrls.some((url) => url.includes("/api/usda/food-environment/legend"))
  ).toBeTruthy();

  const sawMapRequest = requestUrls.some((url) =>
    url.includes("/api/usda/food-environment/map")
  );
  const sawLegendRequest = requestUrls.some((url) =>
    url.includes("/api/usda/food-environment/legend")
  );
  expect(sawMapRequest).toBeTruthy();
  expect(sawLegendRequest).toBeTruthy();

  const sawHeatRequest = requestUrls.some((url) =>
    url.includes("/api/usda/food-access/heat") || url.includes("/api/usda/food-environment/heat")
  );
  expect(sawHeatRequest).toBeFalsy();
});
