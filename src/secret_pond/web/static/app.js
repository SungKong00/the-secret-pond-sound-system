const api = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Request failed: ${response.status}`);
  }
  return payload;
};

const state = {
  snapshot: null,
  draft: null,
  devices: null,
  deviceError: null,
  saveTimer: null,
  spaceRecording: false,
};

const $ = (id) => document.getElementById(id);

const layerLabels = {
  low: "Low Drone",
  mid: "Mid Beam",
  voice: "Voice Stack",
};

const layerControlDefs = [
  ["volume_db", "Volume", -60, 6, 0.5, " dB"],
  ["eq.low_gain_db", "Low EQ", -18, 12, 0.5, " dB"],
  ["eq.mid_gain_db", "Mid EQ", -18, 12, 0.5, " dB"],
  ["eq.high_gain_db", "High EQ", -18, 12, 0.5, " dB"],
  ["eq.highpass_hz", "High-pass", 20, 950, 1, " Hz"],
  ["eq.lowpass_hz", "Low-pass", 1200, 20000, 10, " Hz"],
];

const recordingControlDefs = [
  ["gain_db", "Input gain", -60, 24, 0.5, " dB"],
  ["normalize_peak", "Normalize peak", 0.05, 1, 0.01, ""],
  ["highpass_hz", "High-pass", 20, 950, 1, " Hz"],
  ["lowpass_hz", "Low-pass", 1200, 20000, 10, " Hz"],
  ["presence_gain_db", "Presence", -18, 12, 0.5, " dB"],
  ["reverb_mix", "Reverb", 0, 1, 0.01, ""],
  ["delay_mix", "Delay", 0, 1, 0.01, ""],
  ["fade_ms", "Fade", 0, 5000, 10, " ms"],
];

const formatValue = (value, suffix) => {
  const number = Number(value);
  const rounded = Number.isInteger(number) ? number.toString() : number.toFixed(2);
  return `${rounded}${suffix}`;
};

const getPath = (object, path) =>
  path.split(".").reduce((current, segment) => current[segment], object);

const setPath = (object, path, value) => {
  const segments = path.split(".");
  const last = segments.pop();
  const target = segments.reduce((current, segment) => current[segment], object);
  target[last] = value;
};

const clone = (value) => JSON.parse(JSON.stringify(value));

const showError = (message) => {
  const banner = $("errorBanner");
  if (!message) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }
  banner.hidden = false;
  banner.textContent = message;
};

const requestState = async () => {
  const payload = await api("/api/state");
  applyState(payload);
};

const requestDevices = async () => {
  try {
    state.devices = await api("/api/devices");
    state.deviceError = null;
  } catch (error) {
    state.devices = null;
    state.deviceError = error.message;
  }
  renderDevices();
  renderErrors();
};

const refreshAll = async () => {
  await requestState().catch((error) => showError(error.message));
  await requestDevices();
};

const applyState = (payload) => {
  state.snapshot = payload;
  state.draft = clone(payload.settings.draft);
  renderState();
  renderControls();
  renderDevices();
};

const renderState = () => {
  const snapshot = state.snapshot;
  if (!snapshot) return;

  $("armedBadge").textContent = snapshot.armed ? "Armed" : "Disarmed";
  $("armedBadge").className = `status-pill ${snapshot.armed ? "safe" : "muted"}`;
  $("recordingBadge").textContent = snapshot.is_recording ? "Recording" : "Idle";
  $("recordingBadge").className = `status-pill ${snapshot.is_recording ? "hot" : ""}`;
  $("outputBadge").textContent = snapshot.playback.output_running ? "Output Live" : "Output Off";
  $("outputBadge").className = `status-pill ${snapshot.playback.output_running ? "safe" : "muted"}`;
  $("participantCount").textContent = snapshot.participant_count;
  $("elapsedTime").textContent = `${snapshot.recording_elapsed_seconds.toFixed(1)}s`;
  $("remainingTime").textContent =
    `${snapshot.recording_remaining_seconds.toFixed(1)}s remaining`;
  $("recordCoreStatus").textContent = snapshot.is_recording
    ? "Capturing"
    : snapshot.armed
      ? "Armed"
      : "Safe";
  document.querySelector(".record-core").classList.toggle("recording", snapshot.is_recording);
  $("pendingBadge").textContent = hasPendingChanges(snapshot) ? "Pending changes" : "No pending changes";
  $("pendingBadge").className = `status-pill ${hasPendingChanges(snapshot) ? "hot" : "muted"}`;
  $("startButton").disabled = !snapshot.armed || snapshot.is_recording;
  $("stopButton").disabled = !snapshot.is_recording;
  $("startOutputButton").disabled = snapshot.playback.output_running;
  $("stopOutputButton").disabled = !snapshot.playback.output_running;
  const deviceChanges = hasDraftDeviceChanges(snapshot);
  $("applyButton").disabled = snapshot.playback.output_running || deviceChanges;
  $("applyButton").title = snapshot.playback.output_running
    ? "Stop output before applying staged settings."
    : deviceChanges
      ? "Restart the app to use staged device changes."
      : "";
  renderErrors();
};

const renderErrors = () => {
  const snapshot = state.snapshot;
  const messages = [
    snapshot?.last_error,
    snapshot?.playback.output_latest_error,
    state.deviceError,
  ].filter(Boolean);
  showError(messages.join(" · "));
};

const renderDevices = () => {
  const devices = state.devices;
  if (!devices) {
    $("inputDeviceName").textContent = state.deviceError ? "Unavailable" : "Checking...";
    $("outputDeviceName").textContent = state.deviceError ? "Unavailable" : "Checking...";
    renderDeviceSelect("inputDeviceSelect", [], null);
    renderDeviceSelect("outputDeviceSelect", [], null);
    $("deviceRestartNotice").textContent = state.deviceError
      ? "Audio devices are unavailable."
      : "Checking audio devices...";
    $("deviceWarnings").innerHTML = "";
    return;
  }

  $("inputDeviceName").textContent = devices.selected_input_device?.name || "No input device";
  $("outputDeviceName").textContent = devices.selected_output_device?.name || "No output device";
  renderDeviceSelect(
    "inputDeviceSelect",
    devices.input_devices,
    state.draft?.devices.input_device_id ?? null,
  );
  renderDeviceSelect(
    "outputDeviceSelect",
    devices.output_devices,
    state.draft?.devices.output_device_id ?? null,
    Boolean(state.snapshot?.playback.output_running),
  );
  renderDeviceRestartNotice();
  const warningList = $("deviceWarnings");
  warningList.innerHTML = "";
  devices.warnings.forEach((warning) => {
    const item = document.createElement("li");
    item.textContent = warning;
    warningList.appendChild(item);
  });
};

const renderDeviceSelect = (selectId, devices, selectedId, forceDisabled = false) => {
  const select = $(selectId);
  select.innerHTML = "";
  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = "System default";
  select.appendChild(defaultOption);

  devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.id;
    option.textContent = `${device.name} (${device.default_sample_rate || "unknown"} Hz)`;
    select.appendChild(option);
  });

  if (selectedId && !devices.some((device) => device.id === selectedId)) {
    const missingOption = document.createElement("option");
    missingOption.value = selectedId;
    missingOption.textContent = `Unavailable: ${selectedId}`;
    select.appendChild(missingOption);
  }

  select.value = selectedId || "";
  select.disabled = forceDisabled || !state.draft || !state.devices;
};

const renderDeviceRestartNotice = () => {
  const outputRunning = Boolean(state.snapshot?.playback.output_running);
  const changed = hasDraftDeviceChanges();
  if (outputRunning) {
    $("deviceRestartNotice").textContent = "Stop Output before changing output device.";
  } else if (changed) {
    $("deviceRestartNotice").textContent = "Device changes are staged. Restart the app to use them.";
  } else {
    $("deviceRestartNotice").textContent = "Device changes require app restart.";
  }
};

const hasDraftDeviceChanges = (snapshot = state.snapshot) => {
  if (!snapshot || !state.draft) return false;
  return (
    snapshot.settings.active.devices.input_device_id !== state.draft.devices.input_device_id ||
    snapshot.settings.active.devices.output_device_id !== state.draft.devices.output_device_id
  );
};

const hasPendingChanges = (snapshot) =>
  JSON.stringify(snapshot.settings.active) !== JSON.stringify(snapshot.settings.draft);

const renderControls = () => {
  if (!state.draft) return;
  renderLayerControls();
  renderRecordingControls();
};

const renderLayerControls = () => {
  const container = $("layerControls");
  container.innerHTML = "";
  Object.keys(layerLabels).forEach((layerId) => {
    const layer = state.draft.layers[layerId];
    const card = document.createElement("section");
    card.className = "layer-card";
    card.innerHTML = `
      <div class="layer-head">
        <h3 class="layer-title">${layerLabels[layerId]}</h3>
        <input type="checkbox" aria-label="${layerLabels[layerId]} enabled" ${
          layer.enabled ? "checked" : ""
        } />
      </div>
      <div class="layer-controls"></div>
    `;
    card.querySelector("input[type='checkbox']").addEventListener("change", (event) => {
      state.draft.layers[layerId].enabled = event.target.checked;
      scheduleDraftSave();
    });

    const controls = card.querySelector(".layer-controls");
    layerControlDefs.forEach(([path, label, min, max, step, suffix]) => {
      controls.appendChild(
        rangeControl(label, getPath(layer, path), min, max, step, suffix, (value) => {
          setPath(state.draft.layers[layerId], path, value);
          scheduleDraftSave();
        }),
      );
    });
    container.appendChild(card);
  });
};

const renderRecordingControls = () => {
  const container = $("recordingControls");
  container.innerHTML = "";
  recordingControlDefs.forEach(([path, label, min, max, step, suffix]) => {
    container.appendChild(
      rangeControl(label, getPath(state.draft.recording, path), min, max, step, suffix, (value) => {
        setPath(state.draft.recording, path, value);
        scheduleDraftSave();
      }),
    );
  });
};

const rangeControl = (label, value, min, max, step, suffix, onInput) => {
  const row = document.createElement("div");
  row.className = "control-row";
  const safeId = `control-${label.toLowerCase().replaceAll(" ", "-")}-${Math.random()
    .toString(16)
    .slice(2)}`;
  row.innerHTML = `
    <label for="${safeId}">${label}</label>
    <input id="${safeId}" type="range" min="${min}" max="${max}" step="${step}" value="${value}" />
    <span class="value">${formatValue(value, suffix)}</span>
  `;
  const input = row.querySelector("input");
  const output = row.querySelector(".value");
  input.addEventListener("input", () => {
    const numericValue = Number(input.value);
    output.textContent = formatValue(numericValue, suffix);
    onInput(numericValue);
  });
  return row;
};

const scheduleDraftSave = () => {
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => {
    saveDraft().catch(() => {});
  }, 280);
};

const saveDraft = async () => {
  if (!state.draft) return;
  try {
    const payload = await api("/api/settings/draft", {
      method: "PUT",
      body: JSON.stringify(state.draft),
    });
    state.snapshot.settings = payload.settings;
    state.draft = clone(payload.settings.draft);
    renderState();
    renderDevices();
  } catch (error) {
    showError(error.message);
    throw error;
  }
};

const control = async (path) => {
  try {
    const payload = await api(path, { method: "POST" });
    if (payload.state) {
      applyState(payload.state);
    } else {
      await requestState();
    }
  } catch (error) {
    showError(error.message);
  }
};

const applyAndRestart = async () => {
  try {
    await saveDraft();
    const payload = await api("/api/settings/apply-and-restart", { method: "POST" });
    applyState(payload.state);
  } catch (error) {
    showError(error.message);
  }
};

const resetDraft = async () => {
  try {
    const payload = await api("/api/settings/reset", { method: "POST" });
    state.snapshot.settings = payload.settings;
    state.draft = clone(payload.settings.draft);
    renderState();
    renderControls();
    renderDevices();
  } catch (error) {
    showError(error.message);
  }
};

const changeDraftDevice = (key, value) => {
  if (!state.draft) return;
  state.draft.devices[key] = value || null;
  renderState();
  renderDevices();
  scheduleDraftSave();
};

const shouldIgnoreSpace = () => {
  const element = document.activeElement;
  if (!element) return false;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName);
};

const releaseButtonFocusForSpace = () => {
  const element = document.activeElement;
  if (element?.tagName === "BUTTON") {
    element.blur();
  }
};

const startFromSpace = async (event) => {
  if (event.code !== "Space" || event.repeat || shouldIgnoreSpace()) return;
  releaseButtonFocusForSpace();
  event.preventDefault();
  if (!state.snapshot?.armed || state.snapshot?.is_recording) return;
  state.spaceRecording = true;
  await control("/api/recording/start");
};

const stopFromSpace = async (event) => {
  if (event.code !== "Space" || shouldIgnoreSpace()) return;
  releaseButtonFocusForSpace();
  event.preventDefault();
  if (!state.spaceRecording && !state.snapshot?.is_recording) return;
  state.spaceRecording = false;
  await control("/api/recording/stop");
};

const stopIfRecording = async () => {
  if (!state.snapshot?.is_recording) return;
  state.spaceRecording = false;
  await control("/api/recording/stop");
};

const drawCanvas = () => {
  const canvas = $("pondCanvas");
  const context = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const resize = () => {
    canvas.width = Math.floor(window.innerWidth * ratio);
    canvas.height = Math.floor(window.innerHeight * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  };
  window.addEventListener("resize", resize);
  resize();

  let frame = 0;
  const draw = () => {
    frame += 0.018;
    context.clearRect(0, 0, window.innerWidth, window.innerHeight);
    const active = state.snapshot?.is_recording ? 1 : state.snapshot?.armed ? 0.55 : 0.25;
    const centerY = window.innerHeight * 0.54;
    for (let line = 0; line < 8; line += 1) {
      context.beginPath();
      const color = line % 2 === 0 ? "101, 247, 255" : "255, 79, 216";
      context.strokeStyle = `rgba(${color}, ${0.12 + active * 0.05})`;
      context.lineWidth = 1;
      for (let x = 0; x <= window.innerWidth; x += 12) {
        const wave =
          Math.sin(x * 0.012 + frame + line * 0.7) *
          (18 + active * 18) *
          Math.sin(frame * 0.8 + line);
        const y = centerY + (line - 3.5) * 42 + wave;
        if (x === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      }
      context.stroke();
    }
    requestAnimationFrame(draw);
  };
  draw();
};

const bindEvents = () => {
  $("armButton").addEventListener("click", () => control("/api/input/arm"));
  $("disarmButton").addEventListener("click", () => control("/api/input/disarm"));
  $("startButton").addEventListener("click", () => control("/api/recording/start"));
  $("stopButton").addEventListener("click", () => control("/api/recording/stop"));
  $("startOutputButton").addEventListener("click", () => control("/api/playback/start"));
  $("stopOutputButton").addEventListener("click", () => control("/api/playback/stop"));
  $("refreshButton").addEventListener("click", refreshAll);
  $("applyButton").addEventListener("click", applyAndRestart);
  $("resetButton").addEventListener("click", resetDraft);
  $("inputDeviceSelect").addEventListener("change", (event) => {
    changeDraftDevice("input_device_id", event.target.value);
  });
  $("outputDeviceSelect").addEventListener("change", (event) => {
    changeDraftDevice("output_device_id", event.target.value);
  });
  document.addEventListener("keydown", startFromSpace);
  document.addEventListener("keyup", stopFromSpace);
  window.addEventListener("blur", stopIfRecording);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopIfRecording();
  });
  setInterval(async () => {
    if (state.snapshot?.is_recording) {
      await control("/api/recording/poll-auto-stop");
    } else {
      await requestState().catch(() => {});
    }
  }, 900);
};

bindEvents();
drawCanvas();
refreshAll();
