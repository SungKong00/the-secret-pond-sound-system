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
  low: { ko: "낮은 드론", en: "Low Drone" },
  mid: { ko: "중간 빔", en: "Mid Beam" },
  voice: { ko: "목소리 스택", en: "Voice Stack" },
};

const layerDescriptions = {
  low: "저역 기반 레이어입니다. 공간의 무게감과 바닥 진동을 다룹니다.",
  mid: "중역 중심 레이어입니다. 전시장의 몸통감과 움직임을 만듭니다.",
  voice: "참여자 목소리 레이어입니다. 녹음된 목소리의 존재감과 배치를 다룹니다.",
};

const modeLabels = {
  "live_ephemeral": "운영 모드",
  "test_library": "테스트 모드",
};

const layerControlGroups = [
  {
    title: { ko: "레벨", en: "Level" },
    note: "레이어 전체 크기",
    className: "level-group",
    controls: [
      {
        path: "volume_db",
        label: { ko: "레이어 음량", en: "Layer Level" },
        min: -36,
        max: 6,
        step: 0.5,
        suffix: " dB",
        kind: "level",
        description: "공간 안에서 이 레이어가 차지하는 전체 크기입니다.",
      },
    ],
  },
  {
    title: { ko: "음역 EQ", en: "Tone EQ" },
    note: "저역 20-250Hz · 중역 250Hz-2kHz · 고역 2kHz+",
    className: "eq-group",
    layout: "eq-band-grid",
    guide: "eq",
    controls: [
      {
        path: "eq.low_gain_db",
        label: { ko: "저역", en: "Low" },
        min: -12,
        max: 12,
        step: 0.5,
        suffix: " dB",
        kind: "eq",
        band: "low",
        rangeLabel: "20-250 Hz",
        description: "무게감, 바닥 울림",
      },
      {
        path: "eq.mid_gain_db",
        label: { ko: "중역", en: "Mid" },
        min: -12,
        max: 12,
        step: 0.5,
        suffix: " dB",
        kind: "eq",
        band: "mid",
        rangeLabel: "250 Hz-2 kHz",
        description: "몸통감, 존재감",
      },
      {
        path: "eq.high_gain_db",
        label: { ko: "고역", en: "High" },
        min: -12,
        max: 12,
        step: 0.5,
        suffix: " dB",
        kind: "eq",
        band: "high",
        rangeLabel: "2 kHz+",
        description: "공기감, 선명도",
      },
    ],
  },
  {
    title: { ko: "대역 제한", en: "Band Limits" },
    note: "불필요한 저역과 고역을 잘라 레이어의 위치를 정합니다.",
    className: "filter-group",
    layout: "filter-pair-grid",
    collapsible: true,
    controls: [
      {
        path: "eq.highpass_hz",
        label: { ko: "하한 컷", en: "Low Cut" },
        min: 20,
        max: 500,
        step: 1,
        suffix: " Hz",
        kind: "filter",
        rangeLabel: "below cutoff removed",
        description: "이 값보다 낮은 울림을 줄입니다.",
      },
      {
        path: "eq.lowpass_hz",
        label: { ko: "상한 컷", en: "High Cut" },
        min: 2000,
        max: 20000,
        step: 10,
        suffix: " Hz",
        kind: "filter",
        rangeLabel: "above cutoff removed",
        description: "이 값보다 높은 성분을 줄입니다.",
      },
    ],
  },
];

