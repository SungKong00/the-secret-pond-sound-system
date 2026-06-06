const responseErrorMessage = (payload, status) => {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object") {
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
  transientErrorShownAt: 0,
  deviceError: null,
  diagnosticsError: null,
  sourcesError: null,
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
  confirmedDraftSignature: null,
  sourceMutationRequestId: 0,
  storageModeRequestId: 0,
  stateRefreshRequestId: 0,
  sourceRefreshRequestId: 0,
  diagnosticsRefreshRequestId: 0,
  deviceChangeRequestId: 0,
  deviceRefreshRequestId: 0,
  spaceRecording: false,
  stateSocket: null,
  websocketConnected: false,
  websocketReconnectTimer: null,
  recordingStartInFlight: false,
  recordingStopRequestedAfterStart: false,
  recordingStopInFlight: false,
  playbackControlInFlight: false,
  playbackApplyModeInFlight: false,
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
  expandedControlGroups: {},
  workspaceTab: workspaceTabFromUrl(),
  sideTab: "library",
  deferredInteractiveRenders: {},
};

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
        rangeLabel: "below cut",
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
        rangeLabel: "above cut",
        description: "이 값보다 높은 소리를 줄입니다.",
      },
    ],
  },
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
        rangeLabel: "rumble cut",
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
        rangeLabel: "air cut",
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
    title: "입력 안정화",
    note: "녹음 소스의 기본 크기와 피크를 정리합니다.",
    className: "input-safety-group",
    collapsible: true,
    open: true,
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
    path: "transition_seconds",
    label: { ko: "전환 시간", en: "Transition" },
    min: 1,
    max: 10,
    step: 1,
    suffix: " s",
    kind: "space",
    rangeLabel: "1s · 3s default · 10s",
    defaultValue: 3,
    description: "새 목소리 스택으로 넘어갈 때 겹쳐 전환되는 시간입니다.",
    marks: [
      { value: 1, label: "1s" },
      { value: 3, label: "3s" },
      { value: 10, label: "10s" },
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
  state.transientError = notice?.technical || null;
  state.transientErrorShownAt = notice ? Date.now() : 0;
  renderNoticeBanner(notice ? [notice] : []);
};

const showSettingsApplyFailureCaution = (message = "") => {
  state.transientError = null;
  state.transientErrorShownAt = 0;
  renderNoticeBanner([
    uiNotice(
      message,
      settingsApplyFailureCautionMessage,
      settingsApplyFailureCautionDetail,
      "caution",
    ),
  ]);
};

