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
  diagnostics: null,
  deviceError: null,
  diagnosticsError: null,
  saveTimer: null,
  spaceRecording: false,
  stateSocket: null,
  websocketConnected: false,
  websocketReconnectTimer: null,
  recordingStartInFlight: false,
  recordingStopRequestedAfterStart: false,
  recordingStopInFlight: false,
  applyInFlight: false,
};

const $ = (id) => document.getElementById(id);

const layerLabels = {
  low: "Low Drone",
  mid: "Mid Beam",
  voice: "Voice Stack",
};

const modeLabels = {
  "live_ephemeral": "Mode Live",
  "test_library": "Mode Test",
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

const recordingPresetDefs = {
  Soft: {
    gain_db: -3.0,
    normalize_peak: 0.3,
    highpass_hz: 80.0,
    lowpass_hz: 9000.0,
    presence_gain_db: -4.0,
    reverb_mix: 0.18,
    delay_mix: 0.0,
    fade_ms: 80,
  },
  Misty: {
    gain_db: -1.0,
    normalize_peak: 0.32,
    highpass_hz: 90.0,
    lowpass_hz: 7000.0,
    presence_gain_db: -5.0,
    reverb_mix: 0.45,
    delay_mix: 0.12,
    fade_ms: 120,
  },
  Dense: {
    gain_db: 1.5,
    normalize_peak: 0.45,
    highpass_hz: 120.0,
    lowpass_hz: 6500.0,
    presence_gain_db: -2.0,
    reverb_mix: 0.3,
    delay_mix: 0.08,
    fade_ms: 60,
  },
  "Clearer Voice": {
    gain_db: 0.0,
    normalize_peak: 0.4,
    highpass_hz: 140.0,
    lowpass_hz: 10000.0,
    presence_gain_db: 3.0,
    reverb_mix: 0.12,
    delay_mix: 0.0,
    fade_ms: 40,
  },
};

const formatValue = (value, suffix) => {
  const number = Number(value);
  const rounded = Number.isInteger(number) ? number.toString() : number.toFixed(2);
  return `${rounded}${suffix}`;
};

const formatSeconds = (value) => `${Number(value).toFixed(1)}s`;

const formatBytes = (bytes) => {
  const number = Number(bytes);
  if (!Number.isFinite(number) || number <= 0) return "0 B";
  if (number < 1024) return `${number} B`;
  if (number < 1024 * 1024) return `${(number / 1024).toFixed(1)} KB`;
  return `${(number / (1024 * 1024)).toFixed(1)} MB`;
};

const formatTimestamp = (value) => {
  if (!value) return "No timestamp";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
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

const renderErrorBadge = (message) => {
  if (message) {
    $("errorBadge").textContent = "Error Active";
    $("errorBadge").className = "status-pill hot";
  } else {
    $("errorBadge").textContent = "Error None";
    $("errorBadge").className = "status-pill muted";
  }
};

const replaceableRecordOutcomeKinds = new Set(["ready", "armed-ready", "recording", "processing"]);

const showError = (message) => {
  const banner = $("errorBanner");
  renderErrorBadge(message);
  if (!message) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }
  banner.hidden = false;
  banner.textContent = message;
};

const requestState = async (options = {}) => {
  const payload = await api("/api/state");
  applyState(payload, options);
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
  renderSystemStatus();
  renderErrors();
};

const requestDiagnostics = async () => {
  try {
    state.diagnostics = await api("/api/diagnostics");
    state.diagnosticsError = null;
  } catch (error) {
    state.diagnostics = null;
    state.diagnosticsError = error.message;
  }
  renderLastEventBadge();
  renderSystemStatus();
  renderErrors();
};

const refreshAll = async () => {
  await requestState().catch((error) => showError(error.message));
  await requestDevices();
  await requestDiagnostics();
};

const applyState = (payload, options = {}) => {
  const syncDraft = options.syncDraft ?? true;
  state.snapshot = payload;
  if (syncDraft || !state.draft) {
    state.draft = clone(payload.settings.draft);
    renderControls();
  } else {
    state.snapshot.settings.draft = clone(state.draft);
  }
  renderState();
  renderDevices();
  renderSystemStatus();
};

const renderSyncBadge = () => {
  if (!("WebSocket" in window)) {
    $("syncBadge").textContent = "Sync Polling";
    $("syncBadge").className = "status-pill muted";
  } else if (state.websocketConnected) {
    $("syncBadge").textContent = "Sync Live";
    $("syncBadge").className = "status-pill safe";
  } else if (state.stateSocket) {
    $("syncBadge").textContent = "Sync Connecting";
    $("syncBadge").className = "status-pill muted";
  } else {
    $("syncBadge").textContent = "Sync Polling";
    $("syncBadge").className = "status-pill muted";
  }
};

const renderState = () => {
  renderSyncBadge();
  const snapshot = state.snapshot;
  if (!snapshot) return;
  const recordingStopBusy = state.recordingStopInFlight;
  const captureReady = snapshot.armed && !snapshot.is_recording && !recordingStopBusy;

  $("armedBadge").textContent = snapshot.armed ? "Armed" : "Disarmed";
  $("armedBadge").className = `status-pill ${snapshot.armed ? "safe" : "muted"}`;
  $("recordingBadge").textContent = snapshot.is_recording ? "Recording" : "Idle";
  $("recordingBadge").className = `status-pill ${snapshot.is_recording ? "hot" : ""}`;
  $("outputBadge").textContent = snapshot.playback.output_running ? "Output Live" : "Output Off";
  $("outputBadge").className = `status-pill ${snapshot.playback.output_running ? "safe" : "muted"}`;
  renderModeBadge(snapshot.settings.active.voice_stack.mode);
  $("participantCount").textContent = snapshot.participant_count;
  $("elapsedTime").textContent = `${snapshot.recording_elapsed_seconds.toFixed(1)}s`;
  $("remainingTime").textContent =
    `${snapshot.recording_remaining_seconds.toFixed(1)}s remaining`;
  $("minimumRecordingTime").textContent = formatSeconds(
    snapshot.settings.active.input_control.minimum_recording_seconds,
  );
  $("maximumRecordingTime").textContent = formatSeconds(
    snapshot.settings.active.input_control.maximum_recording_seconds,
  );
  $("recordCoreStatus").textContent = recordingStopBusy
    ? "Processing"
    : snapshot.is_recording
      ? "Capturing"
      : snapshot.armed
        ? "Armed"
        : "Safe";
  document.querySelector(".record-core").classList.toggle("armed", captureReady);
  document.querySelector(".record-core").classList.toggle("recording", snapshot.is_recording);
  renderRecordReadiness(snapshot, recordingStopBusy);
  $("pendingBadge").textContent = hasPendingChanges(snapshot)
    ? "Unsaved audio changes"
    : "No unsaved changes";
  $("pendingBadge").className = `status-pill ${hasPendingChanges(snapshot) ? "hot" : "muted"}`;
  $("outputControlSummary").textContent = state.applyInFlight
    ? "Rendering staged audio settings."
    : snapshot.playback.output_running
      ? "Output stream is live."
      : hasPendingChanges(snapshot)
        ? "Unsaved audio changes are staged for Apply and Restart."
        : "Render staged audio, then start output.";
  $("armButton").disabled = recordingStopBusy || snapshot.armed || snapshot.is_recording;
  $("disarmButton").disabled =
    recordingStopBusy || (!snapshot.armed && !snapshot.is_recording);
  $("startButton").disabled = recordingStopBusy || !snapshot.armed || snapshot.is_recording;
  $("stopButton").disabled = recordingStopBusy || !snapshot.is_recording;
  $("startOutputButton").disabled = snapshot.playback.output_running;
  $("stopOutputButton").disabled = !snapshot.playback.output_running;
  $("restartOutputButton").disabled = !snapshot.playback.output_running;
  $("armButton").setAttribute("aria-pressed", snapshot.armed ? "true" : "false");
  $("disarmButton").setAttribute("aria-pressed", snapshot.armed ? "false" : "true");
  const runtimeConfigChanges = hasDraftRuntimeConfigChanges(snapshot);
  $("applyButton").disabled =
    state.applyInFlight || recordingStopBusy || snapshot.is_recording || runtimeConfigChanges;
  $("applyButton").textContent = state.applyInFlight ? "Applying..." : "Apply and Restart";
  $("resetButton").disabled = state.applyInFlight || snapshot.is_recording;
  $("resetButton").title = snapshot.is_recording
    ? "Stop recording before resetting draft settings."
    : "";
  $("resetParticipantsButton").disabled = state.applyInFlight || snapshot.is_recording;
  $("resetParticipantsButton").title = snapshot.is_recording
    ? "Stop recording before resetting participant count."
    : "";
  $("applyButton").title = recordingStopBusy
    ? "Wait for recording processing to finish."
    : snapshot.is_recording
      ? "Stop recording before applying staged settings."
      : state.applyInFlight
        ? "Rendering and reloading staged audio settings."
        : runtimeConfigChanges
          ? "Restart the app to use staged device changes."
          : snapshot.playback.output_running
            ? "Will stop and restart output while applying staged audio settings."
            : "";
  renderErrors();
};

const recordOutcomeKind = () => {
  const className = $("recordOutcomeStatus").parentElement.className;
  return className.split(/\s+/).find((name) => replaceableRecordOutcomeKinds.has(name));
};

const renderRecordReadiness = (snapshot, recordingStopBusy) => {
  if (recordingStopBusy) {
    setRecordStatus("processing", "Processing recording...");
  } else if (snapshot.is_recording) {
    setRecordStatus("recording", "Recording", "Release Space to stop.");
  } else if (!replaceableRecordOutcomeKinds.has(recordOutcomeKind())) {
    return;
  } else if (snapshot.armed) {
    setRecordStatus("armed-ready", "Hold Space to Record", "Release Space to stop recording.");
  } else {
    setRecordStatus("ready", "Ready", "Arm capture before holding Space.");
  }
};

const renderModeBadge = (mode) => {
  $("modeBadge").textContent = modeLabels[mode] || "Mode Unknown";
  $("modeBadge").className = `status-pill ${mode === "live_ephemeral" ? "safe" : "muted"}`;
};

const renderLastEventBadge = () => {
  const lastEvent = state.diagnostics?.events?.recent?.[0];
  if (state.diagnosticsError || state.diagnostics?.events?.error) {
    $("lastEventBadge").textContent = "Last Event Unavailable";
    $("lastEventBadge").className = "status-pill hot";
  } else if (lastEvent?.event_type) {
    $("lastEventBadge").textContent = `Last ${lastEvent.event_type}`;
    $("lastEventBadge").className = "status-pill";
  } else {
    $("lastEventBadge").textContent = "Last Event None";
    $("lastEventBadge").className = "status-pill muted";
  }
};

const setRecordStatus = (kind, label, detail = "") => {
  const container = $("recordOutcomeStatus").parentElement;
  const nextClassName = `record-outcome ${kind}`;
  if (container.className !== nextClassName) container.className = nextClassName;
  if ($("recordOutcomeStatus").textContent !== label) $("recordOutcomeStatus").textContent = label;
  if ($("recordOutcomeDetail").textContent !== detail) $("recordOutcomeDetail").textContent = detail;
};

const renderRecordingOutcome = (outcome) => {
  if (!outcome) return;
  const duration = `${Number(outcome.duration_seconds || 0).toFixed(1)}s`;
  if (outcome.accepted) {
    const participant = outcome.participant_count
      ? `Participant ${outcome.participant_count}`
      : "Participant count unchanged";
    setRecordStatus("added", "Recording Added", `${participant} · ${duration}`);
  } else if (outcome.reason === "too_short") {
    setRecordStatus("discarded", "Too Short", `${duration} captured. Minimum not met.`);
  } else if (outcome.reason === "empty") {
    setRecordStatus("discarded", "Empty Recording", `${duration} captured.`);
  } else if (outcome.reason === "disarmed") {
    setRecordStatus("discarded", "Recording Disarmed", `${duration} captured.`);
  } else {
    setRecordStatus("discarded", "Recording Discarded", outcome.reason || duration);
  }
};

const currentErrorMessages = () => {
  const snapshot = state.snapshot;
  return [
    snapshot?.last_error,
    snapshot?.playback.output_latest_error,
    state.deviceError,
    state.diagnosticsError,
  ].filter(Boolean);
};

const renderErrors = () => {
  const messages = currentErrorMessages();
  showError(messages.join(" · "));
};

const renderDevices = () => {
  const devices = state.devices;
  renderDeviceHealthBadge();
  if (!devices) {
    $("inputDeviceName").textContent = state.deviceError ? "Unavailable" : "Checking...";
    $("outputDeviceName").textContent = state.deviceError ? "Unavailable" : "Checking...";
    renderDeviceSelect("inputDeviceSelect", [], null);
    renderDeviceSelect("outputDeviceSelect", [], null);
    $("deviceRestartNotice").textContent = state.deviceError
      ? "Audio devices are unavailable."
      : "Checking audio devices...";
    $("deviceWarnings").innerHTML = "";
    renderSystemStatus();
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
  renderSystemStatus();
};

const renderDeviceHealthBadge = () => {
  if (state.deviceError) {
    $("deviceHealthBadge").textContent = "Devices Offline";
    $("deviceHealthBadge").className = "status-pill hot";
  } else if (!state.devices) {
    $("deviceHealthBadge").textContent = "Devices Checking";
    $("deviceHealthBadge").className = "status-pill muted";
  } else if (state.devices.warnings.length) {
    $("deviceHealthBadge").textContent = "Device Warning";
    $("deviceHealthBadge").className = "status-pill hot";
  } else {
    $("deviceHealthBadge").textContent = "Devices OK";
    $("deviceHealthBadge").className = "status-pill safe";
  }
};

const renderSystemStatus = () => {
  renderSystemDevices();

  if (!state.diagnostics) {
    $("systemStatus").textContent = state.diagnosticsError ? "Diagnostics offline" : "Checking";
    $("systemStatus").className = `status-pill ${state.diagnosticsError ? "hot" : "muted"}`;
    $("sourceHealthList").innerHTML = "";
    const placeholder = document.createElement("div");
    placeholder.className = "diagnostic-row";
    const label = document.createElement("span");
    label.textContent = "Files";
    const value = document.createElement("strong");
    value.textContent = state.diagnosticsError ? "Unavailable" : "Checking...";
    placeholder.append(label, value);
    $("sourceHealthList").appendChild(placeholder);
    renderEventLogSummary([]);
    return;
  }

  const missingSources = state.diagnostics.sources.filter((source) => !source.exists);
  $("systemStatus").textContent = missingSources.length
    ? `${missingSources.length} missing`
    : "Sources ready";
  $("systemStatus").className = `status-pill ${missingSources.length ? "hot" : "safe"}`;
  renderSourceHealthList(state.diagnostics.sources);
  renderEventLogSummary(state.diagnostics.events?.recent || [], state.diagnostics.events?.error);
};

const renderSystemDevices = () => {
  $("systemInputDeviceName").textContent = systemDeviceName(
    "selected_input_device",
    "No input device",
  );
  $("systemOutputDeviceName").textContent = systemDeviceName(
    "selected_output_device",
    "No output device",
  );
};

const systemDeviceName = (key, emptyLabel) => {
  if (state.deviceError) return "Unavailable";
  if (!state.devices) return "Checking...";
  return state.devices[key]?.name || emptyLabel;
};

const renderSourceHealthList = (sources) => {
  const container = $("sourceHealthList");
  container.innerHTML = "";
  sources.forEach((source) => {
    const row = document.createElement("div");
    row.className = `diagnostic-row source-row ${source.exists ? "source-ready" : "source-missing"}`;
    const label = document.createElement("span");
    label.textContent = source.label;
    const value = document.createElement("strong");
    value.textContent = source.exists
      ? `Ready · ${formatBytes(source.size_bytes)} · ${formatTimestamp(source.modified_at)}`
      : `Missing · ${source.path}`;
    row.append(label, value);
    container.appendChild(row);
  });
};

const renderEventLogSummary = (events, error = null) => {
  const list = $("eventLogSummary");
  list.innerHTML = "";
  if (error) {
    const item = document.createElement("li");
    item.className = "event-item event-error";
    item.textContent = error;
    list.appendChild(item);
    return;
  }
  if (!events.length) {
    const item = document.createElement("li");
    item.className = "event-item muted";
    item.textContent = "No events yet";
    list.appendChild(item);
    return;
  }
  events.forEach((event) => {
    const item = document.createElement("li");
    item.className = "event-item";
    const time = document.createElement("span");
    time.className = "event-time";
    time.textContent = formatTimestamp(event.timestamp);
    const label = document.createElement("strong");
    label.textContent = event.event_type || "event";
    item.append(time, label);
    list.appendChild(item);
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

const hasDraftRuntimeConfigChanges = (snapshot = state.snapshot) => {
  if (!snapshot || !state.draft) return false;
  return (
    snapshot.settings.active.audio.sample_rate !== state.draft.audio.sample_rate ||
    snapshot.settings.active.audio.channels !== state.draft.audio.channels ||
    snapshot.settings.active.devices.input_device_id !== state.draft.devices.input_device_id ||
    snapshot.settings.active.devices.output_device_id !== state.draft.devices.output_device_id
  );
};

const hasPendingChanges = (snapshot) =>
  JSON.stringify(snapshot.settings.active) !==
  JSON.stringify(state.draft || snapshot.settings.draft);

const hasLayerDraftChanges = (layerId) => {
  if (!state.snapshot || !state.draft) return false;
  return (
    JSON.stringify(state.snapshot.settings.active.layers[layerId]) !==
    JSON.stringify(state.draft.layers[layerId])
  );
};

const layerPendingBadge = (layerId) =>
  `<span class="layer-status ${hasLayerDraftChanges(layerId) ? "pending" : ""}">${
    hasLayerDraftChanges(layerId) ? "Pending Draft" : "Active"
  }</span>`;

const updateLayerPendingBadge = (layerId, card) => {
  const badge = card.querySelector(".layer-status");
  const pending = hasLayerDraftChanges(layerId);
  badge.textContent = pending ? "Pending Draft" : "Active";
  badge.classList.toggle("pending", pending);
};

const renderControls = () => {
  if (!state.draft) return;
  renderLayerControls();
  renderRecordingPresets();
  renderRecordingControls();
};

const renderLayerControls = () => {
  renderLayerGroup("layerControls", ["low", "mid"]);
  renderLayerGroup("voiceLayerControls", ["voice"]);
};

const renderLayerGroup = (containerId, layerIds) => {
  const container = $(containerId);
  container.innerHTML = "";
  layerIds.forEach((layerId) => {
    container.appendChild(renderLayerCard(layerId));
  });
};

const renderLayerCard = (layerId) => {
  const layer = state.draft.layers[layerId];
  const activeLayer = state.snapshot?.settings.active.layers[layerId] || layer;
  const card = document.createElement("section");
  card.className = "layer-card";
  card.innerHTML = `
    <div class="layer-head">
      <h3 class="layer-title">${layerLabels[layerId]}</h3>
      <div class="layer-head-actions">
        ${layerPendingBadge(layerId)}
        <input type="checkbox" aria-label="${layerLabels[layerId]} enabled" ${
          layer.enabled ? "checked" : ""
        } />
      </div>
    </div>
    <div class="layer-controls"></div>
  `;
  card.querySelector("input[type='checkbox']").addEventListener("change", (event) => {
    state.draft.layers[layerId].enabled = event.target.checked;
    updateLayerPendingBadge(layerId, card);
    renderState();
    scheduleDraftSave();
  });

  const controls = card.querySelector(".layer-controls");
  layerControlDefs.forEach(([path, label, min, max, step, suffix]) => {
    controls.appendChild(
      rangeControl(
        label,
        getPath(layer, path),
        min,
        max,
        step,
        suffix,
        (value) => {
          setPath(state.draft.layers[layerId], path, value);
          updateLayerPendingBadge(layerId, card);
          renderState();
          scheduleDraftSave();
        },
        getPath(activeLayer, path),
      ),
    );
  });
  return card;
};

const renderRecordingControls = () => {
  const container = $("recordingControls");
  container.innerHTML = "";
  recordingControlDefs.forEach(([path, label, min, max, step, suffix]) => {
    container.appendChild(
      rangeControl(label, getPath(state.draft.recording, path), min, max, step, suffix, (value) => {
        setPath(state.draft.recording, path, value);
        renderRecordingPresets();
        renderState();
        scheduleDraftSave();
      }),
    );
  });
};

const renderRecordingPresets = () => {
  document.querySelectorAll("#recordingPresets .preset-button").forEach((button) => {
    const active = recordingPresetMatches(button.dataset.preset);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
};

const recordingPresetMatches = (name) => {
  const settings = recordingPresetDefs[name];
  if (!settings || !state.draft) return false;
  return Object.entries(settings).every(([key, value]) => state.draft.recording[key] === value);
};

const applyRecordingPreset = (name) => {
  const settings = recordingPresetDefs[name];
  if (!settings || !state.draft) return;
  state.draft.recording = { ...state.draft.recording, ...settings };
  state.snapshot.settings.draft = clone(state.draft);
  renderRecordingPresets();
  renderRecordingControls();
  renderState();
  scheduleDraftSave();
};

const renderDraftValue = (draftValue, activeValue, suffix) => {
  if (activeValue === undefined) return formatValue(draftValue, suffix);
  const activeChanged = activeValue !== undefined && Number(activeValue) !== Number(draftValue);
  const activeMarkup = activeChanged
    ? `<small class="active-value">Active ${formatValue(activeValue, suffix)}</small>`
    : "";
  return `<strong>Draft ${formatValue(draftValue, suffix)}</strong>${activeMarkup}`;
};

const rangeControl = (label, value, min, max, step, suffix, onInput, activeValue = undefined) => {
  const row = document.createElement("div");
  row.className = "control-row";
  const safeId = `control-${label.toLowerCase().replaceAll(" ", "-")}-${Math.random()
    .toString(16)
    .slice(2)}`;
  row.innerHTML = `
    <label for="${safeId}">${label}</label>
    <input id="${safeId}" type="range" min="${min}" max="${max}" step="${step}" value="${value}" />
    <span class="value">${renderDraftValue(value, activeValue, suffix)}</span>
  `;
  const input = row.querySelector("input");
  const output = row.querySelector(".value");
  input.addEventListener("input", () => {
    const numericValue = Number(input.value);
    output.innerHTML = renderDraftValue(numericValue, activeValue, suffix);
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

const control = async (path, options = {}) => {
  let controlError = null;
  const startsStartRequest = path === "/api/recording/start";
  const allowStaleRecordingStop = options.allowStaleRecordingStop === true;
  const expectsRecordingOutcome =
    path === "/api/recording/stop" ||
    path === "/api/recording/poll-auto-stop" ||
    (path === "/api/input/disarm" && state.snapshot?.is_recording);
  if (startsStartRequest && state.recordingStartInFlight) return;
  if (path === "/api/recording/stop" && !state.snapshot?.is_recording && !allowStaleRecordingStop) {
    return;
  }
  if (path === "/api/input/disarm" && !state.snapshot?.is_recording && !state.snapshot?.armed) {
    return;
  }
  const pollAutoStopRequest =
    path === "/api/recording/poll-auto-stop" &&
    state.snapshot?.is_recording;
  const startsStopRequest =
    ((path === "/api/recording/stop" || path === "/api/input/disarm") &&
      (state.snapshot?.is_recording ||
        (path === "/api/recording/stop" && allowStaleRecordingStop))) ||
    pollAutoStopRequest;
  if (path === "/api/recording/poll-auto-stop" && state.recordingStopInFlight) return;
  if (startsStopRequest && state.recordingStopInFlight) return;
  if (startsStartRequest) {
    state.recordingStartInFlight = true;
  }
  if (startsStopRequest) {
    state.recordingStopInFlight = true;
    renderState();
  }
  if (expectsRecordingOutcome && path !== "/api/recording/poll-auto-stop") {
    setRecordStatus("processing", "Processing recording...");
  }
  try {
    const payload = await api(path, { method: "POST" });
    if (payload.state) {
      applyState(payload.state, options);
    } else {
      await requestState(options);
    }
    if (payload.outcome !== undefined) {
      renderRecordingOutcome(payload.outcome);
    } else if (path === "/api/recording/start") {
      setRecordStatus("recording", "Recording", "Release Space to stop.");
    }
    let deferredStopHandled = false;
    if (startsStartRequest && state.recordingStopRequestedAfterStart) {
      state.recordingStartInFlight = false;
      state.recordingStopRequestedAfterStart = false;
      await control("/api/recording/stop", { allowStaleRecordingStop: true });
      deferredStopHandled = true;
    }
    if (!deferredStopHandled) {
      await requestDiagnostics();
    }
  } catch (error) {
    controlError = error;
    if (path.startsWith("/api/recording/") || path === "/api/input/disarm") {
      setRecordStatus("failed", "Recording Failed", error.message);
      await requestState({ syncDraft: false }).catch(() => {});
      await requestDiagnostics().catch(() => {});
    }
    if (path.startsWith("/api/playback/")) {
      await requestState({ syncDraft: false }).catch(() => {});
    }
  } finally {
    if (startsStopRequest) {
      state.recordingStopInFlight = false;
      renderState();
    }
    if (startsStartRequest) {
      state.recordingStartInFlight = false;
      state.recordingStopRequestedAfterStart = false;
    }
    if (controlError) showError(controlError.message);
  }
};

const applyAndRestart = async () => {
  if (state.applyInFlight) return;
  let applyError = null;
  state.applyInFlight = true;
  renderState();
  try {
    await saveDraft();
    const payload = await api("/api/settings/apply", { method: "POST" });
    applyState(payload.state);
    await requestDiagnostics();
  } catch (error) {
    applyError = error;
    await requestState({ syncDraft: false }).catch(() => {});
    await requestDiagnostics().catch(() => {});
  } finally {
    state.applyInFlight = false;
    renderState();
    if (applyError) showError(applyError.message);
  }
};

const resetDraft = async () => {
  try {
    const payload = await api("/api/settings/reset-draft", { method: "POST" });
    state.snapshot.settings = payload.settings;
    state.draft = clone(payload.settings.draft);
    renderState();
    renderControls();
    renderDevices();
    await requestDiagnostics();
  } catch (error) {
    await requestState({ syncDraft: false }).catch(() => {});
    showError(error.message);
  }
};

const resetParticipants = async () => {
  try {
    const payload = await api("/api/participants/reset", { method: "POST" });
    applyState(payload.state, { syncDraft: false });
    await requestDiagnostics();
  } catch (error) {
    await requestState({ syncDraft: false }).catch(() => {});
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
  if (event.code !== "Space" || shouldIgnoreSpace()) return;
  releaseButtonFocusForSpace();
  event.preventDefault();
  if (event.repeat) return;
  if (
    state.recordingStartInFlight ||
    state.recordingStopInFlight ||
    !state.snapshot?.armed ||
    state.snapshot?.is_recording
  ) {
    return;
  }
  state.spaceRecording = true;
  await control("/api/recording/start");
};

const stopFromSpace = async (event) => {
  if (event.code !== "Space" || shouldIgnoreSpace()) return;
  releaseButtonFocusForSpace();
  event.preventDefault();
  if (!state.spaceRecording && !state.snapshot?.is_recording) return;
  await requestRecordingStop();
};

const stopIfRecording = async () => {
  if (!state.spaceRecording && !state.snapshot?.is_recording && !state.recordingStartInFlight) {
    return;
  }
  await requestRecordingStop();
};

const requestRecordingStop = async () => {
  const allowStaleRecordingStop = state.spaceRecording;
  state.spaceRecording = false;
  if (state.recordingStartInFlight && !state.snapshot?.is_recording) {
    state.recordingStopRequestedAfterStart = true;
    return;
  }
  await control("/api/recording/stop", { allowStaleRecordingStop });
};

const stateSocketUrl = () => {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/state`;
};

const connectStateSocket = () => {
  if (!("WebSocket" in window)) {
    renderSyncBadge();
    return;
  }
  if (state.stateSocket) return;

  const socket = new WebSocket(stateSocketUrl());
  state.stateSocket = socket;
  renderSyncBadge();
  socket.addEventListener("open", () => {
    state.websocketConnected = true;
    clearTimeout(state.websocketReconnectTimer);
    renderSyncBadge();
  });
  socket.addEventListener("message", (event) => {
    try {
      applyState(JSON.parse(event.data), { syncDraft: false });
    } catch (error) {
      showError(error.message);
    }
  });
  socket.addEventListener("close", () => {
    if (state.stateSocket !== socket) return;
    state.stateSocket = null;
    state.websocketConnected = false;
    renderSyncBadge();
    state.websocketReconnectTimer = setTimeout(connectStateSocket, 1500);
  });
  socket.addEventListener("error", () => {
    socket.close();
  });
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
  $("restartOutputButton").addEventListener("click", () => control("/api/playback/restart"));
  $("refreshButton").addEventListener("click", refreshAll);
  $("applyButton").addEventListener("click", applyAndRestart);
  $("resetButton").addEventListener("click", resetDraft);
  $("resetParticipantsButton").addEventListener("click", resetParticipants);
  document.querySelectorAll("#recordingPresets .preset-button").forEach((button) => {
    button.addEventListener("click", () => applyRecordingPreset(button.dataset.preset));
  });
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
    if (!state.websocketConnected && state.snapshot?.is_recording) {
      await control("/api/recording/poll-auto-stop", { syncDraft: false });
    } else if (!state.websocketConnected) {
      await requestState({ syncDraft: false }).catch(() => {});
    }
  }, 900);
};

bindEvents();
drawCanvas();
connectStateSocket();
refreshAll();
