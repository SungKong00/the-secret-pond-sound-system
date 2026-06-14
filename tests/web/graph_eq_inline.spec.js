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

async function openStack(page) {
  await page.goto(appUrl);
  await page.getByRole("tab", { name: /Voice Stack/ }).click();
}

async function openCurrentFirstGraphEq(page) {
  await openMixer(page);
  await expect(firstGraphEqCard(page).locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);
  await expect(firstGraphEqCard(page).locator('[data-graph-eq-dsssp-root="true"]')).toHaveCount(1);
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

const firstGraphEqCard = (page) => page.locator('[data-graph-eq-layer-card="mid"]');

const firstLayerCard = (page) => page.locator(".layer-card").filter({ has: firstGraphEqCard(page) });

const firstGraphEqGraph = (page) => firstGraphEqCard(page).locator(".graph-eq-dsssp-surface svg");

const firstGraphEqHandles = (page) => firstGraphEqCard(page).locator(".graph-eq-dsssp-surface svg circle");

const fixedShelfEdgeTolerancePx = 24;

const firstGraphEqPointLabels = (page) => (
  firstGraphEqCard(page).locator('[data-graph-eq-filter-point-label="true"]')
);

const selectedInspector = (page) => firstGraphEqCard(page).locator("[data-graph-eq-selected-inspector]");

const selectedPointControl = (page, name) => (
  selectedInspector(page).locator(`[data-graph-eq-point-control="${name}"]`)
);

async function viewportBox(locator) {
  return locator.evaluate((node) => {
    const box = node.getBoundingClientRect();
    return {
      x: box.x,
      y: box.y,
      width: box.width,
      height: box.height,
    };
  });
}

async function selectGraphEqBand(page, index) {
  const row = firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(index);
  await row.click();
  await expect(row).toHaveAttribute("aria-pressed", "true");
}

test("DSSSP Graph EQ is docked inside layer cards and no fourth tab exists", async ({ page }) => {
  await openFirstGraphEq(page);
  const legacyEqTag = "weq" + "8-ui";

  await expect(page.locator('[data-workspace-tab="graph-eq"]')).toHaveCount(0);
  await expect(page.locator(".graph-eq-layer-card-section")).toHaveCount(3);
  await expect(page.locator(".graph-eq-mini-preview")).toHaveCount(0);
  await expect(page.locator(".graph-eq-layer-card-section.expanded")).toHaveCount(3);
  await expect(page.locator(".graph-eq-layer-card-section.compact")).toHaveCount(0);
  await expect(page.locator(".graph-eq-collapsed-summary")).toHaveCount(0);
  await expect(page.locator("[data-graph-eq-layer-summary]")).toHaveCount(0);
  await expect(page.locator('[data-graph-eq-dsssp-root="true"]')).toHaveCount(3);
  await expect(page.locator(legacyEqTag)).toHaveCount(0);
  await expect(firstGraphEqGraph(page)).toBeVisible();
  await expect(firstGraphEqPointLabels(page)).toHaveCount(0);
  await expect(firstGraphEqHandles(page).first()).toHaveAttribute("r", "8");
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]")).toHaveCount(3);
  await expect(firstGraphEqCard(page).locator(".graph-eq-band-list .graph-eq-band-number"))
    .toHaveText(["", "1", ""]);
  await expect(selectedInspector(page)).toBeVisible();
  await expect(firstGraphEqCard(page).locator(".graph-eq-selected-band-curve")).toHaveCount(1);
  await selectGraphEqBand(page, 1);
  await expect(firstGraphEqCard(page).locator(".graph-eq-selected-band-curve")).toHaveCount(1);

  const box = await viewportBox(firstGraphEqGraph(page));
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
  const layerId = await firstGraphEqCard(page).getAttribute("data-graph-eq-layer-card");
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

test("clicking an existing DSSSP point selects it for inspector editing", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 0);
  await expect(selectedPointControl(page, "freq")).toHaveValue("80");
  await expect(selectedPointControl(page, "freq")).toBeDisabled();
  await expect(selectedPointControl(page, "gain")).toHaveValue("4");
  await expect(selectedPointControl(page, "q")).toHaveValue("0.7");
  const firstRow = firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(0);
  const secondRow = firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(1);
  const secondHandle = firstGraphEqHandles(page).nth(1);
  const secondHandleBox = await viewportBox(secondHandle);
  expect(secondHandleBox).not.toBeNull();

  await page.mouse.move(
    secondHandleBox.x + secondHandleBox.width / 2,
    secondHandleBox.y + secondHandleBox.height / 2,
  );
  await expect(firstRow).toHaveAttribute("aria-pressed", "true");
  await expect(secondRow).toHaveAttribute("aria-pressed", "false");

  await page.mouse.down();
  await page.mouse.up();

  await expect(secondRow).toHaveAttribute("aria-pressed", "true");
  await expect(selectedInspector(page)).toHaveAttribute("data-graph-eq-point-id", "custom-mid");
  await expect(selectedPointControl(page, "freq")).toHaveAttribute("data-graph-eq-point-id", "custom-mid");
  await expect(selectedPointControl(page, "freq")).toHaveValue("1200");
  await expect(selectedPointControl(page, "freq")).toBeEnabled();
  await expect(selectedPointControl(page, "gain")).toHaveValue("-2");
  await expect(selectedPointControl(page, "q")).toHaveValue("1.1");
});