const transientErrorVisibleLongEnough = () => (
  !state.transientError ||
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
  return {
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
  state.snapshot.settings = nextSettings;
  state.draft = mergeSettingsPayloadDraft(state.draft, nextSettings, {
    syncDraft: shouldSyncDraft,
    mergeDraftSections,
  });
  if (shouldSyncDraft) {
    rememberConfirmedSettingsDraft(nextSettings);
    if (renderControlsOnSync) renderControls();
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
  if (serverPayloadRevisionIsOlder(normalizedPayload)) {
    return false;
  }
  rememberServerPayloadRevision(normalizedPayload);
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
  applySettingsPayload(normalizedPayload.settings, {
    currentSnapshot,
    syncDraft,
    mergeDraftSections,
    renderControlsOnSync,
  });
  state.serverStateSignature = serverStateSignature(state.snapshot, { syncDraft });
  renderState();
  renderSystemPanel();
  clearVoiceRawSelectionAfterPreviewStop(currentSnapshot, state.snapshot);
  return true;
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
} = {}) => {
  const title = firstOperationLockTitle([
    [applyInFlight, operationLockMessages.draftApply],
    [resetDraftInFlight, operationLockMessages.draftReset],
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
  devicesLoaded = true,
  forceDeviceDisabled = false,
} = {}) => {
  const sourceActionTitle = firstOperationLockTitle([
    [applyInFlight, operationLockMessages.sourceApply],
    [resetDraftInFlight, operationLockMessages.sourceReset],
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
  });
  return {
    draftLocked: draftLock.disabled,
    sourceUiLocked: Boolean(sourceActionTitle),
    sourceCommandBlocked: Boolean(sourceActionTitle),
    sourceActionTitle,
    deviceLocked: Boolean(
      forceDeviceDisabled || deviceChangeInFlight || applyInFlight || resetDraftInFlight ||
        sourceMutationInFlight ||
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

const commitDraftChange = (mutator, options = {}) => {
  if (!state.draft || draftEditLocked()) return false;
  mutator?.();
  markDraftEdited();
  const feedbackSurfaceId = draftFeedbackSurfaceIdFromOptions(options);
  if (feedbackSurfaceId !== undefined) {
    state.pendingCoveredFeedbackSurfaceId = feedbackSurfaceId;
    state.pendingLiveFeedbackSurfaceId = feedbackSurfaceId;
  } else {
    state.pendingCoveredFeedbackSurfaceId = undefined;
    state.pendingLiveFeedbackSurfaceId = undefined;
  }
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
  pendingChanges = false,
  runtimeConfigChanged = false,
}) => {
  const recordingStopBusy = Boolean(recordingStopInFlight);
  const resetBusy = Boolean(resetDraftInFlight);
  const sourceMutationBusy = Boolean(sourceMutationInFlight);
  const deviceChangeBusy = Boolean(deviceChangeInFlight);
  const playbackControlBusy = Boolean(playbackControlInFlight);
  const resetParticipantsBusy = Boolean(resetParticipantsInFlight);
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
  pendingChanges = false,
  runtimeConfigChanged = false,
}) => {
  const recordingStartBusy = Boolean(recordingStartInFlight);
  const recordingStopBusy = Boolean(recordingStopInFlight);
  const playbackControlBusy = Boolean(playbackControlInFlight);
  const deviceChangeBusy = Boolean(deviceChangeInFlight);
  const resetParticipantsBusy = Boolean(resetParticipantsInFlight);
  const settingsOperationBusy = Boolean(
    applyInFlight ||
      resetDraftInFlight ||
      sourceMutationInFlight ||
      deviceChangeBusy ||
      resetParticipantsBusy,
  );
  const captureOperationBusy = recordingStartBusy || recordingStopBusy || settingsOperationBusy;
  const outputControlBusy = Boolean(
    applyInFlight ||
      recordingStopBusy ||
      playbackControlBusy ||
      deviceChangeBusy ||
      resetParticipantsBusy,
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
    pendingChanges,
    runtimeConfigChanged,
  });
  const resetParticipantsTitle = resetParticipantsBusy
    ? operationLockMessages.resetParticipants
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
      sourceMutationInFlight || deviceChangeBusy || recordingStopBusy || playbackControlBusy ||
      isRecording,
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
  const live = livePlaybackFeatures(snapshot);
  if (!live.enabled || !live.voice_stack_transition_applies_immediately) return false;
  const activeVoiceStack = clone(snapshot.settings.active.voice_stack || {});
  const draftVoiceStack = clone(state.draft.voice_stack || {});
  draftVoiceStack.transition_seconds = activeVoiceStack.transition_seconds;
  return stableSettingsSignature(activeVoiceStack) === stableSettingsSignature(draftVoiceStack);
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
  if (targetSurfaceId === undefined) return false;
  return targetSurfaceId !== null && targetSurfaceId === normalizeFeedbackSurfaceId(surfaceId);
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

const liveApplicableVoiceStackSurfaceChange = (snapshot, active, draft) => {
  const live = livePlaybackFeatures(snapshot);
  if (!live.enabled || !live.voice_stack_transition_applies_immediately) return false;
  const activeVoiceStack = clone(active?.voice_stack || {});
  const draftVoiceStack = clone(draft?.voice_stack || {});
  draftVoiceStack.transition_seconds = activeVoiceStack.transition_seconds;
  return stableSettingsSignature(activeVoiceStack) === stableSettingsSignature(draftVoiceStack);
};

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

const renderPlaybackTimeline = (snapshot = state.snapshot) => {
  if (
    deferPlaybackTimelineRender() ||
    deferInteractiveRender("playback-timeline", $("playbackTimeline"), renderPlaybackTimeline)
  ) {
    return;
  }
  const playback = snapshot?.playback || {};
  const positionSeconds = Number(playback.position_seconds || 0);
  const durationSeconds = Number(playback.duration_seconds || 0);
  const progress = Math.max(0, Math.min(1, Number(playback.progress || 0)));
  const progressPercent = (progress * 100).toFixed(3).replace(/\.?0+$/, "");
  const progressBar = $("playbackProgressBar");
  const seekSlider = $("playbackSeekSlider");
  const seekEnabled = Boolean(
    playback.output_running &&
      playback.apply_mode === "live" &&
      playback.live?.seek_applies_immediately &&
      durationSeconds > 0,
  );
  $("playbackPositionTime").textContent = formatSeconds(positionSeconds);
  $("playbackDurationTime").textContent = formatSeconds(durationSeconds);
  if (progressBar.style) {
    progressBar.style.width = `${progressPercent}%`;
  } else {
    progressBar.setAttribute("style", `width: ${progressPercent}%`);
  }
  seekSlider.max = String(durationSeconds);
  seekSlider.disabled = !seekEnabled || state.playbackControlInFlight;
  seekSlider.title = seekEnabled
    ? "Live 모드에서는 재생 위치가 즉시 이동합니다."
    : "Live 재생 중에 사용할 수 있습니다.";
  if (!playbackSeekSliderActive()) {
    seekSlider.value = String(positionSeconds);
  }
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
      return "Live 전환 · 새 녹음은 준비되면 목소리 레이어만 부드럽게 전환됩니다.";
    }
    return "Stable fallback · 변경사항 적용 후 렌더링된 캐시로 재생합니다.";
  }
  return "준비된 오디오를 렌더링한 뒤 출력을 시작합니다.";
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
} = {}) => {
  const locks = deriveOperationLocks({
    applyInFlight,
    resetDraftInFlight,
    sourceMutationInFlight,
    deviceChangeInFlight,
    recordingStopInFlight,
    playbackControlInFlight,
    resetParticipantsInFlight,
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
  playbackControlInFlight = false,
  resetParticipantsInFlight = false,
} = {}) => {
  const modeDetails = storageModeDetails[mode];
  const ready = Boolean(snapshot && draft && modeDetails);
  const activeMode = snapshot?.settings?.active?.voice_stack?.mode;
  const draftMode = draft?.voice_stack?.mode;
  const active = draftMode === mode;
  const pending = Boolean(activeMode && draftMode && activeMode !== draftMode);
  const sourceMutationBusy = Boolean(sourceMutationInFlight);
  const deviceChangeBusy = Boolean(deviceChangeInFlight);
  const playbackControlBusy = Boolean(playbackControlInFlight);
  const resetParticipantsBusy = Boolean(resetParticipantsInFlight);
  const disabled =
    !ready ||
    applyInFlight ||
    resetDraftInFlight ||
    sourceMutationBusy ||
    deviceChangeBusy ||
    recordingStopInFlight ||
    playbackControlBusy ||
    resetParticipantsBusy ||
    Boolean(snapshot?.is_recording);
  return {
    active,
    ariaPressed: active ? "true" : "false",
    pendingActive: pending && active,
    disabled,
    title: disabled
      ? resetDraftInFlight
        ? "설정 작업이 끝날 때까지 보관 모드를 바꿀 수 없습니다."
        : sourceMutationBusy
          ? operationLockMessages.sourceMutation
          : deviceChangeBusy
            ? operationLockMessages.deviceChange
            : playbackControlBusy
              ? operationLockMessages.playbackControl
              : resetParticipantsBusy
                ? operationLockMessages.resetParticipants
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

const rememberConfirmedSettingsDraft = (settingsPayload) => {
  if (!settingsPayload?.draft) return;
  state.confirmedDraftSignature = stableSettingsSignature(settingsPayload.draft);
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
  renderLayerControls();
  renderVoiceStackControls();
  renderRecordingPresets();
  renderRecordingControls();
};

const renderOperationLockSurfaces = () => {
  renderState();
  renderControls();
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
  renderOperationLockSurfaces();
};

const renderLayerControls = () => {
  renderLayerGroup("layerControls", ["mid", "low"]);
  renderLayerGroup("voiceLayerControls", ["voice"]);
};

const currentPlaybackApplyMode = (snapshot = state.snapshot) => {
  const settingsMode = snapshot?.settings?.active?.playback?.apply_mode;
  if (playbackApplyModeDetails[settingsMode]) return settingsMode;
  const playbackMode = snapshot?.playback?.apply_mode;
  if (playbackApplyModeDetails[playbackMode]) return playbackMode;
  return "stable";
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

const coveredLayerFeedbackControlPaths = [
  "enabled",
  "volume_db",
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

const coveredFeedbackStateUsesPendingVisual = (feedbackState) => (
  feedbackState?.visual_state === "pending" ||
    feedbackState?.visual_state === "restart_pending"
);

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
  const hasUnappliedChange = feedbackSurfaceHasDraftChange(activeSettings, draft, surfaceId);
  const applyMode = currentPlaybackApplyMode(snapshot);
  if (applyMode === "stable") {
    const applyInFlight = stableApplyAndRestartInFlight(operationFlags);
    return {
      visual_state: hasUnappliedChange
        ? (applyInFlight ? "restart_pending" : "pending")
        : "idle",
      show_spinner: false,
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
  const liveFeedbackInFlight = feedbackOperationInFlight(operationFlags, surfaceId);
  return {
    visual_state: liveApplicableChange && liveFeedbackInFlight ? "pending" : "idle",
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
  container.className = `${baseClassName}${
    coveredFeedbackStateUsesPendingVisual(feedbackState) ? " feedback-pending" : ""
  }`;
  container.innerHTML = `
    <span class="feedback-spinner" aria-hidden="true" ${feedbackState.show_spinner ? "" : "hidden"}></span>
  `;
  return feedbackState;
};

const renderPlaybackApplyModeControls = () => {
  const panel = $("playbackApplyModePanel");
  if (!panel) return;
  const mode = currentPlaybackApplyMode();
  const details = playbackApplyModeDetails[mode] || playbackApplyModeDetails.stable;
  const disabled = !state.snapshot || state.playbackApplyModeInFlight;
  panel.setAttribute("aria-label", "재생 적용 모드");
  panel.className = `playback-apply-mode-panel compact ${details.className}${
    state.playbackApplyModeInFlight ? " pending" : ""
  }`;
  $("playbackApplyModeSummary").textContent = `${details.label} · ${details.summary}`;
  Object.entries(playbackApplyModeDetails).forEach(([buttonMode, buttonDetails]) => {
    const button = $(buttonDetails.buttonId);
    if (!button) return;
    const active = mode === buttonMode;
    button.disabled = disabled;
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.classList.toggle("active", active);
    button.classList.toggle("pending", state.playbackApplyModeInFlight && active);
    button.title = disabled && state.playbackApplyModeInFlight
      ? "재생 적용 모드 변경 중입니다."
      : "";
  });
};

const setPlaybackApplyMode = async (mode) => {
  if (!playbackApplyModeDetails[mode] || state.playbackApplyModeInFlight) return null;
  if (currentPlaybackApplyMode() === mode) {
    renderPlaybackApplyModeControls();
    return null;
  }
  let modeError = null;
  state.playbackApplyModeInFlight = true;
  renderControls();
  try {
    const payload = await api("/api/playback/apply-mode", {
      method: "PUT",
      body: JSON.stringify({ mode }),
    });
    await applyResponseState(payload, { syncDraft: false });
    return payload;
  } catch (error) {
    modeError = error;
    await requestState({ syncDraft: false }).catch(() => {});
    return null;
  } finally {
    state.playbackApplyModeInFlight = false;
    renderControls();
    if (modeError) showError(modeError.message);
    else clearTransientError({ respectMinimumVisibleDuration: true });
  }
};

const renderVoiceStackControls = () => {
  const container = $("voiceStackControls");
  renderCoveredFeedbackContainer(
    container,
    "control-stack compact voice-stack-controls feedback-surface",
    "voice_stack",
  );
  renderStorageModeControls();
  const activeVoiceStack = state.snapshot?.settings.active.voice_stack || state.draft.voice_stack;
  voiceStackControlDefs.forEach((control) => {
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
  });
};

const renderStorageModeControls = () => {
  if (!state.snapshot || !state.draft) return;
  if (deferInteractiveRender("storage-mode", $("storageModePanel"), renderStorageModeControls)) {
    return;
  }
  const activeMode = state.snapshot.settings?.active?.voice_stack?.mode;
  const draftMode = state.draft.voice_stack?.mode;
  if (!activeMode || !draftMode) return;
  const activeDetails = storageModeDetails[activeMode] || storageModeDetails.live_ephemeral;
  const draftDetails = storageModeDetails[draftMode] || activeDetails;
  const pending = activeMode !== draftMode;
  $("storageModeSummary").textContent = pending
    ? `${activeDetails.label} · 적용 중: ${draftDetails.optionLabel}`
    : `${activeDetails.label} · ${activeDetails.summary}`;
  $("storageModePanel").className = `storage-mode-panel ${draftDetails.className}${
    pending ? " pending" : ""
  }`;
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
  state.draft.voice_stack.mode = mode;
  markDraftEdited();
  syncDraftSnapshot();
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
      setOperationLockFlag("applyInFlight", false);
      if (modeError) showSettingsApplyFailureCaution(modeError.message);
      else clearTransientError({ respectMinimumVisibleDuration: true });
    }
  }
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
    ${layerId === "voice" ? "" : layerPresetMarkup(layerId)}
    <div class="layer-controls"></div>
  `;
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
  layerControlGroups.forEach((group) => {
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
  if (!current || !layerPresetDefs[presetName]) return;
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
    { feedbackSurfaceId: `layer:${layerId}`, afterSync: renderLayerControls },
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
    { feedbackSurfaceId: `layer:${layerId}`, afterSync: renderLayerControls },
  );
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
  if (!recordingPresetDefs[name] || !state.draft) return;
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
      afterSync: () => {
        renderRecordingPresets();
        renderRecordingControls();
      },
    },
  );
};

const workspaceTabs = () => Array.from(document.querySelectorAll("[data-workspace-tab]"));

const renderWorkspaceTabs = () => {
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
  let currentValue = value;
  [input, valueInput, nudgeDown, nudgeUp].filter(Boolean).forEach((controlElement) => {
    controlElement.disabled = draftEditLocked();
  });
  const setDisplayedValue = (nextValue) => {
    input.value = String(nextValue);
    if (valueInput) valueInput.value = String(nextValue);
    setRangeProgress(row, nextValue, min, max);
    output.innerHTML = renderDraftValue(nextValue, activeValue, control.suffix);
  };
  const updateValue = (nextValue) => {
    if (draftEditLocked()) {
      setDisplayedValue(currentValue);
      return;
    }
    const numericValue = snappedValue(nextValue, control.step, min, max);
    currentValue = numericValue;
    setDisplayedValue(numericValue);
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

const clearDraftSaveTimer = () => {
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
};

const invalidatePendingDraftSaves = () => {
  clearDraftSaveTimer();
  state.draftSaveRequestId += 1;
  state.pendingCoveredFeedbackSurfaceId = undefined;
  state.coveredFeedbackSurfaceId = undefined;
  state.pendingLiveFeedbackSurfaceId = undefined;
  state.liveFeedbackSurfaceId = undefined;
  state.draftSaveInFlight = false;
};

const beginDraftSave = () => {
  const requestId = state.draftSaveRequestId + 1;
  state.draftSaveRequestId = requestId;
  return { requestId, draftEditRevision: state.draftEditRevision };
};

const isCurrentDraftSave = (request) =>
  request.requestId === state.draftSaveRequestId &&
  request.draftEditRevision === state.draftEditRevision;

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
    applySettingsPayload(payload.settings, { renderControlsOnSync: false });
    renderState();
    renderDevices();
    return payload;
  } catch (error) {
    if (isCurrentDraftSave(request)) {
      showSettingsApplyFailureCaution(error.message);
      throw error;
    }
    return null;
  } finally {
    if (isCurrentDraftSave(request)) {
      state.draftSaveInFlight = false;
      state.pendingCoveredFeedbackSurfaceId = undefined;
      state.coveredFeedbackSurfaceId = undefined;
      state.pendingLiveFeedbackSurfaceId = undefined;
      state.liveFeedbackSurfaceId = undefined;
      renderDraftSaveFeedbackSurfaces();
    }
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
  const playbackControlRequest = path.startsWith("/api/playback/");
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
  setOperationLockFlag("playbackControlInFlight", true);
  try {
    const payload = await api("/api/playback/seek", {
      method: "POST",
      body: JSON.stringify({ progress }),
    });
    await applyResponseState(payload, { syncDraft: false });
  } catch (error) {
    await requestState({ syncDraft: false }).catch(() => {});
    showError(error.message);
  } finally {
    setOperationLockFlag("playbackControlInFlight", false);
  }
};

const applyAndRestart = async () => {
  if (currentSettingsActionState().applyDisabled) return;
  let applyError = null;
  setOperationLockFlag("applyAndRestartInFlight", true);
  setOperationLockFlag("applyInFlight", true);
  try {
    clearDraftSaveTimer();
    await saveDraft();
    const payload = await api("/api/settings/apply", { method: "POST" });
    await applyResponseState(payload);
    await requestDiagnostics();
    await requestSources({ syncAppliedSourceSignature: true });
  } catch (error) {
    applyError = error;
    await requestState({ syncDraft: false }).catch(() => {});
    await requestDiagnostics().catch(() => {});
    await requestSources().catch(() => {});
  } finally {
    setOperationLockFlag("applyInFlight", false);
    setOperationLockFlag("applyAndRestartInFlight", false);
    if (applyError) showSettingsApplyFailureCaution(applyError.message);
    else clearTransientError({ respectMinimumVisibleDuration: true });
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
  $("playbackSeekSlider").addEventListener("pointerdown", () => trackInteractiveControl($("playbackSeekSlider")));
  $("playbackSeekSlider").addEventListener("focus", () => trackInteractiveControl($("playbackSeekSlider")));
  $("playbackSeekSlider").addEventListener("blur", () => releaseInteractiveControl($("playbackSeekSlider")));
  $("playbackSeekSlider").addEventListener("change", seekPlayback);
  $("refreshButton").addEventListener("click", refreshAll);
  $("applyButton").addEventListener("click", applyAndRestart);
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