const recordingControlGroups = [
  {
    title: { ko: "입력 안정화", en: "Input Safety" },
    note: "녹음 소스의 기본 크기와 피크를 정리합니다.",
    className: "input-safety-group",
    controls: [
      {
        path: "gain_db",
        label: { ko: "입력 게인", en: "Input Gain" },
        min: -24,
        max: 12,
        step: 0.5,
        suffix: " dB",
        kind: "level",
        description: "녹음이 너무 작거나 클 때만 조정합니다.",
      },
      {
        path: "normalize_peak",
        label: { ko: "피크 기준", en: "Peak Target" },
        min: 0.1,
        max: 0.8,
        step: 0.01,
        suffix: "",
        kind: "level",
        description: "녹음 후 목표 피크입니다. 높을수록 더 크게 정규화됩니다.",
      },
    ],
  },
  {
    title: { ko: "목소리 음역", en: "Voice Band" },
    note: "목소리의 불필요한 가장자리와 선명도를 조정합니다.",
    className: "voice-band-group",
    controls: [
      {
        path: "highpass_hz",
        label: { ko: "저역 정리", en: "Low Cut" },
        min: 40,
        max: 300,
        step: 1,
        suffix: " Hz",
        kind: "filter",
        rangeLabel: "rumble control",
        description: "숨소리보다 낮은 진동과 바닥 소음을 줄입니다.",
      },
      {
        path: "lowpass_hz",
        label: { ko: "고역 정리", en: "High Cut" },
        min: 4000,
        max: 16000,
        step: 10,
        suffix: " Hz",
        kind: "filter",
        rangeLabel: "air control",
        description: "거친 고역이나 공간 노이즈를 줄입니다.",
      },
      {
        path: "presence_gain_db",
        label: { ko: "존재감", en: "Presence" },
        min: -12,
        max: 9,
        step: 0.5,
        suffix: " dB",
        kind: "eq",
        band: "high",
        rangeLabel: "2 kHz+",
        description: "목소리가 앞으로 나오거나 뒤로 물러나는 느낌입니다.",
      },
    ],
  },
  {
    title: { ko: "공간감", en: "Space Tail" },
    note: "전시장 안개감과 잔향의 길이를 만듭니다.",
    className: "space-tail-group",
    controls: [
      {
        path: "reverb_mix",
        label: { ko: "리버브", en: "Reverb" },
        min: 0,
        max: 0.7,
        step: 0.01,
        suffix: "",
        kind: "space",
        description: "공간 잔향의 양입니다.",
      },
      {
        path: "delay_mix",
        label: { ko: "딜레이", en: "Delay" },
        min: 0,
        max: 0.5,
        step: 0.01,
        suffix: "",
        kind: "space",
        description: "반복되는 메아리 양입니다.",
      },
      {
        path: "fade_ms",
        label: { ko: "페이드", en: "Fade" },
        min: 0,
        max: 500,
        step: 10,
        suffix: " ms",
        kind: "space",
        description: "녹음 앞뒤가 갑자기 튀지 않게 다듬습니다.",
      },
    ],
  },
];

const voiceStackControlDefs = [
  {
    path: "loop_seconds",
    label: { ko: "목소리 루프 길이", en: "Voice Loop" },
    min: 15,
    max: 105,
    step: 5,
    suffix: " s",
    kind: "space",
    rangeLabel: "15s · 1m center · 105s",
    description: "참여자 목소리가 스택 안에서 유지되는 시간입니다. 1분이 중심값입니다.",
    marks: [
      { value: 15, label: "15s" },
      { value: 60, label: "1m" },
      { value: 105, label: "105s" },
    ],
  },
];

const layerPresetLabels = {
  "Warm Bed": { ko: "따뜻한 바닥", en: "Warm Bed" },
  "Clear Pocket": { ko: "목소리 자리", en: "Clear Pocket" },
  "Distant Air": { ko: "먼 공기감", en: "Distant Air" },
};

const layerPresetDefs = {
  "Warm Bed": {
    volume_db: -13,
    eq: {
      low_gain_db: 3,
      mid_gain_db: -2,
      high_gain_db: -3,
      highpass_hz: 20,
      lowpass_hz: 9000,
    },
  },
  "Clear Pocket": {
    volume_db: -14,
    eq: {
      low_gain_db: -3,
      mid_gain_db: 2,
      high_gain_db: 1,
      highpass_hz: 90,
      lowpass_hz: 12000,
    },
  },
  "Distant Air": {
    volume_db: -18,
    eq: {
      low_gain_db: -4,
      mid_gain_db: -1,
      high_gain_db: 4,
      highpass_hz: 140,
      lowpass_hz: 16000,
    },
  },
};

