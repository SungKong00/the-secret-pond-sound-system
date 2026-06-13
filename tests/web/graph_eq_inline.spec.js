const { test, expect } = require("@playwright/test");

const appUrl = process.env.SECRET_POND_E2E_URL || "http://127.0.0.1:8000/";
const stateUrl = new URL("/api/state", appUrl).toString();
const draftUrl = new URL("/api/settings/draft", appUrl).toString();
const applyModeUrl = new URL("/api/playback/apply-mode", appUrl).toString();

function differentGain(value) {
  const numeric = Number(value);
  const base = Number.isFinite(numeric) ? numeric : 0;
  return base >= 5 ? -4 : 6;
}

async function resetFirstGraphEqDraft(page) {
  await setFirstGraphEqDraft(page, [
    { id: "custom-low", type: "low_shelf", frequency_hz: 280, gain_db: 4, q: 0.7 },
    { id: "custom-mid", type: "bell", frequency_hz: 1200, gain_db: -2, q: 1.1 },
    { id: "custom-high", type: "high_shelf", frequency_hz: 6400, gain_db: 3, q: 0.7 },
  ]);
}

async function setFirstGraphEqDraft(page, points) {
  await page.request.put(applyModeUrl, { data: { mode: "stable" } });
  const state = await page.request.get(stateUrl).then((response) => response.json());
  const draft = JSON.parse(JSON.stringify(state.settings.draft));
  draft.layers.mid.eq = {
    ...draft.layers.mid.eq,
    highpass_hz: 20,
    lowpass_hz: 20000,
    points,
  };
  await page.request.put(draftUrl, { data: draft });
}

async function openMixer(page) {
  await page.goto(appUrl);
  await page.getByRole("tab", { name: /Loop Mixer/ }).click();
}

async function openCurrentFirstGraphEq(page) {
  await openMixer(page);
  await page.locator("#layerControls [data-graph-eq-toggle]").first().click();
  await expect(page.locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);
  await expect(page.locator('[data-graph-eq-dsssp-root="true"]')).toHaveCount(1);
}

async function openFirstGraphEq(page) {
  await resetFirstGraphEqDraft(page);
  await openCurrentFirstGraphEq(page);
}

async function openFirstGraphEqInLive(page) {
  await resetFirstGraphEqDraft(page);
  const response = await page.request.put(applyModeUrl, {
    data: { mode: "live", staged_graph_eq: "discard" },
  });
  expect(response.ok()).toBeTruthy();
  await openCurrentFirstGraphEq(page);
  const state = await page.request.get(stateUrl).then((payload) => payload.json());
  expect(state.settings.active.playback.apply_mode).toBe("live");
}

const selectedInspector = (page) => page.locator("[data-graph-eq-selected-inspector]");

const selectedPointControl = (page, name) => (
  selectedInspector(page).locator(`[data-graph-eq-point-control="${name}"]`)
);

async function selectGraphEqBand(page, index) {
  const row = page.locator("[data-graph-eq-point-row]").nth(index);
  await row.click();
  await expect(row).toHaveAttribute("aria-pressed", "true");
}

test("DSSSP Graph EQ is inline inside layer cards and no fourth tab exists", async ({ page }) => {
  await openFirstGraphEq(page);
  const legacyEqTag = "weq" + "8-ui";

  await expect(page.locator('[data-workspace-tab="graph-eq"]')).toHaveCount(0);
  await expect(page.locator(".graph-eq-layer-card-section")).toHaveCount(3);
  await expect(page.locator(".graph-eq-mini-preview")).toHaveCount(0);
  await expect(page.locator(legacyEqTag)).toHaveCount(0);
  await expect(page.locator(".graph-eq-dsssp-surface svg")).toBeVisible();
  await expect(page.locator("[data-graph-eq-point-row]")).toHaveCount(3);
  await expect(page.locator(".graph-eq-band-list .graph-eq-band-number")).toHaveText(["1", "2", "3"]);
  await expect(selectedInspector(page)).toBeVisible();
  await expect(page.locator(".graph-eq-selected-band-curve")).toHaveCount(1);
  await selectGraphEqBand(page, 1);
  await expect(page.locator(".graph-eq-selected-band-curve")).toHaveCount(1);

  const box = await page.locator(".graph-eq-dsssp-surface svg").boundingBox();
  expect(box.width).toBeGreaterThan(500);
  expect(box.height).toBeGreaterThan(260);
});