test("double-click delete eligibility excludes fixed shelf handles", async ({ page }) => {
  await openFirstGraphEq(page);

  await firstGraphEqHandles(page).nth(0).dblclick();
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]")).toHaveCount(3);
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(0))
    .toHaveAttribute("data-graph-eq-point-id", "custom-low");

  await firstGraphEqHandles(page).nth(2).dblclick();
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]")).toHaveCount(3);
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(2))
    .toHaveAttribute("data-graph-eq-point-id", "custom-high");

  await firstGraphEqHandles(page).nth(1).dblclick();
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]")).toHaveCount(2);
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(0))
    .toHaveAttribute("data-graph-eq-point-id", "custom-low");
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(1))
    .toHaveAttribute("data-graph-eq-point-id", "custom-high");
});

test("DSSSP point drag starts only after pointer movement greater than four pixels", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 1);
  const secondGainInput = selectedPointControl(page, "gain");
  const beforeSecondGain = Number(await secondGainInput.inputValue());
  await selectGraphEqBand(page, 0);
  const firstRow = firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(0);
  const secondRow = firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(1);
  const secondHandle = firstGraphEqHandles(page).nth(1);
  const secondHandleBox = await viewportBox(secondHandle);
  expect(secondHandleBox).not.toBeNull();
  const handleCenter = {
    x: secondHandleBox.x + secondHandleBox.width / 2,
    y: secondHandleBox.y + secondHandleBox.height / 2,
  };

  await page.mouse.move(handleCenter.x, handleCenter.y);
  await page.mouse.down();
  await page.mouse.move(handleCenter.x + 4, handleCenter.y);
  await page.mouse.up();

  await expect(secondRow).toHaveAttribute("aria-pressed", "true");
  await expect.poll(async () => Number(await secondGainInput.inputValue())).toBe(beforeSecondGain);

  await selectGraphEqBand(page, 0);
  await expect(firstRow).toHaveAttribute("aria-pressed", "true");
  await page.mouse.move(handleCenter.x, handleCenter.y);
  await page.mouse.down();
  await page.mouse.move(handleCenter.x, handleCenter.y - 5);

  await expect(secondRow).toHaveAttribute("aria-pressed", "true");
  await expect.poll(async () => Number(await secondGainInput.inputValue())).toBeGreaterThan(beforeSecondGain);
  await page.mouse.up();
});

test("dragging a DSSSP point updates the matching point controls", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 1);
  const secondGainInput = selectedPointControl(page, "gain");
  const secondFreqInput = selectedPointControl(page, "freq");
  const beforeGain = Number(await secondGainInput.inputValue());
  const beforeFreq = Number(await secondFreqInput.inputValue());
  const secondRow = firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(1);
  const beforeRowText = await secondRow.innerText();
  const handle = firstGraphEqHandles(page).nth(1);
  const box = await viewportBox(handle);
  expect(box).not.toBeNull();

  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 160, box.y + box.height / 2 - 80, { steps: 8 });
  await page.mouse.up();

  await expect.poll(async () => Number(await secondGainInput.inputValue())).toBeGreaterThan(beforeGain + 1);
  await expect.poll(async () => Number(await secondFreqInput.inputValue())).toBeGreaterThan(beforeFreq);
  await expect.poll(async () => secondRow.innerText()).not.toBe(beforeRowText);
});

test("clicking the DSSSP Graph EQ curve creates a selected Bell band from the click position", async ({ page }) => {
  await openFirstGraphEq(page);

  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  const clickRatio = { x: 0.62, y: 0.28 };
  const expectedFrequency = Math.round(20 * ((20000 / 20) ** clickRatio.x));
  const expectedGain = Number((15 - clickRatio.y * 30).toFixed(1));
  const clickX = graphBox.x + graphBox.width * clickRatio.x;
  const clickY = graphBox.y + graphBox.height * clickRatio.y;

  await Promise.all([
    page.waitForResponse((response) => (
      response.url().includes("/api/settings/draft") && response.request().method() === "PUT"
    )),
    page.mouse.click(clickX, clickY),
  ]);

  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]")).toHaveCount(4);
  await expect.poll(async () => Math.abs(Number(await selectedPointControl(page, "freq").inputValue()) - expectedFrequency))
    .toBeLessThanOrEqual(12);
  await expect.poll(async () => Math.abs(Number(await selectedPointControl(page, "gain").inputValue()) - expectedGain))
    .toBeLessThanOrEqual(0.11);
  await expect(selectedPointControl(page, "q")).toHaveValue("1.4");
  await expect(selectedInspector(page).locator("[data-graph-eq-point-type]")).toHaveValue("bell");

  const layerId = await firstGraphEqCard(page).getAttribute("data-graph-eq-layer-card");
  const pointId = await selectedPointControl(page, "freq").getAttribute("data-graph-eq-point-id");
  const stateAfterClick = await page.request.get(stateUrl).then((response) => response.json());
  const createdPoint = stateAfterClick.settings.draft.layers[layerId].eq.points
    .find((point) => point.id === pointId);
  expect(createdPoint).toMatchObject({
    type: "bell",
    q: 1.4,
  });
  expect(Math.abs(createdPoint.frequency_hz - expectedFrequency)).toBeLessThanOrEqual(12);
  expect(Math.abs(createdPoint.gain_db - expectedGain)).toBeLessThanOrEqual(0.11);
});

