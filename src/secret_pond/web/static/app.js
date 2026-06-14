const responseErrorMessage = (payload, status) => {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object") {
    if (Array.isArray(detail.missing_sources) && detail.missing_sources.length) {
      return `프리셋 소스 파일을 찾을 수 없습니다: ${detail.missing_sources.join(", ")}`;
    }
    return detail.message || detail.reason || detail.code || `Request failed: ${status}`;
  }
  return `Request failed: ${status}`;
};

const api = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = responseErrorMessage(payload, response.status);
    const error = new Error(message);
    error.status = response.status;
    error.detail = payload.detail || null;
    throw error;
  }
  return payload;
};

const workspaceTabNames = ["treatment", "stack", "mixer"];
const sideTabNames = ["library", "system"];

const workspaceTabFromUrl = () => {
  const query = new URLSearchParams(window.location.search || "");
  const tabName = query.get("workspace");
  return workspaceTabNames.includes(tabName) ? tabName : "treatment";
};

const state = {
  snapshot: null,
  draft: null,
  devices: null,
  diagnostics: null,
  sources: null,
  transientError: null,
  transientNotice: null,
  transientErrorShownAt: 0,
  deviceError: null,
  diagnosticsError: null,
  sourcesError: null,
  settingsPresets: [],
  settingsPresetsError: null,
  settingsPresetActionInFlight: false,
  settingsPresetRefreshRequestId: 0,
  appliedSourceSignature: null,
  serverStateSignature: null,
  acceptedStateEpoch: null,
  acceptedStateRevision: null,
  sourceUploads: {},
  sourceCardSelections: {},
  sourceRenameDrafts: {},
  sourceRenameEditing: {},
  sourceMutationInFlight: false,
  saveTimer: null,
  draftSaveInFlight: false,
  draftSaveRequestId: 0,
  draftEditRevision: 0,
  pendingCoveredFeedbackSurfaceId: undefined,
  coveredFeedbackSurfaceId: undefined,
  pendingLiveFeedbackSurfaceId: undefined,
  liveFeedbackSurfaceId: undefined,
  graphEqInlinePreserveMountLayerId: null,
  graphEqInlinePreserveMountToken: 0,
  liveGraphEqLatestRequestIds: {},
  liveApplyFeedback: null,
  stableApplyCoveredFeedbackSurfaceIds: [],
  stableApplyCoveredFeedbackControlSnapshots: [],
  pendingCoveredFeedbackControlIds: [],
  coveredFeedbackControlIds: [],
  confirmedDraftSignature: null,
  confirmedActiveSettingsSnapshot: null,
  sourceMutationRequestId: 0,
  storageModeRequestId: 0,
  stateRefreshRequestId: 0,
  sourceRefreshRequestId: 0,
  diagnosticsRefreshRequestId: 0,
  deviceChangeRequestId: 0,
  deviceRefreshRequestId: 0,
  playbackSeekRequestId: 0,
  playbackSeekPointerId: null,
  playbackTimelineReceivedAtMs: 0,
  playbackTimelineAnimationPending: false,
  spaceRecording: false,
  stateSocket: null,
  websocketConnected: false,
  websocketReconnectTimer: null,
  recordingStartInFlight: false,
  recordingStopRequestedAfterStart: false,
  recordingStopInFlight: false,
  playbackControlInFlight: false,
  playbackApplyModeInFlight: false,
  pendingPlaybackApplyMode: null,
  playbackApplyModeChoiceDialog: null,
  storageModeInFlight: false,
  pendingStorageMode: null,
  applyInFlight: false,
  applyAndRestartInFlight: false,
  resetDraftInFlight: false,
  resetParticipantsInFlight: false,
  deviceChangeInFlight: false,
  activeInteractiveControl: null,
  releasedInteractiveControl: null,
  renderSignatures: {
    deviceSelects: {},
    sourceLibrary: null,
  },
  presetSelections: {
    layers: {},
    recording: null,
  },
  expandedGraphEqLayer: "mid",
  graphEqSelectedPointIds: {
    low: null,
    mid: null,
    voice: null,
  },
  expandedControlGroups: {},
  workspaceTab: workspaceTabFromUrl(),
  sideTab: "library",
  deferredInteractiveRenders: {},
};

let liveGraphEqTickTimer = null;

const $ = (id) => document.getElementById(id);

const containsKorean = (message) => /[ㄱ-ㅎㅏ-ㅣ가-힣]/.test(message);

const noticeSeverityRank = {
  info: 0,
  caution: 1,
  error: 2,
};

const noticeSeverityDisplay = {
  error: {
    label: "오류",
    badge: "오류 있음",
    badgeClass: "hot",
    role: "alert",
    live: "assertive",
  },
  caution: {
    label: "주의",
    badge: "주의 있음",
    badgeClass: "caution",
    role: "status",
    live: "polite",
  },
  info: {
    label: "안내",
    badge: "안내 있음",
    badgeClass: "muted",
    role: "status",
    live: "polite",
  },
};

const transientNoticeMinimumVisibleMs = 6000;

const openNoticeDetailKeys = new Set();
const dismissedNoticeKeys = new Set();

const normalizeNoticeSeverity = (severity = "error") => {
  if (severity === "warning") return "caution";
  return noticeSeverityDisplay[severity] ? severity : "error";
};

const highestNoticeSeverity = (notices) => notices.reduce((highest, notice) => (
  noticeSeverityRank[notice.severity] > noticeSeverityRank[highest] ? notice.severity : highest
), "info");

const genericNoticeDetail = "문제가 반복되면 최근 이벤트와 시스템 진단을 확인하세요.";
const settingsApplyFailureCautionMessage =
  "변경사항을 적용하지 못했습니다. 이전 설정이 계속 사용됩니다.";
const settingsApplyFailureCautionDetail =
  "실패한 변경사항은 활성 재생 설정에 반영되지 않았습니다. 상태를 확인한 뒤 다시 적용하세요.";

const uiNotice = (message, summary, detail, severity = "error") => ({
  summary,
  detail,
  severity: normalizeNoticeSeverity(severity),
  technical: message,
});

const sourceCategoryLabels = {
  low: { title: "Low", helper: "낮은 배경 루프" },
  mid: { title: "Mid", helper: "중간 배경 루프" },
  voice_raw: { title: "Voice Raw", helper: "목소리 원본 보관" },
  voice_stack: { title: "Voice Stack", helper: "목소리 스택 소스" },
};

const describeUiNotice = (message, defaultSeverity = "error") => {
  if (!message) return "";
  const text = String(message).trim();
  if (!text) return "";
  const fallbackSeverity = normalizeNoticeSeverity(defaultSeverity);
  if (containsKorean(text)) {
    return uiNotice(text, text, genericNoticeDetail, fallbackSeverity);
  }

  const normalized = text.toLowerCase();
  const requestStatus = normalized.match(/request failed:\s*(\d+)/);
  if (requestStatus) {
    return uiNotice(
      text,
      `요청을 처리하지 못했습니다. HTTP ${requestStatus[1]} 상태입니다.`,
      "서버가 요청을 완료하지 못했습니다. 같은 작업이 반복해서 실패하면 서버 상태와 최근 이벤트를 확인하세요.",
      "error",
    );
  }
  if (normalized.includes("failed to fetch") || normalized.includes("load failed")) {
    return uiNotice(
      text,
      "서버에 연결하지 못했습니다.",
      "로컬 서버가 실행 중인지, 브라우저가 같은 주소에 연결되어 있는지 확인하세요.",
      "error",
    );
  }
  if (normalized.includes("state is unavailable")) {
    return uiNotice(
      text,
      "상태를 불러오지 못했습니다.",
      "설정 또는 참여자 상태 파일을 읽지 못했습니다. data 디렉터리의 파일 상태를 확인한 뒤 다시 시도하세요.",
      "error",
    );
  }
  if (normalized.includes("not recording")) {
    return uiNotice(
      text,
      "녹음은 이미 중지되어 있습니다.",
      "현재 녹음 세션이 없어서 중지 요청을 적용하지 않았습니다. 화면 상태를 새로고침한 뒤 다시 확인하세요.",
      "info",
    );
  }
  if (normalized.includes("audio devices unavailable")) {
    return uiNotice(
      text,
      "오디오 장치를 사용할 수 없습니다.",
      "운영체제의 오디오 장치 목록을 읽지 못했습니다. 장치를 다시 연결하거나 앱을 재시작한 뒤 System 패널을 확인하세요.",
      "error",
    );
  }
  if (normalized.includes("configured input device is unavailable")) {
    return uiNotice(
      text,
      "설정된 입력 장치를 사용할 수 없습니다.",
      "저장된 입력 장치가 현재 시스템 목록에 없습니다. System 패널에서 사용 가능한 입력 장치를 다시 선택하세요.",
      "error",
    );
  }
  if (normalized.includes("configured output device is unavailable")) {
    return uiNotice(
      text,
      "설정된 출력 장치를 사용할 수 없습니다.",
      "저장된 출력 장치가 현재 시스템 목록에 없습니다. System 패널에서 사용 가능한 출력 장치를 다시 선택하세요.",
      "error",
    );
  }
  if (normalized.includes("device changes must be applied from the system panel")) {
    return uiNotice(
      text,
      "입력/출력 장치는 System 패널에서 선택하세요.",
      "일반 설정 저장에는 장치 변경을 포함할 수 없습니다. System 패널의 입력/출력 장치 목록에서 장치를 선택하면 즉시 적용됩니다.",
      "error",
    );
  }
  const sampleRateMismatch = normalized.match(
    /selected (input|output) default sample rate is (\d+), but settings request (\d+)/,
  );
  if (sampleRateMismatch) {
    const [, direction, deviceRate, settingsRate] = sampleRateMismatch;
    const target = direction === "input" ? "입력" : "출력";
    return uiNotice(
      text,
      `${target} 장치 기본 샘플레이트가 앱 설정과 다릅니다.`,
      `선택한 ${target} 장치의 기본값은 ${deviceRate} Hz이고 앱은 ${settingsRate} Hz로 ${
        direction === "input" ? "녹음" : "출력"
      }하도록 설정되어 있습니다. ${
        direction === "input" ? "녹음" : "재생"
      }은 가능할 수 있지만 macOS 오디오 MIDI 설정이나 앱 ${target} 장치를 확인하세요.`,
      "caution",
    );
  }
  const channelMismatch = normalized.match(
    /selected (input|output) supports (\d+) channels, but settings request (\d+)/,
  );
  if (channelMismatch) {
    const [, direction, deviceChannels, settingsChannels] = channelMismatch;
    const target = direction === "input" ? "입력" : "출력";
    return uiNotice(
      text,
      `선택한 ${target} 장치의 채널 수가 현재 오디오 설정과 맞지 않습니다.`,
      `선택한 ${target} 장치는 ${deviceChannels}채널까지 지원하지만 앱 설정은 ${settingsChannels}채널을 요청합니다. 채널 수를 맞추거나 다른 ${target} 장치를 선택하세요.`,
      "error",
    );
  }
  if (
    normalized.includes("selected input") &&
    normalized.includes("supports") &&
    normalized.includes("channels")
  ) {
    return uiNotice(
      text,
      "선택한 입력 장치의 채널 수가 현재 오디오 설정과 맞지 않습니다.",
      "입력 장치의 지원 채널 수와 앱 설정 채널 수를 맞춰야 합니다.",
      "error",
    );
  }
  if (
    normalized.includes("selected output") &&
    normalized.includes("supports") &&
    normalized.includes("channels")
  ) {
    return uiNotice(
      text,
      "선택한 출력 장치의 채널 수가 현재 오디오 설정과 맞지 않습니다.",
      "출력 장치의 지원 채널 수와 앱 설정 채널 수를 맞춰야 합니다.",
      "error",
    );
  }
  if (normalized.includes("devices failed") || normalized.includes("device")) {
    return uiNotice(
      text,
      "오디오 장치 정보를 불러오지 못했습니다.",
      "System 패널의 장치 목록을 갱신하지 못했습니다. 장치 연결 상태와 로컬 서버 상태를 확인하세요.",
      "error",
    );
  }
  if (normalized.includes("diagnostics failed") || normalized.includes("diagnostic")) {
    return uiNotice(
      text,
      "시스템 진단 정보를 불러오지 못했습니다.",
      "소스 파일 상태와 최근 이벤트를 가져오지 못했습니다. 로컬 서버 로그를 확인하고 다시 시도하세요.",
      "error",
    );
  }
  if (normalized.includes("event log")) {
    return uiNotice(
      text,
      "최근 이벤트를 불러오지 못했습니다.",
      "이벤트 로그 파일을 읽지 못했습니다. 파일 권한과 data 디렉터리 상태를 확인하세요.",
      "error",
    );
  }
  if (normalized.includes("source file") && normalized.includes("does not exist")) {
    return uiNotice(
      text,
      "선택된 소스 파일을 찾지 못했습니다.",
      "현재 설정이 가리키는 WAV 파일이 없습니다. Source Library에서 존재하는 파일을 다시 선택하세요.",
      "error",
    );
  }
  if (
    normalized.includes("stack") ||
    normalized.includes("voice") ||
    normalized.includes("accepted_clip_path")
  ) {
    return uiNotice(
      text,
      "목소리 스택 처리 중 오류가 발생했습니다.",
      "녹음 파일을 스택에 반영하지 못했습니다. 최근 이벤트와 Voice Stack 소스 상태를 확인하세요.",
      "error",
    );
  }
  if (
    normalized.includes("stream") ||
    normalized.includes("output") ||
    normalized.includes("playback") ||
    normalized.includes("player") ||
    normalized.includes("mix") ||
    normalized.includes("render")
  ) {
    return uiNotice(
      text,
      "오디오 출력 처리 중 오류가 발생했습니다.",
      "출력 스트림, 렌더링 파일, 또는 믹서 상태에서 문제가 발생했습니다. 출력 장치와 최근 이벤트를 확인하세요.",
      fallbackSeverity,
    );
  }
  if (normalized.includes("recording") || normalized.includes("recorder")) {
    return uiNotice(
      text,
      "녹음 처리 중 오류가 발생했습니다.",
      "녹음을 시작하거나 저장하는 중 문제가 발생했습니다. 입력 장치와 녹음 준비 상태를 확인하세요.",
      "error",
    );
  }
  if (
    normalized.includes("settings") ||
    normalized.includes("draft") ||
    normalized.includes("invalid json")
  ) {
    return uiNotice(
      text,
      "설정 처리 중 오류가 발생했습니다.",
      "설정 저장 또는 불러오기에 실패했습니다. 저장하지 않은 변경을 확인하고 다시 시도하세요.",
      "error",
    );
  }
  if (normalized.includes("participant")) {
    return uiNotice(
      text,
      "참여자 정보를 처리하는 중 오류가 발생했습니다.",
      "참여자 수 저장 파일을 처리하지 못했습니다. data 디렉터리 쓰기 권한을 확인하세요.",
      "error",
    );
  }
  if (normalized.includes("websocket") || normalized.includes("json")) {
    return uiNotice(
      text,
      "실시간 상태를 해석하지 못했습니다.",
      "브라우저가 받은 실시간 상태 메시지를 읽지 못했습니다. 잠시 후 자동 재연결 상태를 확인하세요.",
      "caution",
    );
  }
  if (normalized.includes("not ready") || normalized.includes("runtime")) {
    return uiNotice(
      text,
      "앱 실행 준비가 아직 끝나지 않았습니다.",
      "서버가 오디오 런타임을 준비하는 중입니다. 계속 반복되면 서버를 재시작하세요.",
      "caution",
    );
  }
  if (normalized.includes("unavailable") || normalized.includes("busy")) {
    return uiNotice(
      text,
      "현재 이 작업을 사용할 수 없습니다.",
      "다른 작업이 진행 중이거나 필요한 장치가 준비되지 않았습니다. 진행 중인 작업이 끝난 뒤 다시 시도하세요.",
      "caution",
    );
  }
  if (normalized.includes("missing") || normalized.includes("not found")) {
    return uiNotice(
      text,
      "필요한 파일이나 데이터를 찾지 못했습니다.",
      "설정이 가리키는 파일이나 데이터가 없습니다. System 패널과 Source Library를 확인하세요.",
      "error",
    );
  }
  if (normalized.includes("invalid")) {
    return uiNotice(
      text,
      "입력값이 올바르지 않습니다.",
      "요청에 포함된 값이 허용 범위를 벗어났습니다. 값을 확인하고 다시 시도하세요.",
      "error",
    );
  }
  if (normalized.includes("cannot")) {
    return uiNotice(
      text,
      "현재 상태에서는 이 작업을 실행할 수 없습니다.",
      "현재 녹음, 적용, 또는 출력 상태와 충돌하는 작업입니다. 상태가 바뀐 뒤 다시 시도하세요.",
      "caution",
    );
  }
  return uiNotice(text, "작업 중 오류가 발생했습니다.", genericNoticeDetail, fallbackSeverity);
};

const translateUiErrorMessage = (message) => {
  const notice = describeUiNotice(message);
  return notice ? notice.summary : "";
};

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

const storageModeDetails = {
  "live_ephemeral": {
    label: "운영 모드",
    optionLabel: "전시",
    summary: "파일 안 남김",
    idleTitle: "개별 accepted clip 파일을 남기지 않습니다.",
    className: "safe",
  },
  "test_library": {
    label: "테스트 모드",
    optionLabel: "테스트 저장",
    summary: "파일 저장",
    idleTitle: "accepted clip을 data/processed/accepted에 저장합니다.",
    className: "library",
  },
};

const playbackApplyModeDetails = {
  live: {
    label: "즉시 반영",
    buttonId: "playbackApplyModeLiveButton",
    summary: "Live · 재생 중 바로 적용",
    className: "live",
  },
  stable: {
    label: "안정 적용",
    buttonId: "playbackApplyModeStableButton",
    summary: "Stable · 적용 후 재생",
    className: "stable",
  },
};

const storageModeBusyTitle = "녹음 중이거나 적용 중일 때는 보관 모드를 바꿀 수 없습니다.";

const eventTypeLabels = {
  "system.startup": "시스템 시작",
  "system.startup_playback_unavailable": "시작 재생 준비 실패",
  "system.startup_playback_autostart_failed": "자동 출력 시작 실패",
  "settings.applied": "설정 적용",
  "settings.apply_failed": "설정 적용 실패",
  "settings.apply_rejected": "설정 적용 보류",
  "playback.started": "출력 시작",
  "playback.stopped": "출력 중지",
  "playback.start_failed": "출력 시작 실패",
  "playback.stop_failed": "출력 중지 실패",
  "playback.restart_failed": "출력 재시작 실패",
  "recording.start": "녹음 시작",
  "recording.stop": "녹음 종료",
  "recording.accepted": "녹음 추가",
  "recording.discarded": "녹음 폐기",
  "recording.start_failed": "녹음 시작 실패",
  "recording.render_failed": "녹음 렌더링 실패",
};

const formatEventType = (eventType) => eventTypeLabels[eventType] || "시스템 이벤트";

const dbMarkLabel = (value) => `${value > 0 ? "+" : ""}${value} dB`;

const zeroCenteredDbMarks = (min, max) => [
  { value: min, label: dbMarkLabel(min) },
  { value: 0, label: "0 dB" },
  { value: max, label: dbMarkLabel(max) },
];

const graphEqMinFrequencyHz = 20;
const graphEqMaxFrequencyHz = 20000;
const graphEqMinGainDb = -15;
const graphEqMaxGainDb = 15;
const graphEqMaxPoints = 8;
const graphEqDefaultBellQ = 1.4;
const graphEqDefaultShelfQ = 0.707;

const graphEqPointTypes = Object.freeze({
  bell: "Bell / Peak",
  low_shelf: "Low Shelf",
  high_shelf: "High Shelf",
});

const isFixedGraphEqShelfPoint = (point) => (
  point?.type === "low_shelf" || point?.type === "high_shelf"
);

const defaultGraphEqPoints = () => [
  { id: "low", type: "low_shelf", frequency_hz: 80, gain_db: 0, q: graphEqDefaultShelfQ },
  { id: "mid", type: "bell", frequency_hz: 1000, gain_db: 0, q: graphEqDefaultBellQ },
  { id: "high", type: "high_shelf", frequency_hz: 10000, gain_db: 0, q: graphEqDefaultShelfQ },
];

const graphEqFilterGroup = {
  title: "Filter Range",
  note: "필터가 통과시킬 대역을 정합니다.",
  className: "filter-group",
  layout: "filter-pair-grid",
  action: "reset-filter",
  controls: [
    {
      path: "eq.highpass_hz",
      label: "Low Cut",
      min: 20,
      max: 500,
      step: 1,
      suffix: " Hz",
      kind: "filter",
      scale: "log-frequency",
      commitOn: "change",
      rangeLabel: "below cut",
      marks: [
        { value: 20, label: "20" },
        { value: 80, label: "80" },
        { value: 200, label: "200" },
        { value: 500, label: "500" },
      ],
      description: "이 값보다 낮은 소리를 줄입니다.",
    },
    {
      path: "eq.lowpass_hz",
      label: "High Cut",
      min: 2000,
      max: 20000,
      step: 10,
      suffix: " Hz",
      kind: "filter",
      scale: "log-frequency",
      commitOn: "change",
      rangeLabel: "above cut",
      marks: [
        { value: 2000, label: "2k" },
        { value: 5000, label: "5k" },
        { value: 10000, label: "10k" },
        { value: 20000, label: "20k" },
      ],
      description: "이 값보다 높은 소리를 줄입니다.",
    },
  ],
};

const clampNumber = (value, min, max) => Math.min(max, Math.max(min, Number(value)));

const normalizeGraphEqPoint = (point, index = 0) => {
  const fallback = defaultGraphEqPoints()[index] || defaultGraphEqPoints()[1];
  const type = graphEqPointTypes[point?.type] ? point.type : fallback.type;
  return {
    id: String(point?.id || fallback.id || `point-${index + 1}`),
    type,
    frequency_hz: clampNumber(
      point?.frequency_hz ?? fallback.frequency_hz,
      graphEqMinFrequencyHz,
      graphEqMaxFrequencyHz,
    ),
    gain_db: clampNumber(point?.gain_db ?? fallback.gain_db, graphEqMinGainDb, graphEqMaxGainDb),
    q: clampNumber(point?.q ?? fallback.q ?? 1, 0.1, 18),
  };
};

const graphEqBasePoints = (eq = {}) => (
  Array.isArray(eq.points) && eq.points.length > 0
    ? eq.points.slice(0, graphEqMaxPoints).map(normalizeGraphEqPoint)
    : defaultGraphEqPoints()
);

const graphEqPointWithFixedShelfDefaults = (point, type) => {
  const fallback = defaultGraphEqPoints().find((candidate) => candidate.type === type);
  return normalizeGraphEqPoint({
    ...fallback,
    ...point,
    id: point?.id || fallback?.id,
    type,
    frequency_hz: fallback?.frequency_hz,
    q: point?.q ?? fallback?.q,
  });
};

const isGraphEqPointDeletable = (point) => point?.type === "bell";

const graphEqOrderedPoints = (points = []) => {
  const normalized = (Array.isArray(points) ? points : [])
    .slice(0, graphEqMaxPoints)
    .map(normalizeGraphEqPoint);
  const defaults = defaultGraphEqPoints();
  const lowShelf = graphEqPointWithFixedShelfDefaults(
    normalized.find((point) => point.type === "low_shelf") || defaults[0],
    "low_shelf",
  );
  const highShelf = graphEqPointWithFixedShelfDefaults(
    normalized.find((point) => point.type === "high_shelf") || defaults[2],
    "high_shelf",
  );
  const bellCapacity = Math.max(0, graphEqMaxPoints - 2);
  const bells = normalized
    .filter((point) => point.type === "bell")
    .slice(0, bellCapacity)
    .map((point, index) => ({
      point: normalizeGraphEqPoint({ ...point, type: "bell", q: point.q ?? graphEqDefaultBellQ }),
      index,
    }))
    .sort((a, b) => (
      Number(a.point.frequency_hz) - Number(b.point.frequency_hz) ||
        a.index - b.index
    ))
    .map(({ point }) => point);
  return [lowShelf, ...bells, highShelf];
};

const graphEqPointsMatchDefaults = (points) => {
  const defaults = defaultGraphEqPoints();
  return points.length === defaults.length && points.every((point, index) => (
    point.id === defaults[index].id &&
    point.type === defaults[index].type &&
    Number(point.frequency_hz) === Number(defaults[index].frequency_hz) &&
    Number(point.gain_db) === Number(defaults[index].gain_db) &&
    Number(point.q) === Number(defaults[index].q)
  ));
};

const graphEqUsesLegacyFields = (eq = {}) => (
  graphEqPointsMatchDefaults(graphEqBasePoints(eq)) &&
  (
    Number(eq.low_gain_db || 0) !== 0 ||
    Number(eq.mid_gain_db || 0) !== 0 ||
    Number(eq.high_gain_db || 0) !== 0
  )
);

const graphEqEffectivePoints = (eq = {}) => {
  if (!graphEqUsesLegacyFields(eq)) return graphEqOrderedPoints(graphEqBasePoints(eq));
  return graphEqOrderedPoints([
    {
      id: "legacy-low",
      type: "low_shelf",
      frequency_hz: 80,
      gain_db: Number(eq.low_gain_db || 0),
      q: graphEqDefaultShelfQ,
    },
    {
      id: "legacy-mid",
      type: "bell",
      frequency_hz: 1000,
      gain_db: Number(eq.mid_gain_db || 0),
      q: graphEqDefaultBellQ,
    },
    {
      id: "legacy-high",
      type: "high_shelf",
      frequency_hz: 10000,
      gain_db: Number(eq.high_gain_db || 0),
      q: graphEqDefaultShelfQ,
    },
  ]);
};

const normalizeGraphEqSettings = (eq = {}) => {
  const points = graphEqEffectivePoints(eq);
  return {
    ...eq,
    points,
    highpass_hz: clampNumber(eq.highpass_hz ?? 20, 20, 1000),
    lowpass_hz: clampNumber(eq.lowpass_hz ?? 20000, 1000, 20000),
  };
};

const graphEqLiveStatusCopy = (liveGraphEq = {}) => {
  if (!liveGraphEq) return null;
  if (liveGraphEq.status === "slow" || liveGraphEq.slow_caution) {
    return {
      label: "Live Graph EQ 적용이 지연되고 있습니다.",
      detail: "재생은 이전 상태로 계속됩니다.",
      className: "status-pill caution",
    };
  }
  if (liveGraphEq.status === "failed" || liveGraphEq.failure_warning) {
    const failureDetail = liveGraphEq.failure_detail || "기존 재생 상태를 유지합니다.";
    return {
      label: liveGraphEq.failure_warning || (
        "Live Graph EQ 적용을 완료하지 못했습니다. 기존 재생 상태를 유지합니다. "
        + "필요하면 Stable Apply and Restart로 적용하세요."
      ),
      detail: [
        failureDetail,
        "현재 들리는 EQ는 마지막 성공 상태입니다.",
      ].filter(Boolean).join(" "),
      className: "status-pill caution",
    };
  }
  if (liveGraphEq.status === "pending") {
    return {
      label: "Live Graph EQ 적용 대기 중",
      detail: "약 1초 debounce 후 최신 곡선만 적용합니다.",
      className: "status-pill caution",
    };
  }
  if (liveGraphEq.status === "applied") {
    return {
      label: "Live Graph EQ 적용됨",
      detail: "현재 들리는 EQ가 마지막 성공 상태입니다.",
      className: "status-pill safe",
    };
  }
  return null;
};

const liveGraphEqRequestLayerId = (liveGraphEq = {}) => (
  layerIds.includes(liveGraphEq?.layer_id) ? liveGraphEq.layer_id : null
);

const liveGraphEqRequestId = (liveGraphEq = {}) => {
  const requestId = Number(liveGraphEq?.request_id);
  return Number.isSafeInteger(requestId) && requestId > 0 ? requestId : null;
};

const rememberLiveGraphEqRequest = (liveGraphEq = {}) => {
  const layerId = liveGraphEqRequestLayerId(liveGraphEq);
  const requestId = liveGraphEqRequestId(liveGraphEq);
  if (!layerId || requestId === null) return;
  const previousRequestId = state.liveGraphEqLatestRequestIds[layerId] || 0;
  state.liveGraphEqLatestRequestIds[layerId] = Math.max(previousRequestId, requestId);
};

const liveGraphEqKnownRequestId = (layerId) => {
  const trackedRequestId = state.liveGraphEqLatestRequestIds[layerId] || 0;
  const snapshotLiveGraphEq = state.snapshot?.playback?.live_graph_eq;
  if (liveGraphEqRequestLayerId(snapshotLiveGraphEq) !== layerId) return trackedRequestId;
  return Math.max(trackedRequestId, liveGraphEqRequestId(snapshotLiveGraphEq) || 0);
};

const liveGraphEqPayloadIsOlder = (payload = {}) => {
  const liveGraphEq = payload?.playback?.live_graph_eq;
  const layerId = liveGraphEqRequestLayerId(liveGraphEq);
  const requestId = liveGraphEqRequestId(liveGraphEq);
  if (!layerId || requestId === null) return false;
  return requestId < liveGraphEqKnownRequestId(layerId);
};

const graphEqFrequencyToX = (frequencyHz) => {
  const minLog = Math.log10(graphEqMinFrequencyHz);
  const maxLog = Math.log10(graphEqMaxFrequencyHz);
  return (Math.log10(clampNumber(frequencyHz, graphEqMinFrequencyHz, graphEqMaxFrequencyHz)) - minLog) /
    (maxLog - minLog);
};

const graphEqXToFrequency = (x) => {
  const minLog = Math.log10(graphEqMinFrequencyHz);
  const maxLog = Math.log10(graphEqMaxFrequencyHz);
  return 10 ** (minLog + clampNumber(x, 0, 1) * (maxLog - minLog));
};

const graphEqGainToY = (gainDb) => (
  (graphEqMaxGainDb - clampNumber(gainDb, graphEqMinGainDb, graphEqMaxGainDb)) /
  (graphEqMaxGainDb - graphEqMinGainDb)
);

const graphEqYToGain = (y) => (
  graphEqMaxGainDb - clampNumber(y, 0, 1) * (graphEqMaxGainDb - graphEqMinGainDb)
);

const graphEqPointResponseGain = (frequencyHz, point) => {
  const center = clampNumber(point.frequency_hz, graphEqMinFrequencyHz, graphEqMaxFrequencyHz);
  const gain = Number(point.gain_db) || 0;
  const q = Math.max(Number(point.q) || 1, 0.1);
  if (point.type === "bell") {
    const octaveDistance = Math.log2(frequencyHz / center);
    return gain / (1 + (octaveDistance * q * 2) ** 2);
  }
  if (point.type === "low_shelf") {
    return gain / (1 + (frequencyHz / center) ** (q * 2));
  }
  if (point.type === "high_shelf") {
    return gain / (1 + (center / frequencyHz) ** (q * 2));
  }
  return 0;
};

const graphEqLockedEndpointX = (point) => {
  if (point?.type === "low_shelf") return 0;
  if (point?.type === "high_shelf") return 1;
  return null;
};

const graphEqPointScreenGain = (point, index = null, points = []) => {
  const lockedX = graphEqLockedEndpointX(point, index, points);
  if (lockedX === null) return Number(point.gain_db) || 0;
  return graphEqPointResponseGain(graphEqXToFrequency(lockedX), point);
};

const graphEqPointScreenPosition = (point, index = null, points = []) => {
  const lockedX = graphEqLockedEndpointX(point, index, points);
  return {
    x: lockedX ?? graphEqFrequencyToX(point.frequency_hz),
    y: graphEqGainToY(graphEqPointScreenGain(point, index, points)),
  };
};

const graphEqVisualResponsePoints = (eq, width = 96) => {
  const normalized = normalizeGraphEqSettings(eq);
  const sampleCount = Math.max(2, width);
  const controlPointSamples = new Map(
    normalized.points.map((point) => {
      const x = graphEqFrequencyToX(point.frequency_hz);
      return [Math.round(x * (sampleCount - 1)), x];
    }),
  );
  return Array.from({ length: sampleCount }, (_value, index) => {
    const x = controlPointSamples.get(index) ?? index / (sampleCount - 1);
    const frequencyHz = graphEqXToFrequency(x);
    const gainDb = normalized.points.reduce(
      (total, point) => total + graphEqPointResponseGain(frequencyHz, point),
      0,
    );
    const clampedGainDb = clampNumber(gainDb, graphEqMinGainDb, graphEqMaxGainDb);
    return {
      frequency_hz: frequencyHz,
      gain_db: clampedGainDb,
      x,
      y: graphEqGainToY(clampedGainDb),
    };
  });
};

const graphEqNearestPointId = (eq, pointer) => {
  const normalized = normalizeGraphEqSettings(eq);
  if (!normalized.points.length) return null;
  return normalized.points
    .map((point, index) => {
      const position = graphEqPointScreenPosition(point, index, normalized.points);
      const dx = position.x - clampNumber(pointer?.x ?? 0, 0, 1);
      const dy = position.y - clampNumber(pointer?.y ?? 0, 0, 1);
      return { id: point.id, distance: Math.hypot(dx * 1.25, dy) };
    })
    .sort((a, b) => a.distance - b.distance)[0].id;
};

const graphEqPointFromPointerRatio = (pointer) => ({
  frequency_hz: Math.round(graphEqXToFrequency(pointer?.x ?? 0)),
  gain_db: Number(graphEqYToGain(pointer?.y ?? 0).toFixed(1)),
});

const graphEqPointGainForScreenGain = (point, screenGainDb, lockedX) => {
  const frequencyHz = graphEqXToFrequency(lockedX);
  const responseFactor = graphEqPointResponseGain(frequencyHz, {
    ...point,
    gain_db: 1,
  });
  if (!Number.isFinite(responseFactor) || Math.abs(responseFactor) < 0.0001) {
    return screenGainDb;
  }
  return clampNumber(screenGainDb / responseFactor, graphEqMinGainDb, graphEqMaxGainDb);
};

const graphEqPointUpdatesFromPointerRatio = (point, pointer, index = null, points = []) => {
  const updates = graphEqPointFromPointerRatio(pointer);
  const lockedX = graphEqLockedEndpointX(point, index, points);
  if (lockedX === null) return updates;
  return {
    gain_db: updates.gain_db,
  };
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
        min: -60,
        max: 12,
        step: 0.5,
        suffix: " dB",
        kind: "level",
        scale: "zero-centered-db",
        marks: zeroCenteredDbMarks(-60, 12),
        description: "공간 안에서 이 레이어가 차지하는 전체 크기입니다.",
      },
    ],
  },
  graphEqFilterGroup,
];

const recordingControlGroups = [
  {
    title: "목소리 음역",
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
        scale: "log-frequency",
        commitOn: "change",
        rangeLabel: "rumble cut",
        marks: [
          { value: 40, label: "40" },
          { value: 80, label: "80" },
          { value: 150, label: "150" },
          { value: 300, label: "300" },
        ],
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
        scale: "log-frequency",
        commitOn: "change",
        rangeLabel: "air cut",
        marks: [
          { value: 4000, label: "4k" },
          { value: 8000, label: "8k" },
          { value: 12000, label: "12k" },
          { value: 16000, label: "16k" },
        ],
        description: "거친 고역이나 공간 노이즈를 줄입니다.",
      },
      {
        path: "presence_gain_db",
        label: { ko: "존재감", en: "Presence" },
        min: -18,
        max: 12,
        step: 0.5,
        suffix: " dB",
        kind: "eq",
        band: "high",
        scale: "zero-centered-db",
        marks: zeroCenteredDbMarks(-18, 12),
        rangeLabel: "2 kHz+",
        description: "목소리가 앞으로 나오거나 뒤로 물러나는 느낌입니다.",
      },
    ],
  },
  {
    title: "입력 안정화",
    note: "녹음 소스의 기본 크기와 피크를 정리합니다.",
    className: "input-safety-group",
    collapsible: true,
    open: true,
    controls: [
      {
        path: "gain_db",
        label: { ko: "입력 게인", en: "Input Gain" },
        min: -60,
        max: 24,
        step: 0.5,
        suffix: " dB",
        kind: "level",
        scale: "zero-centered-db",
        marks: zeroCenteredDbMarks(-60, 24),
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
    title: "공간감",
    note: "전시장 안개감과 잔향의 길이를 만듭니다.",
    className: "space-tail-group",
    collapsible: true,
    open: true,
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
  {
    path: "insert_gain_db",
    label: { ko: "스택 추가 게인", en: "Insert Gain" },
    min: -60,
    max: 12,
    step: 0.5,
    suffix: " dB",
    kind: "level",
    scale: "zero-centered-db",
    defaultValue: -12,
    marks: zeroCenteredDbMarks(-60, 12),
    description: "새 목소리가 Voice Stack에 섞일 때의 기본 크기입니다.",
  },
];

const playbackTransitionControlDef = {
  path: "transition_seconds",
  label: { ko: "전환 시간", en: "Transition" },
  min: 0,
  max: 10,
  step: 1,
  suffix: " s",
  kind: "space",
  rangeLabel: "Off · 3s default · 10s",
  defaultValue: 3,
  positiveToggle: true,
  description: "0s면 겹침 없이 교체하고, 1s 이상이면 새 루프가 겹쳐 fade 됩니다.",
  marks: [
    { value: 0, label: "Off" },
    { value: 1, label: "1s" },
    { value: 3, label: "3s" },
    { value: 10, label: "10s" },
  ],
};

const layerPresetLabels = {
  "Warm Bed": { ko: "따뜻한 바닥", en: "Warm Bed" },
  "Clear Pocket": { ko: "목소리 자리", en: "Clear Pocket" },
  "Distant Air": { ko: "먼 공기감", en: "Distant Air" },
};

const layerPresetDefs = {
  "Warm Bed": {
    volume_db: -13,
  },
  "Clear Pocket": {
    volume_db: -14,
  },
  "Distant Air": {
    volume_db: -18,
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
  return date.toLocaleString("ko-KR", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const formatShortTimestamp = (value) => {
  if (!value) return "시간 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${date.getMonth() + 1}/${date.getDate()} ${hours}:${minutes}`;
};

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

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

const liveApplyFeedbackStates = Object.freeze({
  idle: "idle",
  pending: "pending",
  applying: "applying",
  applied: "applied",
  failed: "failed",
  stale: "stale",
});

const liveApplyResponseEventTypes = new Set(["request_succeeded", "request_failed"]);

const cloneApplyFeedbackValue = (value) => (value === undefined ? undefined : clone(value));

const eventValueOrCurrent = (event, current, key) => (
  Object.hasOwn(event, key) ? cloneApplyFeedbackValue(event[key]) : cloneApplyFeedbackValue(current[key])
);

const createLiveApplyFeedbackState = (value = {}) => {
  value = value || {};
  const confirmedValue = cloneApplyFeedbackValue(value.confirmedValue);
  const rollbackValue = Object.hasOwn(value, "rollbackValue")
    ? cloneApplyFeedbackValue(value.rollbackValue)
    : cloneApplyFeedbackValue(confirmedValue);
  return {
    feedbackState: value.feedbackState || liveApplyFeedbackStates.idle,
    requestId: Number.isFinite(Number(value.requestId)) ? Number(value.requestId) : 0,
    modeEpoch: Number.isFinite(Number(value.modeEpoch)) ? Number(value.modeEpoch) : 0,
    coveredCardId: value.coveredCardId ?? null,
    controlIds: Array.isArray(value.controlIds) ? [...value.controlIds] : [],
    draftValue: cloneApplyFeedbackValue(value.draftValue),
    confirmedValue,
    rollbackValue,
    warningMessage: value.warningMessage || "",
    spinnerVisible: Boolean(value.spinnerVisible),
    staleResponse: value.staleResponse ? { ...value.staleResponse } : null,
  };
};

const staleLiveApplyResponse = (event = {}) => ({
  feedbackState: liveApplyFeedbackStates.stale,
  requestId: Number.isFinite(Number(event.requestId)) ? Number(event.requestId) : null,
  modeEpoch: Number.isFinite(Number(event.modeEpoch)) ? Number(event.modeEpoch) : null,
});

const liveApplyResponseIsStale = (current = {}, event = {}) => {
  if (!liveApplyResponseEventTypes.has(event.type)) return false;
  const stateModel = createLiveApplyFeedbackState(current);
  if (stateModel.feedbackState === liveApplyFeedbackStates.stale) return true;
  return Number(event.requestId) !== stateModel.requestId ||
    Number(event.modeEpoch) !== stateModel.modeEpoch;
};

const reduceLiveApplyFeedbackState = (current = {}, event = {}) => {
  const stateModel = createLiveApplyFeedbackState(current);
  if (liveApplyResponseIsStale(stateModel, event)) {
    return {
      ...stateModel,
      staleResponse: staleLiveApplyResponse(event),
    };
  }

  if (event.type === "edit") {
    return {
      ...stateModel,
      feedbackState: liveApplyFeedbackStates.pending,
      requestId: Number.isFinite(Number(event.requestId)) ? Number(event.requestId) : stateModel.requestId,
      modeEpoch: Number.isFinite(Number(event.modeEpoch)) ? Number(event.modeEpoch) : stateModel.modeEpoch,
      coveredCardId: event.coveredCardId ?? stateModel.coveredCardId,
      controlIds: Array.isArray(event.controlIds) ? [...event.controlIds] : stateModel.controlIds,
      draftValue: eventValueOrCurrent(event, stateModel, "draftValue"),
      rollbackValue: cloneApplyFeedbackValue(stateModel.confirmedValue),
      warningMessage: "",
      spinnerVisible: false,
      staleResponse: null,
    };
  }

  if (event.type === "request_started") {
    return {
      ...stateModel,
      feedbackState: liveApplyFeedbackStates.applying,
      requestId: Number.isFinite(Number(event.requestId)) ? Number(event.requestId) : stateModel.requestId,
      modeEpoch: Number.isFinite(Number(event.modeEpoch)) ? Number(event.modeEpoch) : stateModel.modeEpoch,
      coveredCardId: event.coveredCardId ?? stateModel.coveredCardId,
      controlIds: Array.isArray(event.controlIds) ? [...event.controlIds] : stateModel.controlIds,
      draftValue: eventValueOrCurrent(event, stateModel, "draftValue"),
      rollbackValue: cloneApplyFeedbackValue(stateModel.confirmedValue),
      warningMessage: "",
      spinnerVisible: true,
      staleResponse: null,
    };
  }

  if (event.type === "live_render_pending") {
    return {
      ...stateModel,
      feedbackState: liveApplyFeedbackStates.applying,
      requestId: Number.isFinite(Number(event.requestId)) ? Number(event.requestId) : stateModel.requestId,
      modeEpoch: Number.isFinite(Number(event.modeEpoch)) ? Number(event.modeEpoch) : stateModel.modeEpoch,
      warningMessage: "",
      spinnerVisible: true,
      staleResponse: null,
    };
  }

  if (event.type === "request_succeeded") {
    const confirmedValue = Object.hasOwn(event, "confirmedValue")
      ? cloneApplyFeedbackValue(event.confirmedValue)
      : cloneApplyFeedbackValue(stateModel.draftValue);
    return {
      ...stateModel,
      feedbackState: liveApplyFeedbackStates.applied,
      draftValue: cloneApplyFeedbackValue(confirmedValue),
      confirmedValue: cloneApplyFeedbackValue(confirmedValue),
      rollbackValue: cloneApplyFeedbackValue(confirmedValue),
      warningMessage: "",
      spinnerVisible: false,
      staleResponse: null,
    };
  }

  if (event.type === "request_failed") {
    const rollbackValue = cloneApplyFeedbackValue(stateModel.rollbackValue);
    return {
      ...stateModel,
      feedbackState: liveApplyFeedbackStates.failed,
      draftValue: rollbackValue,
      rollbackValue,
      warningMessage: event.warningMessage || settingsApplyFailureCautionMessage,
      spinnerVisible: false,
      staleResponse: null,
    };
  }

  if (event.type === "mode_changed") {
    const nextEpoch = Number.isFinite(Number(event.modeEpoch))
      ? Number(event.modeEpoch)
      : stateModel.modeEpoch + 1;
    return {
      ...stateModel,
      feedbackState: liveApplyFeedbackStates.stale,
      modeEpoch: nextEpoch,
      warningMessage: "",
      spinnerVisible: false,
      staleResponse: null,
    };
  }

  return stateModel;
};

const deriveLiveApplyFeedbackVisualState = (feedbackState = {}) => {
  const stateModel = createLiveApplyFeedbackState(feedbackState);
  const active = stateModel.feedbackState === liveApplyFeedbackStates.pending ||
    stateModel.feedbackState === liveApplyFeedbackStates.applying;
  return {
    visual_state: active ? "pending" : "idle",
    show_spinner: active && stateModel.spinnerVisible,
  };
};

const isPlainObject = (value) =>
  Boolean(value && typeof value === "object" && !Array.isArray(value));

const stableSettingsValue = (value) => {
  if (Array.isArray(value)) return value.map(stableSettingsValue);
  if (!isPlainObject(value)) return value;
  return Object.keys(value)
    .sort()
    .reduce((normalized, key) => {
      normalized[key] = stableSettingsValue(value[key]);
      return normalized;
    }, {});
};

const stableSettingsSignature = (value) => JSON.stringify(stableSettingsValue(value));

const presetValueMatches = (current, expected) => {
  if (isPlainObject(expected)) return presetValuesMatch(current, expected);
  const currentNumber = Number(current);
  const expectedNumber = Number(expected);
  if (Number.isFinite(currentNumber) && Number.isFinite(expectedNumber)) {
    return currentNumber === expectedNumber;
  }
  return current === expected;
};

const presetValuesMatch = (draft, preset) => {
  if (!draft || !preset) return false;
  return Object.entries(preset).every(([key, value]) => presetValueMatches(draft[key], value));
};

const mergePresetValues = (draft, preset) => {
  const next = clone(draft);
  const mergeInto = (target, values) => {
    Object.entries(values).forEach(([key, value]) => {
      if (isPlainObject(value)) {
        target[key] = isPlainObject(target[key]) ? { ...target[key] } : {};
        mergeInto(target[key], value);
      } else {
        target[key] = value;
      }
    });
  };
  mergeInto(next, preset);
  return next;
};

const presetFeedbackControlIds = (prefix, preset) => {
  const paths = [];
  const appendPaths = (basePath, values) => {
    Object.entries(values || {}).forEach(([key, value]) => {
      const path = `${basePath}.${key}`;
      if (isPlainObject(value)) appendPaths(path, value);
      else paths.push(path);
    });
  };
  appendPaths(prefix, preset);
  return paths;
};

const presetSelectionMatches = (draft, presetDefs, selection) => {
  if (!selection?.name) return false;
  const preset = presetDefs[selection.name];
  return Boolean(preset && presetValuesMatch(draft, preset));
};

const reversiblePresetDraft = (currentDraft, presetDefs, presetName, currentSelection = null) => {
  const preset = presetDefs[presetName];
  if (!currentDraft || !preset) {
    return { draft: currentDraft, selection: currentSelection || null };
  }
  if (
    currentSelection?.name === presetName &&
    presetSelectionMatches(currentDraft, presetDefs, currentSelection)
  ) {
    return { draft: clone(currentSelection.previousDraft), selection: null };
  }
  return {
    draft: mergePresetValues(currentDraft, preset),
    selection: {
      name: presetName,
      previousDraft: clone(currentDraft),
    },
  };
};

const clearLayerPresetSelection = (layerId) => {
  delete state.presetSelections.layers[layerId];
};

const clearRecordingPresetSelection = () => {
  state.presetSelections.recording = null;
};

const selectedLayerPresetName = (layerId) => {
  const selection = state.presetSelections.layers[layerId];
  const layer = state.draft?.layers?.[layerId];
  if (!selection) return null;
  if (presetSelectionMatches(layer, layerPresetDefs, selection)) return selection.name;
  clearLayerPresetSelection(layerId);
  return null;
};

const layerPresetIsSelected = (layerId, presetName) =>
  selectedLayerPresetName(layerId) === presetName;

const selectedRecordingPresetName = () => {
  const selection = state.presetSelections.recording;
  if (!selection) return null;
  if (presetSelectionMatches(state.draft?.recording, recordingPresetDefs, selection)) {
    return selection.name;
  }
  clearRecordingPresetSelection();
  return null;
};

const recordingPresetIsSelected = (name) => selectedRecordingPresetName() === name;

const deferredInteractiveRenderTargets = new WeakSet();
const deferredInteractiveRenderControls = {};
const interactiveControlTags = new Set(["SELECT", "INPUT", "TEXTAREA"]);
const deferredInteractiveControlTags = new Set([...interactiveControlTags, "BUTTON"]);
deferredInteractiveControlTags.add("SUMMARY");
const settingsControlContainerIds = [
  "storageModePanel",
  "layerControls",
  "voiceLayerControls",
  "voiceStackControls",
  "playbackTransitionControls",
  "recordingControls",
  "playbackApplyModePanel",
];

const playbackSeekSliderActive = () => state.activeInteractiveControl === $("playbackSeekSlider");

const deferPlaybackTimelineRender = () => {
  if (!playbackSeekSliderActive()) return false;
  state.deferredInteractiveRenders["playback-timeline"] = renderPlaybackTimeline;
  deferredInteractiveRenderControls["playback-timeline"] = $("playbackSeekSlider");
  return true;
};

const activeInteractiveControlFor = (container) => {
  const tracked = state.activeInteractiveControl;
  if (!container) return null;
  if (tracked && (tracked === container || container.contains?.(tracked))) return tracked;
  const focused = document.activeElement;
  if (
    focused &&
    focused !== state.releasedInteractiveControl &&
    deferredInteractiveControlTags.has(focused.tagName) &&
    (focused === container || container.contains?.(focused))
  ) {
    state.activeInteractiveControl = focused;
    return focused;
  }
  return null;
};

const deferredInteractiveControlFromTarget = (target) => {
  const control = target?.closest?.("select,input,textarea,button,summary") || target;
  if (!control || !deferredInteractiveControlTags.has(control.tagName)) return null;
  return control;
};

const deferredInteractiveControlInContainer = (container, target) => {
  const control = deferredInteractiveControlFromTarget(target);
  if (!control || !container) return null;
  return container === control || container.contains?.(control) ? control : null;
};

const transferDeferredInteractiveRenders = (fromControl, toControl) => {
  Object.entries(deferredInteractiveRenderControls).forEach(([key, control]) => {
    if (control === fromControl) deferredInteractiveRenderControls[key] = toControl;
  });
};

const transferOrReleaseInteractiveControl = (control, nextControl = null) => {
  if (!control) return;
  if (nextControl && nextControl !== control) {
    trackInteractiveControl(nextControl);
    transferDeferredInteractiveRenders(control, nextControl);
    return;
  }
  releaseInteractiveControl(control);
};

const trackDeferredInteractiveBlur = (active, container, nextControlForTarget) => {
  if (deferredInteractiveRenderTargets.has(active)) return;
  deferredInteractiveRenderTargets.add(active);
  active.addEventListener("blur", (event) => {
    deferredInteractiveRenderTargets.delete(active);
    const nextActive = nextControlForTarget(container, event.relatedTarget);
    if (nextActive && nextActive !== active) {
      state.activeInteractiveControl = nextActive;
      transferDeferredInteractiveRenders(active, nextActive);
      trackDeferredInteractiveBlur(nextActive, container, nextControlForTarget);
      return;
    }
    if (state.activeInteractiveControl === active) {
      state.activeInteractiveControl = null;
    }
    flushDeferredInteractiveRenders(active);
  }, { once: true });
};

const deferInteractiveRender = (key, container, renderFn, options = {}) => {
  const active = activeInteractiveControlFor(container);
  if (!active) return false;
  state.deferredInteractiveRenders[key] = renderFn;
  deferredInteractiveRenderControls[key] = active;
  trackDeferredInteractiveBlur(
    active,
    container,
    options.nextControlForTarget || deferredInteractiveControlInContainer,
  );
  return true;
};

const trackInteractiveControl = (element) => {
  state.activeInteractiveControl = element;
  state.releasedInteractiveControl = null;
};

const releaseInteractiveControl = (element) => {
  if (state.activeInteractiveControl === element) {
    state.activeInteractiveControl = null;
  }
  if (element) state.releasedInteractiveControl = element;
  flushDeferredInteractiveRenders(element);
};

const settingsControlContainers = () =>
  settingsControlContainerIds.map((id) => $(id)).filter(Boolean);

const activeSettingsControlContainer = () =>
  settingsControlContainers().find((container) => activeInteractiveControlFor(container)) || null;

const settingsInteractiveControlFromEventTarget = (target) => {
  const control = deferredInteractiveControlFromTarget(target);
  return settingsControlContainers().some((container) => (
    container === control || container.contains?.(control)
  ))
    ? control
    : null;
};

const trackSettingsInteractiveControl = (event) => {
  const control = settingsInteractiveControlFromEventTarget(event.target);
  if (control) trackInteractiveControl(control);
};

const releaseSettingsInteractiveControl = (event) => {
  const control = settingsInteractiveControlFromEventTarget(event.target);
  const nextControl = settingsInteractiveControlFromEventTarget(event.relatedTarget);
  transferOrReleaseInteractiveControl(control, nextControl);
};

const flushDeferredInteractiveRenders = (element) => {
  Object.entries(state.deferredInteractiveRenders).forEach(([key, renderFn]) => {
    if (deferredInteractiveRenderControls[key] !== element) return;
    delete state.deferredInteractiveRenders[key];
    delete deferredInteractiveRenderControls[key];
    renderFn?.();
  });
};

const isStaleRecordingStopError = (error) => {
  if (error?.status && error.status !== 409) return false;
  return String(error?.detail || error?.message || "").toLowerCase().includes("not recording");
};

const clearElement = (element) => {
  element.innerHTML = "";
  element.textContent = "";
  if (Array.isArray(element.children)) {
    element.children.length = 0;
  }
};

const noticeFromMessage = (message, defaultSeverity = "error") => {
  if (!message) return null;
  if (typeof message === "object" && message.summary) return message;
  return describeUiNotice(message, defaultSeverity) || null;
};

const renderErrorBadge = (notices = []) => {
  const activeNotices = notices.filter(Boolean);
  if (activeNotices.length) {
    const severity = highestNoticeSeverity(activeNotices);
    const display = noticeSeverityDisplay[severity];
    $("errorBadge").textContent = display.badge;
    if (severity === "caution") {
      $("errorBadge").className = "status-pill caution";
    } else if (severity === "error") {
      $("errorBadge").className = "status-pill hot";
    } else {
      $("errorBadge").className = "status-pill muted";
    }
  } else {
    $("errorBadge").textContent = "오류 없음";
    $("errorBadge").className = "status-pill muted";
  }
};

const replaceableRecordOutcomeKinds = new Set(["ready", "armed-ready", "recording", "processing"]);

const noticeHeadingElement = (notice) => {
  const heading = document.createElement("div");
  heading.className = "notice-heading";
  const label = document.createElement("span");
  label.className = "notice-label";
  label.textContent = noticeSeverityDisplay[notice.severity].label;
  const summary = document.createElement("strong");
  summary.textContent = notice.summary;
  heading.append(label, summary);
  return heading;
};

const noticeDetailElement = (notice) => {
  const detail = document.createElement("p");
  detail.className = "notice-detail";
  detail.textContent = notice.detail;
  return detail;
};

const noticeDetailKey = (notice) => [notice.severity, notice.summary, notice.technical || ""].join("::");
const noticeDismissKey = noticeDetailKey;
const noticeCanDismiss = (notice) => notice?.severity === "caution";
const noticeIsDismissed = (notice) => (
  noticeCanDismiss(notice) && dismissedNoticeKeys.has(noticeDismissKey(notice))
);

const pruneDismissedNoticeKeys = (notices) => {
  const currentKeys = new Set(
    notices
      .filter(noticeCanDismiss)
      .map((notice) => noticeDismissKey(notice)),
  );
  Array.from(dismissedNoticeKeys).forEach((key) => {
    if (!currentKeys.has(key)) dismissedNoticeKeys.delete(key);
  });
};

const dismissNotices = (notices) => {
  notices.filter(noticeCanDismiss).forEach((notice) => {
    dismissedNoticeKeys.add(noticeDismissKey(notice));
  });
  renderErrors();
};

const collectNoticeDetailElements = (element, result = []) => {
  if (!element?.children) return result;
  Array.from(element.children).forEach((child) => {
    if (child.noticeDetailKey || child.getAttribute?.("data-notice-key")) {
      result.push(child);
    }
    collectNoticeDetailElements(child, result);
  });
  return result;
};

const noticeDetailElements = (container) => {
  const detailElements = container.querySelectorAll?.("details[data-notice-key]");
  const queried = detailElements ? Array.from(detailElements) : [];
  if (queried.length) return queried;
  return collectNoticeDetailElements(container);
};

const rememberNoticeDetailState = (container) => {
  noticeDetailElements(container).forEach((details) => {
    const key = details.getAttribute?.("data-notice-key") || details.noticeDetailKey;
    if (!key) return;
    if (details.open) {
      openNoticeDetailKeys.add(key);
    } else {
      openNoticeDetailKeys.delete(key);
    }
  });
};

const noticeTechnicalElement = (notice) => {
  const details = document.createElement("details");
  const key = noticeDetailKey(notice);
  details.className = "notice-technical";
  details.setAttribute("data-notice-key", key);
  details.noticeDetailKey = key;
  if (openNoticeDetailKeys.has(key)) {
    details.open = true;
  }
  details.addEventListener("toggle", () => {
    if (details.open) {
      openNoticeDetailKeys.add(key);
    } else {
      openNoticeDetailKeys.delete(key);
    }
  });
  const summary = document.createElement("summary");
  summary.textContent = "자세히";
  const technical = document.createElement("p");
  technical.textContent = `원문: ${notice.technical}`;
  details.append(summary, technical);
  return details;
};

const noticeDismissButton = (notices) => {
  const dismissibleNotices = notices.filter(noticeCanDismiss);
  if (!dismissibleNotices.length) return null;
  const severity = highestNoticeSeverity(dismissibleNotices);
  const display = noticeSeverityDisplay[severity];
  const button = document.createElement("button");
  button.type = "button";
  button.className = "notice-dismiss-button";
  button.setAttribute("aria-label", `${display.label} 메시지 닫기`);
  button.textContent = "×";
  button.addEventListener("click", () => dismissNotices(dismissibleNotices));
  return button;
};

const appendNoticeContent = (container, notice, options = {}) => {
  const heading = noticeHeadingElement(notice);
  const dismissButton = options.dismissible ? noticeDismissButton([notice]) : null;
  if (dismissButton) heading.appendChild(dismissButton);
  container.append(
    heading,
    noticeDetailElement(notice),
    noticeTechnicalElement(notice),
  );
};

const noticeItemElement = (notice, elementName = "li", extraClass = "") => {
  const item = document.createElement(elementName);
  item.className = `${extraClass ? `${extraClass} ` : ""}notice-list-item ${notice.severity}`;
  appendNoticeContent(item, notice);
  return item;
};

const renderNoticeBanner = (notices) => {
  const banner = $("errorBanner");
  const normalizedNotices = notices.filter(Boolean);
  pruneDismissedNoticeKeys(normalizedNotices);
  const activeNotices = normalizedNotices.filter((notice) => !noticeIsDismissed(notice));
  renderErrorBadge(activeNotices);
  rememberNoticeDetailState(banner);
  clearElement(banner);
  if (!activeNotices.length) {
    banner.hidden = true;
    banner.className = "error-banner notice-banner";
    return;
  }

  const severity = highestNoticeSeverity(activeNotices);
  const display = noticeSeverityDisplay[severity];
  banner.hidden = false;
  banner.className = `error-banner notice-banner ${severity}`;
  banner.setAttribute("role", display.role);
  banner.setAttribute("aria-live", display.live);

  if (activeNotices.length === 1) {
    appendNoticeContent(banner, activeNotices[0], { dismissible: true });
    return;
  }

  const groupNotice = uiNotice(
    "",
    `${display.label} ${activeNotices.length}개`,
    "아래 항목을 하나씩 확인하세요.",
    severity,
  );
  const heading = noticeHeadingElement(groupNotice);
  const dismissButton = noticeDismissButton(activeNotices);
  if (dismissButton) heading.appendChild(dismissButton);
  banner.append(heading, noticeDetailElement(groupNotice));
  const list = document.createElement("ul");
  list.className = "notice-list";
  activeNotices.forEach((notice) => {
    const item = document.createElement("li");
    item.className = `notice-list-item ${notice.severity}`;
    appendNoticeContent(item, notice);
    list.appendChild(item);
  });
  banner.appendChild(list);
};

const renderNoticeList = (container, notices) => {
  rememberNoticeDetailState(container);
  clearElement(container);
  notices.filter(Boolean).forEach((notice) => {
    const item = document.createElement("li");
    item.className = `notice-list-item ${notice.severity}`;
    const body = document.createElement("div");
    body.className = "notice-list-item-body";
    appendNoticeContent(body, notice);
    item.appendChild(body);
    container.appendChild(item);
  });
};

const setErrorBanner = (message, kind = "error") => {
  const severity = normalizeNoticeSeverity(kind);
  const messages = Array.isArray(message) ? message : [message];
  const notices = messages
    .map((item) => noticeFromMessage(item, severity))
    .filter(Boolean);
  renderNoticeBanner(notices);
};

const showError = (message) => {
  const notice = noticeFromMessage(message, "error");
  state.transientNotice = null;
  state.transientError = notice?.technical || null;
  state.transientErrorShownAt = notice ? Date.now() : 0;
  renderNoticeBanner(notice ? [notice] : []);
};

const settingsApplyFailureNotice = (message = "") => {
  const text = String(message || "").trim();
  const normalized = text.toLowerCase();
  if (normalized.includes("source file") && normalized.includes("does not exist")) {
    return uiNotice(
      text,
      "소스 파일이 없어 변경사항을 적용하지 못했습니다.",
      "Graph EQ와 믹서 변경은 임시 설정에 남아 있지만 활성 재생 설정에는 반영되지 않았습니다. Source Library에서 존재하는 파일을 다시 선택한 뒤 Apply/Restart를 누르세요.",
      "caution",
    );
  }
  return uiNotice(
    text,
    settingsApplyFailureCautionMessage,
    settingsApplyFailureCautionDetail,
    "caution",
  );
};

const showSettingsApplyFailureCaution = (message = "") => {
  const notice = settingsApplyFailureNotice(message);
  state.transientError = null;
  state.transientNotice = notice;
  state.transientErrorShownAt = Date.now();
  renderNoticeBanner([notice]);
};

const transientErrorVisibleLongEnough = () => (
  (!state.transientError && !state.transientNotice) ||
  Date.now() - state.transientErrorShownAt >= transientNoticeMinimumVisibleMs
);

const clearTransientError = (options = {}) => {
  if (
    options.respectMinimumVisibleDuration &&
    state.transientError &&
    !transientErrorVisibleLongEnough()
  ) {
    renderErrors();
    return false;
  }
  state.transientError = null;
  state.transientNotice = null;
  state.transientErrorShownAt = 0;
  renderErrors();
  return true;
};

const requestState = async (options = {}) => {
  const request = beginStateRefresh();
  try {
    const payload = await api("/api/state");
    if (!isCurrentStateRefresh(request)) return payload;
    applyState(payload, { ...options, fromStateRefresh: true });
    return payload;
  } catch (error) {
    if (!isCurrentStateRefresh(request)) return null;
    throw error;
  }
};

const applyResponseState = async (payload, options = {}) => {
  if (payload?.state) {
    return applyState(payload.state, options);
  }
  await requestState(options);
  return false;
};

const beginTrackedRequest = (requestKey, trackedKeys = []) => {
  state[requestKey] += 1;
  return {
    requestKey,
    requestId: state[requestKey],
    tracked: trackedKeys.map((key) => [key, state[key]]),
  };
};

const isCurrentTrackedRequest = (request) =>
  request.requestId === state[request.requestKey] &&
  request.tracked.every(([key, value]) => state[key] === value);

const beginStateRefresh = () => {
  return beginTrackedRequest("stateRefreshRequestId");
};

const isCurrentStateRefresh = (request) =>
  isCurrentTrackedRequest(request);

const invalidatePendingStateRefreshes = () => {
  state.stateRefreshRequestId += 1;
};

const beginDeviceRefresh = (options = {}) => {
  return {
    token: beginTrackedRequest("deviceRefreshRequestId", ["deviceChangeRequestId"]),
    deviceChangeInFlight: state.deviceChangeInFlight,
    allowDuringDeviceChange: options.allowDuringDeviceChange === true,
  };
};

const isCurrentDeviceRefresh = (request) =>
  isCurrentTrackedRequest(request.token) &&
  (
    request.allowDuringDeviceChange ||
    (!request.deviceChangeInFlight && !state.deviceChangeInFlight)
  );

const requestDevices = async (options = {}) => {
  const request = beginDeviceRefresh(options);
  let shouldRender = false;
  try {
    const devices = await api("/api/devices");
    if (!isCurrentDeviceRefresh(request)) return devices;
    state.devices = devices;
    state.deviceError = null;
    shouldRender = true;
    return devices;
  } catch (error) {
    if (!isCurrentDeviceRefresh(request)) return null;
    state.devices = null;
    state.deviceError = error.message;
    shouldRender = true;
    return null;
  } finally {
    if (shouldRender) {
      renderDevices();
      renderSystemStatus();
      renderErrors();
    }
  }
};

const requestDiagnostics = async () => {
  const request = beginDiagnosticsRefresh();
  let shouldRender = false;
  try {
    const diagnostics = await api("/api/diagnostics");
    if (!isCurrentDiagnosticsRefresh(request)) return diagnostics;
    state.diagnostics = diagnostics;
    state.diagnosticsError = null;
    shouldRender = true;
    return diagnostics;
  } catch (error) {
    if (!isCurrentDiagnosticsRefresh(request)) return null;
    state.diagnostics = null;
    state.diagnosticsError = error.message;
    shouldRender = true;
    return null;
  } finally {
    if (shouldRender) {
      renderLastEventBadge();
      renderSystemStatus();
      renderErrors();
    }
  }
};

const beginDiagnosticsRefresh = () => {
  return beginTrackedRequest("diagnosticsRefreshRequestId");
};

const isCurrentDiagnosticsRefresh = (request) =>
  isCurrentTrackedRequest(request);

const beginSourceRefresh = () => {
  return {
    token: beginTrackedRequest("sourceRefreshRequestId", ["sourceMutationRequestId"]),
    sourceMutationInFlight: state.sourceMutationInFlight,
  };
};

const isCurrentSourceRefresh = (request) =>
  isCurrentTrackedRequest(request.token) &&
  !request.sourceMutationInFlight &&
  !state.sourceMutationInFlight;

const requestSources = async (options = {}) => {
  const request = beginSourceRefresh();
  let shouldRender = false;
  try {
    const sources = await api("/api/sources");
    if (!isCurrentSourceRefresh(request)) return sources;
    state.sources = sources;
    state.sourcesError = null;
    if (options.syncAppliedSourceSignature) {
      syncAppliedSourceSignature();
    }
    shouldRender = true;
    return sources;
  } catch (error) {
    if (!isCurrentSourceRefresh(request)) return null;
    state.sources = null;
    state.sourcesError = error.message;
    shouldRender = true;
    return null;
  } finally {
    if (shouldRender) {
      renderState();
      renderSourceLibrary();
      renderErrors();
    }
  }
};

const beginSettingsPresetRefresh = () => {
  state.settingsPresetRefreshRequestId += 1;
  return state.settingsPresetRefreshRequestId;
};

const isCurrentSettingsPresetRefresh = (requestId) =>
  requestId === state.settingsPresetRefreshRequestId;

const requestSettingsPresets = async () => {
  const requestId = beginSettingsPresetRefresh();
  let shouldRender = false;
  try {
    const payload = await api("/api/settings/presets");
    if (!isCurrentSettingsPresetRefresh(requestId)) return payload;
    state.settingsPresets = payload.presets || [];
    state.settingsPresetsError = null;
    shouldRender = true;
    return payload;
  } catch (error) {
    if (!isCurrentSettingsPresetRefresh(requestId)) return null;
    state.settingsPresetsError = error.message;
    shouldRender = true;
    return null;
  } finally {
    if (shouldRender) {
      renderSettingsPresets();
      renderErrors();
    }
  }
};

const volatileServerStateFields = [
  "recording_elapsed_seconds",
  "recording_remaining_seconds",
];

const stateRevisionFromPayload = (payload) => {
  const revision = payload?.state_revision;
  if (!Number.isSafeInteger(revision) || revision < 0) return null;
  return revision;
};

const stateEpochFromPayload = (payload) => {
  const epoch = payload?.state_epoch;
  if (!Number.isSafeInteger(epoch) || epoch < 0) return null;
  return epoch;
};

const defaultPlaybackLivePayload = () => ({
  enabled: false,
  volume_applies_immediately: false,
  mute_applies_immediately: false,
  seek_applies_immediately: false,
  voice_stack_transition_applies_immediately: false,
  voice_raw_preview_treatment_applies_immediately: false,
  eq_applies_immediately: false,
  excluded_apply_flow: [],
  eq_source_contract: null,
});

const normalizePlaybackLivePayload = (live) => {
  if (!live || typeof live !== "object" || Array.isArray(live)) {
    return defaultPlaybackLivePayload();
  }
  return {
    ...defaultPlaybackLivePayload(),
    ...live,
  };
};

const normalizePlaybackPayload = (playback) => {
  if (!playback || typeof playback !== "object" || Array.isArray(playback)) return playback;
  const normalized = {
    apply_mode: "stable",
    position_seconds: 0,
    duration_seconds: 0,
    progress: 0,
    active_voice_transition_target_id: null,
    playback_session_id: null,
    voice_raw_preview_path: null,
    transition_warning: null,
    output_running: false,
    output_latest_status: null,
    output_latest_error: null,
    ...playback,
    live: normalizePlaybackLivePayload(playback.live),
  };
  Object.defineProperty(normalized, "_positionSecondsProvided", {
    value: hasOwnProperty(playback, "position_seconds"),
    enumerable: false,
  });
  return normalized;
};

const normalizeSettingsPlaybackPayload = (settings) => {
  if (!settings || typeof settings !== "object" || Array.isArray(settings)) return settings;
  const playback = settings.playback;
  if (!playback || typeof playback !== "object" || Array.isArray(playback)) return settings;
  return {
    ...settings,
    playback: {
      apply_mode: "stable",
      ...playback,
    },
  };
};

const normalizeStateSettingsPayload = (settings) => {
  if (!settings || typeof settings !== "object" || Array.isArray(settings)) return settings;
  return {
    ...settings,
    active: normalizeSettingsPlaybackPayload(settings.active),
    draft: normalizeSettingsPlaybackPayload(settings.draft),
    change: toServerSettingsChangePayload(normalizeSettingsChangePlan(settings.change)),
  };
};

const normalizeStatePayload = (payload) => {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  return {
    ...payload,
    playback: normalizePlaybackPayload(payload.playback),
    settings: normalizeStateSettingsPayload(payload.settings),
  };
};

const serverPayloadRevisionIsOlder = (payload) => {
  const epoch = stateEpochFromPayload(payload);
  const revision = stateRevisionFromPayload(payload);
  if (
    epoch !== null &&
    state.acceptedStateEpoch !== null &&
    epoch < state.acceptedStateEpoch
  ) {
    return true;
  }
  if (
    epoch !== null &&
    state.acceptedStateEpoch !== null &&
    epoch > state.acceptedStateEpoch
  ) {
    return false;
  }
  return revision !== null &&
    state.acceptedStateRevision !== null &&
    revision < state.acceptedStateRevision;
};

const rememberServerPayloadRevision = (payload) => {
  const epoch = stateEpochFromPayload(payload);
  const revision = stateRevisionFromPayload(payload);
  if (
    epoch !== null &&
    state.acceptedStateEpoch !== null &&
    epoch > state.acceptedStateEpoch
  ) {
    state.acceptedStateEpoch = epoch;
    state.acceptedStateRevision = revision;
    return;
  }
  if (epoch !== null && state.acceptedStateEpoch === null) {
    state.acceptedStateEpoch = epoch;
  }
  if (revision === null) return;
  state.acceptedStateRevision = Math.max(state.acceptedStateRevision ?? revision, revision);
};

const stableServerStatePayload = (payload) => {
  if (!payload || typeof payload !== "object") return payload;
  const stablePayload = clone(payload);
  volatileServerStateFields.forEach((field) => {
    delete stablePayload[field];
  });
  return stablePayload;
};

const effectiveServerStatePayload = (payload, options = {}) => {
  const effectivePayload = stableServerStatePayload(payload);
  if (
    options.syncDraft === false &&
    effectivePayload?.settings?.draft &&
    state.draft
  ) {
    effectivePayload.settings.draft = clone(state.draft);
  }
  return effectivePayload;
};

const serverStateSignature = (payload, options = {}) =>
  JSON.stringify(effectiveServerStatePayload(payload, options));

const volatileServerStateChanged = (currentSnapshot, payload) => (
  Boolean(currentSnapshot && payload) &&
    volatileServerStateFields.some((field) => currentSnapshot[field] !== payload[field])
);

const applyVolatileServerState = (payload) => {
  if (!state.snapshot || !payload) return false;
  volatileServerStateFields.forEach((field) => {
    if (Object.prototype.hasOwnProperty.call(payload, field)) {
      state.snapshot[field] = payload[field];
    }
  });
  renderRecordingTimes();
  return true;
};

const applyVolatileServerStateIfChanged = (payload) => {
  if (!volatileServerStateChanged(state.snapshot, payload)) return false;
  return applyVolatileServerState(payload);
};

const voiceRawPreviewPath = (snapshot) => snapshot?.playback?.voice_raw_preview_path || null;

const clearVoiceRawSelectionAfterPreviewStop = (previousSnapshot, nextSnapshot) => {
  if (!voiceRawPreviewPath(previousSnapshot) || voiceRawPreviewPath(nextSnapshot)) {
    return false;
  }
  if (!state.sourceCardSelections.voice_raw) return false;
  delete state.sourceCardSelections.voice_raw;
  renderSourceLibrary({ allowInteractiveDeferral: false });
  return true;
};

const refreshAll = async () => {
  let stateRefreshFailed = false;
  await requestState({ syncDraft: false }).catch((error) => {
    stateRefreshFailed = true;
    showError(error.message);
  });
  await requestDevices();
  await requestDiagnostics();
  await requestSources({ syncAppliedSourceSignature: true });
  await requestSettingsPresets();
  if (!stateRefreshFailed) clearTransientError({ respectMinimumVisibleDuration: true });
  renderErrors();
};

const hasOwnProperty = (target, key) => Object.prototype.hasOwnProperty.call(target || {}, key);

const mergeSettingsPayloadDraft = (currentDraft, settingsPayload, options = {}) => {
  const syncDraft = options.syncDraft ?? true;
  const mergeDraftSections = options.mergeDraftSections || [];
  const payloadDraft = settingsPayload?.draft;
  if (!payloadDraft) {
    return currentDraft ? clone(currentDraft) : null;
  }
  if (syncDraft || !currentDraft) {
    return clone(payloadDraft);
  }
  const nextDraft = clone(currentDraft);
  mergeDraftSections.forEach((sectionName) => {
    if (hasOwnProperty(payloadDraft, sectionName) && hasOwnProperty(nextDraft, sectionName)) {
      nextDraft[sectionName] = clone(payloadDraft[sectionName]);
    }
  });
  return nextDraft;
};

const syncLiveConfirmedCoveredDraftFields = (draft, settingsPayload, snapshot) => {
  const active = settingsPayload?.active;
  if (!draft || !active || active.playback?.apply_mode !== "live") return draft;
  const live = livePlaybackFeatures(snapshot);
  if (!live.enabled) return draft;
  const nextDraft = clone(draft);
  ["low", "mid", "voice"].forEach((layerId) => {
    const activeLayer = active.layers?.[layerId];
    const draftLayer = nextDraft.layers?.[layerId];
    if (!activeLayer || !draftLayer) return;
    if (live.mute_applies_immediately && hasOwnProperty(activeLayer, "enabled")) {
      draftLayer.enabled = clone(activeLayer.enabled);
    }
    if (live.volume_applies_immediately && hasOwnProperty(activeLayer, "volume_db")) {
      draftLayer.volume_db = clone(activeLayer.volume_db);
    }
  });
  if (
    live.voice_raw_preview_treatment_applies_immediately &&
    active.recording &&
    nextDraft.recording
  ) {
    [
      "gain_db",
      "normalize_peak",
      "highpass_hz",
      "lowpass_hz",
      "presence_gain_db",
      "reverb_mix",
      "delay_mix",
      "fade_ms",
    ].forEach((controlPath) => {
      if (hasOwnProperty(active.recording, controlPath)) {
        nextDraft.recording[controlPath] = clone(active.recording[controlPath]);
      }
    });
  }
  return nextDraft;
};

const applySettingsPayload = (settingsPayload, options = {}) => {
  if (!state.snapshot || !settingsPayload) return false;
  const syncDraft = options.syncDraft ?? true;
  const mergeDraftSections = options.mergeDraftSections || [];
  const renderControlsOnSync = options.renderControlsOnSync ?? true;
  const shouldSyncDraft = shouldSyncIncomingSettingsDraft(
    options.currentSnapshot ?? state.snapshot,
    state.draft,
    { syncDraft },
  );
  const nextSettings = clone(settingsPayload);
  if (options.confirmActiveAsDraft && nextSettings.active) {
    nextSettings.draft = clone(nextSettings.active);
    const runtimeConfigFields = normalizeSettingsChangePlan(nextSettings.change).runtimeConfigFields;
    nextSettings.change = toServerSettingsChangePayload(
      localSettingsChangePlan(nextSettings.active, nextSettings.draft, runtimeConfigFields),
    );
  }
  state.snapshot.settings = nextSettings;
  state.draft = mergeSettingsPayloadDraft(state.draft, nextSettings, {
    syncDraft: shouldSyncDraft,
    mergeDraftSections,
  });
  if (shouldSyncDraft) {
    state.draft = syncLiveConfirmedCoveredDraftFields(state.draft, nextSettings, state.snapshot);
  }
  if (shouldSyncDraft) {
    rememberConfirmedSettingsDraft(nextSettings, state.draft);
    rememberConfirmedActiveSettings(nextSettings);
    if (renderControlsOnSync && !graphEqInlineEditorMountShouldBePreserved()) renderControls();
  } else {
    syncDraftSnapshot();
  }
  return true;
};

const applyState = (payload, options = {}) => {
  const normalizedPayload = normalizeStatePayload(payload);
  const syncDraft = options.syncDraft ?? true;
  const mergeDraftSections = options.mergeDraftSections || [];
  const renderControlsOnSync = options.renderControlsOnSync ?? true;
  const incomingEpoch = stateEpochFromPayload(normalizedPayload);
  if (
    incomingEpoch !== null &&
    state.acceptedStateEpoch !== null &&
    incomingEpoch > state.acceptedStateEpoch
  ) {
    state.liveGraphEqLatestRequestIds = {};
  }
  if (serverPayloadRevisionIsOlder(normalizedPayload)) {
    return false;
  }
  if (liveGraphEqPayloadIsOlder(normalizedPayload)) {
    return false;
  }
  rememberServerPayloadRevision(normalizedPayload);
  rememberLiveGraphEqRequest(normalizedPayload?.playback?.live_graph_eq);
  if (!options.fromStateRefresh) {
    invalidatePendingStateRefreshes();
  }
  const nextServerStateSignature = serverStateSignature(normalizedPayload, { syncDraft });
  const serverStateChanged = state.serverStateSignature !== nextServerStateSignature;
  if (!serverStateChanged && !syncDraft && state.snapshot) {
    return applyVolatileServerStateIfChanged(normalizedPayload);
  }
  const currentSnapshot = state.snapshot;
  state.serverStateSignature = nextServerStateSignature;
  state.snapshot = normalizedPayload;
  markPlaybackTimelineServerUpdate();
  applySettingsPayload(normalizedPayload.settings, {
    currentSnapshot,
    syncDraft,
    mergeDraftSections,
    renderControlsOnSync,
    confirmActiveAsDraft: Boolean(options.confirmActiveAsDraft),
  });
  updateLiveApplyFeedbackForLiveGraphEqState(normalizedPayload?.playback?.live_graph_eq);
  state.serverStateSignature = serverStateSignature(state.snapshot, { syncDraft });
  renderState();
  refreshLayerCoveredFeedbackVisualStates();
  renderSystemPanel();
  clearVoiceRawSelectionAfterPreviewStop(currentSnapshot, state.snapshot);
  scheduleLiveGraphEqTick(state.snapshot?.playback?.live_graph_eq);
  return true;
};

const liveGraphEqTickTransportFailureWarning =
  "Live Graph EQ 적용 상태를 확인하지 못했습니다. 기존 재생 상태를 유지합니다.";

const markLiveGraphEqTickTransportFailure = (error, requestSnapshot = null) => {
  if (currentPlaybackApplyMode() !== "live") return;
  const current = state.snapshot?.playback?.live_graph_eq;
  const expectedLayerId = liveGraphEqRequestLayerId(requestSnapshot || current);
  const expectedRequestId = liveGraphEqRequestId(requestSnapshot || current);
  if (!current?.pending) return;
  if (expectedLayerId && liveGraphEqRequestLayerId(current) !== expectedLayerId) return;
  if (expectedRequestId !== null && liveGraphEqRequestId(current) !== expectedRequestId) return;
  const failed = {
    ...current,
    status: "failed",
    pending: false,
    slow_caution: false,
    layer_id: expectedLayerId || current.layer_id,
    request_id: expectedRequestId || current.request_id,
    failure_warning: current.failure_warning || liveGraphEqTickTransportFailureWarning,
    failure_detail: error?.message || current.failure_detail || "Live Graph EQ tick request failed.",
  };
  if (liveGraphEqTickTimer) {
    (window.clearTimeout || clearTimeout)(liveGraphEqTickTimer);
    liveGraphEqTickTimer = null;
  }
  state.snapshot.playback.live_graph_eq = failed;
  updateLiveApplyFeedbackForLiveGraphEqState(failed);
  refreshLayerCoveredFeedbackVisualStates();
  const layerId = liveGraphEqRequestLayerId(failed);
  if (layerId) refreshInlineGraphEqLiveStatusCopy(
    layerId,
    deriveCoveredSurfaceFeedbackState({ surfaceId: `layer:${layerId}` }),
  );
};

const scheduleLiveGraphEqTick = (liveGraphEq) => {
  if (liveGraphEqTickTimer) {
    (window.clearTimeout || clearTimeout)(liveGraphEqTickTimer);
    liveGraphEqTickTimer = null;
  }
  if (currentPlaybackApplyMode() !== "live" || !liveGraphEq?.pending) return;
  const delayMs = Math.max(100, Number(liveGraphEq.apply_delay_ms || 1000));
  liveGraphEqTickTimer = (window.setTimeout || setTimeout)(async () => {
    liveGraphEqTickTimer = null;
    await control("/api/playback/live-graph-eq/tick", { syncDraft: false }).catch(() => {});
  }, delayMs);
};

const syncDraftSnapshot = () => {
  if (!state.snapshot?.settings || !state.draft) return;
  state.snapshot.settings.draft = clone(state.draft);
  const runtimeConfigFields = settingsChangePlan(state.snapshot).runtimeConfigFields;
  state.snapshot.settings.change = toServerSettingsChangePayload(
    localSettingsChangePlan(state.snapshot.settings.active, state.draft, runtimeConfigFields),
  );
};

const operationLockMessages = {
  draftApply: "설정 적용이 끝날 때까지 기다리세요.",
  draftReset: "설정 변경 취소가 끝날 때까지 기다리세요.",
  sourceMutation: "소스 파일 작업이 끝날 때까지 기다리세요.",
  sourceApply: "설정 적용이 끝날 때까지 소스 파일을 바꿀 수 없습니다.",
  sourceReset: "설정 변경 취소가 끝날 때까지 소스 파일을 바꿀 수 없습니다.",
  sourceDeviceChange: "장치 변경이 끝날 때까지 소스 파일을 바꿀 수 없습니다.",
  playbackControl: "출력 제어가 끝날 때까지 기다리세요.",
  recordingStop: "녹음 처리가 끝날 때까지 기다리세요.",
  resetParticipants: "참여자 초기화가 끝날 때까지 기다리세요.",
  settingsPreset: "프리셋 작업이 끝날 때까지 기다리세요.",
  deviceLoading: "장치 목록을 불러오는 중입니다.",
  deviceApply: "설정 적용이 끝날 때까지 기다리세요.",
  deviceChange: "장치 변경을 적용하는 중입니다.",
  deviceRecording: "녹음 중에는 입력 장치를 바꿀 수 없습니다.",
};

const firstOperationLockTitle = (candidates = []) => {
  const match = candidates.find(([active, title]) => active && title);
  return match ? match[1] : "";
};

const operationFlagKeys = [
  "sourceMutationInFlight",
  "draftSaveInFlight",
  "recordingStartInFlight",
  "recordingStopInFlight",
  "playbackControlInFlight",
  "applyInFlight",
  "applyAndRestartInFlight",
  "resetDraftInFlight",
  "resetParticipantsInFlight",
  "settingsPresetActionInFlight",
  "deviceChangeInFlight",
];

const operationFlagsFrom = (stateLike = {}) => {
  const flags = operationFlagKeys.reduce((nextFlags, key) => {
    nextFlags[key] = Boolean(stateLike[key]);
    return nextFlags;
  }, {});
  if (
    Object.hasOwn(stateLike, "coveredFeedbackSurfaceId") &&
    stateLike.coveredFeedbackSurfaceId !== undefined
  ) {
    flags.coveredSurfaceId = stateLike.coveredFeedbackSurfaceId;
  } else if (
    Object.hasOwn(stateLike, "liveFeedbackSurfaceId") &&
    stateLike.liveFeedbackSurfaceId !== undefined
  ) {
    flags.coveredSurfaceId = stateLike.liveFeedbackSurfaceId;
    flags.liveFeedbackSurfaceId = stateLike.liveFeedbackSurfaceId;
  } else if (
    Object.hasOwn(stateLike, "pendingLiveFeedbackSurfaceId") &&
    stateLike.pendingLiveFeedbackSurfaceId !== undefined
  ) {
    flags.coveredSurfaceId = stateLike.pendingLiveFeedbackSurfaceId;
    flags.liveFeedbackSurfaceId = stateLike.pendingLiveFeedbackSurfaceId;
    flags.liveFeedbackPending = true;
  }
  if (Array.isArray(stateLike.coveredFeedbackControlIds) && stateLike.coveredFeedbackControlIds.length > 0) {
    flags.coveredFeedbackControlIds = [...stateLike.coveredFeedbackControlIds];
  }
  if (stateLike.liveApplyFeedback) {
    let liveFeedback = createLiveApplyFeedbackState(stateLike.liveApplyFeedback);
    if (
      liveFeedback.feedbackState === liveApplyFeedbackStates.pending &&
      Boolean(stateLike.draftSaveInFlight)
    ) {
      liveFeedback = {
        ...liveFeedback,
        feedbackState: liveApplyFeedbackStates.applying,
        spinnerVisible: true,
      };
    }
    const visualState = deriveLiveApplyFeedbackVisualState(liveFeedback);
    if (visualState.visual_state !== "idle" && liveFeedback.coveredCardId) {
      flags.coveredSurfaceId = liveFeedback.coveredCardId;
      flags.liveFeedbackSurfaceId = liveFeedback.coveredCardId;
      flags.liveApplyFeedback = liveFeedback;
      flags.coveredFeedbackControlIds = [...liveFeedback.controlIds];
      flags.liveFeedbackPending = liveFeedback.feedbackState === liveApplyFeedbackStates.pending;
      flags.liveApplyInFlight = liveFeedback.feedbackState === liveApplyFeedbackStates.applying;
    }
  }
  return flags;
};

const currentOperationFlags = () => operationFlagsFrom(state);

const setOperationLockFlag = (key, inFlight) => {
  if (!operationFlagKeys.includes(key)) {
    throw new Error(`unknown operation flag: ${key}`);
  }
  state[key] = Boolean(inFlight);
  renderOperationLockSurfaces();
};

const deriveDraftControlLockState = ({
  applyInFlight = false,
  resetDraftInFlight = false,
  sourceMutationInFlight = false,
  deviceChangeInFlight = false,
  recordingStopInFlight = false,
  playbackControlInFlight = false,
  resetParticipantsInFlight = false,
  settingsPresetActionInFlight = false,
} = {}) => {
  const title = firstOperationLockTitle([
    [applyInFlight, operationLockMessages.draftApply],
    [resetDraftInFlight, operationLockMessages.draftReset],
    [settingsPresetActionInFlight, operationLockMessages.settingsPreset],
    [sourceMutationInFlight, operationLockMessages.sourceMutation],
    [deviceChangeInFlight, operationLockMessages.deviceChange],
    [recordingStopInFlight, operationLockMessages.recordingStop],
    [playbackControlInFlight, operationLockMessages.playbackControl],
    [resetParticipantsInFlight, operationLockMessages.resetParticipants],
  ]);
  return {
    disabled: Boolean(title),
    title,
  };
};

const deriveOperationLocks = ({
  applyInFlight = false,
  resetDraftInFlight = false,
  sourceMutationInFlight = false,
  deviceChangeInFlight = false,
  recordingStopInFlight = false,
  playbackControlInFlight = false,
  resetParticipantsInFlight = false,
  settingsPresetActionInFlight = false,
  devicesLoaded = true,
  forceDeviceDisabled = false,
} = {}) => {
  const sourceActionTitle = firstOperationLockTitle([
    [applyInFlight, operationLockMessages.sourceApply],
    [resetDraftInFlight, operationLockMessages.sourceReset],
    [settingsPresetActionInFlight, operationLockMessages.settingsPreset],
    [sourceMutationInFlight, operationLockMessages.sourceMutation],
    [deviceChangeInFlight, operationLockMessages.sourceDeviceChange],
    [recordingStopInFlight, operationLockMessages.recordingStop],
    [playbackControlInFlight, operationLockMessages.playbackControl],
    [resetParticipantsInFlight, operationLockMessages.resetParticipants],
  ]);
  const deviceTitle = firstOperationLockTitle([
    [!devicesLoaded, operationLockMessages.deviceLoading],
    [applyInFlight, operationLockMessages.deviceApply],
    [resetDraftInFlight, operationLockMessages.draftReset],
    [settingsPresetActionInFlight, operationLockMessages.settingsPreset],
    [sourceMutationInFlight, operationLockMessages.sourceMutation],
    [deviceChangeInFlight, operationLockMessages.deviceChange],
    [recordingStopInFlight, operationLockMessages.recordingStop],
    [playbackControlInFlight, operationLockMessages.playbackControl],
    [resetParticipantsInFlight, operationLockMessages.resetParticipants],
    [forceDeviceDisabled, operationLockMessages.deviceRecording],
  ]);
  const draftLock = deriveDraftControlLockState({
    applyInFlight,
    resetDraftInFlight,
    sourceMutationInFlight,
    deviceChangeInFlight,
    recordingStopInFlight,
    playbackControlInFlight,
    resetParticipantsInFlight,
    settingsPresetActionInFlight,
  });
  return {
    draftLocked: draftLock.disabled,
    sourceUiLocked: Boolean(sourceActionTitle),
    sourceCommandBlocked: Boolean(sourceActionTitle),
    sourceActionTitle,
    deviceLocked: Boolean(
      forceDeviceDisabled || deviceChangeInFlight || applyInFlight || resetDraftInFlight ||
        sourceMutationInFlight ||
        settingsPresetActionInFlight ||
        recordingStopInFlight ||
        playbackControlInFlight ||
        resetParticipantsInFlight ||
        !devicesLoaded,
    ),
    deviceTitle,
  };
};

const draftEditLocked = (stateLike = state) => deriveDraftControlLockState(stateLike).disabled;

const draftEditLockTitle = (stateLike = state) => deriveDraftControlLockState(stateLike).title;

const markDraftEdited = () => {
  state.draftEditRevision += 1;
};

const draftFeedbackSurfaceIdFromOptions = (options = {}) => {
  if (Object.hasOwn(options, "feedbackSurfaceId")) {
    return normalizeFeedbackSurfaceId(options.feedbackSurfaceId);
  }
  if (Object.hasOwn(options, "liveFeedbackSurfaceId")) {
    return normalizeFeedbackSurfaceId(options.liveFeedbackSurfaceId);
  }
  if (Object.hasOwn(options, "feedbackControlId")) {
    return feedbackSurfaceIdForControlId(options.feedbackControlId);
  }
  return undefined;
};

const coveredFeedbackControlIdsFromOptions = (options = {}) => {
  if (Array.isArray(options.feedbackControlIds)) {
    return options.feedbackControlIds
      .map((controlId) => String(controlId || ""))
      .filter((controlId) => feedbackSurfaceIdForControlId(controlId));
  }
  if (Object.hasOwn(options, "feedbackControlId")) {
    const controlId = String(options.feedbackControlId || "");
    return feedbackSurfaceIdForControlId(controlId) ? [controlId] : [];
  }
  const surfaceId = draftFeedbackSurfaceIdFromOptions(options);
  return coveredFeedbackSurfacePaths[surfaceId] || [];
};

const appendPendingCoveredFeedbackControlIds = (controlIds = []) => {
  const ids = controlIds.filter(Boolean);
  if (ids.length === 0) return;
  state.pendingCoveredFeedbackControlIds = [
    ...new Set([...state.pendingCoveredFeedbackControlIds, ...ids]),
  ];
};

const currentLiveApplyModeEpoch = () => Number(state.acceptedStateEpoch ?? 0);

const feedbackControlValues = (settings, controlIds = []) => {
  if (!settings || controlIds.length === 0) return undefined;
  if (controlIds.length === 1) return cloneApplyFeedbackValue(getPath(settings, controlIds[0]));
  return controlIds.reduce((values, controlId) => {
    values[controlId] = cloneApplyFeedbackValue(getPath(settings, controlId));
    return values;
  }, {});
};

const liveApplyFeedbackActive = (feedback = state.liveApplyFeedback) => {
  const model = createLiveApplyFeedbackState(feedback || {});
  return model.feedbackState === liveApplyFeedbackStates.pending ||
    model.feedbackState === liveApplyFeedbackStates.applying;
};

const updateLiveApplyFeedbackForDraftEdit = (feedbackSurfaceId, controlIds = []) => {
  if (currentPlaybackApplyMode() !== "live" || feedbackSurfaceId === undefined || feedbackSurfaceId === null) {
    return;
  }
  state.liveApplyFeedback = reduceLiveApplyFeedbackState(state.liveApplyFeedback, {
    type: "edit",
    requestId: state.draftSaveRequestId + 1,
    modeEpoch: currentLiveApplyModeEpoch(),
    coveredCardId: feedbackSurfaceId,
    controlIds,
    draftValue: feedbackControlValues(state.draft, controlIds),
    confirmedValue: feedbackControlValues(
      state.confirmedActiveSettingsSnapshot || state.snapshot?.settings?.active,
      controlIds,
    ),
  });
};

const invalidateLiveApplyFeedbackForUncoveredDraftEdit = () => {
  if (currentPlaybackApplyMode() !== "live" || !state.liveApplyFeedback) return;
  state.liveApplyFeedback = reduceLiveApplyFeedbackState(state.liveApplyFeedback, {
    type: "mode_changed",
    modeEpoch: currentLiveApplyModeEpoch() + 1,
  });
};

const updateLiveApplyFeedbackForRequestStart = (request) => {
  if (currentPlaybackApplyMode() !== "live" || !liveApplyFeedbackActive()) return;
  const current = createLiveApplyFeedbackState(state.liveApplyFeedback);
  state.liveApplyFeedback = reduceLiveApplyFeedbackState(current, {
    type: "request_started",
    requestId: request.requestId,
    modeEpoch: current.modeEpoch,
    coveredCardId: current.coveredCardId,
    controlIds: request.coveredFeedbackControlIds,
    draftValue: feedbackControlValues(state.draft, request.coveredFeedbackControlIds),
  });
};

const updateLiveApplyFeedbackForRequestSuccess = (request, settingsPayload) => {
  if (!state.liveApplyFeedback) return;
  const current = createLiveApplyFeedbackState(state.liveApplyFeedback);
  if (liveApplyFeedbackWaitsForLiveGraphEqRender(current)) {
    state.liveApplyFeedback = reduceLiveApplyFeedbackState(current, {
      type: "live_render_pending",
      requestId: request.requestId,
      modeEpoch: current.modeEpoch,
    });
    return;
  }
  state.liveApplyFeedback = reduceLiveApplyFeedbackState(current, {
    type: "request_succeeded",
    requestId: request.requestId,
    modeEpoch: current.modeEpoch,
    confirmedValue: feedbackControlValues(settingsPayload?.active, request.coveredFeedbackControlIds),
  });
};

const updateLiveApplyFeedbackForRequestFailure = (request) => {
  if (!state.liveApplyFeedback) return;
  const current = createLiveApplyFeedbackState(state.liveApplyFeedback);
  state.liveApplyFeedback = reduceLiveApplyFeedbackState(current, {
    type: "request_failed",
    requestId: request.requestId,
    modeEpoch: current.modeEpoch,
  });
};

const commitDraftChange = (mutator, options = {}) => {
  if (!state.draft || draftEditLocked()) return false;
  mutator?.();
  markDraftEdited();
  const feedbackSurfaceId = draftFeedbackSurfaceIdFromOptions(options);
  const feedbackControlIds = coveredFeedbackControlIdsFromOptions(options);
  if (feedbackSurfaceId !== undefined) {
    state.pendingCoveredFeedbackSurfaceId = feedbackSurfaceId;
    state.pendingLiveFeedbackSurfaceId = feedbackSurfaceId;
  } else {
    state.pendingCoveredFeedbackSurfaceId = undefined;
    state.pendingLiveFeedbackSurfaceId = undefined;
    invalidateLiveApplyFeedbackForUncoveredDraftEdit();
  }
  appendPendingCoveredFeedbackControlIds(feedbackControlIds);
  updateLiveApplyFeedbackForDraftEdit(feedbackSurfaceId, feedbackControlIds);
  syncDraftSnapshot();
  options.afterSync?.();
  renderState();
  if (options.scheduleSave !== false) scheduleDraftSave();
  return true;
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

const deriveSettingsActionState = ({
  snapshot,
  applyInFlight = false,
  resetDraftInFlight = false,
  sourceMutationInFlight = false,
  deviceChangeInFlight = false,
  recordingStopInFlight = false,
  playbackControlInFlight = false,
  resetParticipantsInFlight = false,
  settingsPresetActionInFlight = false,
  pendingChanges = false,
  runtimeConfigChanged = false,
}) => {
  const recordingStopBusy = Boolean(recordingStopInFlight);
  const resetBusy = Boolean(resetDraftInFlight);
  const sourceMutationBusy = Boolean(sourceMutationInFlight);
  const deviceChangeBusy = Boolean(deviceChangeInFlight);
  const playbackControlBusy = Boolean(playbackControlInFlight);
  const resetParticipantsBusy = Boolean(resetParticipantsInFlight);
  const settingsPresetBusy = Boolean(settingsPresetActionInFlight);
  const isRecording = Boolean(snapshot?.is_recording);
  const outputRunning = Boolean(snapshot?.playback?.output_running);
  const renderedCacheReady = Boolean(snapshot?.playback?.rendered_cache_ready);
  const canApplyRenderedCache = !pendingChanges && !runtimeConfigChanged && renderedCacheReady;
  const liveSampleRateApplyRequired = liveSampleRateApplyRequiredChange(snapshot);
  const liveChannelCountApplyRequired = liveChannelCountApplyRequiredChange(snapshot);
  const liveInputDeviceApplyRequired = liveInputDeviceApplyRequiredChange(snapshot);
  const liveOutputDeviceApplyRequired = liveOutputDeviceApplyRequiredChange(snapshot);
  const liveLoopLengthApplyRequired = liveLoopLengthApplyRequiredChange(snapshot);
  const liveSourceFileSelectionApplyRequired = liveSourceFileSelectionApplyRequiredChange(snapshot);
  const applyTitle = recordingStopBusy
    ? "녹음 처리가 끝날 때까지 기다리세요."
    : resetParticipantsBusy
      ? operationLockMessages.resetParticipants
    : settingsPresetBusy
      ? operationLockMessages.settingsPreset
    : resetBusy
      ? "설정 변경 취소가 끝날 때까지 기다리세요."
      : deviceChangeBusy
        ? operationLockMessages.deviceChange
        : isRecording
          ? "준비된 설정을 적용하기 전에 녹음을 중지하세요."
          : applyInFlight
            ? "준비된 오디오 설정을 렌더링하고 다시 불러오는 중입니다."
            : sourceMutationBusy
              ? operationLockMessages.sourceMutation
              : playbackControlBusy
                ? operationLockMessages.playbackControl
                : liveSampleRateApplyRequired
                  ? "Live 모드에서도 샘플레이트 변경은 Apply and Restart 후 반영됩니다."
                : liveChannelCountApplyRequired
                  ? "Live 모드에서도 샘플레이트 또는 채널 변경은 Apply and Restart 후 반영됩니다."
                : liveInputDeviceApplyRequired
                  ? "Live 모드에서도 입력 장치 변경은 System 패널에서 적용한 뒤 Apply and Restart 후 반영됩니다."
                : liveOutputDeviceApplyRequired
                  ? "Live 모드에서도 출력 장치 변경은 System 패널에서 적용한 뒤 Apply and Restart 후 반영됩니다."
                : runtimeConfigChanged
                  ? "샘플레이트, 채널 변경은 앱 재시작이 필요하고 장치 변경은 System 패널에서 적용해야 합니다."
                  : liveLoopLengthApplyRequired
                    ? "Live 모드에서도 루프 길이는 Apply and Restart 후 반영됩니다."
                  : liveSourceFileSelectionApplyRequired
                    ? "Live 모드에서도 소스 파일 선택은 Apply and Restart 후 반영됩니다."
                  : canApplyRenderedCache
                    ? "준비된 오디오 설정을 적용하는 동안 출력을 멈췄다가 다시 시작합니다."
                  : !pendingChanges
                    ? "적용할 변경사항이 없습니다."
                    : outputRunning
                      ? "준비된 오디오 설정을 적용하는 동안 출력을 멈췄다가 다시 시작합니다."
                      : "";
  const resetTitle = resetBusy
    ? "설정 변경 취소가 끝날 때까지 기다리세요."
    : recordingStopBusy
      ? "녹음 처리가 끝날 때까지 기다리세요."
      : resetParticipantsBusy
        ? operationLockMessages.resetParticipants
      : settingsPresetBusy
        ? operationLockMessages.settingsPreset
      : applyInFlight
        ? "설정 적용이 끝날 때까지 기다리세요."
        : deviceChangeBusy
          ? operationLockMessages.deviceChange
          : sourceMutationBusy
            ? operationLockMessages.sourceMutation
            : playbackControlBusy
              ? operationLockMessages.playbackControl
              : isRecording
                ? "저장하지 않은 설정 변경을 취소하기 전에 녹음을 중지하세요."
                : !pendingChanges
                  ? "취소할 설정 변경사항이 없습니다."
                  : "";
  const resetDisabled = Boolean(
    applyInFlight ||
      resetBusy ||
      sourceMutationBusy ||
      deviceChangeBusy ||
      playbackControlBusy ||
      recordingStopBusy ||
      resetParticipantsBusy ||
      settingsPresetBusy ||
      isRecording ||
      !pendingChanges,
  );
  return {
    applyDisabled: Boolean(
      applyInFlight ||
        resetBusy ||
        sourceMutationBusy ||
        deviceChangeBusy ||
        playbackControlBusy ||
        recordingStopBusy ||
        resetParticipantsBusy ||
        settingsPresetBusy ||
        isRecording ||
        runtimeConfigChanged ||
        (!pendingChanges && !canApplyRenderedCache),
    ),
    applyLabel: applyInFlight ? "적용 중…" : "변경사항 적용 후 재생",
    applyAttention: pendingChanges && !runtimeConfigChanged,
    applyTitle,
    resetDisabled,
    resetTitle,
  };
};

const deriveDashboardControlState = ({
  snapshot,
  applyInFlight = false,
  resetDraftInFlight = false,
  sourceMutationInFlight = false,
  deviceChangeInFlight = false,
  recordingStartInFlight = false,
  recordingStopInFlight = false,
  playbackControlInFlight = false,
  resetParticipantsInFlight = false,
  settingsPresetActionInFlight = false,
  pendingChanges = false,
  runtimeConfigChanged = false,
}) => {
  const recordingStartBusy = Boolean(recordingStartInFlight);
  const recordingStopBusy = Boolean(recordingStopInFlight);
  const playbackControlBusy = Boolean(playbackControlInFlight);
  const deviceChangeBusy = Boolean(deviceChangeInFlight);
  const resetParticipantsBusy = Boolean(resetParticipantsInFlight);
  const settingsPresetBusy = Boolean(settingsPresetActionInFlight);
  const settingsOperationBusy = Boolean(
    applyInFlight ||
      resetDraftInFlight ||
      sourceMutationInFlight ||
      deviceChangeBusy ||
      resetParticipantsBusy ||
      settingsPresetBusy,
  );
  const captureOperationBusy = recordingStartBusy || recordingStopBusy || settingsOperationBusy;
  const outputControlBusy = Boolean(
    applyInFlight ||
      recordingStopBusy ||
      playbackControlBusy ||
      deviceChangeBusy ||
      resetParticipantsBusy ||
      settingsPresetBusy,
  );
  const isRecording = Boolean(snapshot?.is_recording);
  const armed = Boolean(snapshot?.armed);
  const outputRunning = Boolean(snapshot?.playback?.output_running);
  const captureGateClass = recordingStartBusy || recordingStopBusy
    ? "capture-gate-processing"
    : isRecording
      ? "capture-gate-recording"
      : armed
        ? "capture-gate-on"
        : "capture-gate-off";
  const settingsActionState = deriveSettingsActionState({
    snapshot,
    applyInFlight,
    resetDraftInFlight,
    sourceMutationInFlight,
    deviceChangeInFlight,
    recordingStopInFlight,
    playbackControlInFlight,
    resetParticipantsInFlight,
    settingsPresetActionInFlight,
    pendingChanges,
    runtimeConfigChanged,
  });
  const resetParticipantsTitle = resetParticipantsBusy
      ? operationLockMessages.resetParticipants
    : settingsPresetBusy
      ? operationLockMessages.settingsPreset
    : isRecording
      ? "참여자 수를 초기화하기 전에 녹음을 중지하세요."
      : recordingStopBusy
        ? "녹음 처리가 끝날 때까지 기다리세요."
        : applyInFlight
          ? "설정 적용이 끝날 때까지 기다리세요."
          : resetDraftInFlight
            ? operationLockMessages.draftReset
            : deviceChangeBusy
              ? operationLockMessages.deviceChange
              : sourceMutationInFlight
                ? operationLockMessages.sourceMutation
                : playbackControlBusy
                  ? operationLockMessages.playbackControl
                  : "";
  return {
    recordingStartBusy,
    recordingStopBusy,
    outputControlBusy,
    captureReady: armed && !isRecording && !captureOperationBusy,
    captureGateOn: armed || isRecording,
    captureGateClass,
    captureGateSwitchDisabled: captureOperationBusy || isRecording,
    startDisabled: captureOperationBusy || !armed || isRecording,
    stopDisabled: recordingStartBusy || recordingStopBusy || !isRecording,
    startOutputDisabled: outputControlBusy || outputRunning,
    stopOutputDisabled: outputControlBusy || !outputRunning,
    restartOutputDisabled: outputControlBusy || !outputRunning,
    ...settingsActionState,
    resetParticipantsDisabled: resetParticipantsBusy || applyInFlight || resetDraftInFlight ||
      settingsPresetBusy || sourceMutationInFlight || deviceChangeBusy || recordingStopBusy ||
      playbackControlBusy || isRecording,
    resetParticipantsTitle,
  };
};

const layerIds = ["low", "mid", "voice"];

const livePlaybackFeatures = (snapshot) => snapshot?.playback?.live || {};

const liveLoopLengthApplyRequiredChange = (snapshot = state.snapshot) => {
  const activeVoiceStack = snapshot?.settings?.active?.voice_stack || {};
  const draftVoiceStack = state.draft?.voice_stack || snapshot?.settings?.draft?.voice_stack || {};
  const live = livePlaybackFeatures(snapshot);
  return Boolean(
    live.enabled &&
      draftVoiceStack.loop_seconds !== undefined &&
      activeVoiceStack.loop_seconds !== draftVoiceStack.loop_seconds,
  );
};

const liveSampleRateApplyRequiredChange = (snapshot = state.snapshot) => {
  const activeAudio = snapshot?.settings?.active?.audio || {};
  const draftAudio = state.draft?.audio || snapshot?.settings?.draft?.audio || {};
  const live = livePlaybackFeatures(snapshot);
  return Boolean(
    live.enabled &&
      draftAudio.sample_rate !== undefined &&
      activeAudio.sample_rate !== draftAudio.sample_rate,
  );
};

const liveChannelCountApplyRequiredChange = (snapshot = state.snapshot) => {
  const activeAudio = snapshot?.settings?.active?.audio || {};
  const draftAudio = state.draft?.audio || snapshot?.settings?.draft?.audio || {};
  const live = livePlaybackFeatures(snapshot);
  return Boolean(
    live.enabled &&
      draftAudio.channels !== undefined &&
      activeAudio.channels !== draftAudio.channels,
  );
};

const liveInputDeviceApplyRequiredChange = (snapshot = state.snapshot) => {
  const activeDevices = snapshot?.settings?.active?.devices || {};
  const draftDevices = state.draft?.devices || snapshot?.settings?.draft?.devices || {};
  const live = livePlaybackFeatures(snapshot);
  return Boolean(
    live.enabled &&
      draftDevices.input_device_id !== undefined &&
      activeDevices.input_device_id !== draftDevices.input_device_id,
  );
};

const liveOutputDeviceApplyRequiredChange = (snapshot = state.snapshot) => {
  const activeDevices = snapshot?.settings?.active?.devices || {};
  const draftDevices = state.draft?.devices || snapshot?.settings?.draft?.devices || {};
  const live = livePlaybackFeatures(snapshot);
  return Boolean(
    live.enabled &&
      draftDevices.output_device_id !== undefined &&
      activeDevices.output_device_id !== draftDevices.output_device_id,
  );
};

const liveSourceFileSelectionApplyRequiredChange = (snapshot = state.snapshot) => {
  const live = livePlaybackFeatures(snapshot);
  return Boolean(live.enabled && hasSourceFileChanges(snapshot));
};

const liveLayerControlChangeOnly = (snapshot, settingsPlan) => {
  if (!snapshot?.settings?.active || !state.draft) return false;
  if (!settingsPlan?.changedSections?.length || settingsPlan.runtimeConfigChanged) return false;
  if (settingsPlan.changedSections.some((section) => section !== "layers")) return false;
  const live = livePlaybackFeatures(snapshot);
  if (!live.enabled) return false;
  const volumeLive = Boolean(live.volume_applies_immediately);
  const muteLive = Boolean(live.mute_applies_immediately);
  const eqLive = Boolean(live.eq_applies_immediately);
  if (!volumeLive && !muteLive && !eqLive) return false;
  const activeLayers = clone(snapshot.settings.active.layers || {});
  const draftLayers = clone(state.draft.layers || {});
  layerIds.forEach((layerId) => {
    if (!activeLayers[layerId] || !draftLayers[layerId]) return;
    if (volumeLive) draftLayers[layerId].volume_db = activeLayers[layerId].volume_db;
    if (muteLive) draftLayers[layerId].enabled = activeLayers[layerId].enabled;
    if (eqLive) draftLayers[layerId].eq = activeLayers[layerId].eq;
  });
  return stableSettingsSignature(activeLayers) === stableSettingsSignature(draftLayers);
};

const liveVoiceStackTransitionChangeOnly = (snapshot, settingsPlan) => {
  if (!snapshot?.settings?.active || !state.draft) return false;
  if (!settingsPlan?.changedSections?.length || settingsPlan.runtimeConfigChanged) return false;
  if (settingsPlan.changedSections.some((section) => section !== "voice_stack")) return false;
  return false;
};

const liveVoiceRawPreviewTreatmentChangeOnly = (snapshot, settingsPlan) => {
  if (!snapshot?.settings?.active || !state.draft) return false;
  if (!settingsPlan?.changedSections?.length || settingsPlan.runtimeConfigChanged) return false;
  if (settingsPlan.changedSections.some((section) => section !== "recording")) return false;
  const live = livePlaybackFeatures(snapshot);
  if (!live.enabled || !live.voice_raw_preview_treatment_applies_immediately) return false;
  if (!snapshot.playback?.voice_raw_preview_path) return false;
  const reprocessableFields = Array.isArray(settingsPlan.livePreviewReprocessableFields)
    ? settingsPlan.livePreviewReprocessableFields
    : [];
  if (reprocessableFields.length === 0) return false;
  const activeRecording = clone(snapshot.settings.active.recording || {});
  const draftRecording = clone(state.draft.recording || {});
  reprocessableFields.forEach((fieldName) => {
    if (!fieldName.startsWith("recording.")) return;
    const recordingFieldName = fieldName.slice("recording.".length);
    if (recordingFieldName) {
      draftRecording[recordingFieldName] = activeRecording[recordingFieldName];
    }
  });
  return stableSettingsSignature(activeRecording) === stableSettingsSignature(draftRecording);
};

const idleCoveredSurfaceFeedbackState = () => ({
  visual_state: "idle",
  show_spinner: false,
});

const normalizeFeedbackSurfaceId = (surfaceId) => {
  const layerId = layerIdForFeedbackSurface(surfaceId);
  if (layerId) return `layer:${layerId}`;
  if (surfaceId === "voice_stack" || surfaceId === "recording") return surfaceId;
  return null;
};

const feedbackSurfaceIdFromOperationFlags = (operationFlags = {}) => {
  if (Object.hasOwn(operationFlags, "liveFeedbackSurfaceId")) {
    return normalizeFeedbackSurfaceId(operationFlags.liveFeedbackSurfaceId);
  }
  if (Object.hasOwn(operationFlags, "feedbackSurfaceId")) {
    return normalizeFeedbackSurfaceId(operationFlags.feedbackSurfaceId);
  }
  if (Object.hasOwn(operationFlags, "coveredSurfaceId")) {
    return normalizeFeedbackSurfaceId(operationFlags.coveredSurfaceId);
  }
  const controlId = operationFlags.feedbackControlId || operationFlags.controlId || null;
  if (controlId) return feedbackSurfaceIdForControlId(controlId);
  return undefined;
};

const operationTargetsFeedbackSurface = (operationFlags = {}, surfaceId) => {
  const targetSurfaceId = feedbackSurfaceIdFromOperationFlags(operationFlags);
  const normalizedSurfaceId = normalizeFeedbackSurfaceId(surfaceId);
  if (targetSurfaceId !== undefined) {
    return targetSurfaceId !== null && targetSurfaceId === normalizedSurfaceId;
  }
  const controlIds = [
    ...(Array.isArray(operationFlags.coveredFeedbackControlIds)
      ? operationFlags.coveredFeedbackControlIds
      : []),
    ...(Array.isArray(operationFlags.feedbackControlIds)
      ? operationFlags.feedbackControlIds
      : []),
  ];
  if (controlIds.length === 0) return false;
  return controlIds.some((controlId) => (
    feedbackSurfaceIdForControlId(controlId) === normalizedSurfaceId
  ));
};

const liveApplyFeedbackTargetsSurface = (liveFeedback, surfaceId) => {
  if (!liveFeedback) return false;
  const normalizedSurfaceId = normalizeFeedbackSurfaceId(surfaceId);
  const targetSurfaceId = normalizeFeedbackSurfaceId(liveFeedback.coveredCardId);
  if (targetSurfaceId) return targetSurfaceId === normalizedSurfaceId;
  return liveFeedback.controlIds.some((controlId) => (
    feedbackSurfaceIdForControlId(controlId) === normalizedSurfaceId
  ));
};

const deriveLiveApplyFeedbackSurfaceState = (liveFeedback, surfaceId) => {
  if (!liveApplyFeedbackTargetsSurface(liveFeedback, surfaceId)) return null;
  const visualState = deriveLiveApplyFeedbackVisualState(liveFeedback);
  return visualState.visual_state === "idle" ? null : visualState;
};

const feedbackOperationInFlight = (operationFlags = {}, surfaceId = null) => {
  if (!operationTargetsFeedbackSurface(operationFlags, surfaceId)) return false;
  return Boolean(
    operationFlags.draftSaveInFlight ||
      operationFlags.settingsSaveInFlight ||
      operationFlags.applyInFlight ||
      operationFlags.liveApplyInFlight,
  );
};

const stableApplyAndRestartInFlight = (operationFlags = {}) => {
  if (Object.hasOwn(operationFlags, "applyAndRestartInFlight")) {
    return Boolean(operationFlags.applyInFlight && operationFlags.applyAndRestartInFlight);
  }
  return Boolean(operationFlags.applyInFlight);
};

const settingsApplyMode = (snapshot, draft) => (
  snapshot?.playback?.apply_mode ||
    draft?.playback?.apply_mode ||
    snapshot?.settings?.active?.playback?.apply_mode ||
    "stable"
);

const layerIdForFeedbackSurface = (surfaceId) => {
  const match = String(surfaceId || "").match(/^layer[:.](low|mid|voice)$/);
  return match ? match[1] : null;
};

const graphEqLayerIdForControlId = (controlId) => {
  const match = String(controlId || "").match(/^layers\.(low|mid|voice)\.eq(?:\.|$)/);
  return match ? match[1] : null;
};

const liveApplyFeedbackGraphEqLayerId = (feedback = {}) => {
  const controlIds = Array.isArray(feedback.controlIds) ? feedback.controlIds : [];
  const controlLayerId = controlIds
    .map((controlId) => graphEqLayerIdForControlId(controlId))
    .find(Boolean);
  if (controlIds.length) return controlLayerId || null;
  return layerIdForFeedbackSurface(feedback.coveredCardId);
};

const liveApplyFeedbackWaitsForLiveGraphEqRender = (feedback = {}) => (
  currentPlaybackApplyMode() === "live" && Boolean(liveApplyFeedbackGraphEqLayerId(feedback))
);

const liveGraphEqTargetsFeedbackSurface = (liveGraphEq = {}, surfaceId) => {
  const surfaceLayerId = layerIdForFeedbackSurface(surfaceId);
  if (!surfaceLayerId) return false;
  return liveGraphEqRequestLayerId(liveGraphEq) === surfaceLayerId;
};

const deriveLiveGraphEqFeedbackState = (snapshot, surfaceId) => {
  if (currentPlaybackApplyMode(snapshot) !== "live") return null;
  if (!snapshot?.playback?.live?.eq_applies_immediately) return null;
  const liveGraphEq = snapshot?.playback?.live_graph_eq;
  if (!liveGraphEqTargetsFeedbackSurface(liveGraphEq, surfaceId)) return null;
  if (liveGraphEq?.pending || liveGraphEq?.status === "pending" || liveGraphEq?.status === "slow") {
    return {
      visual_state: "pending",
      show_spinner: true,
    };
  }
  return null;
};

const updateLiveApplyFeedbackForLiveGraphEqState = (liveGraphEq = {}) => {
  if (!state.liveApplyFeedback) return;
  const current = createLiveApplyFeedbackState(state.liveApplyFeedback);
  const layerId = liveApplyFeedbackGraphEqLayerId(current);
  if (!layerId || liveGraphEqRequestLayerId(liveGraphEq) !== layerId) return;
  if (liveGraphEq?.pending || liveGraphEq?.status === "pending" || liveGraphEq?.status === "slow") {
    state.liveApplyFeedback = reduceLiveApplyFeedbackState(current, {
      type: "live_render_pending",
      requestId: current.requestId,
      modeEpoch: current.modeEpoch,
    });
    return;
  }
  if (liveGraphEq?.status === "applied") {
    state.liveApplyFeedback = reduceLiveApplyFeedbackState(current, {
      type: "request_succeeded",
      requestId: current.requestId,
      modeEpoch: current.modeEpoch,
      confirmedValue: feedbackControlValues(state.draft, current.controlIds),
    });
  } else if (liveGraphEq?.status === "failed") {
    state.liveApplyFeedback = reduceLiveApplyFeedbackState(current, {
      type: "request_failed",
      requestId: current.requestId,
      modeEpoch: current.modeEpoch,
      warningMessage: liveGraphEq.failure_warning,
    });
  }
};

const surfaceSettingsChanged = (active, draft, surfaceId) => {
  const layerId = layerIdForFeedbackSurface(surfaceId);
  if (layerId) {
    return stableSettingsSignature(active?.layers?.[layerId]) !==
      stableSettingsSignature(draft?.layers?.[layerId]);
  }
  if (surfaceId === "voice_stack") {
    return stableSettingsSignature(active?.voice_stack) !== stableSettingsSignature(draft?.voice_stack);
  }
  if (surfaceId === "recording") {
    return stableSettingsSignature(active?.recording) !== stableSettingsSignature(draft?.recording);
  }
  return false;
};

const liveApplicableLayerSurfaceChange = (snapshot, active, draft, surfaceId) => {
  const layerId = layerIdForFeedbackSurface(surfaceId);
  if (!layerId || !active?.layers?.[layerId] || !draft?.layers?.[layerId]) return false;
  const live = livePlaybackFeatures(snapshot);
  if (!live.enabled) return false;
  const activeLayer = clone(active.layers[layerId]);
  const draftLayer = clone(draft.layers[layerId]);
  if (live.volume_applies_immediately) draftLayer.volume_db = activeLayer.volume_db;
  if (live.mute_applies_immediately) draftLayer.enabled = activeLayer.enabled;
  if (live.eq_applies_immediately) draftLayer.eq = activeLayer.eq;
  return stableSettingsSignature(activeLayer) === stableSettingsSignature(draftLayer);
};

const liveApplicableVoiceStackSurfaceChange = () => false;

const liveApplicableRecordingSurfaceChange = (snapshot, active, draft, settingsPlan) => {
  const live = livePlaybackFeatures(snapshot);
  if (!live.enabled || !live.voice_raw_preview_treatment_applies_immediately) return false;
  if (!snapshot?.playback?.voice_raw_preview_path) return false;
  const reprocessableFields = Array.isArray(settingsPlan?.livePreviewReprocessableFields)
    ? settingsPlan.livePreviewReprocessableFields
    : [];
  if (reprocessableFields.length === 0) return false;
  const activeRecording = clone(active?.recording || {});
  const draftRecording = clone(draft?.recording || {});
  reprocessableFields.forEach((fieldName) => {
    if (!fieldName.startsWith("recording.")) return;
    const recordingFieldName = fieldName.slice("recording.".length);
    if (recordingFieldName) {
      draftRecording[recordingFieldName] = activeRecording[recordingFieldName];
    }
  });
  return stableSettingsSignature(activeRecording) === stableSettingsSignature(draftRecording);
};

const liveApplicableCoveredSurfaceChange = ({ snapshot, draft, surfaceId, settingsPlan }) => {
  const active = snapshot?.settings?.active;
  if (!active || !draft || !surfaceSettingsChanged(active, draft, surfaceId)) return false;
  if (layerIdForFeedbackSurface(surfaceId)) {
    return liveApplicableLayerSurfaceChange(snapshot, active, draft, surfaceId);
  }
  if (surfaceId === "voice_stack") {
    return liveApplicableVoiceStackSurfaceChange(snapshot, active, draft);
  }
  if (surfaceId === "recording") {
    return liveApplicableRecordingSurfaceChange(snapshot, active, draft, settingsPlan);
  }
  return false;
};

const derivePendingChangeState = (
  settingsPlan,
  sourceFilesChanged = false,
  snapshot = state.snapshot,
) => {
  const runtimeConfigChanged = Boolean(settingsPlan?.runtimeConfigChanged);
  const liveAppliedSettingsChanged =
    liveLayerControlChangeOnly(snapshot, settingsPlan) ||
    liveVoiceStackTransitionChangeOnly(snapshot, settingsPlan) ||
    liveVoiceRawPreviewTreatmentChangeOnly(snapshot, settingsPlan);
  const settingsChanged =
    Boolean(settingsPlan?.changedSections?.length || runtimeConfigChanged) &&
    !liveAppliedSettingsChanged;
  return {
    settingsChanged,
    sourceFilesChanged: Boolean(sourceFilesChanged),
    pendingChanges: settingsChanged || Boolean(sourceFilesChanged),
    runtimeConfigChanged,
  };
};

const deriveSettingsUiState = ({
  snapshot = null,
  settingsPlan = null,
  sourceFilesChanged = false,
  operationFlags = {},
} = {}) => {
  const pendingChangeState = derivePendingChangeState(settingsPlan, sourceFilesChanged, snapshot);
  return {
    pendingChangeState,
    controlState: deriveDashboardControlState({
      snapshot,
      ...operationFlagsFrom(operationFlags),
      pendingChanges: pendingChangeState.pendingChanges,
      runtimeConfigChanged: pendingChangeState.runtimeConfigChanged,
    }),
  };
};

const currentSettingsUiState = (snapshot = state.snapshot) => {
  return deriveSettingsUiState({
    snapshot,
    settingsPlan: settingsChangePlan(snapshot),
    sourceFilesChanged: hasSourceFileChanges(snapshot),
    operationFlags: currentOperationFlags(),
  });
};

const currentDashboardControlState = (snapshot = state.snapshot) => {
  const { pendingChangeState, controlState } = currentSettingsUiState(snapshot);
  return { pendingChangeState, controlState };
};

const renderRecordingTimes = (snapshot = state.snapshot) => {
  if (!snapshot) return;
  $("elapsedTime").textContent = `${snapshot.recording_elapsed_seconds.toFixed(1)}s`;
  $("remainingTime").textContent =
    `${snapshot.recording_remaining_seconds.toFixed(1)}s 남음`;
};

const playbackTimelineNowMs = () => {
  const performanceNow = globalThis.performance?.now?.();
  return Number.isFinite(performanceNow) ? performanceNow : Date.now();
};

const markPlaybackTimelineServerUpdate = () => {
  state.playbackTimelineReceivedAtMs = playbackTimelineNowMs();
};

const playbackTimelineRunning = (snapshot = state.snapshot) => (
  Boolean(snapshot?.playback?.output_running)
);

const playbackTimelineDurationFromSettings = (audio = {}, voiceStack = {}, fallback = 0) => {
  const loopSeconds = Number(voiceStack.loop_seconds || fallback || audio.loop_seconds || 0);
  if (!Number.isFinite(loopSeconds) || loopSeconds <= 0) return 0;
  const transitionSeconds = Number(voiceStack.transition_seconds || 0);
  if (
    Number.isFinite(transitionSeconds) &&
    transitionSeconds > 0 &&
    transitionSeconds < loopSeconds
  ) {
    return loopSeconds - transitionSeconds;
  }
  return loopSeconds;
};

const activePlaybackTimeline = (snapshot = state.snapshot, options = {}) => {
  const playback = snapshot?.playback || {};
  const audio = snapshot?.settings?.active?.audio || {};
  const voiceStack = snapshot?.settings?.active?.voice_stack || {};
  const sampleRate = Number(audio.sample_rate || 0);
  const payloadDuration = Number(playback.duration_seconds || 0);
  const settingsDuration = playbackTimelineDurationFromSettings(
    audio,
    voiceStack,
    payloadDuration,
  );
  const durationSeconds =
    Number.isFinite(settingsDuration) && settingsDuration > 0 ? settingsDuration : payloadDuration;
  const payloadPosition = Number(playback.position_seconds || 0);
  const frameCursor = Number(playback.frame_cursor || 0);
  const positionSeconds =
    playback._positionSecondsProvided !== false &&
    Number.isFinite(payloadPosition) && payloadPosition >= 0
      ? payloadPosition
      : Number.isFinite(sampleRate) && sampleRate > 0 && Number.isFinite(frameCursor)
        ? frameCursor / sampleRate
        : 0;
  const elapsedSeconds = options.interpolate && playbackTimelineRunning(snapshot)
    ? Math.max(0, (Number(options.nowMs ?? playbackTimelineNowMs()) -
      state.playbackTimelineReceivedAtMs) / 1000)
    : 0;
  const boundedPosition =
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? Math.max(0, positionSeconds + elapsedSeconds) % durationSeconds
      : Math.max(0, Number.isFinite(positionSeconds) ? positionSeconds + elapsedSeconds : 0);
  const progress =
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? boundedPosition / durationSeconds
      : Number(playback.progress || 0);
  return {
    positionSeconds: boundedPosition,
    durationSeconds: Number.isFinite(durationSeconds) && durationSeconds > 0 ? durationSeconds : 0,
    progress: Math.max(0, Math.min(1, Number.isFinite(progress) ? progress : 0)),
  };
};

const renderPlaybackTimelinePosition = ({ positionSeconds, durationSeconds, progress }) => {
  const boundedProgress = Math.max(0, Math.min(1, Number.isFinite(progress) ? progress : 0));
  const progressPercent = (boundedProgress * 100).toFixed(3).replace(/\.?0+$/, "");
  const progressBar = $("playbackProgressBar");
  const seekSlider = $("playbackSeekSlider");
  $("playbackPositionTime").textContent = formatSeconds(positionSeconds);
  $("playbackDurationTime").textContent = formatSeconds(durationSeconds);
  if (progressBar.style) {
    progressBar.style.width = `${progressPercent}%`;
  } else {
    progressBar.setAttribute("style", `width: ${progressPercent}%`);
  }
  seekSlider.style?.setProperty("--control-percent", `${progressPercent}%`);
};

const renderPlaybackTimeline = (snapshot = state.snapshot, options = {}) => {
  if (
    deferPlaybackTimelineRender() ||
    deferInteractiveRender("playback-timeline", $("playbackTimeline"), renderPlaybackTimeline)
  ) {
    return;
  }
  const playback = snapshot?.playback || {};
  const { positionSeconds, durationSeconds, progress } = activePlaybackTimeline(snapshot, options);
  const seekSlider = $("playbackSeekSlider");
  const seekReady = Boolean(
    playback.output_running || playback.is_playing || playback.rendered_cache_ready,
  );
  const seekEnabled = Boolean(seekReady && durationSeconds > 0);
  renderPlaybackTimelinePosition({ positionSeconds, durationSeconds, progress });
  seekSlider.max = String(durationSeconds);
  seekSlider.disabled = !seekEnabled || state.playbackControlInFlight;
  seekSlider.title = seekEnabled
    ? "재생 위치가 즉시 이동합니다."
    : "재생 준비가 끝나면 사용할 수 있습니다.";
  if (!playbackSeekSliderActive()) {
    seekSlider.value = String(positionSeconds);
  }
};

const playbackTimelineShouldAnimate = (snapshot = state.snapshot) => {
  const { durationSeconds } = activePlaybackTimeline(snapshot);
  return playbackTimelineRunning(snapshot) && durationSeconds > 0;
};

const schedulePlaybackTimelineAnimation = () => {
  if (state.playbackTimelineAnimationPending) return;
  if (!playbackTimelineShouldAnimate()) return;
  if (typeof requestAnimationFrame !== "function") return;
  state.playbackTimelineAnimationPending = true;
  requestAnimationFrame(renderPlaybackTimelineAnimationFrame);
};

const renderPlaybackTimelineAnimationFrame = (nowMs = playbackTimelineNowMs()) => {
  state.playbackTimelineAnimationPending = false;
  if (!playbackTimelineShouldAnimate()) return;
  renderPlaybackTimeline(state.snapshot, { interpolate: true, nowMs });
  schedulePlaybackTimelineAnimation();
};

const renderTransitionModeBadge = (snapshot) => {
  const badge = $("transitionModeBadge");
  const transitionTarget = snapshot.playback.active_voice_transition_target_id;
  if (transitionTarget) {
    badge.innerHTML = `Live Transition <small lang="ko">목소리 전환 중</small>`;
    badge.className = "status-pill hot";
    badge.title = transitionTarget;
    return;
  }
  if (snapshot.playback.rendered_cache_ready) {
    badge.innerHTML = `Stable Fallback <small lang="ko">기존 재생 경로</small>`;
    badge.className = "status-pill safe";
    badge.title = "Apply and Restart로 렌더링된 캐시를 사용합니다.";
    return;
  }
  badge.innerHTML = `No Rendered Cache <small lang="ko">재생 준비 전</small>`;
  badge.className = "status-pill muted";
  badge.title = "먼저 오디오 설정을 적용하세요.";
};

const outputControlSummaryText = (
  snapshot,
  pendingChangeState = { pendingChanges: false },
  operationFlags = currentOperationFlags(),
) => {
  const flags = operationFlagsFrom(operationFlags);
  if (flags.applyInFlight) {
    return "준비된 오디오 설정을 렌더링하는 중입니다.";
  }
  if (snapshot?.playback?.voice_raw_preview_path) {
    return "녹음 원본을 재생 중입니다.";
  }
  if (liveSampleRateApplyRequiredChange(snapshot)) {
    return "Live 모드 · 샘플레이트 변경은 Apply and Restart 후 반영됩니다.";
  }
  if (liveChannelCountApplyRequiredChange(snapshot)) {
    return "Live 모드 · 샘플레이트 또는 채널 변경은 Apply and Restart 후 반영됩니다.";
  }
  if (liveInputDeviceApplyRequiredChange(snapshot)) {
    return "Live 모드 · 입력 장치 변경은 System 패널 적용 후 Apply and Restart 후 반영됩니다.";
  }
  if (liveOutputDeviceApplyRequiredChange(snapshot)) {
    return "Live 모드 · 출력 장치 변경은 System 패널 적용 후 Apply and Restart 후 반영됩니다.";
  }
  if (liveLoopLengthApplyRequiredChange(snapshot)) {
    return "Live 모드 · 루프 길이 변경은 Apply and Restart 후 반영됩니다.";
  }
  if (liveSourceFileSelectionApplyRequiredChange(snapshot)) {
    return "Live 모드 · 소스 파일 선택은 Apply and Restart 후 반영됩니다.";
  }
  if (pendingChangeState.pendingChanges) {
    return "저장 안 된 오디오 변경이 적용 후 재시작을 기다립니다.";
  }
  if (snapshot?.playback?.output_running) {
    if (snapshot.settings?.active?.voice_stack?.mode === "live_ephemeral") {
      return "Live 전환 · 새 녹음은 준비되면 Low/Mid/Voice가 함께 부드럽게 전환됩니다.";
    }
    return "Stable fallback · 변경사항 적용 후 렌더링된 캐시로 재생합니다.";
  }
  return "준비된 오디오를 렌더링한 뒤 출력을 시작합니다.";
};

const settingsPresetLayerShortLabels = {
  low: "Low",
  mid: "Mid",
  voice: "Voice",
};

const settingsPresetDbLabel = (value) => {
  const number = Number(value);
  if (!Number.isFinite(number)) return "0.0dB";
  return `${number.toFixed(1)}dB`;
};

const settingsPresetLayerSummary = (preset) => {
  const layers = preset?.payload?.layers || {};
  return ["low", "mid", "voice"]
    .map((layerId) => {
      const layer = layers[layerId];
      if (!layer) return null;
      const label = settingsPresetLayerShortLabels[layerId] || layerId;
      const muted = layer.enabled === false ? " off" : "";
      return `${label} ${settingsPresetDbLabel(layer.volume_db)}${muted}`;
    })
    .filter(Boolean);
};

const settingsPresetSourceSummary = (preset) => {
  const sources = preset?.payload?.sources || {};
  return Object.values(sources)
    .filter(Boolean)
    .map((path) => String(path).split("/").pop())
    .slice(0, 3);
};

const settingsPresetSummary = (preset) => {
  const layerSummary = settingsPresetLayerSummary(preset);
  const sourceSummary = settingsPresetSourceSummary(preset);
  if (layerSummary.length && sourceSummary.length) {
    return `${layerSummary.join(" · ")} / ${sourceSummary.join(", ")}`;
  }
  if (layerSummary.length) return layerSummary.join(" · ");
  if (sourceSummary.length) return sourceSummary.join(", ");
  return "Graph EQ, mixer, source selection";
};

const settingsPresetLoadBlockedReason = () => {
  if (!state.snapshot) return "상태를 불러온 뒤 사용할 수 있습니다.";
  if (currentPlaybackApplyMode() !== "stable") {
    return "Live 중에는 Stable로 전환한 뒤 불러오세요.";
  }
  if (state.settingsPresetActionInFlight) return "프리셋 작업 중입니다.";
  return "";
};

const renderSettingsPresets = () => {
  const list = $("settingsPresetList");
  if (!list) return;
  const input = $("settingsPresetNameInput");
  const saveButton = $("settingsPresetSaveButton");
  const loadBlockedReason = settingsPresetLoadBlockedReason();
  const actionDisabled = state.settingsPresetActionInFlight || !state.snapshot;
  if (input) input.disabled = state.settingsPresetActionInFlight;
  if (saveButton) {
    saveButton.disabled = actionDisabled;
    saveButton.title = actionDisabled ? "상태를 불러온 뒤 저장할 수 있습니다." : "";
  }
  if (state.settingsPresetsError) {
    list.innerHTML = `
      <p class="settings-preset-empty">${escapeHtml(state.settingsPresetsError)}</p>
    `;
    return;
  }
  if (!state.settingsPresets?.length) {
    list.innerHTML = `
      <p class="settings-preset-empty">저장된 프리셋 없음</p>
    `;
    return;
  }
  const liveModeHint = loadBlockedReason && currentPlaybackApplyMode() !== "stable"
    ? `<p class="settings-preset-mode-hint">${escapeHtml(loadBlockedReason)}</p>`
    : "";
  list.innerHTML = `
    ${liveModeHint}
    ${state.settingsPresets.map((preset) => {
      const loadDisabled = Boolean(loadBlockedReason);
      const commandDisabled = state.settingsPresetActionInFlight;
      const title = loadDisabled ? ` title="${escapeHtml(loadBlockedReason)}"` : "";
      return `
        <article class="settings-preset-item" role="listitem">
          <div class="settings-preset-main">
            <strong>${escapeHtml(preset.name || "Untitled")}</strong>
            <small>${escapeHtml(settingsPresetSummary(preset))}</small>
          </div>
          <div class="settings-preset-actions">
            <button
              class="settings-preset-action primary"
              type="button"
              data-settings-preset-load="${escapeHtml(preset.id)}"
              ${loadDisabled ? "disabled" : ""}
              ${title}
            >
              Load
            </button>
            <button
              class="settings-preset-action"
              type="button"
              data-settings-preset-update="${escapeHtml(preset.id)}"
              ${commandDisabled ? "disabled" : ""}
            >
              Update
            </button>
            <button
              class="settings-preset-action danger"
              type="button"
              data-settings-preset-delete="${escapeHtml(preset.id)}"
              ${commandDisabled ? "disabled" : ""}
            >
              Delete
            </button>
          </div>
        </article>
      `;
    }).join("")}
  `;
};

const renderState = () => {
  renderSyncBadge();
  const snapshot = state.snapshot;
  if (!snapshot) return;
  const { pendingChangeState, controlState } = currentDashboardControlState(snapshot);

  $("armedBadge").textContent = snapshot.armed ? "녹음 준비 켜짐" : "녹음 준비 꺼짐";
  $("armedBadge").className = `status-pill ${snapshot.armed ? "safe" : "muted"}`;
  $("recordingBadge").textContent = snapshot.is_recording ? "녹음 중" : "대기";
  $("recordingBadge").className = `status-pill ${snapshot.is_recording ? "hot" : ""}`;
  $("outputBadge").textContent = snapshot.playback.output_running ? "출력 중" : "출력 꺼짐";
  $("outputBadge").className = `status-pill ${snapshot.playback.output_running ? "safe" : "muted"}`;
  renderTransitionModeBadge(snapshot);
  renderStorageModeControls();
  $("participantCount").textContent = snapshot.participant_count;
  renderRecordingTimes(snapshot);
  renderPlaybackTimeline(snapshot);
  schedulePlaybackTimelineAnimation();
  $("minimumRecordingTime").textContent = formatSeconds(
    snapshot.settings.active.input_control.minimum_recording_seconds,
  );
  $("maximumRecordingTime").textContent = formatSeconds(
    snapshot.settings.active.input_control.maximum_recording_seconds,
  );
  $("recordCoreStatus").textContent = controlState.recordingStartBusy || controlState.recordingStopBusy
    ? "처리 중"
    : snapshot.is_recording
      ? "녹음 중"
      : controlState.captureReady
        ? "준비 완료"
        : snapshot.armed
          ? "대기 중"
          : "준비 전";
  document.querySelector(".record-core").classList.toggle("armed", controlState.captureReady);
  document.querySelector(".record-core").classList.toggle("recording", snapshot.is_recording);
  renderRecordReadiness(snapshot, controlState);
  $("pendingBadge").hidden = !pendingChangeState.pendingChanges;
  $("pendingBadge").textContent = pendingChangeState.pendingChanges ? "저장 안 된 오디오 변경" : "";
  $("pendingBadge").className = "status-pill hot";
  $("outputControlSummary").textContent = outputControlSummaryText(
    snapshot,
    pendingChangeState,
  );
  $("captureGate").className = `capture-gate ${controlState.captureGateClass}`;
  $("captureGateSwitch").disabled = controlState.captureGateSwitchDisabled;
  $("captureGateSwitch").setAttribute(
    "aria-checked",
    controlState.captureGateOn ? "true" : "false",
  );
  $("captureGateSwitch").classList.toggle("checked", controlState.captureGateOn);
  $("captureGateState").textContent = snapshot.is_recording
    ? "녹음 중"
    : snapshot.armed
      ? "켜짐"
      : "꺼짐";
  $("startButton").disabled = controlState.startDisabled;
  $("stopButton").disabled = controlState.stopDisabled;
  $("startOutputButton").disabled = controlState.startOutputDisabled;
  $("stopOutputButton").disabled = controlState.stopOutputDisabled;
  $("restartOutputButton").disabled = controlState.restartOutputDisabled;
  $("applyButton").disabled = controlState.applyDisabled;
  $("applyButton").textContent = controlState.applyLabel;
  $("applyButton").classList.toggle("attention", controlState.applyAttention);
  $("resetButton").disabled = controlState.resetDisabled;
  $("resetButton").title = controlState.resetTitle;
  $("resetParticipantsButton").disabled = controlState.resetParticipantsDisabled;
  $("resetParticipantsButton").title = controlState.resetParticipantsTitle;
  $("applyButton").title = controlState.applyTitle;
  renderSettingsPresets();
  renderErrors();
};

const recordOutcomeKind = () => {
  const className = $("recordOutcomeStatus").parentElement.className;
  return className.split(/\s+/).find((name) => replaceableRecordOutcomeKinds.has(name));
};

const renderRecordReadiness = (snapshot, controlState) => {
  if (controlState.recordingStartBusy) {
    setRecordStatus("processing", "녹음 시작 중...", "녹음 준비를 확인하고 있습니다.");
  } else if (controlState.recordingStopBusy) {
    setRecordStatus("processing", "녹음 처리 중...");
  } else if (snapshot.is_recording) {
    setRecordStatus("recording", "녹음 중", "스페이스바를 떼면 중지됩니다.");
  } else if (!replaceableRecordOutcomeKinds.has(recordOutcomeKind())) {
    return;
  } else if (controlState.captureReady) {
    setRecordStatus(
      "armed-ready",
      "준비 완료",
      "누르고 있는 동안 녹음되고, 떼면 중지됩니다.",
    );
  } else if (snapshot.armed) {
    setRecordStatus("processing", "설정 작업 중...", "설정 작업이 끝나면 녹음을 시작할 수 있습니다.");
  } else {
    setRecordStatus(
      "ready",
      "녹음 준비 필요",
      "켜면 스페이스바로 녹음할 수 있습니다.",
    );
  }
};

const renderLastEventBadge = () => {
  const lastEvent = state.diagnostics?.events?.recent?.[0];
  if (state.diagnosticsError || state.diagnostics?.events?.error) {
    $("lastEventBadge").textContent = "최근 이벤트 불러오기 실패";
    $("lastEventBadge").className = "status-pill hot";
  } else if (lastEvent?.event_type) {
    $("lastEventBadge").textContent = `최근 ${formatEventType(lastEvent.event_type)}`;
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
  } else if (outcome.reason === "silent_input") {
    setRecordStatus(
      "discarded",
      "녹음 실패",
      "마이크 입력이 거의 감지되지 않았습니다. 선택된 마이크, 운영체제 마이크 권한, 외장 마이크 연결을 확인한 뒤 다시 녹음해 주세요.",
    );
  } else if (outcome.reason === "disarmed") {
    setRecordStatus("discarded", "녹음 준비 꺼짐", `${duration} 녹음됨.`);
  } else {
    setRecordStatus("discarded", "녹음 폐기됨", translateUiErrorMessage(outcome.reason) || duration);
  }
};

const currentErrorMessages = () => {
  return currentErrorNotices().map((notice) => notice.summary);
};

const currentErrorNotices = () => {
  return [
    state.deviceError,
    state.diagnosticsError,
    state.sourcesError,
    state.settingsPresetsError,
  ].map((message) => noticeFromMessage(message, "error")).filter(Boolean);
};

const currentWarningMessages = () => {
  return currentWarningNotices().map((notice) => notice.summary);
};

const currentWarningNotices = () => {
  return [
    ...(state.snapshot?.operator_notices || []),
    ...(state.devices?.warnings || []),
    state.snapshot?.playback?.transition_warning || null,
  ]
    .map((message) => noticeFromMessage(message, "caution"))
    .filter(Boolean);
};

const renderErrors = () => {
  const notices = currentErrorNotices();
  if (notices.length) {
    renderNoticeBanner(notices);
    return;
  }
  if (state.transientError) {
    setErrorBanner(state.transientError);
    return;
  }
  if (state.transientNotice) {
    renderNoticeBanner([state.transientNotice]);
    return;
  }
  const warnings = currentWarningNotices();
  if (warnings.length) {
    renderNoticeBanner(warnings);
    return;
  }
  renderNoticeBanner([]);
};

const renderDevices = () => {
  renderDeviceHealthBadge();
  renderSystemPanel();
};

const renderSystemPanel = () => {
  renderSystemDevices();
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
    const severity = highestNoticeSeverity(currentWarningNotices());
    $("deviceHealthBadge").textContent = severity === "error" ? "장치 오류" : "장치 주의";
    $("deviceHealthBadge").className =
      `status-pill ${noticeSeverityDisplay[severity].badgeClass}`;
  } else {
    $("deviceHealthBadge").textContent = "장치 정상";
    $("deviceHealthBadge").className = "status-pill safe";
  }
};

const renderSystemStatus = () => {
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
  const devices = state.devices;
  const activeDevices = state.snapshot?.settings.active.devices || {};
  if (!devices) {
    renderSystemDeviceSelect("inputDeviceSelect", [], null, true);
    renderSystemDeviceSelect("outputDeviceSelect", [], null, true);
    renderDeviceWarnings([]);
    return;
  }
  const inputSelectedId = effectiveSystemDeviceSelectedId(
    activeDevices.input_device_id,
    devices.selected_input_device,
  );
  const outputSelectedId = effectiveSystemDeviceSelectedId(
    activeDevices.output_device_id,
    devices.selected_output_device,
  );
  renderSystemDeviceSelect(
    "inputDeviceSelect",
    devices.input_devices || [],
    inputSelectedId,
    deviceChangeForceDisabled("input_device_id"),
  );
  renderSystemDeviceSelect(
    "outputDeviceSelect",
    devices.output_devices || [],
    outputSelectedId,
  );
  renderDeviceWarnings(devices.warnings || []);
};

const effectiveSystemDeviceSelectedId = (configuredId, selectedDevice) => {
  if (!configuredId) return null;
  return selectedDevice?.id || configuredId;
};

const renderDeviceWarnings = (warnings) => {
  const warningList = $("deviceWarnings");
  renderNoticeList(
    warningList,
    warnings.map((warning) => noticeFromMessage(warning, "caution")),
  );
};

const renderSourceHealthList = (sources) => {
  const container = $("sourceHealthList");
  container.innerHTML = "";
  sources.forEach((source) => {
    const row = document.createElement("div");
    row.className = `diagnostic-row source-row ${source.exists ? "source-ready" : "source-missing"}`;
    const label = document.createElement("span");
    label.textContent = source.label;
    const value = document.createElement("div");
    value.className = "source-status-value";
    const main = document.createElement("strong");
    main.className = "source-status-main";
    const meta = document.createElement("small");
    meta.className = "source-status-meta";
    if (source.exists) {
      main.textContent = "준비됨";
      meta.textContent = `${formatBytes(source.size_bytes)} · ${formatTimestamp(source.modified_at)}`;
    } else {
      main.textContent = "없음";
      meta.textContent = source.path;
    }
    value.append(main, meta);
    row.append(label, value);
    container.appendChild(row);
  });
};

const renderSourceLibrary = (options = {}) => {
  const container = $("sourceLibraryList");
  if (!container) return;
  syncSourceLibraryBusyControls(container);
  if (
    options.allowInteractiveDeferral !== false &&
    deferInteractiveRender("source-library", container, renderSourceLibrary, {
      nextControlForTarget: (_container, target) => sourceInteractiveControlFromEventTarget(target),
    })
  ) {
    return;
  }
  const status = $("sourceLibraryStatus");
  if (!state.sources) {
    status.textContent = state.sourcesError ? "목록 실패" : "확인 중";
    status.className = `status-pill ${state.sourcesError ? "hot" : "muted"}`;
    const nextSignature = `empty:${state.sourcesError || ""}`;
    if (state.renderSignatures.sourceLibrary === nextSignature) return;
    state.renderSignatures.sourceLibrary = nextSignature;
    container.innerHTML = "";
    let placeholder;
    if (state.sourcesError) {
      placeholder = noticeItemElement(
        noticeFromMessage(state.sourcesError, "error"),
        "div",
        "source-library-empty",
      );
    } else {
      placeholder = document.createElement("div");
      placeholder.className = "source-library-empty";
      placeholder.textContent = "파일 목록을 확인하는 중입니다.";
    }
    container.appendChild(placeholder);
    return;
  }

  const categories = orderedSourceCategories(state.sources.categories || []);
  const statusState = deriveSourceLibraryStatusState(categories);
  status.textContent = statusState.text;
  status.className = statusState.className;
  const nextSignature = sourceLibrarySignature(categories);
  if (state.renderSignatures.sourceLibrary === nextSignature) return;
  state.renderSignatures.sourceLibrary = nextSignature;
  container.innerHTML = "";
  categories.forEach((category) => {
    container.appendChild(sourceCategoryCard(category));
  });
};

const sourceLibrarySignature = (categories) => {
  const sourceLockState = currentSourceLockState();
  return JSON.stringify([
    sourceLockState.sourceActionTitle,
    state.sourceCardSelections,
    state.sourceRenameDrafts,
    state.sourceRenameEditing,
    categories.map((category) => [
      category.id,
      category.label,
      category.settings_field,
      category.required,
      category.directory,
      category.active_exists,
      category.legacy_exists,
      category.legacy_path,
      category.legacy_size_bytes,
      category.legacy_modified_at,
      category.selected_path,
      (category.files || []).map((file) => [
        file.name,
        file.path,
        file.size_bytes,
        file.modified_at,
        file.active,
        file.applied,
      ]),
      sourceUploadSignature(category.id),
    ]),
  ]);
};

const sourceCategoryDisplayOrder = ["voice_stack", "voice_raw", "mid", "low"];

const orderedSourceCategories = (categories = []) => {
  const order = new Map(sourceCategoryDisplayOrder.map((id, index) => [id, index]));
  return [...categories].sort((left, right) => {
    const leftOrder = order.has(left.id) ? order.get(left.id) : sourceCategoryDisplayOrder.length;
    const rightOrder = order.has(right.id) ? order.get(right.id) : sourceCategoryDisplayOrder.length;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
    return String(left.id || "").localeCompare(String(right.id || ""));
  });
};

const sourceCategoryRequired = (category) => category?.required !== false;

const sourceCategorySelectable = (_category) => true;

const sourceCategoryConfirmable = (category) => category !== "voice_raw";

const sourceCategoryHasPendingSelection = (category = {}) =>
  Boolean((category.files || []).some((file) => file.active && !file.applied));

const deriveSourceCategoryStatusState = (category = {}) => {
  if (!sourceCategoryConfirmable(category.id)) {
    return { text: "", className: "" };
  }
  if (sourceCategoryHasPendingSelection(category)) {
    return {
      text: "적용 대기",
      className: "status-pill caution",
    };
  }
  if (category.active_exists) {
    return { text: "", className: "" };
  }
  const required = sourceCategoryRequired(category);
  return {
    text: required ? "없음" : "",
    className: required ? "status-pill hot" : "",
  };
};

const deriveSourceLibraryStatusState = (categories = []) => {
  const missingCount = categories.filter(
    (category) => sourceCategoryRequired(category) && !category.active_exists,
  ).length;
  return {
    missingCount,
    text: missingCount ? `${missingCount}개 선택 필요` : "파일 준비됨",
    className: `status-pill ${missingCount ? "hot" : "safe"}`,
  };
};

const sourceUploadState = (category) => {
  if (!state.sourceUploads[category]) {
    state.sourceUploads[category] = { file: null };
  }
  return state.sourceUploads[category];
};

const sourceUploadSignature = (category) => {
  const upload = sourceUploadState(category);
  const file = upload.file;
  return [
    file ? [file.name, file.size, file.lastModified] : null,
  ];
};

const shouldSelectUploadedSource = (_category) => false;

const sourceActionBusyTitle = (operationFlags = {}) =>
  deriveOperationLocks(operationFlagsFrom(operationFlags)).sourceActionTitle;

const currentSourceLockState = () => deriveOperationLocks(currentOperationFlags());

const sourceCommandBlocked = () =>
  currentSourceLockState().sourceCommandBlocked;

const sourceLibraryInteractiveControlSelector = [
  "[data-source-pick]",
  "[data-source-file]",
  "[data-source-delete]",
  "[data-source-rename]",
  "[data-source-rename-input]",
  "[data-source-rename-save]",
  "[data-source-rename-cancel]",
  "[data-voice-raw-preview-selected]",
  "[data-voice-raw-add-selected]",
].join(", ");

const sourceFileControlFromEventTarget = (target) =>
  target?.closest?.("[data-source-pick]") || null;

const sourceFileSelectionControlSelector = "button,input,select,textarea";

const selectSourceFileFromEventTarget = (target) => {
  if (target?.closest?.(sourceFileSelectionControlSelector)) return false;
  const fileControl = sourceFileControlFromEventTarget(target);
  if (!fileControl) return false;
  return selectSourceFileFromCard(fileControl.dataset.sourcePick, fileControl.dataset.sourcePath);
};

const sourceInteractiveControlFromEventTarget = (target) => {
  const container = $("sourceLibraryList");
  const control = target?.closest?.(sourceLibraryInteractiveControlSelector) || null;
  if (!control || !interactiveControlTags.has(control.tagName)) return null;
  return container === control || container?.contains?.(control) ? control : null;
};

const sourceDropZoneFromEventTarget = (target) =>
  target?.closest?.("[data-source-drop]") || null;

const blockSourceFileDrop = (event, dropZone) => {
  event.preventDefault();
  dropZone?.classList.remove("is-dragging");
  if (event.dataTransfer) event.dataTransfer.dropEffect = "none";
};

const sourceLibraryBusyControlSelector = [
  "[data-source-pick]",
  "[data-source-file]",
  "[data-source-delete]",
  "[data-source-rename]",
  "[data-source-rename-input]",
  "[data-source-rename-save]",
  "[data-source-rename-cancel]",
  "[data-voice-raw-preview-selected]",
  "[data-voice-raw-add-selected]",
].join(", ");
const sourceLibraryBusyControlState = new WeakMap();

const syncSourceLibraryBusyControls = (container) => {
  if (typeof container.querySelectorAll !== "function") return;
  const controls = container.querySelectorAll(sourceLibraryBusyControlSelector);
  const activeControl = activeInteractiveControlFor(container);
  const busyTitle = currentSourceLockState().sourceActionTitle;
  if (!busyTitle) {
    controls.forEach((control) => {
      const previous = sourceLibraryBusyControlState.get(control);
      if (!previous) return;
      control.disabled = previous.disabled;
      control.title = previous.title;
      sourceLibraryBusyControlState.delete(control);
    });
    return;
  }
  controls.forEach((control) => {
    if (!sourceLibraryBusyControlState.has(control)) {
      sourceLibraryBusyControlState.set(control, {
        disabled: control.disabled,
        title: control.title,
      });
    }
    if (control === activeControl) {
      control.title = busyTitle;
      return;
    }
    control.disabled = true;
    control.title = busyTitle;
  });
};

const deriveSourceUploadActionState = (upload = {}) => {
  const file = upload.file || null;
  const hasFile = Boolean(file);
  return {
    hasFile,
    hint: hasFile
      ? `${file.name} · ${formatBytes(file.size || 0)} 선택됨`
      : "WAV 파일을 이 폴더로 복사합니다.",
  };
};

const deriveSourceFileActionState = (file = {}, operationFlags = {}) => {
  const active = Boolean(file.active);
  const applied = Boolean(file.applied);
  const busyTitle = sourceActionBusyTitle(operationFlags);
  const busy = Boolean(busyTitle);
  return {
    active,
    deleteDisabled: active || applied || busy,
    deleteTitle: active
      ? "현재 선택된 파일은 삭제할 수 없습니다"
      : applied
        ? "현재 적용된 파일은 삭제할 수 없습니다"
      : busy ? busyTitle : "",
  };
};

const deriveVoiceRawActionState = (file = {}, operationFlags = {}) => {
  const busyTitle = sourceActionBusyTitle(operationFlags);
  const busy = Boolean(busyTitle);
  return {
    previewDisabled: busy,
    addDisabled: busy,
    previewTitle: busy ? busyTitle : "현재 목소리 처리로 VR을 미리 듣습니다.",
    addTitle: busy ? busyTitle : "선택된 Voice Stack에 VR을 추가합니다.",
  };
};

const deriveSourceFileStatusBadges = (file = {}, action = null) => {
  const fileState = action || deriveSourceFileActionState(file);
  const active = Boolean(fileState.active);
  if (active && !file.applied) return [{ text: "적용 대기", tone: "pending" }];
  return [];
};

const rememberSourceUploadFile = (category, file) => {
  sourceUploadState(category).file = file || null;
};

const rememberSourceUploadFileFromInput = (fileInput) => {
  if (sourceCommandBlocked()) return false;
  rememberSourceUploadFile(fileInput.dataset.sourceFile, fileInput.files?.[0] || null);
  return true;
};

const clearSourceUploadFile = (category) => {
  rememberSourceUploadFile(category, null);
};

const sourceRenameKey = (category, path) => `${category}:${path}`;

const sourceFileNameParts = (name = "") => {
  const index = name.lastIndexOf(".");
  if (index <= 0) return { stem: name, extension: "" };
  return {
    stem: name.slice(0, index),
    extension: name.slice(index),
  };
};

const sourceRenameDraft = (category, file) => {
  const key = sourceRenameKey(category, file.path);
  const fallback = sourceFileNameParts(file.name).stem;
  return state.sourceRenameDrafts[key] ?? fallback;
};

const startSourceRename = (category, file) => {
  const key = sourceRenameKey(category, file.path);
  state.sourceRenameEditing[key] = true;
  state.sourceRenameDrafts[key] = sourceRenameDraft(category, file);
  renderSourceLibrary({ allowInteractiveDeferral: false });
};

const rememberSourceRenameDraft = (category, path, stem) => {
  state.sourceRenameDrafts[sourceRenameKey(category, path)] = stem;
};

const clearSourceRename = (category, path) => {
  const key = sourceRenameKey(category, path);
  delete state.sourceRenameEditing[key];
  delete state.sourceRenameDrafts[key];
};

const cancelSourceRename = (category, path) => {
  clearSourceRename(category, path);
  renderSourceLibrary({ allowInteractiveDeferral: false });
};

const selectSourceFileFromCard = (category, path) => {
  if (sourceCommandBlocked()) return false;
  if (!sourceCategorySelectable(category)) return false;
  state.sourceCardSelections[category] = path;
  renderSourceLibrary({ allowInteractiveDeferral: false });
  return true;
};

const cancelSelectedSourceCard = (category) => {
  delete state.sourceCardSelections[category];
  renderSourceLibrary({ allowInteractiveDeferral: false });
};

const confirmSelectedSourceCard = (category) => {
  const path = state.sourceCardSelections[category];
  if (!path) return null;
  return selectSourceFile(category, path, { clearCardSelection: true });
};

const sourceStatusMarkup = (status) => {
  if (!status?.text) return "";
  return `
      <span class="${status.className}">
        ${escapeHtml(status.text)}
      </span>
    `;
};

const sourceCategoryVoiceRawActionsMarkup = (category) => {
  const selectedPath = state.sourceCardSelections.voice_raw || null;
  const selectedFile = category.files?.find((file) => file.path === selectedPath) || null;
  const noSelectionTitle = "먼저 Voice Raw 파일을 선택하세요.";
  const action = selectedFile
    ? deriveVoiceRawActionState(selectedFile, currentOperationFlags())
    : {
        previewDisabled: true,
        addDisabled: true,
        previewTitle: noSelectionTitle,
        addTitle: noSelectionTitle,
      };
  const selectedPathValue = selectedFile?.path || "";
  return `
    <div class="source-category-actions voice-raw-source-actions">
      <button
        class="mini-button"
        type="button"
        data-voice-raw-preview-selected="${escapeHtml(selectedPathValue)}"
        title="${escapeHtml(action.previewTitle)}"
        ${action.previewDisabled ? " disabled" : ""}
      >Preview</button>
      <button
        class="mini-button"
        type="button"
        data-voice-raw-add-selected="${escapeHtml(selectedPathValue)}"
        title="${escapeHtml(action.addTitle)}"
        ${action.addDisabled ? " disabled" : ""}
      >Add to Stack</button>
    </div>
  `;
};

const sourceCategoryHeaderActionMarkup = (category, status) => {
  if (category.id === "voice_raw") {
    return sourceCategoryVoiceRawActionsMarkup(category);
  }
  const selectedPath = state.sourceCardSelections[category.id] || null;
  const selectedFile = category.files?.find((file) => file.path === selectedPath) || null;
  if (!selectedFile) {
    return sourceStatusMarkup(status);
  }
  const canConfirmSelection = selectedPath !== category.selected_path;
  const confirmDisabled = canConfirmSelection && !sourceCommandBlocked() ? "" : " disabled";
  const confirmTitle = sourceCommandBlocked()
    ? ` title="${escapeHtml(currentSourceLockState().sourceActionTitle)}"`
    : "";
  return `
    <div class="source-category-actions">
      <button
        class="mini-button primary"
        type="button"
        data-source-confirm-selection="${escapeHtml(category.id)}"
        ${confirmTitle}
        ${confirmDisabled}
      >선택</button>
      <button
        class="mini-button"
        type="button"
        data-source-cancel="${escapeHtml(category.id)}"
      >취소</button>
    </div>
  `;
};

const sourceCategoryCard = (category) => {
  const label = sourceCategoryLabels[category.id] || {
    title: category.label || category.id,
    helper: category.directory,
  };
  const upload = sourceUploadState(category.id);
  const busyTitle = currentSourceLockState().sourceActionTitle;
  const sourceActionDisabled = busyTitle ? " disabled" : "";
  const sourceActionTitle = busyTitle ? ` title="${escapeHtml(busyTitle)}"` : "";
  const status = deriveSourceCategoryStatusState(category);
  const uploadAction = deriveSourceUploadActionState(upload);
  const card = document.createElement("section");
  card.className = "source-category-card";
  card.innerHTML = `
    <div class="source-category-head">
      <div>
        <h3>${escapeHtml(label.title)}</h3>
        <p>${escapeHtml(label.helper)}</p>
      </div>
      ${sourceCategoryHeaderActionMarkup(category, status)}
    </div>
    <div class="source-file-list source-file-list-scroll">
      ${sourceFileRows(category)}
    </div>
    <div class="source-upload-row">
      <label class="source-drop-zone" data-source-drop="${escapeHtml(category.id)}">
        <input
          class="sr-only"
          type="file"
          accept=".wav,audio/wav,audio/x-wav"
          data-source-file="${escapeHtml(category.id)}"
          ${sourceActionDisabled}
          ${sourceActionTitle}
        />
        <strong>파일 선택 또는 드롭</strong>
        <small>${escapeHtml(uploadAction.hint)}</small>
      </label>
    </div>
  `;
  return card;
};

const sourceFileRows = (category) => {
  if (!category.files?.length) {
    return `<div class="source-library-empty">아직 추가된 WAV 파일이 없습니다.</div>`;
  }
  return category.files.map((file) => {
    const selectable = sourceCategorySelectable(category.id);
    const confirmable = sourceCategoryConfirmable(category.id);
    const action = deriveSourceFileActionState(file, currentOperationFlags());
    const selectedPath = selectable ? state.sourceCardSelections[category.id] || null : null;
    const locallySelected = selectedPath === file.path;
    const badges = (confirmable ? deriveSourceFileStatusBadges(file, action) : [])
      .map((badge) => (
        `<span class="source-file-badge ${escapeHtml(badge.tone)}">${escapeHtml(badge.text)}</span>`
      ))
      .join("");
    const disabled = action.deleteDisabled ? " disabled" : "";
    const deleteTitle = action.deleteTitle
      ? ` title="${escapeHtml(action.deleteTitle)}"`
      : "";
    const deleteButton = `
        <button
          class="mini-button danger source-file-delete-button"
          type="button"
          data-source-delete="${escapeHtml(category.id)}"
          data-source-path="${escapeHtml(file.path)}"
          ${deleteTitle}
          ${disabled}
        >삭제</button>
      `;
    const renameKey = sourceRenameKey(category.id, file.path);
    const renaming = Boolean(state.sourceRenameEditing[renameKey]);
    const nameParts = sourceFileNameParts(file.name);
    const renameDraft = sourceRenameDraft(category.id, file);
    const shortModifiedAt = formatShortTimestamp(file.modified_at);
    const modifiedDatetime = file.modified_at
      ? ` datetime="${escapeHtml(file.modified_at)}"`
      : "";
    const renameControls = renaming ? `
        <div class="source-rename-row">
          <input
            class="source-rename-input"
            type="text"
            value="${escapeHtml(renameDraft)}"
            data-source-rename-input="${escapeHtml(category.id)}"
            data-source-path="${escapeHtml(file.path)}"
            aria-label="${escapeHtml(file.name)} 파일명"
            ${sourceCommandBlocked() ? " disabled" : ""}
          />
          <span class="source-rename-extension">${escapeHtml(nameParts.extension)}</span>
          <button
            class="mini-button"
            type="button"
            data-source-rename-save="${escapeHtml(category.id)}"
            data-source-path="${escapeHtml(file.path)}"
            ${sourceCommandBlocked() ? " disabled" : ""}
          >저장</button>
          <button
            class="mini-button"
            type="button"
            data-source-rename-cancel="${escapeHtml(category.id)}"
            data-source-path="${escapeHtml(file.path)}"
          >취소</button>
        </div>
      ` : `
        <div class="source-file-name-line">
          <span class="source-file-title">
            <strong>${escapeHtml(file.name)}</strong>
            <button
              class="icon-mini-button"
              type="button"
              data-source-rename="${escapeHtml(category.id)}"
              data-source-path="${escapeHtml(file.path)}"
              aria-label="${escapeHtml(file.name)} 파일명 수정"
              title="파일명 수정"
              ${sourceCommandBlocked() ? " disabled" : ""}
            >✎</button>
          </span>
          <time class="source-file-date"${modifiedDatetime}>${escapeHtml(shortModifiedAt)}</time>
          ${deleteButton}
        </div>
      `;
    const metaLine = badges ? `
        <div class="source-file-meta-line">
          <div class="source-file-badges">${badges}</div>
        </div>
      ` : "";
    const rowClass = [
      "source-file-row",
      category.id === "voice_raw" ? "voice-raw" : "",
      locallySelected ? "selected" : "",
      confirmable && file.active && !file.applied ? "pending" : "",
      confirmable && file.applied ? "applied" : "",
    ].filter(Boolean).join(" ");
    const selectionAttributes = selectable
      ? `
        role="button"
        tabindex="0"
        data-source-pick="${escapeHtml(category.id)}"
        data-source-path="${escapeHtml(file.path)}"
      `
      : "";
    return `
      <div
        class="${rowClass}"
        ${selectionAttributes}
      >
        <div class="source-file-main">
          ${renameControls}
          ${metaLine}
        </div>
      </div>
    `;
  }).join("");
};

const renderEventLogSummary = (events, error = null) => {
  const list = $("eventLogSummary");
  clearElement(list);
  if (error) {
    const notice = noticeFromMessage(error, "error");
    list.appendChild(noticeItemElement(notice));
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
    label.textContent = formatEventType(event.event_type);
    item.append(time, label);
    list.appendChild(item);
  });
};

const nextSourceMutationRequestId = () => {
  state.sourceMutationRequestId += 1;
  return state.sourceMutationRequestId;
};

const isCurrentSourceMutation = (requestId) => requestId === state.sourceMutationRequestId;

const beginStorageModeChange = () => {
  state.storageModeRequestId += 1;
  return state.storageModeRequestId;
};

const isCurrentStorageModeChange = (requestId) => requestId === state.storageModeRequestId;

const invalidatePendingStorageModeChanges = () => {
  state.storageModeRequestId += 1;
  state.storageModeInFlight = false;
  state.pendingStorageMode = null;
};

const beginSourceMutation = () => {
  const requestId = nextSourceMutationRequestId();
  setOperationLockFlag("sourceMutationInFlight", true);
  return requestId;
};

const finishSourceMutation = (requestId) => {
  if (!isCurrentSourceMutation(requestId)) return;
  setOperationLockFlag("sourceMutationInFlight", false);
};

const applySourceMutationPayload = (payload, options = {}) => {
  if (serverPayloadRevisionIsOlder(payload)) return false;
  rememberServerPayloadRevision(payload);
  if (payload.settings) {
    applySettingsPayload(payload.settings, {
      syncDraft: false,
      mergeDraftSections: ["sources"],
    });
  }
  if (payload.sources) {
    state.sources = payload.sources;
  }
  if (options.clearUploadCategory) {
    clearSourceUploadFile(options.clearUploadCategory);
  }
  if (payload.settings) {
    renderState();
  }
  renderSourceLibrary({ allowInteractiveDeferral: false });
  return true;
};

const recoverSourceMutationError = async (error) => {
  showError(error.message);
  await requestSources().catch(() => {});
};

const selectSourceFile = async (category, path, options = {}) => {
  if (sourceCommandBlocked()) return null;
  const requestId = beginSourceMutation();
  try {
    const payload = await api(`/api/sources/${encodeURIComponent(category)}/select`, {
      method: "PUT",
      body: JSON.stringify({ path: path || null }),
    });
    if (!isCurrentSourceMutation(requestId)) return payload;
    if (options.clearCardSelection) delete state.sourceCardSelections[category];
    applySourceMutationPayload(payload);
    await requestDiagnostics();
    return payload;
  } catch (error) {
    if (isCurrentSourceMutation(requestId)) {
      await recoverSourceMutationError(error);
    }
    return null;
  } finally {
    finishSourceMutation(requestId);
  }
};

const uploadSourceFile = async (category, droppedFile = null) => {
  if (sourceCommandBlocked()) return null;
  const input = document.querySelector(`[data-source-file="${category}"]`);
  const selectedFile = input?.files?.[0] || sourceUploadState(category).file;
  const file = droppedFile || selectedFile;
  if (!file) {
    showError("추가할 WAV 파일을 선택하세요.");
    return;
  }
  if (!file.name.toLowerCase().endsWith(".wav")) {
    showError("WAV 파일만 추가할 수 있습니다.");
    return;
  }
  const requestId = beginSourceMutation();
  const params = new URLSearchParams({
    filename: file.name,
    select: String(shouldSelectUploadedSource(category)),
  });
  try {
    const payload = await api(
      `/api/sources/${encodeURIComponent(category)}/files?${params.toString()}`,
      {
        method: "POST",
        headers: { "Content-Type": "audio/wav" },
        body: file,
      },
    );
    if (!isCurrentSourceMutation(requestId)) return payload;
    if (input) input.value = "";
    applySourceMutationPayload(payload, { clearUploadCategory: category });
    await requestDiagnostics();
    return payload;
  } catch (error) {
    if (isCurrentSourceMutation(requestId)) {
      await recoverSourceMutationError(error);
    }
    return null;
  } finally {
    finishSourceMutation(requestId);
  }
};

const handleSourceFileDrop = (event, category) => {
  const dropZone = sourceDropZoneFromEventTarget(event.target);
  if (sourceCommandBlocked()) {
    blockSourceFileDrop(event, dropZone);
    return null;
  }
  event.preventDefault();
  dropZone?.classList.remove("is-dragging");
  const file = event.dataTransfer?.files?.[0];
  if (!file) {
    showError("추가할 WAV 파일을 선택하세요.");
    return null;
  }
  rememberSourceUploadFile(category, file);
  return uploadSourceFile(category, file);
};

const deleteSourceFile = async (category, path) => {
  if (sourceCommandBlocked()) return null;
  if (!window.confirm("선택한 WAV 파일을 삭제할까요?")) return;
  const requestId = beginSourceMutation();
  try {
    const payload = await api(
      `/api/sources/${encodeURIComponent(category)}/files?path=${encodeURIComponent(path)}`,
      { method: "DELETE" },
    );
    if (!isCurrentSourceMutation(requestId)) return payload;
    applySourceMutationPayload(payload);
    await requestDiagnostics();
    return payload;
  } catch (error) {
    if (isCurrentSourceMutation(requestId)) {
      await recoverSourceMutationError(error);
    }
    return null;
  } finally {
    finishSourceMutation(requestId);
  }
};

const renameSourceFile = async (category, path, stem) => {
  if (sourceCommandBlocked()) return null;
  const requestId = beginSourceMutation();
  try {
    const payload = await api(`/api/sources/${encodeURIComponent(category)}/files`, {
      method: "PATCH",
      body: JSON.stringify({ path, stem }),
    });
    if (!isCurrentSourceMutation(requestId)) return payload;
    clearSourceRename(category, path);
    applySourceMutationPayload(payload);
    await requestSettingsPresets().catch(() => {});
    await requestDiagnostics();
    return payload;
  } catch (error) {
    if (isCurrentSourceMutation(requestId)) {
      await recoverSourceMutationError(error);
    }
    return null;
  } finally {
    finishSourceMutation(requestId);
  }
};

const previewVoiceRaw = async (path) => {
  if (sourceCommandBlocked()) return null;
  const requestId = beginSourceMutation();
  try {
    const payload = await api("/api/voice-raw/preview", {
      method: "POST",
      body: JSON.stringify({ voice_raw_path: path }),
    });
    if (!isCurrentSourceMutation(requestId)) return payload;
    await applyResponseState(payload, { syncDraft: false });
    await requestDiagnostics();
    return payload;
  } catch (error) {
    if (isCurrentSourceMutation(requestId)) {
      await recoverSourceMutationError(error);
    }
    return null;
  } finally {
    finishSourceMutation(requestId);
  }
};

const addVoiceRawToStack = async (path) => {
  if (sourceCommandBlocked()) return null;
  const requestId = beginSourceMutation();
  try {
    const payload = await api("/api/voice-stack/add-source", {
      method: "POST",
      body: JSON.stringify({ voice_raw_path: path }),
    });
    if (!isCurrentSourceMutation(requestId)) return payload;
    applySourceMutationPayload(payload);
    await requestDiagnostics();
    return payload;
  } catch (error) {
    if (isCurrentSourceMutation(requestId)) {
      await recoverSourceMutationError(error);
    }
    return null;
  } finally {
    finishSourceMutation(requestId);
  }
};

const nextDeviceChangeRequestId = () => {
  state.deviceChangeRequestId += 1;
  return state.deviceChangeRequestId;
};

const isCurrentDeviceChange = (requestId) => requestId === state.deviceChangeRequestId;

const beginDeviceChange = () => {
  const requestId = nextDeviceChangeRequestId();
  setOperationLockFlag("deviceChangeInFlight", true);
  return requestId;
};

const finishDeviceChange = (requestId) => {
  if (!isCurrentDeviceChange(requestId)) return;
  setOperationLockFlag("deviceChangeInFlight", false);
};

const deriveSystemDeviceSelectState = ({
  forceDisabled = false,
  devicesLoaded = false,
  deviceChangeInFlight = false,
  applyInFlight = false,
  resetDraftInFlight = false,
  sourceMutationInFlight = false,
  recordingStopInFlight = false,
  playbackControlInFlight = false,
  resetParticipantsInFlight = false,
  settingsPresetActionInFlight = false,
} = {}) => {
  const locks = deriveOperationLocks({
    applyInFlight,
    resetDraftInFlight,
    sourceMutationInFlight,
    deviceChangeInFlight,
    recordingStopInFlight,
    playbackControlInFlight,
    resetParticipantsInFlight,
    settingsPresetActionInFlight,
    devicesLoaded,
    forceDeviceDisabled: forceDisabled,
  });
  return { disabled: locks.deviceLocked, title: locks.deviceTitle };
};

const deviceChangeForceDisabled = (key) => (
  key === "input_device_id" && Boolean(state.snapshot?.is_recording)
);

const currentDeviceChangeState = (key) => deriveSystemDeviceSelectState({
  forceDisabled: deviceChangeForceDisabled(key),
  devicesLoaded: Boolean(state.devices),
  ...currentOperationFlags(),
});

const deriveStorageModeControlState = ({
  snapshot = null,
  draft = null,
  mode = null,
  applyInFlight = false,
  resetDraftInFlight = false,
  sourceMutationInFlight = false,
  deviceChangeInFlight = false,
  recordingStopInFlight = false,
  resetParticipantsInFlight = false,
  settingsPresetActionInFlight = false,
  storageModeInFlight = false,
  pendingMode = null,
} = {}) => {
  const modeDetails = storageModeDetails[mode];
  const ready = Boolean(snapshot && draft && modeDetails);
  const activeMode = snapshot?.settings?.active?.voice_stack?.mode;
  const draftMode = draft?.voice_stack?.mode;
  const pendingTarget = Boolean(storageModeInFlight && pendingMode === mode);
  const active = pendingTarget || draftMode === mode;
  const pending = Boolean(activeMode && draftMode && activeMode !== draftMode);
  const sourceMutationBusy = Boolean(sourceMutationInFlight);
  const deviceChangeBusy = Boolean(deviceChangeInFlight);
  const resetParticipantsBusy = Boolean(resetParticipantsInFlight);
  const settingsPresetBusy = Boolean(settingsPresetActionInFlight);
  const storageModeBusy = Boolean(storageModeInFlight);
  const disabled =
    !ready ||
    storageModeBusy ||
    applyInFlight ||
    resetDraftInFlight ||
    sourceMutationBusy ||
    deviceChangeBusy ||
    recordingStopInFlight ||
    resetParticipantsBusy ||
    settingsPresetBusy ||
    Boolean(snapshot?.is_recording);
  return {
    active,
    ariaPressed: active ? "true" : "false",
    pendingActive: pendingTarget || (pending && active),
    disabled,
    title: disabled
      ? storageModeBusy
        ? (pendingTarget ? `${modeDetails.optionLabel}으로 전환 중입니다.` : "보관 모드 변경 중입니다.")
        : resetDraftInFlight
          ? "설정 작업이 끝날 때까지 보관 모드를 바꿀 수 없습니다."
          : sourceMutationBusy
            ? operationLockMessages.sourceMutation
            : deviceChangeBusy
              ? operationLockMessages.deviceChange
              : resetParticipantsBusy
                ? operationLockMessages.resetParticipants
                : settingsPresetBusy
                  ? operationLockMessages.settingsPreset
                  : storageModeBusyTitle
      : modeDetails.idleTitle,
    canCommit: ready && !disabled,
  };
};

const renderSystemDeviceSelect = (selectId, devices, selectedId, forceDisabled = false) => {
  const select = $(selectId);
  const selectState = deriveSystemDeviceSelectState({
    forceDisabled,
    devicesLoaded: Boolean(state.devices),
    ...currentOperationFlags(),
  });
  if (deferInteractiveRender(`device-${selectId}`, select, renderDevices)) {
    return;
  }

  const nextSignature = deviceSelectOptionsSignature(devices, selectedId);
  if (state.renderSignatures.deviceSelects[selectId] !== nextSignature) {
    state.renderSignatures.deviceSelects[selectId] = nextSignature;
    select.innerHTML = "";
    const defaultOption = document.createElement("option");
    defaultOption.value = "";
    defaultOption.textContent = "시스템 기본값";
    select.appendChild(defaultOption);

    devices.forEach((device) => {
      const option = document.createElement("option");
      option.value = device.id;
      option.textContent = deviceOptionLabel(device);
      select.appendChild(option);
    });

    if (selectedId && !devices.some((device) => device.id === selectedId)) {
      const missingOption = document.createElement("option");
      missingOption.value = selectedId;
      missingOption.textContent = `사용 불가: ${selectedId}`;
      select.appendChild(missingOption);
    }
  }

  select.value = selectedId || "";
  select.disabled = selectState.disabled;
  select.title = selectState.title;
};

const deviceSelectOptionsSignature = (devices, selectedId) => {
  const missingSelectedId =
    selectedId && !devices.some((device) => device.id === selectedId) ? selectedId : null;
  return JSON.stringify({
    devices: devices.map((device) => [
      device.id,
      device.name,
      device.host_api_name,
      device.kind,
      device.max_input_channels,
      device.max_output_channels,
      device.default_sample_rate,
    ]),
    missingSelectedId,
  });
};

const deviceOptionLabel = (device, emptyLabel = "시스템 기본값") => {
  if (!device) return emptyLabel;
  const channelCount = device.kind === "input"
    ? device.max_input_channels
    : device.max_output_channels;
  return [
    device.name,
    channelCount ? `${channelCount}ch` : null,
    device.default_sample_rate ? formatValue(device.default_sample_rate, " Hz") : "Hz 미확인",
  ].filter(Boolean).join(" · ");
};

const defaultRuntimeConfigFields = [
  "audio.sample_rate",
  "audio.channels",
  "devices.input_device_id",
  "devices.output_device_id",
];

const normalizeRuntimeConfigFields = (runtimeConfigFields) => (
  Array.isArray(runtimeConfigFields) && runtimeConfigFields.length > 0
    ? runtimeConfigFields
    : defaultRuntimeConfigFields
);

const readSettingsPath = (settings, path) => (
  path.split(".").reduce((value, segment) => value?.[segment], settings)
);

const normalizeSettingsChangePlan = (change) => {
  const runtimeConfigFields = normalizeRuntimeConfigFields(change?.runtime_config_fields);
  const livePreviewReprocessableFieldNames = Array.isArray(
    change?.live_preview_reprocessable_field_names,
  )
    ? change.live_preview_reprocessable_field_names
    : [];
  return {
    runtimeConfigChanged: Boolean(change?.runtime_config_changed),
    changedRuntimeFields: Array.isArray(change?.changed_runtime_fields)
      ? change.changed_runtime_fields
      : [],
    livePreviewReprocessableFields: Array.isArray(change?.live_preview_reprocessable_fields)
      ? change.live_preview_reprocessable_fields
      : [],
    changedSections: Array.isArray(change?.changed_sections) ? change.changed_sections : [],
    runtimeConfigFields,
    livePreviewReprocessableFieldNames,
  };
};

const settingsPayloadMatchesDraft = (snapshot, draft) => (
  stableSettingsSignature(snapshot.settings.draft) === stableSettingsSignature(draft)
);

const rememberConfirmedSettingsDraft = (settingsPayload, confirmedDraft = settingsPayload?.draft) => {
  if (!confirmedDraft) return;
  state.confirmedDraftSignature = stableSettingsSignature(confirmedDraft);
};

const rememberConfirmedActiveSettings = (settingsPayload) => {
  if (!settingsPayload?.active) return;
  state.confirmedActiveSettingsSnapshot = clone(settingsPayload.active);
};

const confirmedSettingsDraftMatches = (draft) => (
  Boolean(draft && state.confirmedDraftSignature === stableSettingsSignature(draft))
);

const shouldSyncIncomingSettingsDraft = (currentSnapshot, currentDraft, options = {}) => {
  const syncDraft = options.syncDraft ?? true;
  if (syncDraft || !currentDraft) return true;
  if (!currentSnapshot?.settings?.draft) return false;
  if (state.confirmedDraftSignature === null) {
    return state.draftEditRevision === 0 && settingsPayloadMatchesDraft(currentSnapshot, currentDraft);
  }
  return confirmedSettingsDraftMatches(currentDraft);
};

const canUseServerSettingsChangePlan = (snapshot, draft) => (
  snapshot?.settings?.change?.runtime_config_changed !== undefined &&
  settingsPayloadMatchesDraft(snapshot, draft)
);

const settingsChangePlan = (snapshot = state.snapshot) => {
  if (!snapshot?.settings) return normalizeSettingsChangePlan(null);
  const draft = state.draft || snapshot.settings.draft;
  if (!snapshot.settings.active || !draft) return normalizeSettingsChangePlan(null);
  if (canUseServerSettingsChangePlan(snapshot, draft)) {
    return normalizeSettingsChangePlan(snapshot.settings.change);
  }
  const runtimeConfigFields = normalizeSettingsChangePlan(
    snapshot.settings.change,
  ).runtimeConfigFields;
  const livePreviewReprocessableFieldNames = normalizeSettingsChangePlan(
    snapshot.settings.change,
  ).livePreviewReprocessableFieldNames;
  return localSettingsChangePlan(
    snapshot.settings.active,
    draft,
    runtimeConfigFields,
    livePreviewReprocessableFieldNames,
  );
};

const localSettingsChangePlan = (
  active,
  draft,
  runtimeConfigFields = defaultRuntimeConfigFields,
  livePreviewReprocessableFieldNames = [],
) => {
  const normalizedRuntimeConfigFields = normalizeRuntimeConfigFields(runtimeConfigFields);
  const changedRuntimeFields = normalizedRuntimeConfigFields
    .filter((fieldName) => (
      readSettingsPath(active, fieldName) !== readSettingsPath(draft, fieldName)
    ));
  const normalizedLivePreviewReprocessableFieldNames = Array.isArray(
    livePreviewReprocessableFieldNames,
  )
    ? livePreviewReprocessableFieldNames
    : [];
  const livePreviewReprocessableFields = normalizedLivePreviewReprocessableFieldNames
    .filter((fieldName) => (
      readSettingsPath(active, fieldName) !== readSettingsPath(draft, fieldName)
    ));
  const activePayload = clone(active);
  const draftPayload = clone(draft);
  const sectionNames = [...new Set([
    ...Object.keys(activePayload),
    ...Object.keys(draftPayload),
  ])];
  const changedSections = sectionNames
    .sort()
    .filter((section) => (
      stableSettingsSignature(activePayload[section]) !== stableSettingsSignature(draftPayload[section])
    ));
  return {
    runtimeConfigChanged: changedRuntimeFields.length > 0,
    changedRuntimeFields,
    livePreviewReprocessableFields,
    changedSections,
    runtimeConfigFields: normalizedRuntimeConfigFields,
    livePreviewReprocessableFieldNames: normalizedLivePreviewReprocessableFieldNames,
  };
};

const toServerSettingsChangePayload = (change) => {
  const normalizedChange = change || normalizeSettingsChangePlan(null);
  return {
    runtime_config_changed: Boolean(normalizedChange.runtimeConfigChanged),
    changed_runtime_fields: Array.isArray(normalizedChange.changedRuntimeFields)
      ? normalizedChange.changedRuntimeFields
      : [],
    live_preview_reprocessable_fields: Array.isArray(
      normalizedChange.livePreviewReprocessableFields,
    )
      ? normalizedChange.livePreviewReprocessableFields
      : [],
    changed_sections: Array.isArray(normalizedChange.changedSections)
      ? normalizedChange.changedSections
      : [],
    runtime_config_fields: normalizeRuntimeConfigFields(normalizedChange.runtimeConfigFields),
    live_preview_reprocessable_field_names: Array.isArray(
      normalizedChange.livePreviewReprocessableFieldNames,
    )
      ? normalizedChange.livePreviewReprocessableFieldNames
      : [],
  };
};

const legacySourceSettingsFields = {
  low: "low_path",
  mid: "mid_path",
  voice_raw: "voice_raw_path",
  voice_stack: "voice_stack_path",
};

const sourceSettingsFieldForCategory = (category) => {
  if (typeof category === "string") {
    return legacySourceSettingsFields[category] || null;
  }
  if (typeof category?.settings_field === "string" && category.settings_field) {
    return category.settings_field;
  }
  return legacySourceSettingsFields[category?.id] || null;
};

const sourceSettingsFieldsForCategories = (categories) => {
  if (!Array.isArray(categories)) return Object.values(legacySourceSettingsFields);
  return [
    ...new Set(
      categories
        .map((category) => sourceSettingsFieldForCategory(category))
        .filter(Boolean),
    ),
  ];
};

const selectedSourcePathFor = (settings, category) => {
  const field = sourceSettingsFieldForCategory(category);
  if (!field) return null;
  return settings?.sources?.[field] || null;
};

const sourcePathSignatureForSettings = (
  settings,
  categories = sourceCategories(),
) => JSON.stringify(
  sourceSettingsFieldsForCategories(categories).map(
    (field) => settings?.sources?.[field] || null,
  ),
);

const activeSourcePathsChanged = (
  previousSnapshot,
  nextSnapshot,
  categories = sourceCategories(),
) => (
  sourcePathSignatureForSettings(previousSnapshot?.settings?.active, categories) !==
    sourcePathSignatureForSettings(nextSnapshot?.settings?.active, categories)
);

const sourceCategories = () => state.sources?.categories || null;

const sourceSignatureForSettings = (settings, categories) => {
  if (!Array.isArray(categories) || !settings) return null;
  return categories
    .map((category) => {
      const selectedPath = selectedSourcePathFor(settings, category) ||
        category.legacy_path ||
        null;
      const file = (category.files || []).find((item) => item.path === selectedPath);
      const legacySelected = selectedPath && selectedPath === category.legacy_path;
      return [
        category.id,
        selectedPath || "",
        file?.size_bytes ?? (legacySelected ? category.legacy_size_bytes : ""),
        file?.modified_at ?? (legacySelected ? category.legacy_modified_at : ""),
      ].join(":");
    })
    .join("|");
};

const syncAppliedSourceSignature = () => {
  const signature = sourceSignatureForSettings(
    state.snapshot?.settings?.active,
    sourceCategories(),
  );
  if (signature !== null) {
    state.appliedSourceSignature = signature;
  }
};

const hasSourceFileChanges = (snapshot = state.snapshot) => {
  if (!snapshot || state.appliedSourceSignature === null) return false;
  const draftSignature = sourceSignatureForSettings(
    state.draft || snapshot.settings.draft,
    sourceCategories(),
  );
  return draftSignature !== null && draftSignature !== state.appliedSourceSignature;
};

const hasPendingChanges = (snapshot) =>
  currentSettingsUiState(snapshot).pendingChangeState.pendingChanges;

const currentSettingsActionState = (snapshot = state.snapshot) =>
  currentSettingsUiState(snapshot).controlState;

const hasLayerInclusionDraftChange = (layerId) => {
  if (!state.snapshot || !state.draft) return false;
  if (livePlaybackFeatures(state.snapshot).enabled &&
    livePlaybackFeatures(state.snapshot).mute_applies_immediately) {
    return false;
  }
  return (
    Boolean(state.snapshot.settings.active.layers[layerId].enabled) !==
    Boolean(state.draft.layers[layerId].enabled)
  );
};

const layerEnabledText = (enabled) => (enabled ? "켜짐" : "꺼짐");

const updateLayerEnabledControl = (card, layerId, enabled) => {
  const toggle = card.querySelector(".layer-toggle");
  const label = card.querySelector(".layer-toggle-label");
  const note = card.querySelector(".layer-toggle-note");
  const pending = hasLayerInclusionDraftChange(layerId);
  toggle?.classList.toggle("enabled", enabled);
  toggle?.classList.toggle("pending", pending);
  if (label) label.textContent = layerEnabledText(enabled);
  if (note) {
    note.textContent = pending ? "재시작 시 적용" : "";
    note.hidden = !pending;
  }
};

const renderControls = () => {
  if (!state.draft) return;
  const activeContainer = activeSettingsControlContainer();
  if (
    activeContainer &&
    deferInteractiveRender("settings-controls", activeContainer, renderControls, {
      nextControlForTarget: (_container, target) => settingsInteractiveControlFromEventTarget(target),
    })
  ) {
    return;
  }
  renderPlaybackApplyModeControls();
  renderPlaybackTransitionControls();
  renderLayerControls();
  renderVoiceStackControls();
  renderRecordingPresets();
  renderRecordingControls();
};

const refreshLayerFeedbackVisualState = (containerId, layerIds) => {
  const container = $(containerId);
  layerIds.forEach((layerId, index) => {
    const card = container?.children?.[index];
    if (!card) return;
    const feedbackState = deriveCoveredSurfaceFeedbackState({
      snapshot: state.snapshot,
      draft: state.draft,
      operationFlags: currentOperationFlags(),
      surfaceId: `layer:${layerId}`,
    });
    applyCoveredFeedbackVisualState(card, "layer-card", feedbackState);
    refreshInlineGraphEqLiveStatusCopy(layerId, feedbackState);
  });
};

const refreshLayerCoveredFeedbackVisualStates = () => {
  refreshLayerFeedbackVisualState("layerControls", ["mid", "low"]);
  refreshLayerFeedbackVisualState("voiceLayerControls", ["voice"]);
};

const refreshCoveredFeedbackVisualStates = () => {
  refreshLayerCoveredFeedbackVisualStates();
  applyCoveredFeedbackVisualState(
    $("voiceStackControls"),
    "control-stack compact voice-stack-controls feedback-surface",
    deriveCoveredSurfaceFeedbackState({
      snapshot: state.snapshot,
      draft: state.draft,
      operationFlags: currentOperationFlags(),
      surfaceId: "voice_stack",
    }),
  );
  applyCoveredFeedbackVisualState(
    $("playbackTransitionControls"),
    "control-stack compact playback-transition-controls feedback-surface",
    deriveCoveredSurfaceFeedbackState({
      snapshot: state.snapshot,
      draft: state.draft,
      operationFlags: currentOperationFlags(),
      surfaceId: "voice_stack",
    }),
  );
  applyCoveredFeedbackVisualState(
    $("recordingControls"),
    "control-stack compact feedback-surface",
    deriveCoveredSurfaceFeedbackState({
      snapshot: state.snapshot,
      draft: state.draft,
      operationFlags: currentOperationFlags(),
      surfaceId: "recording",
    }),
  );
};

const preserveInlineGraphEqMount = (layerId) => {
  if (!layerIds.includes(layerId)) return state.graphEqInlinePreserveMountToken;
  state.graphEqInlinePreserveMountLayerId = layerId;
  state.graphEqInlinePreserveMountToken += 1;
  return state.graphEqInlinePreserveMountToken;
};

const clearPreservedInlineGraphEqMount = (layerId = state.graphEqInlinePreserveMountLayerId, token = null) => {
  if (!layerId) return false;
  if (state.graphEqInlinePreserveMountLayerId !== layerId) return false;
  if (token !== null && state.graphEqInlinePreserveMountToken !== token) return false;
  state.graphEqInlinePreserveMountLayerId = null;
  state.graphEqInlinePreserveMountToken += 1;
  return true;
};

const graphEqInlineEditorMountShouldBePreserved = () => {
  const layerId = state.graphEqInlinePreserveMountLayerId;
  if (!layerId) return false;
  return Boolean(document.querySelector(`[data-graph-eq-inline-editor="${layerId}"]`));
};

const renderOperationLockSurfaces = ({ preserveControls = false } = {}) => {
  renderState();
  if (!preserveControls) renderControls();
  renderDevices();
  renderSourceLibrary();
};

const renderDraftSaveFeedbackSurfaces = () => {
  if (
    !state.snapshot?.settings?.active?.layers ||
    !state.snapshot?.settings?.active?.voice_stack ||
    !state.snapshot?.settings?.active?.recording ||
    !state.draft?.layers ||
    !state.draft?.voice_stack ||
    !state.draft?.recording
  ) {
    return;
  }
  renderOperationLockSurfaces({
    preserveControls: graphEqInlineEditorMountShouldBePreserved(),
  });
  refreshCoveredFeedbackVisualStates();
};

const renderLayerControls = () => {
  renderLayerGroup("layerControls", ["mid", "low"]);
  renderLayerGroup("voiceLayerControls", ["voice"]);
  initializeInlineGraphEqEditors();
};

const currentPlaybackApplyMode = (snapshot = state.snapshot) => {
  const settingsMode = snapshot?.settings?.active?.playback?.apply_mode;
  if (playbackApplyModeDetails[settingsMode]) return settingsMode;
  const playbackMode = snapshot?.playback?.apply_mode;
  if (playbackApplyModeDetails[playbackMode]) return playbackMode;
  return "stable";
};

const currentPendingPlaybackApplyMode = () => {
  const mode = state.pendingPlaybackApplyMode;
  return state.playbackApplyModeInFlight && playbackApplyModeDetails[mode] ? mode : null;
};

const playbackApplyModeLiveSwitchConfirmationMessage =
  "안정 적용에서 아직 적용하지 않은 변경사항은 즉시 반영 모드로 전환할 때 바로 적용되지 않습니다. 마지막으로 적용된 설정에서 Live를 시작할까요?";

const playbackApplyModeSwitchNeedsStagedChangeConfirmation = (mode) => (
  currentPlaybackApplyMode() === "stable" &&
    mode === "live" &&
    hasPendingChanges(state.snapshot)
);

const stagedGraphEqLayerIdsForLiveSwitch = () => {
  const active = state.snapshot?.settings?.active;
  const draft = state.draft || state.snapshot?.settings?.draft;
  if (!active || !draft) return [];
  return layerIds.filter((layerId) => (
    stableSettingsSignature(active.layers?.[layerId]?.eq || {}) !==
      stableSettingsSignature(draft.layers?.[layerId]?.eq || {})
  ));
};

const playbackApplyModeSwitchNeedsStagedGraphEqChoice = (mode) => (
  currentPlaybackApplyMode() === "stable" &&
    mode === "live" &&
    stagedGraphEqLayerIdsForLiveSwitch().length > 0
);

const playbackApplyModeDialogRoot = () => (
  document.body || $("secret-pond-app") || document.documentElement || null
);

const removePlaybackApplyModeDialogElement = (element) => {
  if (!element) return;
  if (typeof element.remove === "function") {
    element.remove();
    return;
  }
  const parent = element.parentElement;
  if (Array.isArray(parent?.children)) {
    const index = parent.children.indexOf(element);
    if (index >= 0) parent.children.splice(index, 1);
  }
};

const closePlaybackApplyModeChoiceDialog = (choice) => {
  const dialogState = state.playbackApplyModeChoiceDialog;
  if (!dialogState) return;
  state.playbackApplyModeChoiceDialog = null;
  document.removeEventListener?.("keydown", dialogState.handleKeydown);
  removePlaybackApplyModeDialogElement(dialogState.overlay);
  dialogState.resolve(choice);
};

const playbackApplyModeChoiceButton = (action) => {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `playback-apply-mode-choice ${action.className || ""}`.trim();
  button.setAttribute("data-playback-apply-mode-choice", action.choice);
  button.dataset.playbackApplyModeChoice = action.choice;
  button.setAttribute("aria-label", `${action.label}. ${action.helper}`);
  const label = document.createElement("strong");
  label.textContent = action.label;
  const helper = document.createElement("small");
  helper.textContent = ` ${action.helper}`;
  button.append(label, helper);
  button.addEventListener("click", (event) => {
    event.preventDefault?.();
    closePlaybackApplyModeChoiceDialog(action.result);
  });
  return button;
};

const showPlaybackApplyModeChoiceDialog = ({ title, detail, actions }) => {
  const root = playbackApplyModeDialogRoot();
  if (!root) return Promise.resolve(null);
  if (state.playbackApplyModeChoiceDialog) {
    closePlaybackApplyModeChoiceDialog({ proceed: false, stagedGraphEq: "discard" });
  }
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "playback-apply-mode-dialog-backdrop";
    overlay.setAttribute("role", "presentation");
    const dialog = document.createElement("section");
    dialog.className = "playback-apply-mode-dialog";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "playbackApplyModeChoiceTitle");
    dialog.setAttribute("aria-describedby", "playbackApplyModeChoiceDetail");
    const heading = document.createElement("h2");
    heading.id = "playbackApplyModeChoiceTitle";
    heading.textContent = title;
    const body = document.createElement("p");
    body.id = "playbackApplyModeChoiceDetail";
    body.textContent = detail;
    const actionsEl = document.createElement("div");
    actionsEl.className = "playback-apply-mode-dialog-actions";
    actions.forEach((action) => {
      actionsEl.appendChild(playbackApplyModeChoiceButton(action));
    });
    dialog.append(heading, body, actionsEl);
    overlay.appendChild(dialog);
    const cancelChoice = { proceed: false, stagedGraphEq: "discard" };
    const handleKeydown = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault?.();
      closePlaybackApplyModeChoiceDialog(cancelChoice);
    };
    state.playbackApplyModeChoiceDialog = { overlay, resolve, handleKeydown };
    root.appendChild(overlay);
    document.addEventListener?.("keydown", handleKeydown);
    actionsEl.children[0]?.focus?.();
  });
};

const playbackApplyModeStagedGraphEqChoice = () => (
  showPlaybackApplyModeChoiceDialog({
    title: "Graph EQ 변경을 Live에 어떻게 넘길까요?",
    detail:
      "Stable에서 조정한 Graph EQ가 있습니다. Live를 시작할 때 현재 EQ를 적용하거나 마지막 적용값으로 시작할 수 있습니다.",
    actions: [
      {
        choice: "apply",
        label: "현재 Graph EQ 적용",
        helper: "Live 시작 후 준비되면 반영",
        className: "primary",
        result: { proceed: true, stagedGraphEq: "apply" },
      },
      {
        choice: "discard",
        label: "마지막 적용값 사용",
        helper: "이번 EQ draft는 Live에 넘기지 않음",
        className: "caution",
        result: { proceed: true, stagedGraphEq: "discard" },
      },
      {
        choice: "cancel",
        label: "취소",
        helper: "Stable 유지",
        result: { proceed: false, stagedGraphEq: "discard" },
      },
    ],
  })
);

const playbackApplyModePendingChangeChoice = () => (
  showPlaybackApplyModeChoiceDialog({
    title: "Live로 전환할까요?",
    detail: playbackApplyModeLiveSwitchConfirmationMessage,
    actions: [
      {
        choice: "start",
        label: "Live 시작",
        helper: "마지막 적용값 사용",
        className: "primary",
        result: { proceed: true, stagedGraphEq: "discard" },
      },
      {
        choice: "cancel",
        label: "취소",
        helper: "Stable 유지",
        result: { proceed: false, stagedGraphEq: "discard" },
      },
    ],
  })
);

const playbackApplyModeSwitchChoice = (mode) => {
  if (playbackApplyModeSwitchNeedsStagedGraphEqChoice(mode)) {
    return playbackApplyModeStagedGraphEqChoice().then(
      (choice) => choice || { proceed: false, stagedGraphEq: "discard" },
    );
  }
  if (!playbackApplyModeSwitchNeedsStagedChangeConfirmation(mode)) {
    return { proceed: true, stagedGraphEq: "discard" };
  }
  return playbackApplyModePendingChangeChoice().then(
    (choice) => choice || { proceed: false, stagedGraphEq: "discard" },
  );
};

const currentPendingStorageMode = () => {
  const mode = state.pendingStorageMode;
  return state.storageModeInFlight && storageModeDetails[mode] ? mode : null;
};

const coveredFeedbackSurfacePaths = {
  "layer:low": ["layers.low"],
  "layer.low": ["layers.low"],
  "layer:mid": ["layers.mid"],
  "layer.mid": ["layers.mid"],
  "layer:voice": ["layers.voice"],
  "layer.voice": ["layers.voice"],
  voice_stack: ["voice_stack"],
  recording: ["recording"],
};

const excludedFeedbackSurfaceIds = Object.freeze(["output", "playback_apply_mode", "source_library"]);

const coveredLayerFeedbackControlPaths = [
  "enabled",
  "volume_db",
  "eq.points",
  "eq.low_gain_db",
  "eq.mid_gain_db",
  "eq.high_gain_db",
  "eq.highpass_hz",
  "eq.lowpass_hz",
];

const coveredRecordingFeedbackControlPaths = [
  "gain_db",
  "normalize_peak",
  "highpass_hz",
  "lowpass_hz",
  "presence_gain_db",
  "reverb_mix",
  "delay_mix",
  "fade_ms",
];

const coveredLiveFeedbackControlSurfaceTargets = (() => {
  const entries = [];
  layerIds.forEach((layerId) => {
    coveredLayerFeedbackControlPaths.forEach((controlPath) => {
      entries.push([`layers.${layerId}.${controlPath}`, `layer:${layerId}`]);
    });
  });
  entries.push(["voice_stack.insert_gain_db", "voice_stack"]);
  entries.push(["voice_stack.transition_seconds", "voice_stack"]);
  coveredRecordingFeedbackControlPaths.forEach((controlPath) => {
    entries.push([`recording.${controlPath}`, "recording"]);
  });
  return Object.freeze(Object.fromEntries(entries));
})();

const feedbackSurfaceIdForControlId = (controlId) => (
  coveredLiveFeedbackControlSurfaceTargets[String(controlId || "")] || null
);

const feedbackSurfaceHasDraftChange = (activeSettings, draftSettings, surfaceId) => {
  const paths = coveredFeedbackSurfacePaths[surfaceId] || [];
  return paths.some((path) => (
    stableSettingsSignature(readSettingsPath(activeSettings, path)) !==
      stableSettingsSignature(readSettingsPath(draftSettings, path))
  ));
};

const stableCoveredFeedbackSurfaceIds = ["layer:low", "layer:mid", "layer:voice", "voice_stack", "recording"];

const captureStableCoveredFeedbackSurfaceDiffs = ({
  snapshot = state.snapshot,
  draft = state.draft || snapshot?.settings?.draft || null,
} = {}) => {
  const activeSettings = snapshot?.settings?.active || null;
  if (!activeSettings || !draft) return [];
  return stableCoveredFeedbackSurfaceIds.filter((surfaceId) => (
    feedbackSurfaceHasDraftChange(activeSettings, draft, surfaceId)
  ));
};

const stableCoveredFeedbackControlIds = Object.freeze(
  Object.keys(coveredLiveFeedbackControlSurfaceTargets),
);

const confirmedActiveSettingsForRollback = (snapshot = state.snapshot, draft = null) => {
  const snapshotActive = snapshot?.settings?.active || null;
  if (
    snapshotActive &&
    draft &&
    stableSettingsSignature(snapshotActive) !== stableSettingsSignature(draft)
  ) {
    return snapshotActive;
  }
  return state.confirmedActiveSettingsSnapshot || snapshotActive || null;
};

const captureStableCoveredFeedbackControlSnapshots = ({
  snapshot = state.snapshot,
  draft = state.draft || snapshot?.settings?.draft || null,
} = {}) => {
  const activeSettings = confirmedActiveSettingsForRollback(snapshot, draft);
  if (!activeSettings || !draft) return [];
  return stableCoveredFeedbackControlIds
    .filter((controlId) => (
      stableSettingsSignature(readSettingsPath(activeSettings, controlId)) !==
        stableSettingsSignature(readSettingsPath(draft, controlId))
    ))
    .map((controlId) => ({
      controlId,
      activeValue: clone(readSettingsPath(activeSettings, controlId)),
      draftValue: clone(readSettingsPath(draft, controlId)),
    }));
};

const captureStableCoveredFeedbackControlDiffs = captureStableCoveredFeedbackControlSnapshots;

const coveredFeedbackStateUsesPendingVisual = (feedbackState) => (
  feedbackState?.visual_state === "pending" ||
    feedbackState?.visual_state === "restart_pending"
);

const feedbackSpinnerMarkup = (showSpinner = false) => (
  `<span class="feedback-spinner" aria-hidden="true" ${showSpinner ? "" : "hidden"}></span>`
);

const updateFeedbackSpinnerVisibility = (container, showSpinner = false) => {
  if (!container) return;
  const spinner = container.querySelector?.(".feedback-spinner");
  if (spinner?.parentElement === container) {
    spinner.hidden = !showSpinner;
    if (showSpinner) spinner.removeAttribute?.("hidden");
    else spinner.setAttribute?.("hidden", "");
    return;
  }
  const markup = feedbackSpinnerMarkup(showSpinner);
  if (typeof container.innerHTML === "string" && container.innerHTML.includes("feedback-spinner")) {
    container.innerHTML = container.innerHTML.replace(
      /<span class="feedback-spinner" aria-hidden="true"[^>]*><\/span>/,
      markup,
    );
  }
};

const applyCoveredFeedbackVisualState = (container, baseClassName, feedbackState) => {
  if (!container) return;
  container.className = `${baseClassName}${
    coveredFeedbackStateUsesPendingVisual(feedbackState) ? " feedback-pending" : ""
  }`;
  updateFeedbackSpinnerVisibility(container, feedbackState?.show_spinner);
};

const deriveCoveredSurfaceFeedbackState = ({
  snapshot = state.snapshot,
  draft = state.draft || snapshot?.settings?.draft || null,
  operationFlags = currentOperationFlags(),
  surfaceId,
  backendState = null,
} = {}) => {
  const activeSettings = snapshot?.settings?.active || null;
  if (!coveredFeedbackSurfacePaths[surfaceId] || !activeSettings || !draft) {
    return idleCoveredSurfaceFeedbackState();
  }
  if (backendState?.visual_state || backendState?.show_spinner !== undefined) {
    return {
      visual_state: backendState.visual_state || "idle",
      show_spinner: Boolean(backendState.show_spinner),
    };
  }
  const liveApplyFeedbackState = deriveLiveApplyFeedbackSurfaceState(
    operationFlags.liveApplyFeedback,
    surfaceId,
  );
  if (liveApplyFeedbackState) return liveApplyFeedbackState;
  const liveGraphEqFeedbackState = deriveLiveGraphEqFeedbackState(snapshot, surfaceId);
  if (liveGraphEqFeedbackState) return liveGraphEqFeedbackState;
  const hasUnappliedChange = feedbackSurfaceHasDraftChange(activeSettings, draft, surfaceId);
  const applyMode = currentPlaybackApplyMode(snapshot);
  if (applyMode === "stable") {
    const applyInFlight = stableApplyAndRestartInFlight(operationFlags);
    return {
      visual_state: hasUnappliedChange
        ? (applyInFlight ? "restart_pending" : "pending")
        : "idle",
      show_spinner: hasUnappliedChange && applyInFlight,
    };
  }
  const plan = localSettingsChangePlan(
    activeSettings,
    draft,
    normalizeSettingsChangePlan(snapshot?.settings?.change).runtimeConfigFields,
    normalizeSettingsChangePlan(snapshot?.settings?.change).livePreviewReprocessableFieldNames,
  );
  const liveApplicableChange = liveApplicableCoveredSurfaceChange({
    snapshot,
    draft,
    surfaceId,
    settingsPlan: plan,
  });
  const liveFeedbackTargeted = operationTargetsFeedbackSurface(operationFlags, surfaceId);
  const liveFeedbackInFlight = feedbackOperationInFlight(operationFlags, surfaceId);
  const liveFeedbackPending = Boolean(operationFlags.liveFeedbackPending && liveFeedbackTargeted);
  const applyInFlight = stableApplyAndRestartInFlight(operationFlags);
  if (!liveApplicableChange && hasUnappliedChange) {
    return {
      visual_state: applyInFlight ? "restart_pending" : "pending",
      show_spinner: applyInFlight,
    };
  }
  return {
    visual_state: liveApplicableChange && (liveFeedbackPending || liveFeedbackInFlight)
      ? "pending"
      : "idle",
    show_spinner: liveApplicableChange && liveFeedbackInFlight,
  };
};

const renderCoveredFeedbackContainer = (container, baseClassName, surfaceId) => {
  const feedbackState = deriveCoveredSurfaceFeedbackState({
    snapshot: state.snapshot,
    draft: state.draft,
    operationFlags: currentOperationFlags(),
    surfaceId,
  });
  container.className = baseClassName;
  container.innerHTML = feedbackSpinnerMarkup(feedbackState.show_spinner);
  applyCoveredFeedbackVisualState(container, baseClassName, feedbackState);
  const spinner = container.querySelector(".feedback-spinner");
  if (spinner) spinner.hidden = !feedbackState.show_spinner;
  return feedbackState;
};

const renderPlaybackApplyModeControls = () => {
  const panel = $("playbackApplyModePanel");
  if (!panel) return;
  const pendingMode = currentPendingPlaybackApplyMode();
  const mode = pendingMode || currentPlaybackApplyMode();
  const details = playbackApplyModeDetails[mode] || playbackApplyModeDetails.stable;
  const disabled = !state.snapshot || state.playbackApplyModeInFlight;
  panel.setAttribute("aria-label", "재생 적용 모드");
  panel.setAttribute("aria-busy", state.playbackApplyModeInFlight ? "true" : "false");
  panel.className = `playback-apply-mode-panel compact ${details.className}${
    state.playbackApplyModeInFlight ? " pending" : ""
  }`;
  const summary = $("playbackApplyModeSummary");
  summary.setAttribute("role", "status");
  summary.setAttribute("aria-live", "polite");
  summary.textContent = pendingMode
    ? `${details.label}으로 전환 중`
    : `${details.label} · ${details.summary}`;
  Object.entries(playbackApplyModeDetails).forEach(([buttonMode, buttonDetails]) => {
    const button = $(buttonDetails.buttonId);
    if (!button) return;
    const active = mode === buttonMode;
    button.disabled = disabled;
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.classList.toggle("active", active);
    button.classList.toggle("pending", pendingMode === buttonMode);
    button.title = disabled && state.playbackApplyModeInFlight
      ? (pendingMode === buttonMode
        ? `${buttonDetails.label}으로 전환 중입니다.`
        : "재생 적용 모드 변경 중입니다.")
      : "";
  });
};

const setPlaybackApplyMode = async (mode) => {
  if (!playbackApplyModeDetails[mode] || state.playbackApplyModeInFlight) return null;
  if (currentPlaybackApplyMode() === mode) {
    renderPlaybackApplyModeControls();
    return null;
  }
  const pendingSwitchChoice = playbackApplyModeSwitchChoice(mode);
  const switchChoice = typeof pendingSwitchChoice?.then === "function"
    ? await pendingSwitchChoice
    : pendingSwitchChoice;
  if (!switchChoice.proceed) {
    renderPlaybackApplyModeControls();
    return null;
  }
  let modeError = null;
  invalidatePendingDraftSaves();
  state.playbackApplyModeInFlight = true;
  state.pendingPlaybackApplyMode = mode;
  renderPlaybackApplyModeControls();
  renderControls();
  try {
    const payload = await api("/api/playback/apply-mode", {
      method: "PUT",
      body: JSON.stringify({ mode, staged_graph_eq: switchChoice.stagedGraphEq }),
    });
    await applyResponseState(payload, { syncDraft: false });
    return payload;
  } catch (error) {
    modeError = error;
    await requestState({ syncDraft: false }).catch(() => {});
    return null;
  } finally {
    state.playbackApplyModeInFlight = false;
    state.pendingPlaybackApplyMode = null;
    renderPlaybackApplyModeControls();
    renderControls();
    if (modeError) showError(modeError.message);
    else clearTransientError({ respectMinimumVisibleDuration: true });
  }
};

const appendVoiceStackRangeControl = (container, control) => {
  const activeVoiceStack = state.snapshot?.settings.active.voice_stack || state.draft.voice_stack;
  const draftValue = getPath(state.draft.voice_stack, control.path) ?? control.defaultValue;
  const activeValue = getPath(activeVoiceStack, control.path) ?? control.defaultValue;
  container.appendChild(
    rangeControl(
      control,
      draftValue,
      (value) => {
        commitDraftChange(
          () => {
            setPath(state.draft.voice_stack, control.path, value);
          },
          { feedbackControlId: `voice_stack.${control.path}` },
        );
      },
      activeValue,
    ),
  );
};

const renderPlaybackTransitionControls = () => {
  const container = $("playbackTransitionControls");
  if (!container) return;
  renderCoveredFeedbackContainer(
    container,
    "control-stack compact playback-transition-controls feedback-surface",
    "voice_stack",
  );
  appendVoiceStackRangeControl(container, playbackTransitionControlDef);
};

const renderVoiceStackControls = () => {
  const container = $("voiceStackControls");
  renderCoveredFeedbackContainer(
    container,
    "control-stack compact voice-stack-controls feedback-surface",
    "voice_stack",
  );
  renderStorageModeControls();
  voiceStackControlDefs.forEach((control) => {
    appendVoiceStackRangeControl(container, control);
  });
};

const renderStorageModeControls = ({ force = false } = {}) => {
  if (!state.snapshot || !state.draft) return;
  if (!force && deferInteractiveRender("storage-mode", $("storageModePanel"), renderStorageModeControls)) {
    return;
  }
  const activeMode = state.snapshot.settings?.active?.voice_stack?.mode;
  const pendingMode = currentPendingStorageMode();
  const draftMode = pendingMode || state.draft.voice_stack?.mode;
  if (!activeMode || !draftMode) return;
  const activeDetails = storageModeDetails[activeMode] || storageModeDetails.live_ephemeral;
  const draftDetails = storageModeDetails[draftMode] || activeDetails;
  const pending = activeMode !== draftMode;
  const summary = $("storageModeSummary");
  summary.setAttribute("role", "status");
  summary.setAttribute("aria-live", "polite");
  summary.textContent = pendingMode
    ? `${draftDetails.optionLabel}으로 전환 중`
    : pending
      ? `${activeDetails.label} · 적용 중: ${draftDetails.optionLabel}`
      : `${activeDetails.label} · ${activeDetails.summary}`;
  $("storageModePanel").className = `storage-mode-panel ${draftDetails.className}${
    pending ? " pending" : ""
  }`;
  $("storageModePanel").setAttribute("aria-busy", state.storageModeInFlight ? "true" : "false");
  [
    ["storageModeLiveButton", "live_ephemeral"],
    ["storageModeLibraryButton", "test_library"],
  ].forEach(([id, mode]) => {
    const button = $(id);
    const controlState = deriveStorageModeControlState({
      snapshot: state.snapshot,
      draft: state.draft,
      mode,
      ...currentOperationFlags(),
      storageModeInFlight: state.storageModeInFlight,
      pendingMode,
    });
    button.disabled = controlState.disabled;
    button.setAttribute("aria-pressed", controlState.ariaPressed);
    button.classList.toggle("active", controlState.active);
    button.classList.toggle("pending", controlState.pendingActive);
    button.title = controlState.title;
  });
};

const setStorageMode = async (mode) => {
  const controlState = deriveStorageModeControlState({
    snapshot: state.snapshot,
    draft: state.draft,
    mode,
    ...currentOperationFlags(),
  });
  if (!controlState.canCommit) return null;
  const requestId = beginStorageModeChange();
  state.storageModeInFlight = true;
  state.pendingStorageMode = mode;
  state.draft.voice_stack.mode = mode;
  markDraftEdited();
  syncDraftSnapshot();
  renderStorageModeControls({ force: true });
  renderState();
  let modeError = null;
  setOperationLockFlag("applyInFlight", true);
  try {
    clearDraftSaveTimer();
    await saveDraft();
    if (!isCurrentStorageModeChange(requestId)) return null;
    const payload = await api("/api/voice-stack/mode", {
      method: "PUT",
      body: JSON.stringify({ mode }),
    });
    if (!isCurrentStorageModeChange(requestId)) return payload;
    await applyResponseState(payload, {
      syncDraft: false,
      mergeDraftSections: ["voice_stack"],
    });
    return payload;
  } catch (error) {
    if (!isCurrentStorageModeChange(requestId)) return null;
    modeError = error;
    await requestState({ syncDraft: false }).catch(() => {});
    return null;
  } finally {
    if (isCurrentStorageModeChange(requestId)) {
      state.storageModeInFlight = false;
      state.pendingStorageMode = null;
      setOperationLockFlag("applyInFlight", false);
      renderStorageModeControls({ force: true });
      if (modeError) showSettingsApplyFailureCaution(modeError.message);
      else clearTransientError({ respectMinimumVisibleDuration: true });
    }
  }
};

const renderLayerGroup = (containerId, layerIds) => {
  const container = $(containerId);
  if (!container) return;
  container.innerHTML = "";
  layerIds.forEach((layerId) => {
    container.appendChild(renderLayerCard(layerId));
  });
};

const renderLayerCard = (layerId) => {
  const layer = state.draft.layers[layerId];
  const activeLayer = state.snapshot?.settings.active.layers[layerId] || layer;
  const feedbackState = deriveCoveredSurfaceFeedbackState({
    snapshot: state.snapshot,
    draft: state.draft,
    operationFlags: currentOperationFlags(),
    surfaceId: `layer:${layerId}`,
  });
  const draftLock = deriveDraftControlLockState(state);
  const draftLocked = draftLock.disabled;
  const draftLockTitle = draftLock.title;
  const card = document.createElement("section");
  card.className = `layer-card${
    coveredFeedbackStateUsesPendingVisual(feedbackState) ? " feedback-pending" : ""
  }`;
  const layerLabel = layerLabels[layerId];
  const pendingEnabled = hasLayerInclusionDraftChange(layerId);
  card.innerHTML = `
    <span class="feedback-spinner" aria-hidden="true" ${feedbackState.show_spinner ? "" : "hidden"}></span>
    <div class="layer-head">
      <div>
        <h3 class="layer-title">${labelMarkup(layerLabel)}</h3>
        <p class="layer-role">${layerDescriptions[layerId] || ""}</p>
      </div>
      <div class="layer-head-actions">
        <label class="layer-toggle ${layer.enabled ? "enabled" : ""} ${
          pendingEnabled ? "pending" : ""
        }" ${draftLockTitle ? `title="${escapeHtml(draftLockTitle)}"` : ""}>
          <input
            type="checkbox"
            role="switch"
            aria-label="${labelText(layerLabel)} 켜짐 꺼짐"
            aria-checked="${layer.enabled ? "true" : "false"}"
            ${draftLocked ? "disabled" : ""}
            ${
            layer.enabled ? "checked" : ""
          }
          />
          <span class="layer-toggle-copy">
            <span class="layer-toggle-label">${layerEnabledText(layer.enabled)}</span>
            <small class="layer-toggle-note" ${pendingEnabled ? "" : "hidden"}>재시작 시 적용</small>
          </span>
        </label>
      </div>
    </div>
    <div class="layer-controls"></div>
  `;
  const spinner = card.querySelector(".feedback-spinner");
  if (spinner) spinner.hidden = !feedbackState.show_spinner;
  const toggle = card.querySelector("input[type='checkbox']");
  toggle.disabled = draftLocked;
  toggle.title = draftLockTitle;
  toggle.addEventListener("change", (event) => {
    const previousChecked = Boolean(state.draft.layers[layerId].enabled);
    const nextChecked = event.target.checked;
    const committed = commitDraftChange(
      () => {
        state.draft.layers[layerId].enabled = nextChecked;
      },
      {
        feedbackControlId: `layers.${layerId}.enabled`,
        afterSync: () => {
          event.target.setAttribute("aria-checked", nextChecked ? "true" : "false");
          updateLayerEnabledControl(card, layerId, nextChecked);
        },
      },
    );
    if (!committed) {
      event.target.checked = previousChecked;
      event.target.setAttribute("aria-checked", previousChecked ? "true" : "false");
      updateLayerEnabledControl(card, layerId, previousChecked);
    }
  });

  const controls = card.querySelector(".layer-controls");
  const levelGroups = layerControlGroups.filter((group) => group.action !== "reset-filter");
  const filterGroup = layerControlGroups.find((group) => group.action === "reset-filter");
  levelGroups.forEach((group) => {
    controls.appendChild(
      controlGroup(
        group,
        layer,
        activeLayer,
        (control, value) => {
          commitDraftChange(
            () => {
              setPath(state.draft.layers[layerId], control.path, value);
              clearLayerPresetSelection(layerId);
            },
            {
              feedbackControlId: `layers.${layerId}.${control.path}`,
              afterSync: () => updateLayerPresetButtons(card, layerId),
            },
          );
        },
        group.action === "reset-filter" ? () => resetLayerFilter(layerId) : undefined,
      ),
    );
  });
  if (typeof controls.insertAdjacentHTML === "function") {
    controls.insertAdjacentHTML("beforeend", renderLayerGraphEqSection(layerId));
  } else {
    const graphEqSection = document.createElement("section");
    graphEqSection.className = "graph-eq-layer-card-section";
    graphEqSection.setAttribute("data-graph-eq-layer-card", layerId);
    graphEqSection.innerHTML = renderLayerGraphEqSection(layerId);
    controls.appendChild(graphEqSection);
  }
  if (filterGroup) {
    controls.appendChild(
      controlGroup(
        filterGroup,
        layer,
        activeLayer,
        (control, value) => commitGraphEqFilterEdit(layerId, control, value),
        () => resetLayerFilter(layerId),
      ),
    );
  }
  card.querySelector("[data-graph-eq-toggle]")?.addEventListener("click", (event) => {
    const layerId = event.currentTarget.dataset.graphEqToggle;
    if (expandedGraphEqLayerId() === layerId) {
      closeExpandedGraphEqLayer(layerId);
    } else {
      openExpandedGraphEqLayer(layerId);
    }
  });
  bindInlineGraphEqControls(card, layerId);
  card.querySelectorAll?.(".layer-preset-button")?.forEach((button) => {
    button.addEventListener("click", () => applyLayerPreset(layerId, button.dataset.layerPreset));
  });
  updateLayerPresetButtons(card, layerId);
  return card;
};

const layerPresetMarkup = (layerId) => {
  const draftLock = deriveDraftControlLockState(state);
  return `
    <div class="layer-preset-row" role="group" aria-label="${labelText(layerLabels[layerId])} 톤 프리셋">
      ${Object.entries(layerPresetLabels)
        .map(
          ([name, label]) => {
            const active = layerPresetIsSelected(layerId, name);
            return `
            <button
              class="layer-preset-button ${active ? "active" : ""}"
              type="button"
              data-layer-preset="${name}"
              aria-pressed="${active ? "true" : "false"}"
              ${draftLock.disabled ? `disabled title="${escapeHtml(draftLock.title)}"` : ""}
            >
              ${labelMarkup(label)}
            </button>
          `;
          },
        )
        .join("")}
    </div>
  `;
};

const updateLayerPresetButtons = (card, layerId) => {
  const draftLock = deriveDraftControlLockState(state);
  card.querySelectorAll?.(".layer-preset-button")?.forEach((button) => {
    const active = layerPresetIsSelected(layerId, button.dataset.layerPreset);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.disabled = draftLock.disabled;
    button.title = draftLock.disabled ? draftLock.title : "";
  });
};

const applyLayerPreset = (layerId, presetName) => {
  const current = state.draft?.layers?.[layerId];
  const preset = layerPresetDefs[presetName];
  if (!current || !preset) return;
  const next = reversiblePresetDraft(
    current,
    layerPresetDefs,
    presetName,
    state.presetSelections.layers[layerId],
  );
  commitDraftChange(
    () => {
      state.draft.layers[layerId] = next.draft;
      if (next.selection) state.presetSelections.layers[layerId] = next.selection;
      else clearLayerPresetSelection(layerId);
    },
    {
      feedbackSurfaceId: `layer:${layerId}`,
      feedbackControlIds: presetFeedbackControlIds(`layers.${layerId}`, preset),
      afterSync: renderLayerControls,
    },
  );
};

const resetLayerFilter = (layerId) => {
  const layer = state.draft?.layers?.[layerId];
  const filterGroup = layerControlGroups.find((group) => group.action === "reset-filter");
  if (!layer || !filterGroup) return;
  const activeLayer = state.snapshot?.settings?.active?.layers?.[layerId] || null;
  if (filterResetActionState(filterGroup, layer, activeLayer).resetDisabled) return;
  commitDraftChange(
    () => {
      filterGroup.controls.forEach((control) => {
        const resetValue = control.path.endsWith("highpass_hz") ? control.min : control.max;
        setPath(layer, control.path, resetValue);
      });
    },
    {
      feedbackSurfaceId: `layer:${layerId}`,
      feedbackControlIds: filterGroup.controls.map((control) => `layers.${layerId}.${control.path}`),
      afterSync: renderLayerControls,
    },
  );
};

const expandedGraphEqLayerId = () => (
  layerIds.includes(state.expandedGraphEqLayer) ? state.expandedGraphEqLayer : null
);

const currentGraphEqLayerId = () => expandedGraphEqLayerId() || "mid";

const graphEqForLayer = (settings, layerId = currentGraphEqLayerId()) => (
  normalizeGraphEqSettings(settings?.layers?.[layerId]?.eq || {})
);

const scrollExpandedGraphEqLayerIntoView = (layerId) => {
  const section = document.querySelector?.(`[data-graph-eq-layer-card="${layerId}"]`);
  section?.scrollIntoView?.({ block: "start", inline: "nearest" });
};

const selectedGraphEqPointId = (layerId = currentGraphEqLayerId()) => (
  state.graphEqSelectedPointIds[layerId] || null
);

const selectedGraphEqPoint = (eq, layerId = currentGraphEqLayerId()) => {
  const pointId = selectedGraphEqPointId(layerId);
  return eq.points.find((point) => point.id === pointId) || null;
};

const openExpandedGraphEqLayer = (layerId) => {
  if (!layerIds.includes(layerId)) return;
  if (expandedGraphEqLayerId() === layerId) {
    initializeInlineGraphEqEditors();
    return;
  }
  state.expandedGraphEqLayer = layerId;
  renderLayerControls();
  scrollExpandedGraphEqLayerIntoView(layerId);
};

const closeExpandedGraphEqLayer = (layerId) => {
  if (expandedGraphEqLayerId() !== layerId) return;
  state.expandedGraphEqLayer = null;
  renderLayerControls();
};

const setSelectedGraphEqPoint = (layerId, pointId) => {
  state.graphEqSelectedPointIds[layerId] = pointId || null;
  renderLayerControls();
};

const updateDraftGraphEq = (layerId, nextEq) => {
  const layer = state.draft?.layers?.[layerId];
  if (!layer) return;
  layer.eq = {
    ...normalizeGraphEqSettings(nextEq),
    low_gain_db: 0,
    mid_gain_db: 0,
    high_gain_db: 0,
  };
};

const updateDraftGraphEqPoint = (layerId, pointId, updates) => {
  const eq = graphEqForLayer(state.draft, layerId);
  const points = eq.points.map((point) => (
    point.id === pointId ? normalizeGraphEqPoint({ ...point, ...updates }) : point
  ));
  updateDraftGraphEq(layerId, { ...eq, points });
};

const graphEqControlIds = (layerId, pointId = selectedGraphEqPointId(layerId)) => {
  const ids = [`layers.${layerId}.eq.points`];
  if (pointId) ids.push(`layers.${layerId}.eq.points.${pointId}`);
  return ids;
};

const commitGraphEqPointEdit = (layerId, pointId, updates) => {
  commitDraftChange(
    () => {
      updateDraftGraphEqPoint(layerId, pointId, updates);
    },
    {
      feedbackSurfaceId: `layer:${layerId}`,
      feedbackControlIds: graphEqControlIds(layerId, pointId),
      afterSync: renderLayerControls,
    },
  );
};

const commitInlineGraphEqPoints = (layerId, points, selectedPointId = null, options = {}) => {
  if (!layerIds.includes(layerId)) return false;
  const eq = graphEqForLayer(state.draft, layerId);
  const normalized = normalizeGraphEqSettings({ ...eq, points });
  const renderAfterSync = options.renderAfterSync ?? true;
  const committed = commitDraftChange(
    () => {
      updateDraftGraphEq(layerId, normalized);
      if (selectedPointId !== undefined) {
        state.graphEqSelectedPointIds[layerId] = selectedPointId;
      }
    },
    {
      feedbackSurfaceId: `layer:${layerId}`,
      feedbackControlIds: graphEqControlIds(layerId, selectedPointId),
      afterSync: () => {
        if (renderAfterSync) {
          renderLayerControls();
          return;
        }
        refreshCoveredFeedbackVisualStates();
        options.afterSync?.(normalized);
      },
    },
  );
  return committed;
};

const previewInlineGraphEqPoints = (layerId, points, selectedPointId = null, options = {}) => {
  if (!layerIds.includes(layerId) || !state.draft || draftEditLocked()) return false;
  const eq = graphEqForLayer(state.draft, layerId);
  const normalized = normalizeGraphEqSettings({ ...eq, points });
  updateDraftGraphEq(layerId, normalized);
  if (selectedPointId !== undefined) {
    state.graphEqSelectedPointIds[layerId] = selectedPointId;
  }
  markDraftEdited();
  syncDraftSnapshot();
  refreshCoveredFeedbackVisualStates();
  options.afterSync?.(normalized);
  return true;
};

const commitGraphEqFilterEdit = (layerId, control, value) => {
  commitDraftChange(
    () => {
      setPath(state.draft.layers[layerId], control.path, value);
    },
    {
      feedbackSurfaceId: `layer:${layerId}`,
      feedbackControlId: `layers.${layerId}.${control.path}`,
      afterSync: renderLayerControls,
    },
  );
};

const addGraphEqPoint = () => {
  const layerId = currentGraphEqLayerId();
  const eq = graphEqForLayer(state.draft, layerId);
  if (eq.points.length >= graphEqMaxPoints) return;
  const id = `point-${Date.now().toString(36)}`;
  const nextPoint = normalizeGraphEqPoint({
    id,
    type: "bell",
    frequency_hz: 1000,
    gain_db: 0,
    q: graphEqDefaultBellQ,
  });
  commitDraftChange(
    () => {
      const lowShelf = eq.points.find((point) => point.type === "low_shelf");
      const highShelf = eq.points.find((point) => point.type === "high_shelf");
      const bells = eq.points.filter((point) => point.type === "bell");
      updateDraftGraphEq(layerId, { ...eq, points: [lowShelf, nextPoint, ...bells, highShelf].filter(Boolean) });
      state.graphEqSelectedPointIds[layerId] = id;
    },
    {
      feedbackSurfaceId: `layer:${layerId}`,
      feedbackControlIds: graphEqControlIds(layerId, id),
      afterSync: renderLayerControls,
    },
  );
};

const deleteSelectedGraphEqPoint = () => {
  const layerId = currentGraphEqLayerId();
  const eq = graphEqForLayer(state.draft, layerId);
  const pointId = selectedGraphEqPointId(layerId);
  const selected = eq.points.find((point) => point.id === pointId);
  if (!pointId || !isGraphEqPointDeletable(selected)) return;
  commitDraftChange(
    () => {
      updateDraftGraphEq(layerId, {
        ...eq,
        points: eq.points.filter((point) => point.id !== pointId),
      });
      state.graphEqSelectedPointIds[layerId] = null;
    },
    {
      feedbackSurfaceId: `layer:${layerId}`,
      feedbackControlIds: graphEqControlIds(layerId, pointId),
      afterSync: renderLayerControls,
    },
  );
};

const resetGraphEqLayer = (layerId = currentGraphEqLayerId()) => {
  commitDraftChange(
    () => {
      updateDraftGraphEq(layerId, normalizeGraphEqSettings({ points: defaultGraphEqPoints() }));
      state.graphEqSelectedPointIds[layerId] = null;
    },
    {
      feedbackSurfaceId: `layer:${layerId}`,
      feedbackControlIds: graphEqControlIds(layerId),
      afterSync: renderLayerControls,
    },
  );
};

const resetAllGraphEqLayers = () => {
  if (!window.confirm("모든 레이어의 Graph EQ를 초기화할까요?")) return;
  commitDraftChange(
    () => {
      layerIds.forEach((layerId) => {
        updateDraftGraphEq(layerId, normalizeGraphEqSettings({ points: defaultGraphEqPoints() }));
        state.graphEqSelectedPointIds[layerId] = null;
      });
    },
    {
      feedbackSurfaceId: "layer:mid",
      feedbackControlIds: layerIds.flatMap((layerId) => graphEqControlIds(layerId)),
      afterSync: renderLayerControls,
    },
  );
};

const graphEqPathD = (points) => points
  .map((point, index) => {
    const x = point.x * 1000;
    const y = point.y * 360;
    return `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  })
  .join(" ");

const graphEqSafeToken = (value) => String(value || "")
  .replace(/[^a-zA-Z0-9_-]/g, "-")
  .replace(/-+/g, "-");

const graphEqFrequencyLabel = (frequencyHz) => {
  const rounded = Math.round(Number(frequencyHz) || 0);
  if (rounded >= 1000) {
    return `${Number((rounded / 1000).toFixed(1)).toString()} kHz`;
  }
  return `${rounded} Hz`;
};

const graphEqGainLabel = (gainDb) => dbMarkLabel(Number(gainDb.toFixed(1)));

const graphEqBellPointsByFrequency = (points = []) => (Array.isArray(points) ? points : [])
  .map((candidate, index) => ({ point: candidate, index }))
  .filter(({ point }) => point?.type === "bell")
  .sort((a, b) => (
    Number(a.point.frequency_hz) - Number(b.point.frequency_hz) ||
      a.index - b.index
  ));

const graphEqBellBandNumber = (point, pointIndex, points = []) => {
  if (point?.type !== "bell") return "";
  const sourcePoints = Array.isArray(points) && points.length > 0 ? points : [point];
  const rankedBells = graphEqBellPointsByFrequency(sourcePoints);
  const rank = rankedBells.findIndex(({ point: candidate, index }) => (
    candidate?.id === point.id || (candidate === point && index === pointIndex)
  ));
  return rank >= 0 ? String(rank + 1) : "";
};

const graphEqBellCount = (points = []) => (Array.isArray(points) ? points : [])
  .filter((point) => point?.type === "bell")
  .length;

const graphEqBandMetaLabel = (points = []) => (
  `${graphEqBellCount(points)}/${Math.max(0, graphEqMaxPoints - 2)} Bell`
);

const inlineGraphEqSelectedPoint = (eq, layerId) => {
  const selected = selectedGraphEqPoint(eq, layerId);
  return selected || eq.points[0] || null;
};

const renderInlineGraphEqStepper = ({ inputId, controlName, pointId, value, min, max, step, disabled }) => `
  <div class="graph-eq-stepper">
    <button
      class="graph-eq-step-button"
      type="button"
      data-graph-eq-step-target="${escapeHtml(inputId)}"
      data-graph-eq-step-direction="-1"
      aria-label="${escapeHtml(controlName)} 낮추기"
      ${disabled ? "disabled" : ""}
    >-</button>
    <input
      id="${escapeHtml(inputId)}"
      data-graph-eq-point-id="${escapeHtml(pointId)}"
      data-graph-eq-point-control="${escapeHtml(controlName)}"
      type="number"
      min="${min}"
      max="${max}"
      step="${step}"
      value="${escapeHtml(String(value))}"
      ${disabled ? "disabled" : ""}
    />
    <button
      class="graph-eq-step-button"
      type="button"
      data-graph-eq-step-target="${escapeHtml(inputId)}"
      data-graph-eq-step-direction="1"
      aria-label="${escapeHtml(controlName)} 높이기"
      ${disabled ? "disabled" : ""}
    >+</button>
  </div>
`;

const renderInlineGraphEqPointRow = (
  layerId,
  point,
  selected,
  disabled,
  pointIndex,
  points,
) => {
  return `
    <button
      class="graph-eq-point-row ${selected ? "selected" : ""}"
      type="button"
      data-graph-eq-point-row
      data-graph-eq-point-id="${escapeHtml(point.id)}"
      aria-pressed="${selected ? "true" : "false"}"
      ${disabled ? "disabled" : ""}
    >
      ${renderInlineGraphEqPointRowContent(point, pointIndex, points)}
    </button>
  `;
};

const renderInlineGraphEqPointRowContent = (point, pointIndex, points = []) => `
  <span class="graph-eq-band-number" aria-hidden="true">${graphEqBellBandNumber(point, pointIndex, points)}</span>
  <span class="graph-eq-band-main">
    <strong>${escapeHtml(graphEqPointTypes[point.type])}</strong>
    <small>${escapeHtml(graphEqFrequencyLabel(point.frequency_hz))} · ${escapeHtml(graphEqGainLabel(point.gain_db))}</small>
  </span>
  <span class="graph-eq-band-q">Q ${Number(point.q.toFixed(2))}</span>
`;

const renderInlineGraphEqSelectedInspector = (layerId, selected, disabled, pointCount, pointIndex, points) => {
  if (!selected) {
    return `
      <div class="graph-eq-selected-inspector empty" data-graph-eq-selected-inspector>
        <h5>Selected Band <small lang="ko">선택한 점</small></h5>
        <p>점을 추가하세요</p>
      </div>
    `;
  }
  const token = `${graphEqSafeToken(layerId)}-${graphEqSafeToken(selected.id)}-selected`;
  const bandNumber = graphEqBellBandNumber(selected, pointIndex, points);
  const selectedTitle = bandNumber ? `Selected Band ${bandNumber}` : graphEqPointTypes[selected.type];
  const selectedDeletable = isGraphEqPointDeletable(selected);
  const selectedFrequencyLocked = isFixedGraphEqShelfPoint(selected);
  const deleteButton = selectedDeletable
    ? `
        <button
          class="button danger graph-eq-row-delete"
          type="button"
          data-graph-eq-action="delete-point"
          data-graph-eq-point-id="${escapeHtml(selected.id)}"
          ${disabled ? "disabled" : ""}
        >
          Delete
        </button>
      `
    : "";
  return `
    <div
      class="graph-eq-selected-inspector"
      data-graph-eq-selected-inspector
      data-graph-eq-point-id="${escapeHtml(selected.id)}"
    >
      <div class="graph-eq-selected-inspector-head">
        <span class="graph-eq-band-number" aria-hidden="true">${bandNumber}</span>
        <div>
          <h5>${escapeHtml(selectedTitle)} <small lang="ko">선택한 점</small></h5>
          <p data-graph-eq-selected-summary>
            ${graphEqPointTypes[selected.type]} · ${graphEqFrequencyLabel(selected.frequency_hz)} · ${graphEqGainLabel(selected.gain_db)}
          </p>
        </div>
        ${deleteButton}
      </div>
      <div class="graph-eq-selected-fields">
        <label>
          Type
          <select
            data-graph-eq-point-type
            data-graph-eq-point-id="${escapeHtml(selected.id)}"
            data-graph-eq-point-control="type"
            ${disabled || !selectedDeletable ? "disabled" : ""}
          >
            ${Object.entries(graphEqPointTypes)
              .filter(([value]) => selected.type === value || value === "bell")
              .map(([value, label]) => `
              <option value="${value}" ${selected.type === value ? "selected" : ""}>${label}</option>
            `).join("")}
          </select>
        </label>
        <label>
          Freq
          ${renderInlineGraphEqStepper({
            inputId: `graph-eq-${token}-freq`,
            controlName: "freq",
            pointId: selected.id,
            value: Math.round(selected.frequency_hz),
            min: graphEqMinFrequencyHz,
            max: graphEqMaxFrequencyHz,
            step: 1,
            disabled: disabled || selectedFrequencyLocked,
          })}
        </label>
        <label>
          Gain
          ${renderInlineGraphEqStepper({
            inputId: `graph-eq-${token}-gain`,
            controlName: "gain",
            pointId: selected.id,
            value: Number(selected.gain_db.toFixed(1)),
            min: graphEqMinGainDb,
            max: graphEqMaxGainDb,
            step: 0.1,
            disabled,
          })}
        </label>
        <label>
          Q
          ${renderInlineGraphEqStepper({
            inputId: `graph-eq-${token}-q`,
            controlName: "q",
            pointId: selected.id,
            value: Number(selected.q.toFixed(2)),
            min: 0.1,
            max: 18,
            step: 0.1,
            disabled,
          })}
        </label>
      </div>
    </div>
  `;
};

const renderInlineGraphEqPointControls = (layerId, eq) => {
  const disabled = draftEditLocked();
  const selected = inlineGraphEqSelectedPoint(eq, layerId);
  const selectedIndex = Math.max(0, eq.points.findIndex((point) => point.id === selected?.id));
  return `
    <div class="graph-eq-inline-controls" aria-label="Selected Graph EQ point">
      <div class="graph-eq-workflow">
        ${renderInlineGraphEqSelectedInspector(layerId, selected, disabled, eq.points.length, selectedIndex, eq.points)}
        <div class="graph-eq-band-manager">
          <div class="graph-eq-inline-controls-head">
            <div>
              <h5>Bands <small lang="ko">점 목록</small></h5>
              <p>${graphEqBandMetaLabel(eq.points)}</p>
            </div>
            <button
              class="button"
              type="button"
              data-graph-eq-action="add-point"
              ${disabled || eq.points.length >= graphEqMaxPoints ? "disabled" : ""}
            >
              + Band
            </button>
          </div>
          <div class="graph-eq-band-list">
            ${eq.points.map((point, index) => renderInlineGraphEqPointRow(
              layerId,
              point,
              selected?.id === point.id,
              disabled,
              index,
              eq.points,
            )).join("")}
          </div>
          <div class="graph-eq-inline-actions">
            <button
              class="button"
              type="button"
              data-graph-eq-action="reset-layer"
              ${disabled ? "disabled" : ""}
            >
              Layer Reset
            </button>
          </div>
        </div>
      </div>
    </div>
  `;
};

const renderExpandedGraphEqEditorShell = (layerId, eq) => `
  <div
    class="graph-eq-inline-editor expanded"
    data-graph-eq-inline-editor="${escapeHtml(layerId)}"
  >
    <div class="graph-eq-dsssp-host">
      <div
        class="graph-eq-dsssp-root"
        data-graph-eq-dsssp-root-shell="true"
        data-graph-eq-layer-id="${escapeHtml(layerId)}"
        aria-label="${escapeHtml(labelText(layerLabels[layerId]))} Graph EQ"
      ></div>
    </div>
    ${renderInlineGraphEqPointControls(layerId, eq)}
  </div>
`;

const inlineGraphEqStatusCopy = (feedbackState = null) => {
  if (currentPlaybackApplyMode() === "stable") {
    if (feedbackState?.visual_state === "restart_pending") {
      return {
        label: "Apply and Restart 진행 중",
        detail: "렌더링 후 재생에 반영합니다.",
      };
    }
    if (coveredFeedbackStateUsesPendingVisual(feedbackState)) {
      return {
        label: "Apply and Restart 대기 중",
        detail: "변경값은 draft에 저장됐고 재생에는 아직 반영되지 않았습니다.",
      };
    }
    return null;
  }
  if (currentPlaybackApplyMode() !== "live") return null;
  if (coveredFeedbackStateUsesPendingVisual(feedbackState)) {
    return {
      label: "Live Graph EQ 적용 대기 중",
      detail: "마지막 조작값을 렌더링 중입니다.",
    };
  }
  return graphEqLiveStatusCopy(state.snapshot?.playback?.live_graph_eq);
};

const refreshInlineGraphEqLiveStatusCopy = (layerId, feedbackState = null) => {
  const graphEqSection = document.querySelector?.(`[data-graph-eq-layer-card="${layerId}"]`);
  if (!graphEqSection) return;
  const status = graphEqSection.querySelector(".graph-eq-layer-card-status");
  if (!status) return;
  const liveStatus = inlineGraphEqStatusCopy(feedbackState);
  status.textContent = liveStatus?.label || "상시 표시";
  let detail = graphEqSection.querySelector(".graph-eq-layer-card-detail");
  if (liveStatus?.detail) {
    if (!detail) {
      detail = document.createElement("p");
      detail.className = "graph-eq-layer-card-detail";
      graphEqSection.querySelector(".graph-eq-layer-card-head")?.after(detail);
    }
    detail.textContent = liveStatus.detail;
    detail.hidden = false;
  } else if (detail) {
    detail.textContent = "";
    detail.hidden = true;
  }
};

const renderLayerGraphEqSection = (layerId) => {
  const eq = graphEqForLayer(state.draft, layerId);
  const feedbackState = deriveCoveredSurfaceFeedbackState({ surfaceId: `layer:${layerId}` });
  const liveStatus = inlineGraphEqStatusCopy(feedbackState);
  return `
    <section
      class="graph-eq-layer-card-section expanded"
      data-graph-eq-layer-card="${escapeHtml(layerId)}"
      data-graph-eq-expanded="true"
    >
      <div class="graph-eq-layer-card-head">
        <div>
          <h4>${labelMarkup(layerLabels[layerId])} Graph EQ</h4>
          <p class="graph-eq-layer-card-status">
            ${liveStatus?.label || "상시 표시"}
          </p>
        </div>
        <div class="graph-eq-layer-card-meta">${graphEqBandMetaLabel(eq.points)}</div>
      </div>
      ${liveStatus?.detail ? `<p class="graph-eq-layer-card-detail">${escapeHtml(liveStatus.detail)}</p>` : ""}
      ${renderExpandedGraphEqEditorShell(layerId, eq)}
    </section>
  `;
};

const selectedOrFirstGraphEqPointId = (layerId, eq) => (
  selectedGraphEqPointId(layerId) || eq.points[0]?.id || null
);

const syncInlineGraphEqPointControls = (container, layerId, points, selectedPointId) => {
  const orderedPoints = graphEqOrderedPoints(points);
  const rows = Array.from(container.querySelectorAll?.("[data-graph-eq-point-row]") || []);
  const selected = orderedPoints.find((point) => point.id === selectedPointId) || orderedPoints[0] || null;
  const selectedIndex = Math.max(0, orderedPoints.findIndex((point) => point.id === selected?.id));
  if (rows.length !== orderedPoints.length) {
    const controls = container.querySelector?.(".graph-eq-inline-controls");
    if (controls) {
      controls.outerHTML = renderInlineGraphEqPointControls(layerId, {
        ...graphEqForLayer(state.draft, layerId),
        points: orderedPoints,
      });
      bindInlineGraphEqControls(container, layerId);
      return;
    }
  }
  rows.forEach((row, index) => {
    const point = orderedPoints[index];
    if (!point) return;
    if (row.dataset.graphEqPointId !== point.id) row.dataset.graphEqPointId = point.id;
    const pointIndex = Math.max(0, orderedPoints.findIndex((candidate) => candidate.id === point.id));
    row.classList.toggle("selected", point.id === selected?.id);
    row.setAttribute("aria-pressed", point.id === selected?.id ? "true" : "false");
    row.innerHTML = renderInlineGraphEqPointRowContent(point, pointIndex, orderedPoints);
  });
  const inspector = container.querySelector?.("[data-graph-eq-selected-inspector]");
  if (inspector) {
    inspector.outerHTML = renderInlineGraphEqSelectedInspector(
      layerId,
      selected,
      draftEditLocked(),
      orderedPoints.length,
      selectedIndex,
      orderedPoints,
    );
  }
  bindInlineGraphEqControls(container, layerId);
};

const inlineGraphEqPointsWithUpdate = (eq, pointId, updates) => (
  eq.points.map((point) => (
    point.id === pointId ? normalizeGraphEqPoint({ ...point, ...updates }) : point
  ))
);

const commitInlineGraphEqPointControl = (layerId, pointId, controlName, value) => {
  const eq = graphEqForLayer(state.draft, layerId);
  const pointIndex = eq.points.findIndex((candidate) => candidate.id === pointId);
  const point = eq.points[pointIndex];
  if (!point) return;
  const updates = {};
  if (controlName === "type") {
    if (point.type !== "bell" || value !== "bell") return;
    updates.type = value;
  }
  if (controlName === "freq") {
    if (isFixedGraphEqShelfPoint(point)) return;
    updates.frequency_hz = Number(value);
  }
  if (controlName === "gain") updates.gain_db = Number(value);
  if (controlName === "q") updates.q = Number(value);
  if (!Object.keys(updates).length) return;
  commitInlineGraphEqPoints(
    layerId,
    inlineGraphEqPointsWithUpdate(eq, pointId, updates),
    pointId,
  );
};

const addInlineGraphEqPoint = (layerId) => {
  const eq = graphEqForLayer(state.draft, layerId);
  if (eq.points.length >= graphEqMaxPoints || draftEditLocked()) return;
  const id = `point-${Date.now().toString(36)}`;
  const sortedFrequencies = eq.points
    .map((point) => clampNumber(point.frequency_hz, graphEqMinFrequencyHz, graphEqMaxFrequencyHz))
    .sort((a, b) => a - b);
  const boundaries = [graphEqMinFrequencyHz, ...sortedFrequencies, graphEqMaxFrequencyHz];
  let widestGap = [120, 1000];
  let widestLogSpan = -Infinity;
  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const low = Math.max(boundaries[index], graphEqMinFrequencyHz);
    const high = Math.min(boundaries[index + 1], graphEqMaxFrequencyHz);
    const span = Math.log10(high) - Math.log10(low);
    if (span > widestLogSpan) {
      widestLogSpan = span;
      widestGap = [low, high];
    }
  }
  const nextPoint = normalizeGraphEqPoint({
    id,
    type: "bell",
    frequency_hz: Math.round(Math.sqrt(widestGap[0] * widestGap[1])),
    gain_db: 0,
    q: graphEqDefaultBellQ,
  });
  const lowShelf = eq.points.find((point) => point.type === "low_shelf");
  const highShelf = eq.points.find((point) => point.type === "high_shelf");
  const bells = eq.points.filter((point) => point.type === "bell");
  commitInlineGraphEqPoints(layerId, [lowShelf, nextPoint, ...bells, highShelf].filter(Boolean), id);
};

const deleteInlineGraphEqPoint = (layerId, pointId) => {
  const eq = graphEqForLayer(state.draft, layerId);
  const selected = eq.points.find((point) => point.id === pointId);
  if (!pointId || !isGraphEqPointDeletable(selected) || draftEditLocked()) return;
  const nextPoints = eq.points.filter((point) => point.id !== pointId);
  commitInlineGraphEqPoints(layerId, nextPoints, nextPoints.find((point) => point.type === "bell")?.id || null);
};

const resetInlineGraphEqLayer = (layerId) => {
  if (draftEditLocked()) return;
  commitInlineGraphEqPoints(layerId, defaultGraphEqPoints(), null);
};

const stepInlineGraphEqNumericControl = (button) => {
  const input = $(button.dataset.graphEqStepTarget);
  if (!input || input.disabled) return;
  const direction = Number(button.dataset.graphEqStepDirection || 0);
  const step = Number(input.step) || 1;
  const min = Number(input.min);
  const max = Number(input.max);
  const current = Number(input.value || 0);
  const next = clampNumber(current + direction * step, min, max);
  input.value = String(Number(next.toFixed(graphEqStepDecimalPlaces(input))));
  commitInlineGraphEqPointControl(
    button.closest("[data-graph-eq-layer-card]")?.dataset.graphEqLayerCard,
    input.dataset.graphEqPointId,
    input.dataset.graphEqPointControl,
    input.value,
  );
};

const bindInlineGraphEqControls = (card, layerId) => {
  (card.querySelectorAll?.("[data-graph-eq-point-control]") || []).forEach((control) => {
    if (control.dataset.graphEqBound === "true") return;
    control.dataset.graphEqBound = "true";
    const commit = () => commitInlineGraphEqPointControl(
      layerId,
      control.dataset.graphEqPointId,
      control.dataset.graphEqPointControl,
      control.value,
    );
    if (control.tagName === "SELECT") {
      control.addEventListener("change", commit);
      return;
    }
    control.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      commit();
    });
    control.addEventListener("blur", commit);
  });
  (card.querySelectorAll?.("[data-graph-eq-step-target]") || []).forEach((button) => {
    if (button.dataset.graphEqBound === "true") return;
    button.dataset.graphEqBound = "true";
    button.addEventListener("click", () => stepInlineGraphEqNumericControl(button));
  });
  (card.querySelectorAll?.("[data-graph-eq-point-row]") || []).forEach((row) => {
    if (row.dataset.graphEqBound === "true") return;
    row.dataset.graphEqBound = "true";
    row.addEventListener("click", () => {
      syncInlineGraphEqSelection(card, layerId, row.dataset.graphEqPointId);
    });
  });
  (card.querySelectorAll?.("[data-graph-eq-action]") || []).forEach((button) => {
    if (button.dataset.graphEqBound === "true") return;
    button.dataset.graphEqBound = "true";
    button.addEventListener("click", () => {
      if (button.dataset.graphEqAction === "add-point") addInlineGraphEqPoint(layerId);
      if (button.dataset.graphEqAction === "delete-point") {
        deleteInlineGraphEqPoint(layerId, button.dataset.graphEqPointId);
      }
      if (button.dataset.graphEqAction === "reset-layer") resetInlineGraphEqLayer(layerId);
    });
  });
};

const graphEqIslandApi = () => window.secretPondDssspGraphEq || window.secretPondGraphEq || null;

const syncInlineGraphEqSelection = (container, layerId, pointId) => {
  if (!pointId) return;
  state.graphEqSelectedPointIds[layerId] = pointId;
  const eq = graphEqForLayer(state.draft, layerId);
  syncInlineGraphEqPointControls(container, layerId, eq.points, pointId);
  const root = container.querySelector("[data-graph-eq-dsssp-root-shell]");
  graphEqIslandApi()?.syncEditor?.(root, { selectedPointId: pointId });
};

const mountInlineGraphEqEditor = (container, layerId) => {
  const root = container.querySelector("[data-graph-eq-dsssp-root-shell]");
  const api = graphEqIslandApi();
  if (!layerIds.includes(layerId) || !root || !api?.mountEditor) return;
  const eq = graphEqForLayer(state.draft, layerId);
  const selectedPointId = selectedOrFirstGraphEqPointId(layerId, eq);
  api.mountEditor(root, {
    layerId,
    points: eq.points,
    selectedPointId,
    disabled: draftEditLocked(),
    onSelect: (pointId) => syncInlineGraphEqSelection(container, layerId, pointId),
    onDelete: (payload) => {
      preserveInlineGraphEqMount(layerId);
      const nextPoints = payload?.points || [];
      const nextSelectedPointId = payload?.selectedPointId || null;
      commitInlineGraphEqPoints(layerId, nextPoints, nextSelectedPointId, {
        renderAfterSync: false,
        afterSync: () => syncInlineGraphEqPointControls(
          container,
          layerId,
          nextPoints,
          nextSelectedPointId,
        ),
      });
    },
    onDragState: ({ dragging }) => {
      if (dragging) preserveInlineGraphEqMount(layerId);
    },
    onChange: (payload) => {
      if (payload?.ended) return;
      preserveInlineGraphEqMount(layerId);
      const nextPoints = payload?.points || [];
      if (!nextPoints.length) return;
      const nextSelectedPointId = payload.selectedPointId || selectedOrFirstGraphEqPointId(layerId, {
        points: nextPoints,
      });
      previewInlineGraphEqPoints(layerId, nextPoints, nextSelectedPointId, {
        afterSync: () => syncInlineGraphEqPointControls(
          container,
          layerId,
          nextPoints,
          nextSelectedPointId,
        ),
      });
    },
    onChangeCommitted: (payload) => {
      preserveInlineGraphEqMount(layerId);
      const nextPoints = payload?.points || [];
      if (!nextPoints.length) return;
      const nextSelectedPointId = payload.selectedPointId || selectedOrFirstGraphEqPointId(layerId, {
        points: nextPoints,
      });
      commitInlineGraphEqPoints(layerId, nextPoints, nextSelectedPointId, {
        renderAfterSync: false,
        afterSync: () => syncInlineGraphEqPointControls(
          container,
          layerId,
          nextPoints,
          nextSelectedPointId,
        ),
      });
    },
  });
};

const initializeInlineGraphEqEditors = () => {
  document.querySelectorAll("[data-graph-eq-inline-editor]").forEach((container) => {
    const layerId = container.dataset.graphEqInlineEditor;
    mountInlineGraphEqEditor(container, layerId);
  });
};

const startGraphEqDrag = (layerId, pointId, event) => {
  if (!pointId || draftEditLocked()) return;
  event.preventDefault();
  state.graphEqSelectedPointIds[layerId] = pointId;
  state.graphEqDrag = { layerId, pointId, pointerId: event.pointerId };
  const canvas = $("graphEqCanvas");
  canvas?.classList.add("drag-active");
  canvas?.setPointerCapture?.(event.pointerId);
  renderGraphEqPointControls(graphEqForLayer(state.draft, layerId), layerId);
};

const renderGraphEqLayerTabs = () => {
  const container = $("graphEqLayerTabs");
  if (!container) return;
  const activeLayerId = currentGraphEqLayerId();
  container.innerHTML = layerIds.map((layerId) => {
    const active = layerId === activeLayerId;
    return `
      <button
        class="graph-eq-layer-tab ${active ? "active" : ""}"
        type="button"
        role="tab"
        aria-selected="${active ? "true" : "false"}"
        data-graph-eq-layer="${layerId}"
      >
        ${labelMarkup(layerLabels[layerId])}
      </button>
    `;
  }).join("");
  (container.querySelectorAll?.("[data-graph-eq-layer]") || []).forEach((button) => {
    button.addEventListener("click", () => setGraphEqLayer(button.dataset.graphEqLayer));
  });
};

const renderGraphEqEditor = (eq, layerId) => {
  const svg = $("graphEqSvg");
  const overlay = $("graphEqPointOverlay");
  if (!svg || !overlay) return;
  const selectedId = selectedGraphEqPointId(layerId);
  const responsePath = graphEqPathD(graphEqVisualResponsePoints(eq, 96));
  const zeroY = graphEqGainToY(0) * 360;
  svg.innerHTML = `
    <rect
      class="graph-eq-hit-surface"
      data-graph-eq-hit-surface="true"
      x="0"
      y="0"
      width="1000"
      height="360"
    ></rect>
    <line class="graph-eq-zero-line" x1="0" y1="${zeroY}" x2="1000" y2="${zeroY}" />
    <path class="graph-eq-curve" data-graph-eq-curve="true" d="${responsePath}" />
  `;
  overlay.innerHTML = eq.points.map((point, index) => {
      const position = graphEqPointScreenPosition(point, index, eq.points);
      const selected = point.id === selectedId;
      const lockedX = graphEqLockedEndpointX(point, index, eq.points);
      const edgeClass = lockedX === 0 ? "edge-left" : lockedX === 1 ? "edge-right" : "";
      return `
        <button
          class="graph-eq-point-hit ${selected ? "selected" : ""} ${lockedX !== null ? "locked-x" : ""} ${edgeClass}"
          data-graph-eq-point="${escapeHtml(point.id)}"
          style="left: ${(position.x * 100).toFixed(3)}%; top: ${(position.y * 100).toFixed(3)}%;"
          type="button"
          role="button"
          aria-pressed="${selected ? "true" : "false"}"
          aria-label="${graphEqPointTypes[point.type]} ${Math.round(point.frequency_hz)} Hz"
        >
          <span class="graph-eq-point-marker" aria-hidden="true"></span>
        </button>
      `;
    }).join("");
  (overlay.querySelectorAll?.("[data-graph-eq-point]") || []).forEach((pointNode) => {
    const pointId = pointNode.dataset.graphEqPoint;
    pointNode.addEventListener("click", () => setSelectedGraphEqPoint(layerId, pointId));
    pointNode.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      startGraphEqDrag(layerId, pointId, event);
    });
  });
  svg.onpointerdown = (event) => {
    const target = event.target;
    if (!target?.closest?.("[data-graph-eq-hit-surface], [data-graph-eq-curve]")) return;
    const pointer = graphEqPointerRatioFromPointerEvent(event);
    if (!pointer) return;
    const pointId = graphEqNearestPointId(eq, pointer);
    startGraphEqDrag(layerId, pointId, event);
    if (!pointId) return;
    const pointIndex = eq.points.findIndex((item) => item.id === pointId);
    const point = eq.points[pointIndex];
    updateDraftGraphEqPoint(
      layerId,
      pointId,
      graphEqPointUpdatesFromPointerRatio(point, pointer, pointIndex, eq.points),
    );
    syncDraftSnapshot();
    renderGraphEqWorkspace();
  };
};

const graphEqPointerRatioFromPointerEvent = (event) => {
  const canvas = $("graphEqCanvas") || $("graphEqSvg");
  const rect = canvas?.getBoundingClientRect?.();
  if (!rect || rect.width <= 0 || rect.height <= 0) return null;
  const x = clampNumber((event.clientX - rect.left) / rect.width, 0, 1);
  const y = clampNumber((event.clientY - rect.top) / rect.height, 0, 1);
  return { x, y };
};

const graphEqPointFromPointerEvent = (event, point, index = null, points = []) => {
  const pointer = graphEqPointerRatioFromPointerEvent(event);
  return pointer ? graphEqPointUpdatesFromPointerRatio(point, pointer, index, points) : null;
};

const setGraphEqStepButtonsDisabled = (controlId, disabled) => {
  document.querySelectorAll?.(`[data-graph-eq-step-target="${controlId}"]`).forEach((button) => {
    button.disabled = disabled;
  });
};

const renderGraphEqPointControls = (eq, layerId) => {
  const selected = selectedGraphEqPoint(eq, layerId);
  const selectedIndex = selected
    ? eq.points.findIndex((point) => point.id === selected.id)
    : -1;
  const controls = $("graphEqPointControls");
  const status = $("graphEqStatus");
  const detail = $("graphEqStatusDetail");
  const liveStatus = currentPlaybackApplyMode() === "live"
    ? graphEqLiveStatusCopy(state.snapshot?.playback?.live_graph_eq)
    : null;
  if (!controls) return;
  controls.classList.toggle("empty", !selected);
  controls.querySelector(".graph-eq-empty-state").hidden = Boolean(selected);
  ["graphEqPointType", "graphEqPointFreq", "graphEqPointGain", "graphEqPointQ"].forEach((id) => {
    const input = $(id);
    input.disabled = !selected || draftEditLocked();
    setGraphEqStepButtonsDisabled(id, input.disabled);
  });
  $("graphEqDeletePointButton").disabled = !selected || draftEditLocked() || eq.points.length <= 1;
  $("graphEqAddPointButton").disabled = draftEditLocked() || eq.points.length >= graphEqMaxPoints;
  $("graphEqResetLayerButton").disabled = draftEditLocked();
  $("graphEqResetAllButton").disabled = draftEditLocked();
  if (status) {
    status.textContent = liveStatus?.label || (
      selected ? `${graphEqPointTypes[selected.type]} 선택됨` : "점을 선택하세요"
    );
    status.className = liveStatus?.className || `status-pill ${selected ? "safe" : "muted"}`;
  }
  if (detail) {
    detail.textContent = liveStatus?.detail || "";
    detail.hidden = !liveStatus?.detail;
  }
  if (!selected) return;
  $("graphEqPointType").value = selected.type;
  $("graphEqPointFreq").value = String(Math.round(selected.frequency_hz));
  $("graphEqPointGain").value = String(Number(selected.gain_db.toFixed(1)));
  $("graphEqPointQ").value = String(Number(selected.q.toFixed(2)));
};

const renderGraphEqFilterRange = (layerId) => {
  const container = $("graphEqFilterControls");
  if (!container || !state.draft) return;
  container.innerHTML = "";
  const layer = state.draft.layers[layerId];
  const activeLayer = state.snapshot?.settings?.active?.layers?.[layerId] || layer;
  container.appendChild(
    controlGroup(
      graphEqFilterGroup,
      layer,
      activeLayer,
      (control, value) => commitGraphEqFilterEdit(layerId, control, value),
      () => resetLayerFilter(layerId),
    ),
  );
};

const renderGraphEqWorkspace = () => {
  if (!state.draft?.layers) return;
  const layerId = currentGraphEqLayerId();
  const eq = graphEqForLayer(state.draft, layerId);
  renderGraphEqLayerTabs();
  renderGraphEqEditor(eq, layerId);
  renderGraphEqPointControls(eq, layerId);
  renderGraphEqFilterRange(layerId);
};

const commitGraphEqSelectedControl = (controlId) => {
  const layerId = currentGraphEqLayerId();
  const pointId = selectedGraphEqPointId(layerId);
  if (!pointId) return;
  const eq = graphEqForLayer(state.draft, layerId);
  const selected = selectedGraphEqPoint(eq, layerId);
  const selectedIndex = selected
    ? eq.points.findIndex((point) => point.id === selected.id)
    : -1;
  const updates = {};
  if (controlId === "graphEqPointType") updates.type = $("graphEqPointType").value;
  if (controlId === "graphEqPointFreq") updates.frequency_hz = Number($("graphEqPointFreq").value);
  if (controlId === "graphEqPointGain") updates.gain_db = Number($("graphEqPointGain").value);
  if (controlId === "graphEqPointQ") updates.q = Number($("graphEqPointQ").value);
  commitGraphEqPointEdit(layerId, pointId, updates);
};

const graphEqStepDecimalPlaces = (input) => {
  const step = String(input.step || "");
  const decimalIndex = step.indexOf(".");
  return decimalIndex >= 0 ? step.length - decimalIndex - 1 : 0;
};

const stepGraphEqNumericControl = (button) => {
  const input = $(button.dataset.graphEqStepTarget);
  if (!input || input.disabled) return;
  const direction = Number(button.dataset.graphEqStepDirection || 0);
  if (!direction) return;
  const step = Number(input.step) || 1;
  const min = Number(input.min);
  const max = Number(input.max);
  const current = Number(input.value || 0);
  const next = clampNumber(current + direction * step, min, max);
  input.value = String(Number(next.toFixed(graphEqStepDecimalPlaces(input))));
  commitGraphEqSelectedControl(input.id);
};

const bindGraphEqControls = () => {
  ["graphEqPointFreq", "graphEqPointGain", "graphEqPointQ"].forEach((id) => {
    $(id).addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      commitGraphEqSelectedControl(id);
    });
    $(id).addEventListener("blur", () => commitGraphEqSelectedControl(id));
  });
  document.querySelectorAll("[data-graph-eq-step-target]").forEach((button) => {
    button.addEventListener("click", () => stepGraphEqNumericControl(button));
  });
  $("graphEqPointType").addEventListener("change", () => commitGraphEqSelectedControl("graphEqPointType"));
  $("graphEqAddPointButton").addEventListener("click", addGraphEqPoint);
  $("graphEqDeletePointButton").addEventListener("click", deleteSelectedGraphEqPoint);
  $("graphEqResetLayerButton").addEventListener("click", () => resetGraphEqLayer());
  $("graphEqResetAllButton").addEventListener("click", resetAllGraphEqLayers);
  $("graphEqCanvas").addEventListener("pointermove", (event) => {
    const drag = state.graphEqDrag;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const eq = graphEqForLayer(state.draft, drag.layerId);
    const pointIndex = eq.points.findIndex((item) => item.id === drag.pointId);
    const point = eq.points[pointIndex];
    const updates = graphEqPointFromPointerEvent(event, point, pointIndex, eq.points);
    if (!updates) return;
    updateDraftGraphEqPoint(drag.layerId, drag.pointId, updates);
    syncDraftSnapshot();
    renderGraphEqWorkspace();
  });
  $("graphEqCanvas").addEventListener("pointerup", (event) => {
    const drag = state.graphEqDrag;
    if (!drag || drag.pointerId !== event.pointerId) return;
    state.graphEqDrag = null;
    $("graphEqCanvas").classList.remove("drag-active");
    $("graphEqCanvas").releasePointerCapture?.(event.pointerId);
    commitDraftChange(() => {}, {
      feedbackSurfaceId: `layer:${drag.layerId}`,
      feedbackControlIds: graphEqControlIds(drag.layerId, drag.pointId),
      afterSync: renderGraphEqWorkspace,
    });
  });
  $("graphEqCanvas").addEventListener("pointercancel", (event) => {
    state.graphEqDrag = null;
    $("graphEqCanvas").classList.remove("drag-active");
    $("graphEqCanvas").releasePointerCapture?.(event.pointerId);
  });
};

const renderRecordingControls = () => {
  const container = $("recordingControls");
  renderCoveredFeedbackContainer(
    container,
    "control-stack compact feedback-surface",
    "recording",
  );
  const activeRecording = state.snapshot?.settings.active.recording || state.draft.recording;
  recordingControlGroups.forEach((group) => {
    container.appendChild(
      controlGroup(group, state.draft.recording, activeRecording, (control, value) => {
        commitDraftChange(
          () => {
            setPath(state.draft.recording, control.path, value);
            clearRecordingPresetSelection();
          },
          {
            feedbackControlId: `recording.${control.path}`,
            afterSync: renderRecordingPresets,
          },
        );
      }),
    );
  });
};

const renderRecordingPresets = () => {
  const draftLock = deriveDraftControlLockState(state);
  document.querySelectorAll("#recordingPresets .preset-button").forEach((button) => {
    const label = presetLabels[button.dataset.preset];
    if (label) button.innerHTML = labelMarkup(label);
    const active = recordingPresetMatches(button.dataset.preset);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.disabled = draftLock.disabled;
    button.title = draftLock.disabled ? draftLock.title : "";
  });
};

const recordingPresetMatches = (name) => recordingPresetIsSelected(name);

const applyRecordingPreset = (name) => {
  const preset = recordingPresetDefs[name];
  if (!preset || !state.draft) return;
  const next = reversiblePresetDraft(
    state.draft.recording,
    recordingPresetDefs,
    name,
    state.presetSelections.recording,
  );
  commitDraftChange(
    () => {
      state.draft.recording = next.draft;
      state.presetSelections.recording = next.selection;
    },
    {
      feedbackSurfaceId: "recording",
      feedbackControlIds: presetFeedbackControlIds("recording", preset),
      afterSync: () => {
        renderRecordingPresets();
        renderRecordingControls();
      },
    },
  );
};

const workspaceTabs = () => Array.from(document.querySelectorAll("[data-workspace-tab]"));

const renderWorkspaceTabs = () => {
  document.documentElement.dataset.workspaceTab = state.workspaceTab;
  workspaceTabs().forEach((button) => {
    const active = button.dataset.workspaceTab === state.workspaceTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll("[data-workspace-pane]").forEach((pane) => {
    pane.hidden = pane.dataset.workspacePane !== state.workspaceTab;
  });
};

const updateWorkspaceUrl = () => {
  if (!window.history?.replaceState || !window.location?.href) return;
  const url = new URL(window.location.href);
  if (state.workspaceTab === "treatment") url.searchParams.delete("workspace");
  else url.searchParams.set("workspace", state.workspaceTab);
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
};

const setWorkspaceTab = (tabName, options = {}) => {
  if (!workspaceTabNames.includes(tabName)) return;
  state.workspaceTab = tabName;
  renderWorkspaceTabs();
  if (options.syncUrl !== false) updateWorkspaceUrl();
};

const sideTabs = () => Array.from(document.querySelectorAll("[data-side-tab]"));

const renderSideTabs = () => {
  const activeTab = sideTabNames.includes(state.sideTab) ? state.sideTab : "library";
  state.sideTab = activeTab;
  sideTabs().forEach((button) => {
    const active = button.dataset.sideTab === activeTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll("[data-side-pane]").forEach((pane) => {
    pane.hidden = pane.dataset.sidePane !== activeTab;
  });
};

const setSideTab = (tabName) => {
  if (!sideTabNames.includes(tabName)) return;
  state.sideTab = tabName;
  renderSideTabs();
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

const filterStatus = (group, draftSource, activeSource = null) => {
  const highpassControl = group.controls.find((control) => control.path.endsWith("highpass_hz"));
  const lowpassControl = group.controls.find((control) => control.path.endsWith("lowpass_hz"));
  if (!highpassControl || !lowpassControl) return null;
  const highpass = getPath(draftSource, highpassControl.path);
  const lowpass = getPath(draftSource, lowpassControl.path);
  const activeHighpass = activeSource ? getPath(activeSource, highpassControl.path) : highpass;
  const activeLowpass = activeSource ? getPath(activeSource, lowpassControl.path) : lowpass;
  const pending =
    Number(activeHighpass) !== Number(highpass) || Number(activeLowpass) !== Number(lowpass);
  const bypassed =
    Number(highpass) <= Number(highpassControl.min) &&
    Number(lowpass) >= Number(lowpassControl.max);
  const highpassLabel = formatValue(highpass, highpassControl.suffix);
  const lowpassLabel = formatValue(lowpass, lowpassControl.suffix);
  const fullBandLabel = `${formatValue(highpassControl.min, highpassControl.suffix)} - ${formatValue(
    lowpassControl.max,
    lowpassControl.suffix,
  )}`;
  const passRangeLabel = `${highpassLabel} - ${lowpassLabel}`;
  return {
    bypassed,
    pending,
    label: pending ? "아직 적용 안 됨" : bypassed ? "필터 없음" : "필터 적용됨",
    detail: pending
      ? `변경 대역: ${passRangeLabel}`
      : bypassed
        ? `전체 대역: ${fullBandLabel}`
        : `통과 대역: ${passRangeLabel}`,
  };
};

const filterResetActionState = (group, draftSource, activeSource = null, stateLike = state) => {
  const status = filterStatus(group, draftSource, activeSource);
  const draftLock = deriveDraftControlLockState(stateLike);
  return {
    status,
    resetDisabled: !status || draftLock.disabled || Boolean(status.bypassed),
    resetTitle: draftLock.title,
  };
};

const groupActionsMarkup = (group, draftSource, activeSource = null) => {
  if (group.action !== "reset-filter") return "";
  const actionState = filterResetActionState(group, draftSource, activeSource);
  const { status } = actionState;
  if (!status) return "";
  return `
    <div class="control-group-actions">
      <span class="filter-status ${
        status.pending ? "pending" : status.bypassed ? "bypassed" : "active"
      }">
        <span>필터 상태</span>
        <strong>${status.label}</strong>
        <small>${status.detail}</small>
      </span>
      <button
        class="mini-button filter-reset-button"
        type="button"
        ${actionState.resetDisabled ? "disabled" : ""}
        ${actionState.resetTitle ? `title="${escapeHtml(actionState.resetTitle)}"` : ""}
      >
        필터 초기화
      </button>
    </div>
  `;
};

const controlGroupKey = (group) =>
  [labelText(group.title), group.className || "", group.action || ""].join(":");

const controlGroup = (group, draftSource, activeSource, onInput, onGroupAction = null) => {
  const section = document.createElement(group.collapsible ? "details" : "section");
  section.className = `control-group ${group.className || ""}`;
  const groupKey = controlGroupKey(group);
  if (group.collapsible) {
    section.open = state.expandedControlGroups[groupKey] ?? Boolean(group.open);
    section.addEventListener("toggle", () => {
      state.expandedControlGroups[groupKey] = Boolean(section.open);
    });
  } else if (group.open) section.open = true;
  let currentDraftSource = draftSource;
  const headTag = group.collapsible ? "summary" : "div";
  section.innerHTML = `
    <${headTag} class="control-group-head">
      <div class="control-group-title">
        <h4>${labelMarkup(group.title)}</h4>
        <p>${group.note || ""}</p>
      </div>
      ${groupActionsMarkup(group, draftSource, activeSource)}
    </${headTag}>
    ${frequencyGuideMarkup(group.guide)}
    <div class="control-group-body ${group.layout || ""}"></div>
  `;
  const body = section.querySelector(".control-group-body");
  const attachGroupAction = () => {
    section
      .querySelector(".filter-reset-button")
      ?.addEventListener("click", () => onGroupAction?.(group));
  };
  const refreshGroupActions = () => {
    const currentActions = section.querySelector(".control-group-actions");
    const nextMarkup = groupActionsMarkup(group, currentDraftSource, activeSource);
    if (!currentActions || !nextMarkup) return;
    const template = document.createElement("template");
    template.innerHTML = nextMarkup.trim();
    const nextActions = template.content.firstElementChild;
    if (!nextActions) return;
    currentActions.replaceWith(nextActions);
    attachGroupAction();
  };
  attachGroupAction();
  if (!body.parentElement) section.appendChild(body);
  group.controls.forEach((control) => {
    body.appendChild(
      rangeControl(
        control,
        getPath(draftSource, control.path),
        (value) => {
          setPath(currentDraftSource, control.path, value);
          currentDraftSource = onInput(control, value) || currentDraftSource;
          refreshGroupActions();
        },
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
    ? `<small class="active-value">현재 적용 ${formatValue(activeValue, suffix)}</small>`
    : "";
  const statusLabel = activeChanged ? "변경값" : "현재값";
  return `<strong>${statusLabel} ${formatValue(draftValue, suffix)}</strong>${activeMarkup}`;
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

const useZeroCenteredRange = (control, min, max) =>
  control.scale === "zero-centered-db" && Number(min) < 0 && Number(max) > 0;

const useLogFrequencyRange = (control, min, max) =>
  control.scale === "log-frequency" && Number(min) > 0 && Number(max) > Number(min);

const logFrequencySliderMax = 1000;

const rangeSliderValueFromActual = (control, value, min, max) => {
  const numericValue = Number(value);
  if (useLogFrequencyRange(control, min, max)) {
    const minLog = Math.log10(Number(min));
    const maxLog = Math.log10(Number(max));
    const valueLog = Math.log10(clamp(numericValue, min, max));
    return ((valueLog - minLog) / (maxLog - minLog)) * logFrequencySliderMax;
  }
  if (!useZeroCenteredRange(control, min, max)) return numericValue;
  if (numericValue < 0) return -(Math.abs(numericValue) / Math.abs(Number(min))) * 100;
  if (numericValue > 0) return (numericValue / Number(max)) * 100;
  return 0;
};

const rangeActualValueFromSlider = (control, sliderValue, min, max) => {
  const numericValue = Number(sliderValue);
  if (useLogFrequencyRange(control, min, max)) {
    const minLog = Math.log10(Number(min));
    const maxLog = Math.log10(Number(max));
    const normalized = rangePercent(numericValue, 0, logFrequencySliderMax) / 100;
    return 10 ** (minLog + normalized * (maxLog - minLog));
  }
  if (!useZeroCenteredRange(control, min, max)) return numericValue;
  if (numericValue < 0) return (Math.abs(numericValue) / 100) * Number(min);
  if (numericValue > 0) return (numericValue / 100) * Number(max);
  return 0;
};

const rangeInputBounds = (control, min, max) => {
  if (useLogFrequencyRange(control, min, max)) {
    return { min: 0, max: logFrequencySliderMax, step: "any" };
  }
  if (!useZeroCenteredRange(control, min, max)) {
    return { min, max, step: control.step };
  }
  return { min: -100, max: 100, step: "any" };
};

const rangeMarkPercent = (control, value, min, max) => {
  if (useLogFrequencyRange(control, min, max)) {
    return rangePercent(rangeSliderValueFromActual(control, value, min, max), 0, logFrequencySliderMax);
  }
  if (!useZeroCenteredRange(control, min, max)) return rangePercent(value, min, max);
  return rangePercent(rangeSliderValueFromActual(control, value, min, max), -100, 100);
};

const setRangeProgress = (row, value, min, max, control = {}) => {
  row.style?.setProperty("--control-percent", `${rangeMarkPercent(control, value, min, max)}%`);
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
            <span style="--mark-position: ${rangeMarkPercent(control, mark.value, min, max)}%">
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

const normalizedTransitionSeconds = (value) => {
  const seconds = Number(value);
  return Number.isFinite(seconds) ? seconds : 0;
};

const positiveToggleMarkup = (control, value) => {
  if (!control.positiveToggle) return "";
  const enabled = normalizedTransitionSeconds(value) > 0;
  return `
    <label class="layer-toggle value-toggle ${enabled ? "enabled" : ""}">
      <input
        type="checkbox"
        role="switch"
        data-positive-toggle="true"
        aria-label="${labelText(control.label)} ${enabled ? "끄기" : "켜기"}"
        ${enabled ? "checked" : ""}
      />
      <span class="layer-toggle-copy">
        <span class="layer-toggle-label">${layerEnabledText(enabled)}</span>
      </span>
    </label>
  `;
};

const valueLineDescriptionMarkup = (control) => {
  if (!control.positiveToggle || !control.description) return "";
  return `<small class="control-description value-description">${helperText(control.description)}</small>`;
};

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
  const rangeBounds = rangeInputBounds(control, min, max);
  setRangeProgress(row, value, min, max, control);
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
      ${control.positiveToggle ? "" : `<small class="control-description">${helperText(control.description)}</small>`}
    </label>
    <div class="slider-cell">
      <div class="range-rail">
        <input
          id="${safeId}"
          type="range"
          min="${rangeBounds.min}"
          max="${rangeBounds.max}"
          step="${rangeBounds.step}"
          value="${rangeSliderValueFromActual(control, value, min, max)}"
        />
      </div>
      <div class="range-assist">
        ${control.rangeLabel ? `<small class="range-context">${control.rangeLabel}</small>` : ""}
        ${rangeMarksMarkup(control, min, max)}
      </div>
    </div>
    <div class="value-stack">
      <div class="value-line">
        <span class="value">${renderDraftValue(value, activeValue, control.suffix)}</span>
        ${valueLineDescriptionMarkup(control)}
        ${positiveToggleMarkup(control, value)}
      </div>
      ${precisionControlMarkup(control, value, min, max, safeId)}
    </div>
  `;
  const input = row.querySelector("input");
  const output = row.querySelector(".value");
  const valueInput = row.querySelector(".value-input");
  const positiveToggle = row.querySelector("[data-positive-toggle]");
  const nudgeDown = row.querySelector(".nudge-down");
  const nudgeUp = row.querySelector(".nudge-up");
  let currentValue = value;
  const commitRangeInputOnChange = control.commitOn === "change";
  let lastPositiveValue =
    control.positiveToggle && normalizedTransitionSeconds(value) > 0
      ? value
      : control.defaultValue;
  [input, valueInput, positiveToggle, nudgeDown, nudgeUp].filter(Boolean).forEach((controlElement) => {
    controlElement.disabled = draftEditLocked();
  });
  const setPositiveToggleState = (nextValue) => {
    if (!positiveToggle) return;
    const enabled = normalizedTransitionSeconds(nextValue) > 0;
    positiveToggle.checked = enabled;
    positiveToggle.setAttribute(
      "aria-label",
      `${labelText(control.label)} ${enabled ? "끄기" : "켜기"}`,
    );
    const valueToggle =
      typeof positiveToggle.closest === "function"
        ? positiveToggle.closest(".value-toggle")
        : null;
    const label = valueToggle?.querySelector(".layer-toggle-label");
    if (label) label.textContent = layerEnabledText(enabled);
    valueToggle?.classList.toggle("enabled", enabled);
  };
  const setDisplayedValue = (nextValue) => {
    input.value = String(rangeSliderValueFromActual(control, nextValue, min, max));
    if (valueInput) valueInput.value = String(nextValue);
    setRangeProgress(row, nextValue, min, max, control);
    output.innerHTML = renderDraftValue(nextValue, activeValue, control.suffix);
    setPositiveToggleState(nextValue);
  };
  const updateValue = (nextValue, { fromSlider = false, commit = true } = {}) => {
    if (draftEditLocked()) {
      setDisplayedValue(currentValue);
      return;
    }
    const actualValue = fromSlider
      ? rangeActualValueFromSlider(control, nextValue, min, max)
      : nextValue;
    const numericValue = snappedValue(actualValue, control.step, min, max);
    if (control.positiveToggle && numericValue > 0) lastPositiveValue = numericValue;
    currentValue = numericValue;
    setDisplayedValue(numericValue);
    if (commit) onInput(numericValue);
  };
  input.addEventListener("input", () => {
    updateValue(input.value, { fromSlider: true, commit: !commitRangeInputOnChange });
  });
  if (commitRangeInputOnChange) {
    input.addEventListener("change", () => updateValue(input.value, { fromSlider: true }));
  }
  valueInput?.addEventListener("change", () => updateValue(valueInput.value));
  valueInput?.addEventListener("input", () => {
    if (Number.isFinite(Number(valueInput.value))) updateValue(valueInput.value);
  });
  positiveToggle?.addEventListener("change", () => {
    updateValue(positiveToggle.checked ? lastPositiveValue : 0);
  });
  nudgeDown?.addEventListener("click", () => updateValue(Number(currentValue) - Number(control.step)));
  nudgeUp?.addEventListener("click", () => updateValue(Number(currentValue) + Number(control.step)));
  return row;
};

const clearDraftSaveTimer = () => {
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
};

const invalidatePendingDraftSaves = () => {
  clearDraftSaveTimer();
  state.draftSaveRequestId += 1;
  clearPreservedInlineGraphEqMount();
  if (state.liveApplyFeedback) {
    state.liveApplyFeedback = reduceLiveApplyFeedbackState(state.liveApplyFeedback, {
      type: "mode_changed",
      modeEpoch: currentLiveApplyModeEpoch() + 1,
    });
  }
  state.pendingCoveredFeedbackSurfaceId = undefined;
  state.coveredFeedbackSurfaceId = undefined;
  state.pendingLiveFeedbackSurfaceId = undefined;
  state.liveFeedbackSurfaceId = undefined;
  state.pendingCoveredFeedbackControlIds = [];
  state.coveredFeedbackControlIds = [];
  state.draftSaveInFlight = false;
};

const beginDraftSave = () => {
  const requestId = state.draftSaveRequestId + 1;
  state.draftSaveRequestId = requestId;
  return {
    requestId,
    draftEditRevision: state.draftEditRevision,
    coveredFeedbackControlIds: [...state.pendingCoveredFeedbackControlIds],
    graphEqPreserveLayerId: state.graphEqInlinePreserveMountLayerId,
    graphEqPreserveToken: state.graphEqInlinePreserveMountToken,
  };
};

const isCurrentDraftSave = (request) =>
  request.requestId === state.draftSaveRequestId &&
  request.draftEditRevision === state.draftEditRevision;

const rollbackDraftCoveredControlsFromActive = (controlIds = []) => {
  const activeSettings = state.confirmedActiveSettingsSnapshot || state.snapshot?.settings?.active;
  if (!state.draft || !activeSettings || controlIds.length === 0) return false;
  controlIds.forEach((controlId) => {
    const activeValue = getPath(activeSettings, controlId);
    setPath(state.draft, controlId, clone(activeValue));
    if (state.snapshot?.settings?.draft) {
      setPath(state.snapshot.settings.draft, controlId, clone(activeValue));
    }
  });
  syncDraftSnapshot();
  refreshCoveredFeedbackVisualStates();
  return true;
};

const rollbackDraftCoveredControlSnapshots = (controlSnapshots = []) => {
  if (!state.draft || controlSnapshots.length === 0) return false;
  controlSnapshots.forEach(({ controlId, activeValue }) => {
    setPath(state.draft, controlId, clone(activeValue));
    if (state.snapshot?.settings?.draft) {
      setPath(state.snapshot.settings.draft, controlId, clone(activeValue));
    }
  });
  syncDraftSnapshot();
  refreshCoveredFeedbackVisualStates();
  return true;
};

const clearStableRestartRollbackFeedbackState = ({ refresh = false } = {}) => {
  const controlSnapshots = [...state.stableApplyCoveredFeedbackControlSnapshots];
  state.applyInFlight = false;
  state.applyAndRestartInFlight = false;
  state.stableApplyCoveredFeedbackSurfaceIds = [];
  state.stableApplyCoveredFeedbackControlSnapshots = [];
  state.pendingCoveredFeedbackSurfaceId = undefined;
  state.coveredFeedbackSurfaceId = undefined;
  state.pendingLiveFeedbackSurfaceId = undefined;
  state.liveFeedbackSurfaceId = undefined;
  state.pendingCoveredFeedbackControlIds = [];
  state.coveredFeedbackControlIds = [];
  const rolledBack = rollbackDraftCoveredControlSnapshots(controlSnapshots);
  if (refresh && !rolledBack) refreshCoveredFeedbackVisualStates();
  return rolledBack;
};

const scheduleDraftSave = () => {
  clearDraftSaveTimer();
  state.saveTimer = setTimeout(() => {
    state.saveTimer = null;
    saveDraft().catch(() => {});
  }, 280);
};

const saveDraft = async () => {
  if (!state.draft) return null;
  clearDraftSaveTimer();
  const request = beginDraftSave();
  const draftPayload = clone(state.draft);
  state.coveredFeedbackSurfaceId = state.pendingCoveredFeedbackSurfaceId;
  state.liveFeedbackSurfaceId = state.pendingLiveFeedbackSurfaceId;
  state.coveredFeedbackControlIds = [...state.pendingCoveredFeedbackControlIds];
  updateLiveApplyFeedbackForRequestStart(request);
  state.draftSaveInFlight = true;
  renderDraftSaveFeedbackSurfaces();
  try {
    const payload = await api("/api/settings/draft", {
      method: "PUT",
      body: JSON.stringify(draftPayload),
    });
    if (!isCurrentDraftSave(request)) return payload;
    if (serverPayloadRevisionIsOlder(payload)) return payload;
    rememberServerPayloadRevision(payload);
    updateLiveApplyFeedbackForRequestSuccess(request, payload.settings);
    applySettingsPayload(payload.settings, { renderControlsOnSync: false });
    renderState();
    renderDevices();
    return payload;
  } catch (error) {
    if (isCurrentDraftSave(request)) {
      updateLiveApplyFeedbackForRequestFailure(request);
      clearPreservedInlineGraphEqMount();
      rollbackDraftCoveredControlsFromActive(request.coveredFeedbackControlIds);
      showSettingsApplyFailureCaution(error.message);
      throw error;
    }
    return null;
  } finally {
    if (isCurrentDraftSave(request)) {
      const preservedGraphEqLayerId = request.graphEqPreserveLayerId;
      const preservedGraphEqToken = request.graphEqPreserveToken;
      state.draftSaveInFlight = false;
      state.pendingCoveredFeedbackSurfaceId = undefined;
      state.coveredFeedbackSurfaceId = undefined;
      state.pendingLiveFeedbackSurfaceId = undefined;
      state.liveFeedbackSurfaceId = undefined;
      state.pendingCoveredFeedbackControlIds = [];
      state.coveredFeedbackControlIds = [];
      renderDraftSaveFeedbackSurfaces();
      if (preservedGraphEqLayerId) {
        setTimeout(() => {
          clearPreservedInlineGraphEqMount(preservedGraphEqLayerId, preservedGraphEqToken);
        }, 700);
      }
    } else if (request.requestId === state.draftSaveRequestId) {
      state.draftSaveInFlight = false;
      renderDraftSaveFeedbackSurfaces();
    }
  }
};

const setSettingsPresetActionInFlight = (inFlight) => {
  if (dashboardSnapshotRenderable(state.snapshot)) {
    setOperationLockFlag("settingsPresetActionInFlight", inFlight);
  } else {
    state.settingsPresetActionInFlight = Boolean(inFlight);
  }
  renderSettingsPresets();
};

const flushPendingDraftBeforePresetAction = async () => {
  if (!state.draft || (!state.saveTimer && !state.draftSaveInFlight)) return null;
  return saveDraft();
};

const dashboardSnapshotRenderable = (snapshot) => (
  Boolean(
    snapshot?.playback &&
      snapshot?.settings?.active?.input_control?.minimum_recording_seconds !== undefined &&
      snapshot?.settings?.active?.input_control?.maximum_recording_seconds !== undefined,
  )
);

const applySettingsPresetPayload = async (payload, options = {}) => {
  if (payload?.state?.playback && payload?.state?.settings) {
    const applied = await applyResponseState(payload, options);
    if (applied === false) return false;
  } else if (payload?.settings) {
    const normalizedPayload = normalizeStatePayload(payload);
    if (serverPayloadRevisionIsOlder(normalizedPayload)) return false;
    rememberServerPayloadRevision(normalizedPayload);
    applySettingsPayload(normalizedPayload.settings, {
      renderControlsOnSync: false,
      ...options,
    });
    if (dashboardSnapshotRenderable(state.snapshot)) {
      renderState();
      renderControls();
    }
  } else {
    await requestState(options);
  }
  if (payload?.sources) {
    state.sources = payload.sources;
    renderSourceLibrary({ allowInteractiveDeferral: false });
  }
  return true;
};

const saveSettingsPreset = async () => {
  const input = $("settingsPresetNameInput");
  const name = String(input?.value || "").trim();
  if (!name) {
    showError("프리셋 이름을 입력하세요.");
    return null;
  }
  let presetError = null;
  setSettingsPresetActionInFlight(true);
  try {
    await flushPendingDraftBeforePresetAction();
    const payload = await api("/api/settings/presets", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    state.settingsPresets = payload.presets || [];
    state.settingsPresetsError = null;
    if (input) input.value = "";
    renderSettingsPresets();
    clearTransientError({ respectMinimumVisibleDuration: true });
    return payload;
  } catch (error) {
    presetError = error;
    state.settingsPresetsError = null;
    showError(error.message);
    return null;
  } finally {
    setSettingsPresetActionInFlight(false);
    if (presetError) await requestSettingsPresets().catch(() => {});
  }
};

const updateSettingsPreset = async (presetId) => {
  if (!presetId || state.settingsPresetActionInFlight) return null;
  const preset = state.settingsPresets.find((item) => item.id === presetId);
  const name = preset?.name || "이 프리셋";
  if (window.confirm?.(`${name}을 현재 draft로 덮어쓸까요?`) === false) return null;
  let presetError = null;
  setSettingsPresetActionInFlight(true);
  try {
    await flushPendingDraftBeforePresetAction();
    const payload = await api(`/api/settings/presets/${encodeURIComponent(presetId)}`, {
      method: "PATCH",
      body: JSON.stringify({}),
    });
    state.settingsPresets = payload.presets || [];
    state.settingsPresetsError = null;
    renderSettingsPresets();
    clearTransientError({ respectMinimumVisibleDuration: true });
    return payload;
  } catch (error) {
    presetError = error;
    showError(error.message);
    return null;
  } finally {
    setSettingsPresetActionInFlight(false);
    if (presetError) await requestSettingsPresets().catch(() => {});
  }
};

const deleteSettingsPreset = async (presetId) => {
  if (!presetId || state.settingsPresetActionInFlight) return null;
  const preset = state.settingsPresets.find((item) => item.id === presetId);
  const name = preset?.name || "이 프리셋";
  if (window.confirm?.(`${name}을 삭제할까요?`) === false) return null;
  let presetError = null;
  setSettingsPresetActionInFlight(true);
  try {
    const payload = await api(`/api/settings/presets/${encodeURIComponent(presetId)}`, {
      method: "DELETE",
    });
    state.settingsPresets = payload.presets || [];
    state.settingsPresetsError = null;
    renderSettingsPresets();
    clearTransientError({ respectMinimumVisibleDuration: true });
    return payload;
  } catch (error) {
    presetError = error;
    showError(error.message);
    return null;
  } finally {
    setSettingsPresetActionInFlight(false);
    if (presetError) await requestSettingsPresets().catch(() => {});
  }
};

const loadSettingsPreset = async (presetId) => {
  if (!presetId || state.settingsPresetActionInFlight) return null;
  const blockedReason = settingsPresetLoadBlockedReason();
  if (blockedReason) {
    showError(blockedReason);
    renderSettingsPresets();
    return null;
  }
  let presetError = null;
  setSettingsPresetActionInFlight(true);
  try {
    const payload = await api(`/api/settings/presets/${encodeURIComponent(presetId)}/load`, {
      method: "POST",
    });
    await applySettingsPresetPayload(payload, { syncDraft: true });
    clearTransientError({ respectMinimumVisibleDuration: true });
    return payload;
  } catch (error) {
    presetError = error;
    await requestState({ syncDraft: false }).catch(() => {});
    showError(error.message);
    return null;
  } finally {
    setSettingsPresetActionInFlight(false);
    if (presetError) await requestSettingsPresets().catch(() => {});
  }
};

const deriveDashboardControlStateForRequest = (currentState = state) =>
  deriveDashboardControlState({
    snapshot: currentState.snapshot,
    ...operationFlagsFrom(currentState),
  });

const controlDisabledByDashboardState = (path, currentState = state) => {
  const controlState = deriveDashboardControlStateForRequest(currentState);
  if (path === "/api/input/arm") return controlState.captureGateSwitchDisabled;
  if (path === "/api/input/disarm" && !currentState.snapshot?.is_recording) {
    return controlState.captureGateSwitchDisabled;
  }
  if (path === "/api/recording/start") return controlState.startDisabled;
  if (path === "/api/playback/start") return controlState.startOutputDisabled;
  if (path === "/api/playback/stop") return controlState.stopOutputDisabled;
  if (path === "/api/playback/restart") return controlState.restartOutputDisabled;
  return false;
};

const deriveControlRequestState = (path, options = {}, currentState = state) => {
  const snapshot = currentState.snapshot;
  const startsStartRequest = path === "/api/recording/start";
  const backgroundPlaybackRequest = path === "/api/playback/live-graph-eq/tick";
  const playbackControlRequest = path.startsWith("/api/playback/") && !backgroundPlaybackRequest;
  const allowStaleRecordingStop = options.allowStaleRecordingStop === true;
  const expectsRecordingOutcome =
    path === "/api/recording/stop" ||
    path === "/api/recording/poll-auto-stop" ||
    (path === "/api/input/disarm" && Boolean(snapshot?.is_recording));
  const pollAutoStopRequest =
    path === "/api/recording/poll-auto-stop" &&
    Boolean(snapshot?.is_recording);
  const startsStopRequest =
    ((path === "/api/recording/stop" || path === "/api/input/disarm") &&
      (Boolean(snapshot?.is_recording) ||
        (path === "/api/recording/stop" && allowStaleRecordingStop))) ||
    pollAutoStopRequest;
  const skip =
    controlDisabledByDashboardState(path, currentState) ||
    (startsStartRequest && currentState.recordingStartInFlight) ||
    (path === "/api/recording/stop" && !snapshot?.is_recording && !allowStaleRecordingStop) ||
    (path === "/api/input/disarm" && !snapshot?.is_recording && !snapshot?.armed) ||
    (path === "/api/recording/poll-auto-stop" && currentState.recordingStopInFlight) ||
    (startsStopRequest && currentState.recordingStopInFlight) ||
    (playbackControlRequest && currentState.playbackControlInFlight);
  return {
    startsStartRequest,
    playbackControlRequest,
    allowStaleRecordingStop,
    expectsRecordingOutcome,
    pollAutoStopRequest,
    startsStopRequest,
    skip,
  };
};

const control = async (path, options = {}) => {
  let controlError = null;
  const liveGraphEqTickRequest = path === "/api/playback/live-graph-eq/tick"
    ? clone(state.snapshot?.playback?.live_graph_eq || null)
    : null;
  const controlRequest = deriveControlRequestState(path, options);
  if (controlRequest.skip) return;
  const {
    startsStartRequest,
    playbackControlRequest,
    expectsRecordingOutcome,
    startsStopRequest,
  } = controlRequest;
  if (startsStartRequest) {
    state.recordingStartInFlight = true;
    renderState();
  }
  if (startsStopRequest) {
    setOperationLockFlag("recordingStopInFlight", true);
  }
  if (playbackControlRequest) {
    setOperationLockFlag("playbackControlInFlight", true);
  }
  if (expectsRecordingOutcome && path !== "/api/recording/poll-auto-stop") {
    setRecordStatus("processing", "녹음 처리 중...");
  }
  try {
    const payload = await api(path, { method: "POST" });
    await applyResponseState(payload, options);
    if (payload.outcome !== undefined) {
      renderRecordingOutcome(payload.outcome);
    } else if (path === "/api/recording/start") {
      setRecordStatus("recording", "녹음 중", "스페이스바를 떼면 중지됩니다.");
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
      await requestSources();
    }
  } catch (error) {
    if (path === "/api/recording/stop" && isStaleRecordingStopError(error)) {
      state.spaceRecording = false;
      state.recordingStopRequestedAfterStart = false;
      await requestState({ syncDraft: false }).catch(() => {});
      await requestDiagnostics().catch(() => {});
      await requestSources().catch(() => {});
      return;
    }
    controlError = error;
    if (path.startsWith("/api/recording/") || path === "/api/input/disarm") {
      setRecordStatus("failed", "녹음 실패", translateUiErrorMessage(error.message));
      await requestState({ syncDraft: false }).catch(() => {});
      await requestDiagnostics().catch(() => {});
    }
    if (path.startsWith("/api/playback/")) {
      await requestState({ syncDraft: false }).catch(() => {});
      if (path === "/api/playback/live-graph-eq/tick") {
        markLiveGraphEqTickTransportFailure(error, liveGraphEqTickRequest);
      }
    }
  } finally {
    if (startsStopRequest) {
      setOperationLockFlag("recordingStopInFlight", false);
    }
    if (playbackControlRequest) {
      setOperationLockFlag("playbackControlInFlight", false);
    }
    if (startsStartRequest) {
      state.recordingStartInFlight = false;
      state.recordingStopRequestedAfterStart = false;
      renderState();
    }
    if (controlError) showError(controlError.message);
  }
};

const seekPlayback = async (event) => {
  const slider = event.target;
  if (slider.disabled) return;
  const durationSeconds = Number(slider.max || 0);
  const positionSeconds = Number(slider.value || 0);
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) return;
  if (!Number.isFinite(positionSeconds)) return;
  const progress = Math.max(0, Math.min(1, positionSeconds / durationSeconds));
  const requestId = state.playbackSeekRequestId + 1;
  state.playbackSeekRequestId = requestId;
  renderPlaybackTimelinePosition({ positionSeconds, durationSeconds, progress });
  try {
    const payload = await api("/api/playback/seek", {
      method: "POST",
      body: JSON.stringify({ progress }),
    });
    if (requestId !== state.playbackSeekRequestId) return;
    await applyResponseState(payload, { syncDraft: false });
  } catch (error) {
    if (requestId !== state.playbackSeekRequestId) return;
    await requestState({ syncDraft: false }).catch(() => {});
    showError(error.message);
  }
};

const playbackSeekPositionFromPointer = (slider, event) => {
  const durationSeconds = Number(slider.max || 0);
  const rect = slider.getBoundingClientRect?.();
  const clientX = Number(event.clientX);
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) return null;
  if (!rect || !Number.isFinite(rect.width) || rect.width <= 0) return null;
  if (!Number.isFinite(clientX)) return null;
  const progress = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  return progress * durationSeconds;
};

const seekPlaybackFromPointer = (event) => {
  const slider = $("playbackSeekSlider");
  if (slider.disabled) return;
  const positionSeconds = playbackSeekPositionFromPointer(slider, event);
  if (positionSeconds === null) return;
  slider.value = String(positionSeconds);
  seekPlayback({ target: slider });
};

const startPlaybackSeekDrag = (event) => {
  const slider = $("playbackSeekSlider");
  if (slider.disabled) return;
  trackInteractiveControl(slider);
  state.playbackSeekPointerId = event.pointerId ?? null;
  if (event.pointerId !== undefined) {
    slider.setPointerCapture?.(event.pointerId);
  }
  event.preventDefault?.();
  seekPlaybackFromPointer(event);
};

const updatePlaybackSeekDrag = (event) => {
  if (state.playbackSeekPointerId === null) return;
  if (event.pointerId !== state.playbackSeekPointerId) return;
  event.preventDefault?.();
  seekPlaybackFromPointer(event);
};

const finishPlaybackSeekDrag = (event) => {
  if (state.playbackSeekPointerId === null) return;
  if (event.pointerId !== state.playbackSeekPointerId) return;
  const slider = $("playbackSeekSlider");
  slider.releasePointerCapture?.(state.playbackSeekPointerId);
  state.playbackSeekPointerId = null;
  releaseInteractiveControl(slider);
};

const applyAndRestart = async () => {
  if (currentSettingsActionState().applyDisabled) return;
  let applyError = null;
  state.stableApplyCoveredFeedbackSurfaceIds = [];
  state.stableApplyCoveredFeedbackControlSnapshots = [];
  setOperationLockFlag("applyAndRestartInFlight", true);
  setOperationLockFlag("applyInFlight", true);
  try {
    clearDraftSaveTimer();
    await saveDraft();
    state.stableApplyCoveredFeedbackSurfaceIds = captureStableCoveredFeedbackSurfaceDiffs();
    state.stableApplyCoveredFeedbackControlSnapshots =
      captureStableCoveredFeedbackControlSnapshots();
    const payload = await api("/api/settings/apply", { method: "POST" });
    await applyResponseState(payload, { confirmActiveAsDraft: true });
    await requestDiagnostics();
    await requestSources({ syncAppliedSourceSignature: true });
  } catch (error) {
    applyError = error;
    await requestState({ syncDraft: false }).catch(() => {});
    clearStableRestartRollbackFeedbackState({ refresh: true });
    await requestDiagnostics().catch(() => {});
    await requestSources().catch(() => {});
  } finally {
    setOperationLockFlag("applyInFlight", false);
    setOperationLockFlag("applyAndRestartInFlight", false);
    if (applyError) showSettingsApplyFailureCaution(applyError.message);
    else clearTransientError({ respectMinimumVisibleDuration: true });
    if (applyError && state.snapshot) {
      state.serverStateSignature = serverStateSignature(state.snapshot, { syncDraft: false });
    }
    state.stableApplyCoveredFeedbackSurfaceIds = [];
    state.stableApplyCoveredFeedbackControlSnapshots = [];
  }
};

const resetDraft = async () => {
  if (currentSettingsActionState().resetDisabled) return;
  if (!window.confirm("저장하지 않은 설정 변경을 취소할까요?")) return;
  let resetError = null;
  setOperationLockFlag("resetDraftInFlight", true);
  invalidatePendingDraftSaves();
  invalidatePendingStorageModeChanges();
  try {
    const payload = await api("/api/settings/reset-draft", { method: "POST" });
    if (serverPayloadRevisionIsOlder(payload)) return;
    rememberServerPayloadRevision(payload);
    applySettingsPayload(payload.settings, { renderControlsOnSync: false });
    await requestDiagnostics();
    await requestSources();
  } catch (error) {
    resetError = error;
    await requestState({ syncDraft: false }).catch(() => {});
  } finally {
    setOperationLockFlag("resetDraftInFlight", false);
    if (resetError) showError(resetError.message);
    else clearTransientError({ respectMinimumVisibleDuration: true });
  }
};

const resetParticipants = async () => {
  if (
    !state.snapshot ||
    currentDashboardControlState().controlState.resetParticipantsDisabled
  ) {
    return;
  }
  if (!window.confirm("참여자 수를 0으로 초기화할까요? 목소리 스택과 녹음 파일은 삭제되지 않습니다.")) return;
  let resetError = null;
  setOperationLockFlag("resetParticipantsInFlight", true);
  try {
    const payload = await api("/api/participants/reset", { method: "POST" });
    await applyResponseState(payload, { syncDraft: false });
    await requestDiagnostics();
    await requestSources();
  } catch (error) {
    resetError = error;
    await requestState({ syncDraft: false }).catch(() => {});
  } finally {
    setOperationLockFlag("resetParticipantsInFlight", false);
    if (resetError) showError(resetError.message);
    else clearTransientError({ respectMinimumVisibleDuration: true });
  }
};

const toggleCaptureGate = () => {
  const snapshot = state.snapshot;
  if (!snapshot || state.recordingStopInFlight || snapshot.is_recording) return;
  control(snapshot.armed ? "/api/input/disarm" : "/api/input/arm");
};

const changeDevice = async (key, value) => {
  if (currentDeviceChangeState(key).disabled) return;
  const requestId = beginDeviceChange();
  try {
    const payload = await api("/api/devices", {
      method: "PUT",
      body: JSON.stringify({ [key]: value || null }),
    });
    if (!isCurrentDeviceChange(requestId)) return payload;
    const applied = await applyResponseState(
      payload,
      { syncDraft: false, mergeDraftSections: ["devices"] },
    );
    if (!applied) return payload;
    state.devices = payload.devices;
    renderDevices();
    await requestDiagnostics();
    return payload;
  } catch (error) {
    if (!isCurrentDeviceChange(requestId)) return null;
    await requestState({ syncDraft: false }).catch(() => {});
    await requestDevices({ allowDuringDeviceChange: true }).catch(() => {});
    showError(error.message);
    return null;
  } finally {
    finishDeviceChange(requestId);
  }
};

const changeDeviceFromEvent = (key, event) => {
  const selectedValue = event.target.value;
  releaseInteractiveControl(event.target);
  return changeDevice(key, selectedValue);
};

const shouldIgnoreSpace = () => {
  const element = document.activeElement;
  if (!element) return false;
  return interactiveControlTags.has(element.tagName);
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
  if (deriveControlRequestState("/api/recording/start").skip) return;
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
  const allowStaleRecordingStop = state.spaceRecording && state.recordingStartInFlight;
  state.spaceRecording = false;
  if (!state.recordingStartInFlight && !state.snapshot?.is_recording) {
    return;
  }
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

const stateSocketErrorMessage = (payload) => {
  const error = payload?.error;
  if (!error) return "";
  if (typeof error === "string") return error;
  return error.message || error.detail || error.code || "state websocket error";
};

const isStateSocketStatePayload = (payload) => (
  Boolean(
    payload &&
      typeof payload === "object" &&
      !Array.isArray(payload) &&
      payload.settings?.active &&
      payload.settings?.draft &&
      payload.playback &&
      typeof payload.playback === "object" &&
      !Array.isArray(payload.playback),
  )
);

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
  socket.addEventListener("message", async (event) => {
    try {
      const payload = JSON.parse(event.data);
      const errorMessage = stateSocketErrorMessage(payload);
      if (errorMessage) {
        showError(errorMessage);
        return;
      }
      if (!isStateSocketStatePayload(payload)) {
        return;
      }
      const shouldRefreshSources = activeSourcePathsChanged(state.snapshot, payload);
      const applied = applyState(payload, { syncDraft: false });
      if (applied && shouldRefreshSources) {
        await requestSources({ syncAppliedSourceSignature: true });
      }
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
  $("captureGateSwitch").addEventListener("click", toggleCaptureGate);
  $("startButton").addEventListener("click", () => control("/api/recording/start"));
  $("stopButton").addEventListener("click", () => control("/api/recording/stop"));
  $("startOutputButton").addEventListener("click", () => control("/api/playback/start"));
  $("stopOutputButton").addEventListener("click", () => control("/api/playback/stop"));
  $("restartOutputButton").addEventListener("click", () => control("/api/playback/restart"));
  $("playbackSeekSlider").addEventListener("pointerdown", startPlaybackSeekDrag);
  $("playbackSeekSlider").addEventListener("pointermove", updatePlaybackSeekDrag);
  $("playbackSeekSlider").addEventListener("pointerup", finishPlaybackSeekDrag);
  $("playbackSeekSlider").addEventListener("pointercancel", finishPlaybackSeekDrag);
  $("playbackSeekSlider").addEventListener("focus", () => trackInteractiveControl($("playbackSeekSlider")));
  $("playbackSeekSlider").addEventListener("blur", () => releaseInteractiveControl($("playbackSeekSlider")));
  $("playbackSeekSlider").addEventListener("input", seekPlayback);
  $("playbackSeekSlider").addEventListener("change", seekPlayback);
  $("refreshButton").addEventListener("click", refreshAll);
  $("applyButton").addEventListener("click", applyAndRestart);
  $("settingsPresetSaveButton").addEventListener("click", saveSettingsPreset);
  $("settingsPresetNameInput").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    saveSettingsPreset();
  });
  $("settingsPresetList").addEventListener("click", (event) => {
    const loadButton = event.target.closest("[data-settings-preset-load]");
    if (loadButton) {
      if (loadButton.disabled) return;
      loadSettingsPreset(loadButton.dataset.settingsPresetLoad);
      return;
    }
    const updateButton = event.target.closest("[data-settings-preset-update]");
    if (updateButton) {
      if (updateButton.disabled) return;
      updateSettingsPreset(updateButton.dataset.settingsPresetUpdate);
      return;
    }
    const deleteButton = event.target.closest("[data-settings-preset-delete]");
    if (deleteButton) {
      if (deleteButton.disabled) return;
      deleteSettingsPreset(deleteButton.dataset.settingsPresetDelete);
    }
  });
  $("resetButton").addEventListener("click", resetDraft);
  $("resetParticipantsButton").addEventListener("click", resetParticipants);
  document.querySelectorAll("#recordingPresets .preset-button").forEach((button) => {
    button.addEventListener("click", () => applyRecordingPreset(button.dataset.preset));
  });
  workspaceTabs().forEach((button) => {
    button.addEventListener("click", () => setWorkspaceTab(button.dataset.workspaceTab));
    button.addEventListener("keydown", (event) => {
      const tabs = workspaceTabs();
      const index = tabs.indexOf(button);
      const direction = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (direction === 0 || index < 0) return;
      event.preventDefault();
      const next = tabs[(index + direction + tabs.length) % tabs.length];
      next.focus();
      setWorkspaceTab(next.dataset.workspaceTab);
    });
  });
  sideTabs().forEach((button) => {
    button.addEventListener("click", () => setSideTab(button.dataset.sideTab));
    button.addEventListener("keydown", (event) => {
      const tabs = sideTabs();
      const index = tabs.indexOf(button);
      const direction = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (direction === 0 || index < 0) return;
      event.preventDefault();
      const next = tabs[(index + direction + tabs.length) % tabs.length];
      next.focus();
      setSideTab(next.dataset.sideTab);
    });
  });
  renderSideTabs();
  document.querySelectorAll("[data-storage-mode]").forEach((button) => {
    button.addEventListener("click", () => setStorageMode(button.dataset.storageMode));
  });
  document.querySelectorAll("[data-playback-apply-mode]").forEach((button) => {
    button.addEventListener("click", () => setPlaybackApplyMode(button.dataset.playbackApplyMode));
  });
  document.addEventListener("pointerdown", trackSettingsInteractiveControl);
  document.addEventListener("focusin", trackSettingsInteractiveControl);
  document.addEventListener("focusout", releaseSettingsInteractiveControl);
  for (const select of [$("inputDeviceSelect"), $("outputDeviceSelect")]) {
    select.addEventListener("pointerdown", () => trackInteractiveControl(select));
    select.addEventListener("focus", () => trackInteractiveControl(select));
    select.addEventListener("blur", () => releaseInteractiveControl(select));
  }
  $("inputDeviceSelect").addEventListener("change", (event) => {
    changeDeviceFromEvent("input_device_id", event);
  });
  $("outputDeviceSelect").addEventListener("change", (event) => {
    changeDeviceFromEvent("output_device_id", event);
  });
  $("sourceLibraryList").addEventListener("pointerdown", (event) => {
    const control = sourceInteractiveControlFromEventTarget(event.target);
    if (control) trackInteractiveControl(control);
  });
  $("sourceLibraryList").addEventListener("pointerup", (event) => {
    selectSourceFileFromEventTarget(event.target);
  });
  $("sourceLibraryList").addEventListener("focusin", (event) => {
    const control = sourceInteractiveControlFromEventTarget(event.target);
    if (control) trackInteractiveControl(control);
  });
  $("sourceLibraryList").addEventListener("focusout", (event) => {
    const control = sourceInteractiveControlFromEventTarget(event.target);
    const nextControl = sourceInteractiveControlFromEventTarget(event.relatedTarget);
    transferOrReleaseInteractiveControl(control, nextControl);
  });
  $("sourceLibraryList").addEventListener("change", (event) => {
    const fileInput = event.target.closest("[data-source-file]");
    if (fileInput) {
      if (rememberSourceUploadFileFromInput(fileInput)) {
        releaseInteractiveControl(fileInput);
        uploadSourceFile(fileInput.dataset.sourceFile);
      }
      return;
    }
    const renameInput = event.target.closest("[data-source-rename-input]");
    if (renameInput) {
      rememberSourceRenameDraft(
        renameInput.dataset.sourceRenameInput,
        renameInput.dataset.sourcePath,
        renameInput.value,
      );
      return;
    }
  });
  $("sourceLibraryList").addEventListener("input", (event) => {
    const renameInput = event.target.closest("[data-source-rename-input]");
    if (!renameInput) return;
    rememberSourceRenameDraft(
      renameInput.dataset.sourceRenameInput,
      renameInput.dataset.sourcePath,
      renameInput.value,
    );
  });
  $("sourceLibraryList").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const fileControl = sourceFileControlFromEventTarget(event.target);
    if (!fileControl) return;
    event.preventDefault();
    selectSourceFileFromCard(fileControl.dataset.sourcePick, fileControl.dataset.sourcePath);
  });
  $("sourceLibraryList").addEventListener("dragover", (event) => {
    const dropZone = sourceDropZoneFromEventTarget(event.target);
    if (!dropZone) return;
    if (sourceCommandBlocked()) {
      blockSourceFileDrop(event, dropZone);
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    dropZone.classList.add("is-dragging");
  });
  $("sourceLibraryList").addEventListener("dragleave", (event) => {
    const dropZone = sourceDropZoneFromEventTarget(event.target);
    if (!dropZone || dropZone.contains(event.relatedTarget)) return;
    dropZone.classList.remove("is-dragging");
  });
  $("sourceLibraryList").addEventListener("drop", (event) => {
    const dropZone = sourceDropZoneFromEventTarget(event.target);
    if (!dropZone) return;
    handleSourceFileDrop(event, dropZone.dataset.sourceDrop);
  });
  $("sourceLibraryList").addEventListener("click", (event) => {
    const renameButton = event.target.closest("[data-source-rename]");
    if (renameButton) {
      if (renameButton.disabled) return;
      const category = renameButton.dataset.sourceRename;
      const file = state.sources?.categories
        ?.flatMap((item) => item.files || [])
        .find((item) => item.path === renameButton.dataset.sourcePath);
      if (file) startSourceRename(category, file);
      return;
    }
    const renameSaveButton = event.target.closest("[data-source-rename-save]");
    if (renameSaveButton) {
      if (renameSaveButton.disabled) return;
      const category = renameSaveButton.dataset.sourceRenameSave;
      const path = renameSaveButton.dataset.sourcePath;
      const stem = state.sourceRenameDrafts[sourceRenameKey(category, path)] || "";
      renameSourceFile(category, path, stem);
      return;
    }
    const renameCancelButton = event.target.closest("[data-source-rename-cancel]");
    if (renameCancelButton) {
      cancelSourceRename(
        renameCancelButton.dataset.sourceRenameCancel,
        renameCancelButton.dataset.sourcePath,
      );
      return;
    }
    const confirmSelectionButton = event.target.closest("[data-source-confirm-selection]");
    if (confirmSelectionButton) {
      if (confirmSelectionButton.disabled) return;
      confirmSelectedSourceCard(confirmSelectionButton.dataset.sourceConfirmSelection);
      return;
    }
    const cancelButton = event.target.closest("[data-source-cancel]");
    if (cancelButton) {
      cancelSelectedSourceCard(cancelButton.dataset.sourceCancel);
      return;
    }
    const previewButton = event.target.closest("[data-voice-raw-preview-selected]");
    if (previewButton) {
      if (previewButton.disabled) return;
      previewVoiceRaw(previewButton.dataset.voiceRawPreviewSelected);
      return;
    }
    const addButton = event.target.closest("[data-voice-raw-add-selected]");
    if (addButton) {
      if (addButton.disabled) return;
      addVoiceRawToStack(addButton.dataset.voiceRawAddSelected);
      return;
    }
    const deleteButton = event.target.closest("[data-source-delete]");
    if (deleteButton) {
      if (deleteButton.disabled) return;
      deleteSourceFile(deleteButton.dataset.sourceDelete, deleteButton.dataset.sourcePath);
      return;
    }
    const fileControl = sourceFileControlFromEventTarget(event.target);
    if (fileControl) selectSourceFileFromEventTarget(event.target);
  });
  document.addEventListener("keydown", startFromSpace);
  document.addEventListener("keyup", stopFromSpace);
  window.addEventListener("blur", stopIfRecording);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopIfRecording();
  });
  window.addEventListener("popstate", () => {
    setWorkspaceTab(workspaceTabFromUrl(), { syncUrl: false });
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
renderWorkspaceTabs();
drawCanvas();
connectStateSocket();
refreshAll();