const presetLabels = {
  Soft: { ko: "부드럽게", en: "Soft" },
  Misty: { ko: "안개처럼", en: "Misty" },
  Dense: { ko: "풍성하게", en: "Dense" },
  "Clearer Voice": { ko: "선명한 목소리", en: "Clearer Voice" },
};

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
  if (suffix === " Hz" && Math.abs(number) >= 1000) {
    const khz = number / 1000;
    const roundedKhz = Number.isInteger(khz) ? khz.toString() : khz.toFixed(1);
    return `${roundedKhz} kHz`;
  }
  if (suffix === " ms" && Math.abs(number) >= 1000) {
    const seconds = number / 1000;
    const roundedSeconds = Number.isInteger(seconds) ? seconds.toString() : seconds.toFixed(1);
    return `${roundedSeconds} s`;
  }
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
  if (!value) return "시간 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const labelText = (label) => (typeof label === "string" ? label : label.en);

const labelMarkup = (label) => {
  if (typeof label === "string") return label;
  return `<span class="label-with-helper">${label.en}<small lang="ko">${label.ko}</small></span>`;
};

const setLabelMarkup = (id, label) => {
  $(id).innerHTML = labelMarkup(label);
};

const helperText = (value) => {
  if (!value) return "";
  if (typeof value === "string") return value;
  return value.ko || value.en || "";
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
    $("errorBadge").textContent = "오류 있음";
    $("errorBadge").className = "status-pill hot";
  } else {
    $("errorBadge").textContent = "오류 없음";
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
    $("syncBadge").textContent = "동기화 확인";
    $("syncBadge").className = "status-pill muted";
  } else if (state.websocketConnected) {
    $("syncBadge").textContent = "실시간 동기화";
    $("syncBadge").className = "status-pill safe";
  } else if (state.stateSocket) {
    $("syncBadge").textContent = "동기화 연결 중";
    $("syncBadge").className = "status-pill muted";
  } else {
    $("syncBadge").textContent = "동기화 확인";
    $("syncBadge").className = "status-pill muted";
  }
};

