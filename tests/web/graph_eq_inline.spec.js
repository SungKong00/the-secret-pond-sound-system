const { test, expect } = require("@playwright/test");

const appUrl = process.env.SECRET_POND_E2E_URL || "http://127.0.0.1:8000/";
const stateUrl = new URL("/api/state", appUrl).toString();

async function openMixer(page) {
  await page.goto(appUrl);
  await page.getByRole("tab", { name: /Loop Mixer/ }).click();
}

async function openFirstGraphEq(page) {
  await openMixer(page);
  await page.locator("#layerControls [data-graph-eq-toggle]").first().click();
  await expect(page.locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);
}

test("Graph EQ is inline inside layer cards and no fourth tab exists", async ({ page }) => {
  await openFirstGraphEq(page);

  await expect(page.locator('[data-workspace-tab="graph-eq"]')).toHaveCount(0);
  await expect(page.locator(".graph-eq-layer-card-section")).toHaveCount(3);

  const weqCanvas = page.locator(".graph-eq-inline-editor.expanded canvas").first();
  await expect(weqCanvas).toBeVisible();
  const box = await weqCanvas.boundingBox();
  expect(box.width).toBeGreaterThan(200);
  expect(box.height).toBeGreaterThan(160);
});

test("opening another layer collapses the previous Graph EQ editor", async ({ page }) => {
  await openMixer(page);

  const toggles = page.locator("#layerControls [data-graph-eq-toggle]");
  await toggles.nth(0).click();
  await expect(page.locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);

  await toggles.nth(1).click();
  await expect(page.locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);
  await expect(page.locator('[data-graph-eq-layer-card].expanded')).toHaveCount(1);
});

test("WEQ8C edit updates layer EQ draft and persists after reload", async ({ page }) => {
  await openFirstGraphEq(page);

  const gainInput = page.locator('[data-graph-eq-point-control="gain"]').first();
  await gainInput.fill("6");
  await Promise.all([
    page.waitForResponse((response) => (
      response.url().includes("/api/settings/draft") && response.request().method() === "PUT"
    )),
    gainInput.blur(),
  ]);

  const stateAfterEdit = await page.request.get(stateUrl).then((response) => response.json());
  expect(JSON.stringify(stateAfterEdit.settings.draft.layers)).toContain('"gain_db":6');

  await page.reload();
  await page.getByRole("tab", { name: /Loop Mixer/ }).click();
  await page.locator("#layerControls [data-graph-eq-toggle]").first().click();
  await expect(page.locator('[data-graph-eq-point-control="gain"]').first()).toHaveValue(/6(\.0)?/);
});

test("Graph EQ add delete type and max six constraints are enforced", async ({ page }) => {
  await openFirstGraphEq(page);

  for (let index = 0; index < 10; index += 1) {
    const add = page.locator('[data-graph-eq-action="add-point"]').first();
    if (await add.isDisabled()) break;
    await add.click();
  }

  await expect(page.locator("[data-graph-eq-point-row]")).toHaveCount(6);

  await page.locator("[data-graph-eq-point-type]").first().selectOption("high_shelf");
  await expect(page.locator("[data-graph-eq-point-type]").first()).toHaveValue("high_shelf");

  await page.locator('[data-graph-eq-action="delete-point"]').first().click();
  await expect(page.locator("[data-graph-eq-point-row]")).toHaveCount(5);
});