test("creating two Bell bands numbers them from left to right by frequency", async ({ page }) => {
  await setFirstGraphEqDraft(page, [
    { id: "custom-low", type: "low_shelf", frequency_hz: 280, gain_db: 4, q: 0.7 },
    { id: "custom-high", type: "high_shelf", frequency_hz: 6400, gain_db: 3, q: 0.7 },
  ]);
  await openCurrentFirstGraphEq(page);

  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  await Promise.all([
    page.waitForResponse((response) => (
      response.url().includes("/api/settings/draft") && response.request().method() === "PUT"
    )),
    page.mouse.click(graphBox.x + graphBox.width * 0.35, graphBox.y + graphBox.height * 0.35),
  ]);
  const olderBellId = await selectedPointControl(page, "freq").getAttribute("data-graph-eq-point-id");

  await Promise.all([
    page.waitForResponse((response) => (
      response.url().includes("/api/settings/draft") && response.request().method() === "PUT"
    )),
    page.mouse.click(graphBox.x + graphBox.width * 0.65, graphBox.y + graphBox.height * 0.65),
  ]);
  const newestBellId = await selectedPointControl(page, "freq").getAttribute("data-graph-eq-point-id");

  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]")).toHaveCount(4);
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(1))
    .toHaveAttribute("data-graph-eq-point-id", olderBellId);
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(2))
    .toHaveAttribute("data-graph-eq-point-id", newestBellId);
  await expect(firstGraphEqCard(page).locator(".graph-eq-band-list .graph-eq-band-number"))
    .toHaveText(["", "1", "2", ""]);
  await expect(firstGraphEqPointLabels(page)).toHaveCount(0);
  await expect(selectedInspector(page).locator(".graph-eq-band-number")).toHaveText("2");
  await expect(selectedInspector(page).locator("h5")).toContainText("Selected Band 2");
});

test("deleting a Bell band renumbers the remaining Bell bands sequentially", async ({ page }) => {
  await setFirstGraphEqDraft(page, [
    { id: "custom-low", type: "low_shelf", frequency_hz: 280, gain_db: 4, q: 0.7 },
    { id: "custom-newest", type: "bell", frequency_hz: 3200, gain_db: 5, q: 1 },
    { id: "custom-middle", type: "bell", frequency_hz: 1200, gain_db: -2, q: 1.1 },
    { id: "custom-oldest", type: "bell", frequency_hz: 420, gain_db: 1, q: 1.2 },
    { id: "custom-high", type: "high_shelf", frequency_hz: 6400, gain_db: 3, q: 0.7 },
  ]);
  await openCurrentFirstGraphEq(page);

  await selectGraphEqBand(page, 2);
  await selectedInspector(page).locator('[data-graph-eq-action="delete-point"]').click();

  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]")).toHaveCount(4);
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(1))
    .toHaveAttribute("data-graph-eq-point-id", "custom-oldest");
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]").nth(2))
    .toHaveAttribute("data-graph-eq-point-id", "custom-newest");
  await expect(firstGraphEqCard(page).locator(".graph-eq-band-list .graph-eq-band-number"))
    .toHaveText(["", "1", "2", ""]);
  await expect(firstGraphEqPointLabels(page)).toHaveCount(0);

  await selectGraphEqBand(page, 1);
  await expect(selectedInspector(page).locator(".graph-eq-band-number")).toHaveText("1");
  await expect(selectedInspector(page).locator("h5")).toContainText("Selected Band 1");
});

test("Low and High Shelf handles stay pinned and drag gain only", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 0);
  const layerId = await firstGraphEqCard(page).getAttribute("data-graph-eq-layer-card");
  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  const lowFreq = selectedPointControl(page, "freq");
  const lowGain = selectedPointControl(page, "gain");
  const lowPointId = await lowFreq.getAttribute("data-graph-eq-point-id");
  const beforeLow = Number(await lowFreq.inputValue());
  const beforeLowGain = Number(await lowGain.inputValue());
  const handles = firstGraphEqHandles(page);

  const lowHandle = handles.nth(0);
  const lowBox = await viewportBox(lowHandle);
  expect(lowBox).not.toBeNull();
  expect((lowBox.x + lowBox.width / 2) - graphBox.x).toBeLessThan(fixedShelfEdgeTolerancePx);
  await page.mouse.move(lowBox.x + lowBox.width / 2, lowBox.y + lowBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x + graphBox.width * 0.75, lowBox.y + 80, { steps: 10 });
  await page.mouse.up();

  await expect.poll(async () => Number(await lowFreq.inputValue())).toBe(beforeLow);
  await expect.poll(async () => Math.abs(Number(await lowGain.inputValue()) - beforeLowGain))
    .toBeGreaterThan(1);
  const lowAfter = await viewportBox(lowHandle);
  expect(lowAfter).not.toBeNull();
  expect((lowAfter.x + lowAfter.width / 2) - graphBox.x).toBeLessThan(fixedShelfEdgeTolerancePx);
  await expect.poll(async () => {
    const stateAfterDrag = await page.request.get(stateUrl).then((response) => response.json());
    const storedLow = stateAfterDrag.settings.draft.layers[layerId].eq.points
      .find((point) => point.id === lowPointId);
    return storedLow?.frequency_hz;
  }).toBe(80);

  await selectGraphEqBand(page, 2);
  await graph.scrollIntoViewIfNeeded();
  const highGraphBox = await viewportBox(graph);
  expect(highGraphBox).not.toBeNull();
  const highFreq = selectedPointControl(page, "freq");
  const highGain = selectedPointControl(page, "gain");
  const highPointId = await highFreq.getAttribute("data-graph-eq-point-id");
  const beforeHigh = Number(await highFreq.inputValue());
  const beforeHighGain = Number(await highGain.inputValue());
  const highHandle = handles.nth(2);
  const highBox = await viewportBox(highHandle);
  expect(highBox).not.toBeNull();
  expect((highGraphBox.x + highGraphBox.width) - (highBox.x + highBox.width / 2))
    .toBeLessThan(fixedShelfEdgeTolerancePx);
  await page.mouse.move(highBox.x + highBox.width / 2, highBox.y + highBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(highGraphBox.x + highGraphBox.width * 0.25, highBox.y - 80, { steps: 10 });
  await page.mouse.up();

  await expect.poll(async () => Number(await highFreq.inputValue())).toBe(beforeHigh);
  await expect.poll(async () => Math.abs(Number(await highGain.inputValue()) - beforeHighGain))
    .toBeGreaterThan(1);
  const highAfter = await viewportBox(highHandle);
  expect(highAfter).not.toBeNull();
  expect((highGraphBox.x + highGraphBox.width) - (highAfter.x + highAfter.width / 2))
    .toBeLessThan(fixedShelfEdgeTolerancePx);
  await expect.poll(async () => {
    const stateAfterDrag = await page.request.get(stateUrl).then((response) => response.json());
    const storedHigh = stateAfterDrag.settings.draft.layers[layerId].eq.points
      .find((point) => point.id === highPointId);
    return storedHigh?.frequency_hz;
  }).toBe(10000);
});