const renderState = () => {
  renderSyncBadge();
  const snapshot = state.snapshot;
  if (!snapshot) return;
  const recordingStopBusy = state.recordingStopInFlight;
  const outputControlBusy = state.applyInFlight || recordingStopBusy;
  const captureReady = snapshot.armed && !snapshot.is_recording && !recordingStopBusy;

  $("armedBadge").textContent = snapshot.armed ? "준비됨" : "준비 해제";
  $("armedBadge").className = `status-pill ${snapshot.armed ? "safe" : "muted"}`;
  $("recordingBadge").textContent = snapshot.is_recording ? "녹음 중" : "대기";
  $("recordingBadge").className = `status-pill ${snapshot.is_recording ? "hot" : ""}`;
  $("outputBadge").textContent = snapshot.playback.output_running ? "출력 중" : "출력 꺼짐";
  $("outputBadge").className = `status-pill ${snapshot.playback.output_running ? "safe" : "muted"}`;
  renderModeBadge(snapshot.settings.active.voice_stack.mode);
  $("participantCount").textContent = snapshot.participant_count;
  $("elapsedTime").textContent = `${snapshot.recording_elapsed_seconds.toFixed(1)}s`;
  $("remainingTime").textContent =
    `${snapshot.recording_remaining_seconds.toFixed(1)}s 남음`;
  $("minimumRecordingTime").textContent = formatSeconds(
    snapshot.settings.active.input_control.minimum_recording_seconds,
  );
  $("maximumRecordingTime").textContent = formatSeconds(
    snapshot.settings.active.input_control.maximum_recording_seconds,
  );
  $("recordCoreStatus").textContent = recordingStopBusy
    ? "처리 중"
    : snapshot.is_recording
      ? "녹음 중"
      : snapshot.armed
        ? "준비됨"
        : "안전";
  document.querySelector(".record-core").classList.toggle("armed", captureReady);
  document.querySelector(".record-core").classList.toggle("recording", snapshot.is_recording);
  renderRecordReadiness(snapshot, recordingStopBusy);
  $("pendingBadge").textContent = hasPendingChanges(snapshot)
    ? "저장 안 된 오디오 변경"
    : "저장 안 된 변경 없음";
  $("pendingBadge").className = `status-pill ${hasPendingChanges(snapshot) ? "hot" : "muted"}`;
  $("outputControlSummary").textContent = state.applyInFlight
    ? "준비된 오디오 설정을 렌더링하는 중입니다."
    : snapshot.playback.output_running
      ? "출력 스트림이 실행 중입니다."
      : hasPendingChanges(snapshot)
        ? "저장 안 된 오디오 변경이 적용 후 재시작을 기다립니다."
        : "준비된 오디오를 렌더링한 뒤 출력을 시작합니다.";
  $("armButton").disabled = recordingStopBusy || snapshot.armed || snapshot.is_recording;
  $("disarmButton").disabled =
    recordingStopBusy || (!snapshot.armed && !snapshot.is_recording);
  $("startButton").disabled = recordingStopBusy || !snapshot.armed || snapshot.is_recording;
  $("stopButton").disabled = recordingStopBusy || !snapshot.is_recording;
  $("startOutputButton").disabled = outputControlBusy || snapshot.playback.output_running;
  $("stopOutputButton").disabled = outputControlBusy || !snapshot.playback.output_running;
  $("restartOutputButton").disabled = outputControlBusy || !snapshot.playback.output_running;
  $("armButton").setAttribute("aria-pressed", snapshot.armed ? "true" : "false");
  $("disarmButton").setAttribute("aria-pressed", snapshot.armed ? "false" : "true");
  const runtimeConfigChanges = hasDraftRuntimeConfigChanges(snapshot);
  $("applyButton").disabled =
    state.applyInFlight || recordingStopBusy || snapshot.is_recording || runtimeConfigChanges;
  if (state.applyInFlight) {
    $("applyButton").textContent = "적용 중...";
  } else {
    setLabelMarkup("applyButton", { ko: "적용 후 재시작", en: "Apply and Restart" });
  }
  $("resetButton").disabled = state.applyInFlight || snapshot.is_recording;
  $("resetButton").title = snapshot.is_recording
    ? "초안 설정을 초기화하기 전에 녹음을 중지하세요."
    : "";
  $("resetParticipantsButton").disabled = state.applyInFlight || snapshot.is_recording;
  $("resetParticipantsButton").title = snapshot.is_recording
    ? "참여자 수를 초기화하기 전에 녹음을 중지하세요."
    : "";
  $("applyButton").title = recordingStopBusy
    ? "녹음 처리가 끝날 때까지 기다리세요."
    : snapshot.is_recording
      ? "준비된 설정을 적용하기 전에 녹음을 중지하세요."
      : state.applyInFlight
        ? "준비된 오디오 설정을 렌더링하고 다시 불러오는 중입니다."
        : runtimeConfigChanges
          ? "준비된 장치 변경을 적용하려면 앱을 재시작하세요."
          : snapshot.playback.output_running
            ? "준비된 오디오 설정을 적용하는 동안 출력을 멈췄다가 다시 시작합니다."
            : "";
  renderErrors();
};

const recordOutcomeKind = () => {
  const className = $("recordOutcomeStatus").parentElement.className;
  return className.split(/\s+/).find((name) => replaceableRecordOutcomeKinds.has(name));
};

const renderRecordReadiness = (snapshot, recordingStopBusy) => {
  if (recordingStopBusy) {
    setRecordStatus("processing", "녹음 처리 중...");
  } else if (snapshot.is_recording) {
    setRecordStatus("recording", "녹음 중", "스페이스바를 떼면 중지합니다.");
  } else if (!replaceableRecordOutcomeKinds.has(recordOutcomeKind())) {
    return;
  } else if (snapshot.armed) {
    setRecordStatus("armed-ready", "스페이스바를 눌러 녹음", "스페이스바를 떼면 녹음을 중지합니다.");
  } else {
    setRecordStatus("ready", "준비", "먼저 녹음을 준비한 뒤 스페이스바를 누르세요.");
  }
};

const renderModeBadge = (mode) => {
  $("modeBadge").textContent = modeLabels[mode] || "모드 미확인";
  $("modeBadge").className = `status-pill ${mode === "live_ephemeral" ? "safe" : "muted"}`;
};