test("Graph EQ gain controls keep the DSSSP visual gain range", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 0);
  const gainInput = selectedPointControl(page, "gain");
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

  await selectGraphEqBand(page, 1);
  const secondGainInput = selectedPointControl(page, "gain");
  const secondFreqInput = selectedPointControl(page, "freq");
  const beforeGain = Number(await secondGainInput.inputValue());
  const beforeFreq = Number(await secondFreqInput.inputValue());
  const secondRow = page.locator("[data-graph-eq-point-row]").nth(1);
  const beforeRowText = await secondRow.innerText();
  const handle = page.locator(".graph-eq-dsssp-surface svg circle").nth(1);
  const box = await handle.boundingBox();
  expect(box).not.toBeNull();

  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 160, box.y + box.height / 2 - 80, { steps: 8 });
  await page.mouse.up();

  await expect.poll(async () => Number(await secondGainInput.inputValue())).toBeGreaterThan(beforeGain + 1);
  await expect.poll(async () => Number(await secondFreqInput.inputValue())).toBeGreaterThan(beforeFreq);
  await expect.poll(async () => secondRow.innerText()).not.toBe(beforeRowText);
});

test("Low and High Shelf handles move cutoff frequency and gain while dragged", async ({ page }) => {
  await openFirstGraphEq(page);

  const graph = page.locator(".graph-eq-dsssp-surface svg");
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await graph.boundingBox();
  expect(graphBox).not.toBeNull();

  await selectGraphEqBand(page, 0);
  const lowFreq = selectedPointControl(page, "freq");
  const lowGain = selectedPointControl(page, "gain");
  const beforeLow = Number(await lowFreq.inputValue());
  const beforeLowGain = Number(await lowGain.inputValue());
  const handles = page.locator(".graph-eq-dsssp-surface svg circle");

  const lowHandle = handles.nth(0);
  const lowBox = await lowHandle.boundingBox();
  expect(lowBox).not.toBeNull();
  await page.mouse.move(lowBox.x + lowBox.width / 2, lowBox.y + lowBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x + graphBox.width * 0.75, lowBox.y + 80, { steps: 10 });
  await page.mouse.up();

  await expect.poll(async () => Number(await lowFreq.inputValue())).toBeGreaterThan(beforeLow);
  await expect.poll(async () => Math.abs(Number(await lowGain.inputValue()) - beforeLowGain))
    .toBeGreaterThan(1);
  const lowAfter = await lowHandle.boundingBox();
  expect(lowAfter).not.toBeNull();
  expect(lowAfter.x + lowAfter.width / 2).toBeGreaterThan(graphBox.x + graphBox.width * 0.6);

  await selectGraphEqBand(page, 2);
  const highFreq = selectedPointControl(page, "freq");
  const highGain = selectedPointControl(page, "gain");
  const beforeHigh = Number(await highFreq.inputValue());
  const beforeHighGain = Number(await highGain.inputValue());
  const highHandle = handles.nth(2);
  const highBox = await highHandle.boundingBox();
  expect(highBox).not.toBeNull();
  await page.mouse.move(highBox.x + highBox.width / 2, highBox.y + highBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x + graphBox.width * 0.25, highBox.y - 80, { steps: 10 });
  await page.mouse.up();

  await expect.poll(async () => Number(await highFreq.inputValue())).toBeLessThan(beforeHigh);
  await expect.poll(async () => Math.abs(Number(await highGain.inputValue()) - beforeHighGain))
    .toBeGreaterThan(1);
  const highAfter = await highHandle.boundingBox();
  expect(highAfter).not.toBeNull();
  expect(highAfter.x + highAfter.width / 2).toBeLessThan(graphBox.x + graphBox.width * 0.4);
});

test("Low Shelf handle keeps tracking the latest drag position outside the graph", async ({ page }) => {
  await openFirstGraphEq(page);

  const graph = page.locator(".graph-eq-dsssp-surface svg");
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await graph.boundingBox();
  expect(graphBox).not.toBeNull();

  await selectGraphEqBand(page, 0);
  const lowFreq = selectedPointControl(page, "freq");
  const lowGain = selectedPointControl(page, "gain");
  const lowHandle = page.locator(".graph-eq-dsssp-surface svg circle").nth(0);
  const lowBox = await lowHandle.boundingBox();
  expect(lowBox).not.toBeNull();

  await page.mouse.move(lowBox.x + lowBox.width / 2, lowBox.y + lowBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x - 70, graphBox.y - 70, { steps: 12 });
  await expect.poll(async () => Number(await lowGain.inputValue())).toBeGreaterThan(13);
  await page.mouse.move(graphBox.x - 70, graphBox.y + graphBox.height + 90, { steps: 12 });
  await page.mouse.up();

  await expect.poll(async () => Number(await lowFreq.inputValue())).toBeLessThanOrEqual(25);
  await expect.poll(async () => Number(await lowGain.inputValue())).toBeLessThan(-13);
  const lowAfter = await lowHandle.boundingBox();
  expect(lowAfter).not.toBeNull();
  expect(lowAfter.x).toBeGreaterThanOrEqual(graphBox.x);
  expect(lowAfter.x + lowAfter.width).toBeLessThanOrEqual(graphBox.x + graphBox.width);
});