test("Low Shelf handle keeps tracking outside-graph gain while pinned", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 0);
  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  const lowFreq = selectedPointControl(page, "freq");
  const lowGain = selectedPointControl(page, "gain");
  const beforeLowFreq = Number(await lowFreq.inputValue());
  const lowHandle = firstGraphEqHandles(page).nth(0);
  const lowBox = await viewportBox(lowHandle);
  expect(lowBox).not.toBeNull();

  await page.mouse.move(lowBox.x + lowBox.width / 2, lowBox.y + lowBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x - 70, graphBox.y - 70, { steps: 12 });
  await expect.poll(async () => Number(await lowGain.inputValue())).toBeGreaterThan(13);
  await page.mouse.move(graphBox.x - 70, graphBox.y + graphBox.height + 90, { steps: 12 });
  await page.mouse.up();

  await expect.poll(async () => Number(await lowFreq.inputValue())).toBe(beforeLowFreq);
  await expect.poll(async () => Number(await lowGain.inputValue())).toBeLessThan(-13);
  const lowAfter = await viewportBox(lowHandle);
  expect(lowAfter).not.toBeNull();
  expect((lowAfter.x + lowAfter.width / 2) - graphBox.x).toBeLessThan(fixedShelfEdgeTolerancePx);
});

test("fixed shelf handles stay visually pinned to graph edges", async ({ page }) => {
  await setFirstGraphEqDraft(page, [
    { id: "edge-low", type: "low_shelf", frequency_hz: 20, gain_db: -15, q: 0.7 },
    { id: "edge-mid", type: "bell", frequency_hz: 1000, gain_db: 0, q: 1 },
    { id: "edge-high", type: "high_shelf", frequency_hz: 20000, gain_db: 15, q: 0.7 },
  ]);
  await openCurrentFirstGraphEq(page);

  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  const handles = firstGraphEqHandles(page);
  const lowBox = await viewportBox(handles.nth(0));
  const highBox = await viewportBox(handles.nth(2));
  expect(lowBox).not.toBeNull();
  expect(highBox).not.toBeNull();

  expect((lowBox.x + lowBox.width / 2) - graphBox.x).toBeLessThan(fixedShelfEdgeTolerancePx);
  expect((graphBox.x + graphBox.width) - (highBox.x + highBox.width / 2))
    .toBeLessThan(fixedShelfEdgeTolerancePx);
  expect(lowBox.y).toBeGreaterThanOrEqual(graphBox.y);
  expect(highBox.y + highBox.height).toBeLessThanOrEqual(graphBox.y + graphBox.height);
});

test("Bell handle keeps tracking the latest drag position outside the graph", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 1);
  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  const midFreq = selectedPointControl(page, "freq");
  const midGain = selectedPointControl(page, "gain");
  const midHandle = firstGraphEqHandles(page).nth(1);
  const midBox = await viewportBox(midHandle);
  expect(midBox).not.toBeNull();

  await page.mouse.move(midBox.x + midBox.width / 2, midBox.y + midBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x + graphBox.width + 80, graphBox.y - 70, { steps: 12 });
  await page.mouse.move(graphBox.x - 80, graphBox.y + graphBox.height + 90, { steps: 12 });
  await page.mouse.up();

  await expect.poll(async () => Number(await midGain.inputValue())).toBeLessThan(-13);
  await expect.poll(async () => Number(await midFreq.inputValue())).toBeLessThan(40);
});

test("dragging a Bell band outside the graph clamps stored gain to the DSSSP range", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 1);
  const layerId = await firstGraphEqCard(page).getAttribute("data-graph-eq-layer-card");
  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  const midGain = selectedPointControl(page, "gain");
  const pointId = await midGain.getAttribute("data-graph-eq-point-id");
  const midHandle = firstGraphEqHandles(page).nth(1);

  const dragBellTo = async (clientY) => {
    const midBox = await viewportBox(midHandle);
    expect(midBox).not.toBeNull();
    await page.mouse.move(midBox.x + midBox.width / 2, midBox.y + midBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(graphBox.x + graphBox.width * 0.5, clientY, { steps: 12 });
    await page.mouse.up();
  };
  const storedBellGain = async () => {
    const stateAfterDrag = await page.request.get(stateUrl).then((response) => response.json());
    const draggedPoint = stateAfterDrag.settings.draft.layers[layerId].eq.points
      .find((point) => point.id === pointId);
    return draggedPoint?.gain_db;
  };

  await dragBellTo(graphBox.y - 180);
  await expect.poll(storedBellGain).toBe(15);

  await dragBellTo(graphBox.y + graphBox.height + 180);
  await expect.poll(storedBellGain).toBe(-15);
});

test("dragging a Bell band below 20 Hz stores exactly 20 Hz", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 1);
  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  const midFreq = selectedPointControl(page, "freq");
  const midHandle = firstGraphEqHandles(page).nth(1);
  const midBox = await viewportBox(midHandle);
  expect(midBox).not.toBeNull();

  await page.mouse.move(midBox.x + midBox.width / 2, midBox.y + midBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x - 180, graphBox.y + graphBox.height / 2, { steps: 12 });
  await page.mouse.up();

  await expect.poll(async () => Number(await midFreq.inputValue())).toBe(20);
});