const renderLastEventBadge = () => {
  const lastEvent = state.diagnostics?.events?.recent?.[0];
  if (state.diagnosticsError || state.diagnostics?.events?.error) {
    $("lastEventBadge").textContent = "최근 이벤트 불러오기 실패";
    $("lastEventBadge").className = "status-pill hot";
  } else if (lastEvent?.event_type) {
    $("lastEventBadge").textContent = `최근 ${lastEvent.event_type}`;
    $("lastEventBadge").className = "status-pill";
  } else {
    $("lastEventBadge").textContent = "최근 이벤트 없음";
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
      ? `참여자 ${outcome.participant_count}`
      : "참여자 수 변경 없음";
    setRecordStatus("added", "녹음 추가됨", `${participant} · ${duration}`);
  } else if (outcome.reason === "too_short") {
    setRecordStatus("discarded", "너무 짧음", `${duration} 녹음됨. 최소 시간을 채우지 못했습니다.`);
  } else if (outcome.reason === "empty") {
    setRecordStatus("discarded", "빈 녹음", `${duration} 녹음됨.`);
  } else if (outcome.reason === "disarmed") {
    setRecordStatus("discarded", "녹음 준비 해제됨", `${duration} 녹음됨.`);
  } else {
    setRecordStatus("discarded", "녹음 폐기됨", outcome.reason || duration);
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
    $("inputDeviceName").textContent = state.deviceError ? "사용 불가" : "확인 중...";
    $("outputDeviceName").textContent = state.deviceError ? "사용 불가" : "확인 중...";
    renderDeviceSelect("inputDeviceSelect", [], null);
    renderDeviceSelect("outputDeviceSelect", [], null);
    $("deviceRestartNotice").textContent = state.deviceError
      ? "오디오 장치를 사용할 수 없습니다."
      : "오디오 장치를 확인하는 중입니다...";
    $("deviceWarnings").innerHTML = "";
    renderSystemStatus();
    return;
  }

  $("inputDeviceName").textContent = devices.selected_input_device?.name || "입력 장치 없음";
  $("outputDeviceName").textContent = devices.selected_output_device?.name || "출력 장치 없음";
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
    $("deviceHealthBadge").textContent = "장치 오프라인";
    $("deviceHealthBadge").className = "status-pill hot";
  } else if (!state.devices) {
    $("deviceHealthBadge").textContent = "장치 확인 중";
    $("deviceHealthBadge").className = "status-pill muted";
  } else if (state.devices.warnings.length) {
    $("deviceHealthBadge").textContent = "장치 경고";
    $("deviceHealthBadge").className = "status-pill hot";
  } else {
    $("deviceHealthBadge").textContent = "장치 정상";
    $("deviceHealthBadge").className = "status-pill safe";
  }
};

const renderSystemStatus = () => {
  renderSystemDevices();

  if (!state.diagnostics) {
    $("systemStatus").textContent = state.diagnosticsError ? "진단 오프라인" : "확인 중";
    $("systemStatus").className = `status-pill ${state.diagnosticsError ? "hot" : "muted"}`;
    $("sourceHealthList").innerHTML = "";
    const placeholder = document.createElement("div");
    placeholder.className = "diagnostic-row";
    const label = document.createElement("span");
    label.textContent = "파일";
    const value = document.createElement("strong");
    value.textContent = state.diagnosticsError ? "사용 불가" : "확인 중...";
    placeholder.append(label, value);
    $("sourceHealthList").appendChild(placeholder);
    renderEventLogSummary([]);
    return;
  }

  const missingSources = state.diagnostics.sources.filter((source) => !source.exists);
  $("systemStatus").textContent = missingSources.length
    ? `${missingSources.length}개 없음`
    : "소스 준비됨";
  $("systemStatus").className = `status-pill ${missingSources.length ? "hot" : "safe"}`;
  renderSourceHealthList(state.diagnostics.sources);
  renderEventLogSummary(state.diagnostics.events?.recent || [], state.diagnostics.events?.error);
};

const renderSystemDevices = () => {
  $("systemInputDeviceName").textContent = systemDeviceName(
    "selected_input_device",
    "입력 장치 없음",
  );
  $("systemOutputDeviceName").textContent = systemDeviceName(
    "selected_output_device",
    "출력 장치 없음",
  );
};

const systemDeviceName = (key, emptyLabel) => {
  if (state.deviceError) return "사용 불가";
  if (!state.devices) return "확인 중...";
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
      ? `준비됨 · ${formatBytes(source.size_bytes)} · ${formatTimestamp(source.modified_at)}`
      : `없음 · ${source.path}`;
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
    item.textContent = "아직 이벤트가 없습니다";
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
    label.textContent = event.event_type || "이벤트";
    item.append(time, label);
    list.appendChild(item);
  });
};