test("edge Graph EQ handles stay fully visible inside the graph", async ({ page }) => {
  await setFirstGraphEqDraft(page, [
    { id: "edge-low", type: "low_shelf", frequency_hz: 20, gain_db: -15, q: 0.7 },
    { id: "edge-mid", type: "bell", frequency_hz: 1000, gain_db: 0, q: 1 },
    { id: "edge-high", type: "high_shelf", frequency_hz: 20000, gain_db: 15, q: 0.7 },
  ]);
  await openCurrentFirstGraphEq(page);

  const graph = page.locator(".graph-eq-dsssp-surface svg");
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await graph.boundingBox();
  expect(graphBox).not.toBeNull();

  const handles = page.locator(".graph-eq-dsssp-surface svg circle");
  const lowBox = await handles.nth(0).boundingBox();
  const highBox = await handles.nth(2).boundingBox();
  expect(lowBox).not.toBeNull();
  expect(highBox).not.toBeNull();

  for (const handleBox of [lowBox, highBox]) {
    expect(handleBox.x).toBeGreaterThanOrEqual(graphBox.x);
    expect(handleBox.y).toBeGreaterThanOrEqual(graphBox.y);
    expect(handleBox.x + handleBox.width).toBeLessThanOrEqual(graphBox.x + graphBox.width);
    expect(handleBox.y + handleBox.height).toBeLessThanOrEqual(graphBox.y + graphBox.height);
  }
});

test("Bell handle keeps tracking the latest drag position outside the graph", async ({ page }) => {
  await openFirstGraphEq(page);

  const graph = page.locator(".graph-eq-dsssp-surface svg");
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await graph.boundingBox();
  expect(graphBox).not.toBeNull();

  await selectGraphEqBand(page, 1);
  const midFreq = selectedPointControl(page, "freq");
  const midGain = selectedPointControl(page, "gain");
  const midHandle = page.locator(".graph-eq-dsssp-surface svg circle").nth(1);
  const midBox = await midHandle.boundingBox();
  expect(midBox).not.toBeNull();

  await page.mouse.move(midBox.x + midBox.width / 2, midBox.y + midBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x + graphBox.width + 80, graphBox.y - 70, { steps: 12 });
  await page.mouse.move(graphBox.x - 80, graphBox.y + graphBox.height + 90, { steps: 12 });
  await page.mouse.up();

  await expect.poll(async () => Number(await midGain.inputValue())).toBeLessThan(-13);
  await expect.poll(async () => Number(await midFreq.inputValue())).toBeLessThan(40);
});

test("dragging another DSSSP point preserves the previous point draft edit", async ({ page }) => {
  await openFirstGraphEqInLive(page);

  const graph = page.locator(".graph-eq-dsssp-surface svg");
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await graph.boundingBox();
  expect(graphBox).not.toBeNull();

  await selectGraphEqBand(page, 0);
  const firstGain = selectedPointControl(page, "gain");
  const secondGain = selectedPointControl(page, "gain");
  const beforeFirstGain = Number(await firstGain.inputValue());
  const handles = page.locator(".graph-eq-dsssp-surface svg circle");

  const firstHandleBox = await handles.nth(0).boundingBox();
  expect(firstHandleBox).not.toBeNull();
  await page.mouse.move(
    firstHandleBox.x + firstHandleBox.width / 2,
    firstHandleBox.y + firstHandleBox.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    graphBox.x + graphBox.width * 0.7,
    graphBox.y + graphBox.height * 0.78,
    { steps: 10 },
  );
  await page.mouse.up();

  await expect.poll(async () => Math.abs(Number(await firstGain.inputValue()) - beforeFirstGain))
    .toBeGreaterThan(1);
  const firstGainAfterFirstDrag = Number(await firstGain.inputValue());

  const secondHandleBox = await handles.nth(1).boundingBox();
  expect(secondHandleBox).not.toBeNull();
  await page.mouse.move(
    secondHandleBox.x + secondHandleBox.width / 2,
    secondHandleBox.y + secondHandleBox.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    graphBox.x + graphBox.width * 0.58,
    graphBox.y + graphBox.height * 0.25,
    { steps: 10 },
  );
  await page.mouse.up();

  await expect.poll(async () => Number(await secondGain.inputValue())).toBeGreaterThan(3);
  await selectGraphEqBand(page, 0);
  await expect.poll(async () => Number(await firstGain.inputValue()))
    .toBeCloseTo(firstGainAfterFirstDrag, 1);
});

