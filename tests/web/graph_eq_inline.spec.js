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
  await expect(page.locator('[data-graph-eq-dsssp-root="true"]')).toHaveCount(1);
}

test("DSSSP Graph EQ is inline inside layer cards and no fourth tab exists", async ({ page }) => {
  await openFirstGraphEq(page);

  await expect(page.locator('[data-workspace-tab="graph-eq"]')).toHaveCount(0);
  await expect(page.locator(".graph-eq-layer-card-section")).toHaveCount(3);
  await expect(page.locator(".graph-eq-mini-preview")).toHaveCount(0);
  await expect(page.locator("weq8-ui")).toHaveCount(0);
  await expect(page.locator(".graph-eq-dsssp-surface svg")).toBeVisible();
  await expect(page.locator("[data-graph-eq-point-row]")).toHaveCount(3);

  const box = await page.locator(".graph-eq-dsssp-surface svg").boundingBox();
  expect(box.width).toBeGreaterThan(500);
  expect(box.height).toBeGreaterThan(260);
});

test("Graph EQ gain controls keep the DSSSP visual gain range", async ({ page }) => {
  await openFirstGraphEq(page);

  const gainInput = page.locator('[data-graph-eq-point-control="gain"]').first();
  await expect(gainInput).toHaveAttribute("min", "-15");
  await expect(gainInput).toHaveAttribute("max", "15");
  await gainInput.fill("18");
  const layerId = await page.locator("[data-graph-eq-layer-card].expanded")
    .getAttribute("data-graph-eq-layer-card");
  const pointId = await gainInput.getAttribute("data-graph-eq-point-id");
  await Promise.all([
    page.waitForResponse((response) => (
      response.url().includes("/api/settings/draft") && response.request().method() === "PUT"
    )),
    gainInput.blur(),
  ]);

  const stateAfterEdit = await page.request.get(stateUrl).then((response) => response.json());
  const editedPoint = stateAfterEdit.settings.draft.layers[layerId].eq.points
    .find((point) => point.id === pointId);
  expect(editedPoint.gain_db).toBe(15);
});

test("dragging a DSSSP point updates the matching point controls", async ({ page }) => {
  await openFirstGraphEq(page);

  const secondGainInput = page.locator('[data-graph-eq-point-control="gain"]').nth(1);
  const secondFreqInput = page.locator('[data-graph-eq-point-control="freq"]').nth(1);
  const beforeGain = Number(await secondGainInput.inputValue());
  const beforeFreq = Number(await secondFreqInput.inputValue());
  const handle = page.locator(".graph-eq-dsssp-surface svg circle").nth(1);
  const box = await handle.boundingBox();
  expect(box).not.toBeNull();

  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 160, box.y + box.height / 2 - 80, { steps: 8 });
  await page.mouse.up();

  await expect.poll(async () => Number(await secondGainInput.inputValue())).toBeGreaterThan(beforeGain + 1);
  await expect.poll(async () => Number(await secondFreqInput.inputValue())).toBeGreaterThan(beforeFreq);
});

test("opening another layer collapses the previous DSSSP Graph EQ editor", async ({ page }) => {
  await openMixer(page);

  const toggles = page.locator("#layerControls [data-graph-eq-toggle]");
  await toggles.nth(0).click();
  await expect(page.locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);

  await toggles.nth(1).click();
  await expect(page.locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);
  await expect(page.locator('[data-graph-eq-layer-card].expanded')).toHaveCount(1);
  await expect(page.locator('[data-graph-eq-dsssp-root="true"]')).toHaveCount(1);
});

test("DSSSP Graph EQ edit updates layer EQ draft and persists after reload", async ({ page }) => {
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
  await expect(page.locator(".graph-eq-dsssp-surface svg")).toBeVisible();
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