test("dragging a Bell band above 20000 Hz stores exactly 20000 Hz", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 1);
  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  const midFreq = selectedPointControl(page, "freq");
  const midHandle = firstGraphEqHandles(page).nth(1);
  const midBox = await viewportBox(midHandle);
  expect(midBox).not.toBeNull();

  await page.mouse.move(midBox.x + midBox.width / 2, midBox.y + midBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x + graphBox.width + 180, graphBox.y + graphBox.height / 2, { steps: 12 });
  await page.mouse.up();

  await expect.poll(async () => Number(await midFreq.inputValue())).toBe(20000);
});

test("dragging a Bell band within 20-20000 Hz stores the dragged frequency", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 1);
  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  const midFreq = selectedPointControl(page, "freq");
  const midHandle = firstGraphEqHandles(page).nth(1);
  const midBox = await viewportBox(midHandle);
  expect(midBox).not.toBeNull();

  const dragRatio = 0.74;
  const expectedFrequency = Math.round(20 * ((20000 / 20) ** dragRatio));
  await page.mouse.move(midBox.x + midBox.width / 2, midBox.y + midBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    graphBox.x + graphBox.width * dragRatio,
    graphBox.y + graphBox.height * 0.5,
    { steps: 12 },
  );
  await page.mouse.up();

  await expect.poll(async () => Number(await midFreq.inputValue())).toBe(expectedFrequency);

  const layerId = await firstGraphEqCard(page).getAttribute("data-graph-eq-layer-card");
  const pointId = await midFreq.getAttribute("data-graph-eq-point-id");
  await expect.poll(async () => {
    const stateAfterDrag = await page.request.get(stateUrl).then((response) => response.json());
    const draggedPoint = stateAfterDrag.settings.draft.layers[layerId].eq.points
      .find((point) => point.id === pointId);
    return draggedPoint?.frequency_hz;
  }).toBe(expectedFrequency);
});

test("dragging another DSSSP point preserves the previous point draft edit", async ({ page }) => {
  await openFirstGraphEqInLive(page);

  await selectGraphEqBand(page, 0);
  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  const firstGain = selectedPointControl(page, "gain");
  const secondGain = selectedPointControl(page, "gain");
  const beforeFirstGain = Number(await firstGain.inputValue());
  const handles = firstGraphEqHandles(page);

  const firstHandleBox = await viewportBox(handles.nth(0));
  expect(firstHandleBox).not.toBeNull();
  await page.mouse.move(
    firstHandleBox.x + firstHandleBox.width / 2,
    firstHandleBox.y + firstHandleBox.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    graphBox.x - 80,
    beforeFirstGain >= 0 ? graphBox.y + graphBox.height + 90 : graphBox.y - 90,
    { steps: 10 },
  );
  await page.mouse.up();

  await expect.poll(async () => Math.abs(Number(await firstGain.inputValue()) - beforeFirstGain))
    .toBeGreaterThan(1);
  const firstGainAfterFirstDrag = Number(await firstGain.inputValue());

  const secondHandleBox = await viewportBox(handles.nth(1));
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
  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();
  const midHandle = firstGraphEqHandles(page).nth(1);
  const box = await viewportBox(midHandle);
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

test("Bell drag defers draft save until pointerup and saves the final value", async ({ page }) => {
  await openFirstGraphEq(page);
  await selectGraphEqBand(page, 1);

  const before = await page.request.get(stateUrl).then((response) => response.json());
  const activeSettings = JSON.parse(JSON.stringify(before.settings.active));
  const draftSaves = [];
  await page.route("**/api/settings/draft", async (route) => {
    const draft = route.request().postDataJSON();
    draftSaves.push(draft);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        settings: {
          active: activeSettings,
          draft,
        },
      }),
    });
  });

  const midGain = selectedPointControl(page, "gain");
  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();
  const midHandle = firstGraphEqHandles(page).nth(1);
  const box = await viewportBox(midHandle);
  expect(box).not.toBeNull();

  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x + graphBox.width * 0.42, graphBox.y + graphBox.height * 0.2, { steps: 6 });
  await expect.poll(async () => Number(await midGain.inputValue())).toBeGreaterThan(4);
  await page.waitForTimeout(420);
  expect(draftSaves).toHaveLength(0);

  await page.mouse.move(graphBox.x + graphBox.width * 0.66, graphBox.y + graphBox.height * 0.33, { steps: 6 });
  await page.waitForTimeout(420);
  expect(draftSaves).toHaveLength(0);

  const finalVisibleGain = Number(await midGain.inputValue());
  await page.mouse.up();

  await expect.poll(() => draftSaves.length).toBe(1);
  const savedPoint = draftSaves[0].layers.mid.eq.points.find((point) => point.id === "custom-mid");
  expect(savedPoint.gain_db).toBeCloseTo(finalVisibleGain, 1);
});