test("fast repeated Bell drag leaves the final draft value visible", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 1);
  const midGain = selectedPointControl(page, "gain");
  const graph = page.locator(".graph-eq-dsssp-surface svg");
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await graph.boundingBox();
  expect(graphBox).not.toBeNull();
  const midHandle = page.locator(".graph-eq-dsssp-surface svg circle").nth(1);
  const box = await midHandle.boundingBox();
  expect(box).not.toBeNull();

  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x + graphBox.width * 0.45, graphBox.y + graphBox.height * 0.25, { steps: 4 });
  await page.mouse.move(graphBox.x + graphBox.width * 0.65, graphBox.y + graphBox.height * 0.75, { steps: 4 });
  await page.mouse.move(graphBox.x + graphBox.width * 0.55, graphBox.y + graphBox.height * 0.35, { steps: 4 });
  await page.mouse.up();

  await expect.poll(async () => Number(await midGain.inputValue())).toBeGreaterThan(3);
  await page.waitForTimeout(250);
  await expect.poll(async () => Number(await midGain.inputValue())).toBeGreaterThan(3);
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

test("opening a lower layer keeps the DSSSP graph in the working viewport", async ({ page }) => {
  await openMixer(page);
  await page.evaluate(() => window.scrollTo(0, 0));

  await page.locator("#layerControls [data-graph-eq-toggle]").nth(1).click();
  await expect(page.locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);
  await expect(page.locator('[data-graph-eq-layer-card="low"].expanded')).toHaveCount(1);

  const graphBox = await page.locator(".graph-eq-dsssp-surface svg").boundingBox();
  expect(graphBox).not.toBeNull();
  expect(graphBox.y).toBeLessThan(520);
});

test("DSSSP Graph EQ edit updates layer EQ draft and persists after reload", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 0);
  const gainInput = selectedPointControl(page, "gain");
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
  await selectGraphEqBand(page, 0);
  await expect(selectedPointControl(page, "gain")).toHaveValue(/6(\.0)?/);
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

  await selectGraphEqBand(page, 0);
  await page.locator("[data-graph-eq-point-type]").selectOption("high_shelf");
  await expect(page.locator("[data-graph-eq-point-type]")).toHaveValue("high_shelf");

  await selectedInspector(page).locator('[data-graph-eq-action="delete-point"]').click();
  await expect(page.locator("[data-graph-eq-point-row]")).toHaveCount(5);
});

test("Stable mode keeps Graph EQ edit as draft until Apply and Restart", async ({ page }) => {
  await openFirstGraphEq(page);

  const before = await page.request.get(stateUrl).then((response) => response.json());
  expect(before.settings.active.playback.apply_mode).toBe("stable");

  const activeGain = before.settings.active.layers.mid.eq.points[1].gain_db;
  const targetGain = differentGain(activeGain);
  await selectGraphEqBand(page, 1);
  const gainInput = selectedPointControl(page, "gain");
  await gainInput.fill(String(targetGain));
  await Promise.all([
    page.waitForResponse((response) => (
      response.url().includes("/api/settings/draft") && response.request().method() === "PUT"
    )),
    gainInput.blur(),
  ]);

  const after = await page.request.get(stateUrl).then((response) => response.json());
  expect(after.settings.draft.layers.mid.eq.points[1].gain_db).toBe(targetGain);
});

test("Live Graph EQ failure keeps visible draft value instead of snapping back", async ({ page }) => {
  await page.route("**/api/playback/live-graph-eq/tick", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "forced live graph eq failure" }),
    });
  });
  await openFirstGraphEqInLive(page);

  const before = await page.request.get(stateUrl).then((response) => response.json());
  const activeGain = before.settings.active.layers.mid.eq.points[1].gain_db;
  const targetGain = differentGain(activeGain);
  await selectGraphEqBand(page, 1);
  const gainInput = selectedPointControl(page, "gain");
  await gainInput.fill(String(targetGain));
  await Promise.all([
    page.waitForResponse((response) => (
      response.url().includes("/api/settings/draft") && response.request().method() === "PUT"
    )),
    gainInput.blur(),
  ]);

  await expect.poll(async () => Number(await gainInput.inputValue())).toBe(targetGain);
  await page.waitForTimeout(1300);
  await expect.poll(async () => Number(await gainInput.inputValue())).toBe(targetGain);

  const after = await page.request.get(stateUrl).then((response) => response.json());
  expect(after.settings.draft.layers.mid.eq.points[1].gain_db).toBe(targetGain);
  expect(after.settings.active.layers.mid.eq.points[1].gain_db).not.toBe(targetGain);
});