const renderDeviceSelect = (selectId, devices, selectedId, forceDisabled = false) => {
  const select = $(selectId);
  select.innerHTML = "";
  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = "시스템 기본값";
  select.appendChild(defaultOption);

  devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.id;
    option.textContent = `${device.name} (${device.default_sample_rate || "알 수 없음"} Hz)`;
    select.appendChild(option);
  });

  if (selectedId && !devices.some((device) => device.id === selectedId)) {
    const missingOption = document.createElement("option");
    missingOption.value = selectedId;
    missingOption.textContent = `사용 불가: ${selectedId}`;
    select.appendChild(missingOption);
  }

  select.value = selectedId || "";
  select.disabled = forceDisabled || !state.draft || !state.devices;
};

const renderDeviceRestartNotice = () => {
  const outputRunning = Boolean(state.snapshot?.playback.output_running);
  const changed = hasDraftDeviceChanges();
  if (outputRunning) {
    $("deviceRestartNotice").textContent = "출력 장치를 바꾸기 전에 출력을 중지하세요.";
  } else if (changed) {
    $("deviceRestartNotice").textContent = "장치 변경이 준비되었습니다. 앱 재시작 후 적용됩니다.";
  } else {
    $("deviceRestartNotice").textContent = "장치 변경은 앱 재시작 후 적용됩니다.";
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
  renderVoiceStackControls();
  renderRecordingPresets();
  renderRecordingControls();
};

const renderLayerControls = () => {
  renderLayerGroup("layerControls", ["low", "mid"]);
  renderLayerGroup("voiceLayerControls", ["voice"]);
};

const renderVoiceStackControls = () => {
  const container = $("voiceStackControls");
  container.innerHTML = "";
  const activeVoiceStack = state.snapshot?.settings.active.voice_stack || state.draft.voice_stack;
  voiceStackControlDefs.forEach((control) => {
    container.appendChild(
      rangeControl(
        control,
        getPath(state.draft.voice_stack, control.path),
        (value) => {
          setPath(state.draft.voice_stack, control.path, value);
          renderState();
          scheduleDraftSave();
        },
        getPath(activeVoiceStack, control.path),
      ),
    );
  });
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
  const layerLabel = layerLabels[layerId];
  card.innerHTML = `
    <div class="layer-head">
      <div>
        <h3 class="layer-title">${labelMarkup(layerLabel)}</h3>
        <p class="layer-role">${layerDescriptions[layerId] || ""}</p>
      </div>
      <div class="layer-head-actions">
        ${layerPendingBadge(layerId)}
        <label class="layer-toggle">
          <input type="checkbox" aria-label="${labelText(layerLabel)} enabled" ${
            layer.enabled ? "checked" : ""
          } />
          <span>Enabled</span>
        </label>
      </div>
    </div>
    ${layerId === "voice" ? "" : layerPresetMarkup(layerId)}
    <div class="layer-controls"></div>
  `;
  card.querySelector("input[type='checkbox']").addEventListener("change", (event) => {
    state.draft.layers[layerId].enabled = event.target.checked;
    updateLayerPendingBadge(layerId, card);
    renderState();
    scheduleDraftSave();
  });

  const controls = card.querySelector(".layer-controls");
  layerControlGroups.forEach((group) => {
    controls.appendChild(
      controlGroup(group, layer, activeLayer, (control, value) => {
        setPath(state.draft.layers[layerId], control.path, value);
        updateLayerPendingBadge(layerId, card);
        renderState();
        scheduleDraftSave();
      }),
    );
  });
  card.querySelectorAll?.(".layer-preset-button")?.forEach((button) => {
    button.addEventListener("click", () => applyLayerPreset(layerId, button.dataset.layerPreset));
  });
  return card;
};

const layerPresetMarkup = (layerId) => `
  <div class="layer-preset-row" role="group" aria-label="${labelText(layerLabels[layerId])} 톤 프리셋">
    ${Object.entries(layerPresetLabels)
      .map(
        ([name, label]) => `
          <button class="layer-preset-button" type="button" data-layer-preset="${name}">
            ${labelMarkup(label)}
          </button>
        `,
      )
      .join("")}
  </div>
`;

const applyLayerPreset = (layerId, presetName) => {
  const preset = layerPresetDefs[presetName];
  if (!preset || !state.draft?.layers[layerId]) return;
  const current = state.draft.layers[layerId];
  state.draft.layers[layerId] = {
    ...current,
    volume_db: preset.volume_db,
    eq: {
      ...current.eq,
      ...preset.eq,
    },
  };
  state.snapshot.settings.draft = clone(state.draft);
  renderLayerControls();
  renderState();
  scheduleDraftSave();
};

const renderRecordingControls = () => {
  const container = $("recordingControls");
  container.innerHTML = "";
  const activeRecording = state.snapshot?.settings.active.recording || state.draft.recording;
  recordingControlGroups.forEach((group) => {
    container.appendChild(
      controlGroup(group, state.draft.recording, activeRecording, (control, value) => {
        setPath(state.draft.recording, control.path, value);
        renderRecordingPresets();
        renderState();
        scheduleDraftSave();
      }),
    );
  });
};

const renderRecordingPresets = () => {
  document.querySelectorAll("#recordingPresets .preset-button").forEach((button) => {
    const label = presetLabels[button.dataset.preset];
    if (label) button.innerHTML = labelMarkup(label);
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

const frequencyGuideMarkup = (kind) => {
  if (kind !== "eq") return "";
  return `
    <div class="frequency-guide" aria-label="EQ 음역대 안내">
      <span class="guide-band guide-low"><strong>Low</strong> 20-250 Hz</span>
      <span class="guide-band guide-mid"><strong>Mid</strong> 250 Hz-2 kHz</span>
      <span class="guide-band guide-high"><strong>High</strong> 2 kHz+</span>
    </div>
  `;
};

const controlGroup = (group, draftSource, activeSource, onInput) => {
  const section = document.createElement(group.collapsible ? "details" : "section");
  section.className = `control-group ${group.className || ""}`;
  if (group.open) section.open = true;
  const headTag = group.collapsible ? "summary" : "div";
  section.innerHTML = `
    <${headTag} class="control-group-head">
      <h4>${labelMarkup(group.title)}</h4>
      <p>${group.note || ""}</p>
    </${headTag}>
    ${frequencyGuideMarkup(group.guide)}
    <div class="control-group-body ${group.layout || ""}"></div>
  `;
  const body = section.querySelector(".control-group-body");
  if (!body.parentElement) section.appendChild(body);
  group.controls.forEach((control) => {
    body.appendChild(
      rangeControl(
        control,
        getPath(draftSource, control.path),
        (value) => onInput(control, value),
        activeSource ? getPath(activeSource, control.path) : undefined,
      ),
    );
  });
  return section;
};

const renderDraftValue = (draftValue, activeValue, suffix) => {
  if (activeValue === undefined) return formatValue(draftValue, suffix);
  const activeChanged = activeValue !== undefined && Number(activeValue) !== Number(draftValue);
  const activeMarkup = activeChanged
    ? `<small class="active-value">Active ${formatValue(activeValue, suffix)}</small>`
    : "";
  return `<strong>Draft ${formatValue(draftValue, suffix)}</strong>${activeMarkup}`;
};

const decimalPlaces = (value) => {
  const text = String(value);
  if (!text.includes(".")) return 0;
  return text.split(".")[1]?.length || 0;
};

const clamp = (value, min, max) => Math.max(Number(min), Math.min(Number(max), Number(value)));

const snappedValue = (value, step, min, max) => {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return Number(min);
  const numericStep = Number(step) || 1;
  const snapped = Math.round((clamp(numericValue, min, max) - Number(min)) / numericStep) *
    numericStep +
    Number(min);
  return Number(clamp(snapped, min, max).toFixed(decimalPlaces(step)));
};

const rangePercent = (value, min, max) => {
  const span = Number(max) - Number(min);
  if (!Number.isFinite(span) || span <= 0) return 0;
  return Math.max(0, Math.min(100, ((Number(value) - Number(min)) / span) * 100));
};

const setRangeProgress = (row, value, min, max) => {
  row.style?.setProperty("--control-percent", `${rangePercent(value, min, max)}%`);
};

const boundedRange = (control, value, activeValue) => {
  const values = [Number(value), Number(activeValue)].filter((number) => Number.isFinite(number));
  return {
    min: Math.min(Number(control.min), ...values),
    max: Math.max(Number(control.max), ...values),
  };
};

const rangeMarksMarkup = (control, min, max) => {
  if (!control.marks?.length) return "";
  return `
    <div class="range-marks" aria-hidden="true">
      ${control.marks
        .map(
          (mark) => `
            <span style="--mark-position: ${rangePercent(mark.value, min, max)}%">
              ${mark.label}
            </span>
          `,
        )
        .join("")}
    </div>
  `;
};

const precisionControlMarkup = (control, value, min, max, safeId) => `
  <div class="precision-control" aria-label="${labelText(control.label)} 정밀 조정">
    <button class="nudge-button nudge-down" type="button" aria-label="${labelText(
      control.label,
    )} 감소">-</button>
    <input
      class="value-input"
      type="number"
      min="${min}"
      max="${max}"
      step="${control.step}"
      value="${value}"
      aria-label="${labelText(control.label)} 정확한 값"
      aria-describedby="${safeId}"
    />
    <button class="nudge-button nudge-up" type="button" aria-label="${labelText(
      control.label,
    )} 증가">+</button>
  </div>
`;

const rangeControl = (control, value, onInput, activeValue = undefined) => {
  const row = document.createElement("div");
  row.className = [
    "control-row",
    control.kind ? `control-${control.kind}` : "",
    control.band ? `band-${control.band}` : "",
  ]
    .filter(Boolean)
    .join(" ");
  const { min, max } = boundedRange(control, value, activeValue);
  setRangeProgress(row, value, min, max);
  const safeLabel = `${labelText(control.label)}-${control.path}`
    .toLowerCase()
    .replaceAll(".", "-")
    .replaceAll(" ", "-");
  const safeId = `control-${safeLabel}-${Math.random()
    .toString(16)
    .slice(2)}`;
  row.innerHTML = `
    <label for="${safeId}">
      ${labelMarkup(control.label)}
      <small class="control-description">${helperText(control.description)}</small>
    </label>
    <div class="slider-cell">
      <div class="range-rail">
        <input
          id="${safeId}"
          type="range"
          min="${min}"
          max="${max}"
          step="${control.step}"
          value="${value}"
        />
      </div>
      <div class="range-assist">
        ${control.rangeLabel ? `<small class="range-context">${control.rangeLabel}</small>` : ""}
        ${rangeMarksMarkup(control, min, max)}
      </div>
    </div>
    <div class="value-stack">
      <span class="value">${renderDraftValue(value, activeValue, control.suffix)}</span>
      ${precisionControlMarkup(control, value, min, max, safeId)}
    </div>
  `;
  const input = row.querySelector("input");
  const output = row.querySelector(".value");
  const valueInput = row.querySelector(".value-input");
  const nudgeDown = row.querySelector(".nudge-down");
  const nudgeUp = row.querySelector(".nudge-up");
  const updateValue = (nextValue) => {
    const numericValue = snappedValue(nextValue, control.step, min, max);
    input.value = String(numericValue);
    if (valueInput) valueInput.value = String(numericValue);
    setRangeProgress(row, numericValue, min, max);
    output.innerHTML = renderDraftValue(numericValue, activeValue, control.suffix);
    onInput(numericValue);
  };
  input.addEventListener("input", () => {
    updateValue(input.value);
  });
  valueInput?.addEventListener("change", () => updateValue(valueInput.value));
  valueInput?.addEventListener("input", () => {
    if (Number.isFinite(Number(valueInput.value))) updateValue(valueInput.value);
  });
  nudgeDown?.addEventListener("click", () => updateValue(Number(input.value) - Number(control.step)));
  nudgeUp?.addEventListener("click", () => updateValue(Number(input.value) + Number(control.step)));
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
    setRecordStatus("processing", "녹음 처리 중...");
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
      setRecordStatus("recording", "녹음 중", "스페이스바를 떼면 중지합니다.");
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
      setRecordStatus("failed", "녹음 실패", error.message);
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