test("stale Graph EQ save response during the next drag keeps the held point interactive", async ({ page }) => {
  await openFirstGraphEq(page);
  await selectGraphEqBand(page, 1);

  const before = await page.request.get(stateUrl).then((response) => response.json());
  const activeSettings = JSON.parse(JSON.stringify(before.settings.active));
  const pendingDraftSaves = [];
  await page.route("**/api/settings/draft", async (route) => {
    const draft = route.request().postDataJSON();
    await new Promise((resolve) => {
      pendingDraftSaves.push({ draft, resolve });
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        settings: {
          active: activeSettings,
          draft,
        },
      }),
    });
  });

  const midGain = selectedPointControl(page, "gain");
  const graph = firstGraphEqGraph(page);
  await graph.scrollIntoViewIfNeeded();
  const graphBox = await viewportBox(graph);
  expect(graphBox).not.toBeNull();

  let box = await viewportBox(firstGraphEqHandles(page).nth(1));
  expect(box).not.toBeNull();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x + graphBox.width * 0.45, graphBox.y + graphBox.height * 0.25, { steps: 6 });
  await page.mouse.up();
  await expect.poll(() => pendingDraftSaves.length).toBe(1);

  box = await viewportBox(firstGraphEqHandles(page).nth(1));
  expect(box).not.toBeNull();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(graphBox.x + graphBox.width * 0.32, graphBox.y + graphBox.height * 0.72, { steps: 5 });
  const gainDuringSecondDrag = Number(await midGain.inputValue());
  expect(gainDuringSecondDrag).toBeLessThan(0);

  pendingDraftSaves[0].resolve();
  await page.waitForTimeout(760);

  await page.mouse.move(graphBox.x + graphBox.width * 0.58, graphBox.y + graphBox.height * 0.18, { steps: 8 });
  const finalVisibleGain = Number(await midGain.inputValue());
  expect(finalVisibleGain).toBeGreaterThan(6);
  await page.mouse.up();

  await expect.poll(() => pendingDraftSaves.length).toBe(2);
  pendingDraftSaves[1].resolve();
  await expect.poll(async () => Number(await midGain.inputValue())).toBeCloseTo(finalVisibleGain, 1);
  expect(pendingDraftSaves[1].draft.layers.mid.eq.points[1].gain_db).toBeCloseTo(finalVisibleGain, 1);
});

test("Loop Mixer keeps every layer Graph EQ editor expanded without compact summaries", async ({ page }) => {
  await openMixer(page);

  await expect(page.locator(".graph-eq-layer-card-section.expanded")).toHaveCount(3);
  await expect(page.locator(".graph-eq-layer-card-section.compact")).toHaveCount(0);
  await expect(page.locator(".graph-eq-inline-editor.expanded")).toHaveCount(3);
  await expect(page.locator(".graph-eq-collapsed-summary")).toHaveCount(0);
  await expect(page.locator('[data-graph-eq-dsssp-root="true"]')).toHaveCount(3);
});

test("Voice Stack Graph EQ uses the same always-expanded editor as Loop Mixer", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openMixer(page);
  const mixerGraphBox = await viewportBox(firstGraphEqGraph(page));
  expect(mixerGraphBox).not.toBeNull();

  await openStack(page);
  const voiceEqCard = page.locator('[data-graph-eq-layer-card="voice"]');
  const voiceGraph = voiceEqCard.locator(".graph-eq-dsssp-surface svg");

  await expect(voiceEqCard).toHaveClass(/expanded/);
  await expect(voiceEqCard.locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);
  await expect(voiceEqCard.locator(".graph-eq-workflow")).toBeVisible();
  await expect(voiceGraph).toBeVisible();
  await expect(voiceEqCard.locator('[data-graph-eq-dsssp-root="true"]')).toHaveCount(1);
  await expect(voiceEqCard.locator(".graph-eq-collapsed-summary")).toHaveCount(0);
  await expect(voiceEqCard.locator(".graph-eq-band-list")).toBeVisible();
  await expect(voiceEqCard.locator("[data-graph-eq-selected-inspector]")).toBeVisible();

  const voiceGraphBox = await viewportBox(voiceGraph);
  expect(voiceGraphBox).not.toBeNull();
  expect(voiceGraphBox.width).toBeGreaterThanOrEqual(mixerGraphBox.width * 0.9);
  expect(voiceGraphBox.width).toBeGreaterThan(860);

  const layout = await voiceEqCard.evaluate((card) => {
    const layerCard = card.closest(".layer-card");
    const levelGroup = layerCard?.querySelector(".level-group");
    const graphBox = card.getBoundingClientRect();
    const workflow = card.querySelector(".graph-eq-workflow");
    const inspector = card.querySelector("[data-graph-eq-selected-inspector]");
    const bandManager = card.querySelector(".graph-eq-band-manager");
    const levelBox = levelGroup?.getBoundingClientRect();
    const rect = (node) => {
      const box = node?.getBoundingClientRect();
      return box ? { width: box.width, top: box.top } : null;
    };
    return {
      graphTop: graphBox.top,
      graphWidth: graphBox.width,
      levelTop: levelBox?.top ?? 0,
      workflowColumns: workflow ? getComputedStyle(workflow).gridTemplateColumns : "",
      inspector: rect(inspector),
      bandManager: rect(bandManager),
    };
  });
  expect(layout.graphTop).toBeLessThan(layout.levelTop);
  expect(layout.graphWidth).toBeGreaterThan(1000);
  expect(layout.workflowColumns.split(" ").length).toBeGreaterThanOrEqual(2);
  expect(layout.inspector.width).toBeGreaterThan(280);
  expect(layout.bandManager.width).toBeGreaterThan(300);
});

test("docked Graph EQ layout keeps operation controls visible while giving mixer a wide editor", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openMixer(page);
  await page.evaluate(() => window.scrollTo(0, 0));

  await expect(firstGraphEqCard(page).locator(".graph-eq-inline-editor.expanded")).toHaveCount(1);
  await expect(firstGraphEqCard(page).locator(".graph-eq-workflow")).toBeVisible();

  await firstGraphEqCard(page).evaluate((node) => node.scrollIntoView({ block: "start", inline: "nearest" }));
  const graphBox = await viewportBox(firstGraphEqGraph(page));
  expect(graphBox).not.toBeNull();
  expect(graphBox.y).toBeLessThan(560);
  expect(graphBox.width).toBeGreaterThan(860);

  const layout = await page.evaluate(() => {
    const dashboard = document.querySelector(".dashboard-grid");
    const mainWorkspace = document.querySelector(".main-workspace-panel");
    const playbackPanel = document.getElementById("playbackPanel");
    const voiceCapturePanel = document.querySelector(".record-panel");
    const playbackActions = document.querySelector(".playback-actions");
    const takeActions = document.querySelector(".take-actions");
    const card = document.querySelector('[data-graph-eq-layer-card="mid"]');
    const workflow = card?.querySelector(".graph-eq-workflow");
    const inspector = card?.querySelector("[data-graph-eq-selected-inspector]");
    const bandManager = card?.querySelector(".graph-eq-band-manager");
    const body = document.documentElement;
    const rect = (node) => {
      const box = node?.getBoundingClientRect();
      return box
        ? { width: box.width, left: box.left, right: box.right, top: box.top, bottom: box.bottom }
        : null;
    };
    return {
      hasHorizontalOverflow: body.scrollWidth > window.innerWidth + 2,
      dashboardColumns: dashboard ? getComputedStyle(dashboard).gridTemplateColumns : "",
      mainWorkspace: rect(mainWorkspace),
      playbackPanel: rect(playbackPanel),
      voiceCapturePanel: rect(voiceCapturePanel),
      playbackActions: rect(playbackActions),
      takeActions: rect(takeActions),
      workflowColumns: getComputedStyle(workflow).gridTemplateColumns,
      inspector: rect(inspector),
      bandManager: rect(bandManager),
    };
  });
  expect(layout.hasHorizontalOverflow).toBe(false);
  expect(layout.dashboardColumns.split(" ").length).toBe(2);
  expect(layout.mainWorkspace.width).toBeGreaterThan(980);
  expect(layout.playbackPanel.left).toBeLessThan(layout.mainWorkspace.left);
  expect(layout.playbackActions.bottom).toBeLessThanOrEqual(900);
  expect(layout.voiceCapturePanel.left).toBeLessThan(layout.mainWorkspace.left);
  expect(layout.takeActions.bottom).toBeLessThanOrEqual(900);
  expect(layout.workflowColumns.split(" ").length).toBeGreaterThanOrEqual(2);
  expect(layout.inspector.width).toBeGreaterThan(280);
  expect(layout.bandManager.width).toBeGreaterThan(300);
});

test("docked Graph EQ layout keeps the core exhibition controls usable at 1280 by 800", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await openMixer(page);
  await page.evaluate(() => window.scrollTo(0, 0));

  await expect(firstGraphEqGraph(page)).toBeVisible();
  await expect(page.locator(".graph-eq-collapsed-summary")).toHaveCount(0);

  const layout = await page.evaluate(() => {
    const rect = (node) => {
      const box = node?.getBoundingClientRect();
      return box ? { width: box.width, left: box.left, right: box.right, top: box.top, bottom: box.bottom } : null;
    };
    return {
      hasHorizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 2,
      graph: rect(document.querySelector('[data-graph-eq-layer-card="mid"] .graph-eq-dsssp-surface svg')),
      playbackActions: rect(document.querySelector(".playback-actions")),
      takeActions: rect(document.querySelector(".take-actions")),
      liveStatus: rect(document.querySelector('[data-graph-eq-layer-card="mid"] .graph-eq-layer-card-status')),
    };
  });

  expect(layout.hasHorizontalOverflow).toBe(false);
  expect(layout.graph.width).toBeGreaterThan(720);
  expect(layout.graph.top).toBeLessThan(500);
  expect(layout.playbackActions.bottom).toBeLessThanOrEqual(800);
  expect(layout.takeActions.bottom).toBeLessThanOrEqual(800);
  expect(layout.liveStatus.top).toBeLessThan(layout.graph.top);
  expect(layout.liveStatus.bottom).toBeLessThan(500);
});

test("docked Graph EQ layout stays usable at mobile width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await openFirstGraphEq(page);
  await selectGraphEqBand(page, 1);
  await firstGraphEqCard(page).evaluate((node) => node.scrollIntoView({ block: "start", inline: "nearest" }));

  const graphBox = await viewportBox(firstGraphEqGraph(page));
  expect(graphBox.width).toBeGreaterThan(250);
  expect(graphBox.height).toBeGreaterThan(120);
  expect(graphBox.height).toBeLessThan(190);

  const layout = await page.evaluate(() => {
    const card = document.querySelector('[data-graph-eq-layer-card="mid"]');
    const workflow = card?.querySelector(".graph-eq-workflow");
    const deleteButton = card?.querySelector('[data-graph-eq-action="delete-point"]');
    const addButton = card?.querySelector('[data-graph-eq-action="add-point"]');
    const rect = (node) => {
      const box = node?.getBoundingClientRect();
      return box ? { width: box.width, left: box.left, right: box.right } : null;
    };
    return {
      hasHorizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 2,
      workflowColumns: workflow ? getComputedStyle(workflow).gridTemplateColumns : "",
      card: rect(card),
      deleteButton: rect(deleteButton),
      addButton: rect(addButton),
    };
  });

  expect(layout.hasHorizontalOverflow).toBe(false);
  expect(layout.workflowColumns.split(" ").length).toBe(1);
  expect(layout.card.left).toBeGreaterThanOrEqual(0);
  expect(layout.card.right).toBeLessThanOrEqual(390);
  expect(layout.deleteButton.width).toBeLessThan(96);
  expect(layout.addButton.width).toBeLessThan(96);
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
  await selectGraphEqBand(page, 0);
  await expect(selectedPointControl(page, "gain")).toHaveValue(/6(\.0)?/);
  await expect(firstGraphEqGraph(page)).toBeVisible();
});

test("stale Graph EQ save response does not overwrite the rendered selected band", async ({ page }) => {
  await openFirstGraphEq(page);

  await selectGraphEqBand(page, 1);
  const before = await page.request.get(stateUrl).then((response) => response.json());
  const activeSettings = JSON.parse(JSON.stringify(before.settings.active));
  const gainInput = selectedPointControl(page, "gain");
  const freqInput = selectedPointControl(page, "freq");

  const pendingDraftSaves = [];
  await page.route("**/api/settings/draft", async (route) => {
    const draft = route.request().postDataJSON();
    await new Promise((resolve) => {
      pendingDraftSaves.push({ draft, resolve });
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        settings: {
          active: activeSettings,
          draft,
        },
      }),
    });
  });

  await gainInput.fill("1");
  await gainInput.blur();
  await expect.poll(() => pendingDraftSaves.length).toBe(1);

  await gainInput.fill("7");
  await gainInput.blur();
  await expect.poll(() => pendingDraftSaves.length).toBe(2);

  expect(pendingDraftSaves[0].draft.layers.mid.eq.points[1].gain_db).toBe(1);
  expect(pendingDraftSaves[1].draft.layers.mid.eq.points[1].gain_db).toBe(7);

  pendingDraftSaves[1].resolve();
  await expect.poll(async () => Number(await gainInput.inputValue())).toBe(7);
  await expect(freqInput).toHaveValue("1200");

  pendingDraftSaves[0].resolve();
  await expect.poll(async () => Number(await gainInput.inputValue())).toBe(7);
  await expect(freqInput).toHaveValue("1200");
  await expect(selectedInspector(page)).toHaveAttribute("data-graph-eq-point-id", "custom-mid");
});

test("Graph EQ add delete and max eight constraints keep shelves fixed", async ({ page }) => {
  await openFirstGraphEq(page);

  const add = firstGraphEqCard(page).locator('[data-graph-eq-action="add-point"]');
  await add.click();
  await expect(selectedPointControl(page, "q")).toHaveValue("1.4");

  for (let index = 0; index < 9; index += 1) {
    if (await add.isDisabled()) break;
    await add.click();
  }

  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]")).toHaveCount(8);
  await expect(firstGraphEqCard(page).locator(".graph-eq-band-list .graph-eq-band-number"))
    .toHaveText(["", "1", "2", "3", "4", "5", "6", ""]);

  await selectGraphEqBand(page, 0);
  await expect(selectedInspector(page).locator("[data-graph-eq-point-type]")).toBeDisabled();
  await expect(selectedInspector(page).locator('[data-graph-eq-action="delete-point"]')).toHaveCount(0);

  await selectGraphEqBand(page, 1);
  await expect(selectedInspector(page).locator("[data-graph-eq-point-type]")).toHaveValue("bell");
  await selectedInspector(page).locator('[data-graph-eq-action="delete-point"]').click();
  await expect(firstGraphEqCard(page).locator("[data-graph-eq-point-row]")).toHaveCount(7);
  await expect(firstGraphEqCard(page).locator(".graph-eq-band-list .graph-eq-band-number"))
    .toHaveText(["", "1", "2", "3", "4", "5", ""]);
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
  await expect(firstLayerCard(page)).toHaveClass(/feedback-pending/);
  await expect(firstLayerCard(page).locator(".feedback-spinner")).toBeHidden();
  await expect(firstGraphEqCard(page).locator(".graph-eq-layer-card-status"))
    .toContainText("Apply and Restart 대기 중");
  await expect(firstGraphEqCard(page).locator(".graph-eq-layer-card-detail"))
    .toContainText("재생에는 아직 반영되지 않았습니다");
});

test("Live Graph EQ highlight stays pending after save until render state catches up", async ({ page }) => {
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

  await expect(firstLayerCard(page)).toHaveClass(/feedback-pending/);
  await expect(firstLayerCard(page).locator(".feedback-spinner")).toBeVisible();
  await expect(firstGraphEqCard(page).locator(".graph-eq-layer-card-status"))
    .toContainText("Live Graph EQ 적용 대기 중");
  await expect(firstGraphEqCard(page).locator(".graph-eq-layer-card-status"))
    .toContainText("Live Graph EQ 적용됨");
  await expect(firstLayerCard(page)).not.toHaveClass(/feedback-pending/);
  await expect(firstLayerCard(page).locator(".feedback-spinner")).toBeHidden();
});

test("Live Graph EQ failure keeps visible draft value instead of snapping back", async ({ page }) => {
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.__liveGraphEqTickFailures = 0;
    window.fetch = async (input, init) => {
      const rawUrl = typeof input === "string" ? input : input?.url;
      const url = rawUrl ? new URL(rawUrl, window.location.href) : null;
      if (url?.pathname === "/api/playback/live-graph-eq/tick") {
        window.__liveGraphEqTickFailures += 1;
        return new Response(JSON.stringify({ detail: "forced live graph eq failure" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        });
      }
      return originalFetch(input, init);
    };
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
  await expect.poll(
    async () => page.evaluate(() => window.__liveGraphEqTickFailures || 0),
  ).toBeGreaterThan(0);
  await expect.poll(async () => Number(await gainInput.inputValue())).toBe(targetGain);
  await expect(firstGraphEqCard(page).locator(".graph-eq-layer-card-status"))
    .toContainText("Live Graph EQ 적용 상태를 확인하지 못했습니다");
  await expect(firstLayerCard(page)).not.toHaveClass(/feedback-pending/);
  await expect(firstLayerCard(page).locator(".feedback-spinner")).toBeHidden();

  const after = await page.request.get(stateUrl).then((response) => response.json());
  expect(after.settings.draft.layers.mid.eq.points[1].gain_db).toBe(targetGain);
});
