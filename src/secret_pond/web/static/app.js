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
  deviceError: null,
  diagnosticsError: null,
  sourcesError: null,
  appliedSourceSignature: null,
  serverStateSignature: null,
  sourceUploads: {},
  sourceMutationInFlight: false,
  saveTimer: null,
  draftSaveRequestId: 0,
  draftEditRevision: 0,
  sourceMutationRequestId: 0,
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
  applyInFlight: false,
  resetDraftInFlight: false,
  resetParticipantsInFlight: false,
  deviceChangeInFlight: false,
  activeInteractiveControl: null,
  renderSignatures: {
    deviceSelects: {},
    sourceLibrary: null,
  },
  presetSelections: {
    layers: {},
    recording: null,
  },
  workspaceTab: workspaceTabFromUrl(),
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

const openNoticeDetailKeys = new Set();

const normalizeNoticeSeverity = (severity = "error") => {
  if (severity === "warning") return "caution";
  return noticeSeverityDisplay[severity] ? severity : "error";
};

const highestNoticeSeverity = (notices) => notices.reduce((highest, notice) => (
  noticeSeverityRank[notice.severity] > noticeSeverityRank[highest] ? notice.severity : highest
), "info");

const genericNoticeDetail = "문제가 반복되면 최근 이벤트와 시스템 진단을 확인하세요.";

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
  return date.toLocaleString("ko-KR", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
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
const interactiveControlTags = new Set(["SELECT", "INPUT", "TEXTAREA"]);

const activeInteractiveControlFor = (container) => {
  const tracked = state.activeInteractiveControl;
  if (!tracked || !container) return null;
  return tracked === container || container.contains?.(tracked) ? tracked : null;
};

const deferInteractiveRender = (key, container, renderFn) => {
  const active = activeInteractiveControlFor(container);
  if (!active) return false;
  state.deferredInteractiveRenders[key] = renderFn;
  if (!deferredInteractiveRenderTargets.has(active)) {
    deferredInteractiveRenderTargets.add(active);
    active.addEventListener("blur", () => {
      deferredInteractiveRenderTargets.delete(active);
      if (state.activeInteractiveControl === active) {
        state.activeInteractiveControl = null;
      }
      const deferred = state.deferredInteractiveRenders[key];
      delete state.deferredInteractiveRenders[key];
      deferred?.();
    }, { once: true });
  }
  return true;
};

const trackInteractiveControl = (element) => {
  state.activeInteractiveControl = element;
};

const releaseInteractiveControl = (element) => {
  if (state.activeInteractiveControl === element) {
    state.activeInteractiveControl = null;
  }
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
  if (detailElements) return Array.from(detailElements);
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

const appendNoticeContent = (container, notice) => {
  container.append(
    noticeHeadingElement(notice),
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
  const activeNotices = notices.filter(Boolean);
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
    appendNoticeContent(banner, activeNotices[0]);
    return;
  }

  const groupNotice = uiNotice(
    "",
    `${display.label} ${activeNotices.length}개`,
    "아래 항목을 하나씩 확인하세요.",
    severity,
  );
  banner.append(noticeHeadingElement(groupNotice), noticeDetailElement(groupNotice));
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
  renderNoticeBanner(notice ? [notice] : []);
};

const clearTransientError = () => {
  state.transientError = null;
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
    applyState(payload.state, options);
    return true;
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

const serverStateSignature = (payload) => JSON.stringify(payload);

const refreshAll = async () => {
  let stateRefreshFailed = false;
  await requestState({ syncDraft: false }).catch((error) => {
    stateRefreshFailed = true;
    showError(error.message);
  });
  await requestDevices();
  await requestDiagnostics();
  await requestSources({ syncAppliedSourceSignature: true });
  if (!stateRefreshFailed) clearTransientError();
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
    if (renderControlsOnSync) renderControls();
  } else {
    syncDraftSnapshot();
  }
  return true;
};

const applyState = (payload, options = {}) => {
  const syncDraft = options.syncDraft ?? true;
  const mergeDraftSections = options.mergeDraftSections || [];
  if (!options.fromStateRefresh) {
    invalidatePendingStateRefreshes();
  }
  const nextServerStateSignature = serverStateSignature(payload);
  const serverStateChanged = state.serverStateSignature !== nextServerStateSignature;
  if (!serverStateChanged && !syncDraft && state.snapshot) {
    return false;
  }
  const currentSnapshot = state.snapshot;
  state.serverStateSignature = nextServerStateSignature;
  state.snapshot = payload;
  applySettingsPayload(payload.settings, { currentSnapshot, syncDraft, mergeDraftSections });
  renderState();
  renderSystemStatus();
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
  playbackControl: "출력 제어가 끝날 때까지 기다리세요.",
  resetParticipants: "참여자 초기화가 끝날 때까지 기다리세요.",
  deviceLoading: "장치 목록을 불러오는 중입니다.",
  deviceApply: "설정 적용이 끝날 때까지 기다리세요.",
  deviceChange: "장치 변경을 적용하는 중입니다.",
  deviceRecording: "녹음 중에는 입력 장치를 바꿀 수 없습니다.",
};

const deriveDraftControlLockState = ({
  applyInFlight = false,
  resetDraftInFlight = false,
} = {}) => {
  const title = applyInFlight
    ? operationLockMessages.draftApply
    : resetDraftInFlight
      ? operationLockMessages.draftReset
      : "";
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
  devicesLoaded = true,
  forceDeviceDisabled = false,
} = {}) => {
  const sourceActionTitle = applyInFlight
    ? operationLockMessages.sourceApply
    : resetDraftInFlight
      ? operationLockMessages.sourceReset
    : sourceMutationInFlight
      ? operationLockMessages.sourceMutation
      : "";
  const deviceTitle = !devicesLoaded
    ? operationLockMessages.deviceLoading
    : applyInFlight
      ? operationLockMessages.deviceApply
      : deviceChangeInFlight
        ? operationLockMessages.deviceChange
        : forceDeviceDisabled
          ? operationLockMessages.deviceRecording
          : "";
  const draftLock = deriveDraftControlLockState({ applyInFlight, resetDraftInFlight });
  return {
    draftLocked: draftLock.disabled,
    sourceUiLocked: Boolean(sourceActionTitle),
    sourceCommandBlocked: Boolean(sourceActionTitle),
    sourceActionTitle,
    deviceLocked: Boolean(
      forceDeviceDisabled || deviceChangeInFlight || applyInFlight || !devicesLoaded,
    ),
    deviceTitle,
  };
};

const draftEditLocked = (stateLike = state) => deriveDraftControlLockState(stateLike).disabled;

const draftEditLockTitle = (stateLike = state) => deriveDraftControlLockState(stateLike).title;

const markDraftEdited = () => {
  state.draftEditRevision += 1;
};

const commitDraftChange = (mutator, options = {}) => {
  if (!state.draft || draftEditLocked()) return false;
  mutator?.();
  markDraftEdited();
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
  recordingStopInFlight = false,
  playbackControlInFlight = false,
  pendingChanges = false,
  runtimeConfigChanged = false,
}) => {
  const recordingStopBusy = Boolean(recordingStopInFlight);
  const resetBusy = Boolean(resetDraftInFlight);
  const sourceMutationBusy = Boolean(sourceMutationInFlight);
  const playbackControlBusy = Boolean(playbackControlInFlight);
  const isRecording = Boolean(snapshot?.is_recording);
  const outputRunning = Boolean(snapshot?.playback?.output_running);
  const applyTitle = recordingStopBusy
    ? "녹음 처리가 끝날 때까지 기다리세요."
    : resetBusy
      ? "설정 변경 취소가 끝날 때까지 기다리세요."
      : isRecording
        ? "준비된 설정을 적용하기 전에 녹음을 중지하세요."
        : applyInFlight
          ? "준비된 오디오 설정을 렌더링하고 다시 불러오는 중입니다."
          : sourceMutationBusy
            ? operationLockMessages.sourceMutation
            : playbackControlBusy
              ? operationLockMessages.playbackControl
              : runtimeConfigChanged
                ? "샘플레이트, 채널 변경은 앱 재시작이 필요하고 장치 변경은 System 패널에서 적용해야 합니다."
                : !pendingChanges
                  ? "적용할 변경사항이 없습니다."
                  : outputRunning
                    ? "준비된 오디오 설정을 적용하는 동안 출력을 멈췄다가 다시 시작합니다."
                    : "";
  const resetTitle = resetBusy
    ? "설정 변경 취소가 끝날 때까지 기다리세요."
    : recordingStopBusy
      ? "녹음 처리가 끝날 때까지 기다리세요."
      : applyInFlight
        ? "설정 적용이 끝날 때까지 기다리세요."
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
      playbackControlBusy ||
      recordingStopBusy ||
      isRecording ||
      !pendingChanges,
  );
  return {
    applyDisabled: Boolean(
      applyInFlight ||
        resetBusy ||
        sourceMutationBusy ||
        playbackControlBusy ||
        recordingStopBusy ||
        isRecording ||
        runtimeConfigChanged ||
        !pendingChanges,
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
  recordingStopInFlight = false,
  playbackControlInFlight = false,
  resetParticipantsInFlight = false,
  pendingChanges = false,
  runtimeConfigChanged = false,
}) => {
  const recordingStopBusy = Boolean(recordingStopInFlight);
  const playbackControlBusy = Boolean(playbackControlInFlight);
  const resetParticipantsBusy = Boolean(resetParticipantsInFlight);
  const outputControlBusy = Boolean(applyInFlight || recordingStopBusy || playbackControlBusy);
  const isRecording = Boolean(snapshot?.is_recording);
  const armed = Boolean(snapshot?.armed);
  const outputRunning = Boolean(snapshot?.playback?.output_running);
  const captureGateClass = recordingStopBusy
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
    recordingStopInFlight,
    playbackControlInFlight,
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
          : "";
  return {
    recordingStopBusy,
    outputControlBusy,
    captureReady: armed && !isRecording && !recordingStopBusy,
    captureGateOn: armed || isRecording,
    captureGateClass,
    captureGateSwitchDisabled: recordingStopBusy || isRecording,
    startDisabled: recordingStopBusy || !armed || isRecording,
    stopDisabled: recordingStopBusy || !isRecording,
    startOutputDisabled: outputControlBusy || outputRunning,
    stopOutputDisabled: outputControlBusy || !outputRunning,
    restartOutputDisabled: outputControlBusy || !outputRunning,
    ...settingsActionState,
    resetParticipantsDisabled: resetParticipantsBusy || applyInFlight || recordingStopBusy ||
      isRecording,
    resetParticipantsTitle,
  };
};

const derivePendingChangeState = (settingsPlan, sourceFilesChanged = false) => {
  const runtimeConfigChanged = Boolean(settingsPlan?.runtimeConfigChanged);
  const settingsChanged = Boolean(settingsPlan?.changedSections?.length || runtimeConfigChanged);
  return {
    settingsChanged,
    sourceFilesChanged: Boolean(sourceFilesChanged),
    pendingChanges: settingsChanged || Boolean(sourceFilesChanged),
    runtimeConfigChanged,
  };
};

const currentDashboardControlState = (snapshot = state.snapshot) => {
  const pendingChangeState = derivePendingChangeState(
    settingsChangePlan(snapshot),
    hasSourceFileChanges(snapshot),
  );
  return {
    pendingChangeState,
    controlState: deriveDashboardControlState({
      snapshot,
      applyInFlight: state.applyInFlight,
      resetDraftInFlight: state.resetDraftInFlight,
      sourceMutationInFlight: state.sourceMutationInFlight,
      recordingStopInFlight: state.recordingStopInFlight,
      playbackControlInFlight: state.playbackControlInFlight,
      resetParticipantsInFlight: state.resetParticipantsInFlight,
      pendingChanges: pendingChangeState.pendingChanges,
      runtimeConfigChanged: pendingChangeState.runtimeConfigChanged,
    }),
  };
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
  renderStorageModeControls();
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
  $("recordCoreStatus").textContent = controlState.recordingStopBusy
    ? "처리 중"
    : snapshot.is_recording
      ? "녹음 중"
      : snapshot.armed
        ? "준비 완료"
        : "준비 전";
  document.querySelector(".record-core").classList.toggle("armed", controlState.captureReady);
  document.querySelector(".record-core").classList.toggle("recording", snapshot.is_recording);
  renderRecordReadiness(snapshot, controlState.recordingStopBusy);
  $("pendingBadge").hidden = !pendingChangeState.pendingChanges;
  $("pendingBadge").textContent = pendingChangeState.pendingChanges ? "저장 안 된 오디오 변경" : "";
  $("pendingBadge").className = "status-pill hot";
  $("outputControlSummary").textContent = state.applyInFlight
    ? "준비된 오디오 설정을 렌더링하는 중입니다."
    : snapshot.playback.output_running
      ? "출력 스트림이 실행 중입니다."
      : pendingChangeState.pendingChanges
        ? "저장 안 된 오디오 변경이 적용 후 재시작을 기다립니다."
        : "준비된 오디오를 렌더링한 뒤 출력을 시작합니다.";
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
      ? "녹음 준비 켜짐"
      : "녹음 준비 꺼짐";
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
    setRecordStatus("ready", "녹음 준비 필요", "녹음 준비를 켠 뒤 스페이스바를 누르세요.");
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
  return (state.devices?.warnings || [])
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
  const devices = state.devices;
  const activeDevices = state.snapshot?.settings.active.devices || {};
  if (!devices) {
    renderSystemDeviceSelect("inputDeviceSelect", [], null, true);
    renderSystemDeviceSelect("outputDeviceSelect", [], null, true);
    renderDeviceWarnings([]);
    return;
  }
  renderSystemDeviceSelect(
    "inputDeviceSelect",
    devices.input_devices || [],
    activeDevices.input_device_id ?? null,
    Boolean(state.snapshot?.is_recording),
  );
  renderSystemDeviceSelect(
    "outputDeviceSelect",
    devices.output_devices || [],
    activeDevices.output_device_id ?? null,
  );
  renderDeviceWarnings(devices.warnings || []);
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
    const value = document.createElement("strong");
    value.textContent = source.exists
      ? `준비됨 · ${formatBytes(source.size_bytes)} · ${formatTimestamp(source.modified_at)}`
      : `없음 · ${source.path}`;
    row.append(label, value);
    container.appendChild(row);
  });
};

const renderSourceLibrary = () => {
  const container = $("sourceLibraryList");
  if (!container) return;
  syncSourceLibraryBusyControls(container);
  if (deferInteractiveRender("source-library", container, renderSourceLibrary)) return;
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

  const categories = state.sources.categories || [];
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

const sourceLibrarySignature = (categories) => JSON.stringify([
  state.sourceMutationInFlight,
  state.applyInFlight,
  state.resetDraftInFlight,
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

const sourceCategoryRequired = (category) => category?.required !== false;

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
    state.sourceUploads[category] = { selectAfterUpload: true, file: null };
  }
  return state.sourceUploads[category];
};

const sourceUploadSignature = (category) => {
  const upload = sourceUploadState(category);
  const file = upload.file;
  return [
    upload.selectAfterUpload,
    file ? [file.name, file.size, file.lastModified] : null,
  ];
};

const sourceActionBusyTitle = ({
  sourceMutationInFlight = false,
  applyInFlight = false,
  resetDraftInFlight = false,
} = {}) => deriveOperationLocks({
  sourceMutationInFlight,
  applyInFlight,
  resetDraftInFlight,
}).sourceActionTitle;

const currentSourceLockState = () => deriveOperationLocks({
  sourceMutationInFlight: state.sourceMutationInFlight,
  applyInFlight: state.applyInFlight,
  resetDraftInFlight: state.resetDraftInFlight,
});

const sourceCommandBlocked = () =>
  currentSourceLockState().sourceCommandBlocked;

const sourceLibraryBusyControlSelector = [
  "[data-source-select]",
  "[data-source-file]",
  "[data-source-upload-select]",
  "[data-source-upload]",
  "[data-source-delete]",
].join(", ");
const sourceLibraryBusyControlState = new WeakMap();

const syncSourceLibraryBusyControls = (container) => {
  if (typeof container.querySelectorAll !== "function") return;
  const controls = container.querySelectorAll(sourceLibraryBusyControlSelector);
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
    control.disabled = true;
    control.title = busyTitle;
  });
};

const deriveSourceUploadActionState = (
  upload = {},
  sourceMutationInFlight = false,
  applyInFlight = false,
  resetDraftInFlight = false,
) => {
  const file = upload.file || null;
  const hasFile = Boolean(file);
  const busyTitle = sourceActionBusyTitle({
    sourceMutationInFlight,
    applyInFlight,
    resetDraftInFlight,
  });
  const busy = Boolean(busyTitle);
  return {
    selectAfterUpload: upload.selectAfterUpload !== false,
    hasFile,
    hint: hasFile
      ? `${file.name} · ${formatBytes(file.size || 0)} 선택됨`
      : "WAV 파일을 이 폴더로 복사합니다.",
    uploadDisabled: busy || !hasFile,
    uploadTitle: busy
      ? busyTitle
      : hasFile ? "" : "추가할 WAV 파일을 먼저 선택하세요.",
  };
};

const deriveSourceFileActionState = (
  file = {},
  sourceMutationInFlight = false,
  applyInFlight = false,
  resetDraftInFlight = false,
) => {
  const active = Boolean(file.active);
  const applied = Boolean(file.applied);
  const busyTitle = sourceActionBusyTitle({
    sourceMutationInFlight,
    applyInFlight,
    resetDraftInFlight,
  });
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

const rememberSourceUploadFile = (category, file) => {
  sourceUploadState(category).file = file || null;
};

const clearSourceUploadFile = (category) => {
  rememberSourceUploadFile(category, null);
};

const rememberSourceUploadMode = (category, selectAfterUpload) => {
  sourceUploadState(category).selectAfterUpload = selectAfterUpload;
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
  const required = sourceCategoryRequired(category);
  const statusClass = category.active_exists ? "safe" : required ? "hot" : "muted";
  const statusText = category.active_exists ? "선택됨" : required ? "없음" : "보관용";
  const uploadAction = deriveSourceUploadActionState(
    upload,
    state.sourceMutationInFlight,
    state.applyInFlight,
    state.resetDraftInFlight,
  );
  const uploadChecked = uploadAction.selectAfterUpload ? " checked" : "";
  const uploadDisabled = uploadAction.uploadDisabled ? " disabled" : "";
  const uploadTitle = uploadAction.uploadTitle
    ? ` title="${escapeHtml(uploadAction.uploadTitle)}"`
    : "";
  const card = document.createElement("section");
  card.className = "source-category-card";
  const options = [
    `<option value="">${category.legacy_exists ? "기존 파일 사용" : "선택 안 함"}</option>`,
    ...(category.files || []).map((file) => {
      const selected = category.selected_path === file.path ? " selected" : "";
      return `<option value="${escapeHtml(file.path)}"${selected}>${escapeHtml(file.name)}</option>`;
    }),
  ].join("");
  card.innerHTML = `
    <div class="source-category-head">
      <div>
        <h3>${escapeHtml(label.title)}</h3>
        <p>${escapeHtml(label.helper)}</p>
      </div>
      <span class="status-pill ${statusClass}">
        ${statusText}
      </span>
    </div>
    <label class="source-select-row">
      <span>사용 파일</span>
      <select
        class="source-file-select"
        data-source-select="${escapeHtml(category.id)}"
        ${sourceActionDisabled}
        ${sourceActionTitle}
      >${options}</select>
    </label>
    <div class="source-file-list">
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
      <button
        class="button"
        type="button"
        data-source-upload="${escapeHtml(category.id)}"
        ${uploadDisabled}
        ${uploadTitle}
      >추가</button>
      <label class="source-upload-select">
        <input type="checkbox" data-source-upload-select="${escapeHtml(category.id)}"${uploadChecked}${sourceActionDisabled}${sourceActionTitle} />
        <span>업로드 후 바로 선택</span>
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
    const action = deriveSourceFileActionState(
      file,
      state.sourceMutationInFlight,
      state.applyInFlight,
      state.resetDraftInFlight,
    );
    const badges = [
      action.active ? `<span class="source-file-badge">선택됨</span>` : "",
      file.applied ? `<span class="source-file-badge">적용됨</span>` : "",
    ].join("");
    const disabled = action.deleteDisabled ? " disabled" : "";
    const deleteTitle = action.deleteTitle
      ? ` title="${escapeHtml(action.deleteTitle)}"`
      : "";
    return `
      <div class="source-file-row">
        <div>
          <strong>${escapeHtml(file.name)}</strong>
          <small>${formatBytes(file.size_bytes)} · ${formatTimestamp(file.modified_at)}</small>
        </div>
        ${badges}
        <button
          class="mini-button danger"
          type="button"
          data-source-delete="${escapeHtml(category.id)}"
          data-source-path="${escapeHtml(file.path)}"
          ${deleteTitle}
          ${disabled}
        >삭제</button>
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

const beginSourceMutation = () => {
  const requestId = nextSourceMutationRequestId();
  state.sourceMutationInFlight = true;
  renderSourceLibrary();
  return requestId;
};

const finishSourceMutation = (requestId) => {
  if (!isCurrentSourceMutation(requestId)) return;
  state.sourceMutationInFlight = false;
  renderSourceLibrary();
};

const applySourceMutationPayload = (payload, options = {}) => {
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
  renderSourceLibrary();
};

const recoverSourceMutationError = async (error) => {
  showError(error.message);
  await requestSources().catch(() => {});
};

const selectSourceFile = async (category, path) => {
  if (sourceCommandBlocked()) return null;
  const requestId = beginSourceMutation();
  try {
    const payload = await api(`/api/sources/${encodeURIComponent(category)}/select`, {
      method: "PUT",
      body: JSON.stringify({ path: path || null }),
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

const selectedSourceUploadMode = (category) => {
  const checkbox = document.querySelector(`[data-source-upload-select="${category}"]`);
  if (typeof checkbox?.checked === "boolean") {
    rememberSourceUploadMode(category, checkbox.checked);
  }
  return sourceUploadState(category).selectAfterUpload;
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
    select: String(selectedSourceUploadMode(category)),
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
  event.preventDefault();
  const dropZone = event.target.closest("[data-source-drop]");
  dropZone?.classList.remove("is-dragging");
  const file = event.dataTransfer?.files?.[0];
  if (!file) {
    showError("추가할 WAV 파일을 선택하세요.");
    return;
  }
  rememberSourceUploadFile(category, file);
  uploadSourceFile(category, file);
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

const deriveSystemDeviceSelectState = ({
  forceDisabled = false,
  devicesLoaded = false,
  deviceChangeInFlight = false,
  applyInFlight = false,
} = {}) => {
  const locks = deriveOperationLocks({
    applyInFlight,
    deviceChangeInFlight,
    devicesLoaded,
    forceDeviceDisabled: forceDisabled,
  });
  return { disabled: locks.deviceLocked, title: locks.deviceTitle };
};

const deriveStorageModeControlState = ({
  snapshot = null,
  draft = null,
  mode = null,
  applyInFlight = false,
  resetDraftInFlight = false,
  recordingStopInFlight = false,
} = {}) => {
  const modeDetails = storageModeDetails[mode];
  const ready = Boolean(snapshot && draft && modeDetails);
  const activeMode = snapshot?.settings?.active?.voice_stack?.mode;
  const draftMode = draft?.voice_stack?.mode;
  const active = draftMode === mode;
  const pending = Boolean(activeMode && draftMode && activeMode !== draftMode);
  const disabled =
    !ready ||
    applyInFlight ||
    resetDraftInFlight ||
    recordingStopInFlight ||
    Boolean(snapshot?.is_recording);
  return {
    active,
    ariaPressed: active ? "true" : "false",
    pendingActive: pending && active,
    disabled,
    title: disabled
      ? resetDraftInFlight
        ? "설정 작업이 끝날 때까지 보관 모드를 바꿀 수 없습니다."
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
    deviceChangeInFlight: state.deviceChangeInFlight,
    applyInFlight: state.applyInFlight,
  });
  if (deferInteractiveRender(`device-${selectId}`, select, renderDevices)) {
    select.disabled = selectState.disabled;
    select.title = selectState.title;
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
    device.host_api_name,
    channelCount ? `${channelCount}ch` : null,
    `${device.default_sample_rate || "알 수 없음"} Hz`,
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
  return {
    runtimeConfigChanged: Boolean(change?.runtime_config_changed),
    changedRuntimeFields: Array.isArray(change?.changed_runtime_fields)
      ? change.changed_runtime_fields
      : [],
    changedSections: Array.isArray(change?.changed_sections) ? change.changed_sections : [],
    runtimeConfigFields,
  };
};

const settingsPayloadMatchesDraft = (snapshot, draft) => (
  stableSettingsSignature(snapshot.settings.draft) === stableSettingsSignature(draft)
);

const shouldSyncIncomingSettingsDraft = (currentSnapshot, currentDraft, options = {}) => {
  const syncDraft = options.syncDraft ?? true;
  if (syncDraft || !currentDraft) return true;
  if (!currentSnapshot?.settings?.draft) return false;
  return settingsPayloadMatchesDraft(currentSnapshot, currentDraft);
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
  return localSettingsChangePlan(snapshot.settings.active, draft, runtimeConfigFields);
};

const localSettingsChangePlan = (active, draft, runtimeConfigFields = defaultRuntimeConfigFields) => {
  const normalizedRuntimeConfigFields = normalizeRuntimeConfigFields(runtimeConfigFields);
  const changedRuntimeFields = normalizedRuntimeConfigFields
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
    changedSections,
    runtimeConfigFields: normalizedRuntimeConfigFields,
  };
};

const toServerSettingsChangePayload = (change) => {
  const normalizedChange = change || normalizeSettingsChangePlan(null);
  return {
    runtime_config_changed: Boolean(normalizedChange.runtimeConfigChanged),
    changed_runtime_fields: Array.isArray(normalizedChange.changedRuntimeFields)
      ? normalizedChange.changedRuntimeFields
      : [],
    changed_sections: Array.isArray(normalizedChange.changedSections)
      ? normalizedChange.changedSections
      : [],
    runtime_config_fields: normalizeRuntimeConfigFields(normalizedChange.runtimeConfigFields),
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

const hasPendingChanges = (snapshot) => derivePendingChangeState(
  settingsChangePlan(snapshot),
  hasSourceFileChanges(snapshot),
).pendingChanges;

const currentSettingsActionState = (snapshot = state.snapshot) => {
  const pendingChangeState = derivePendingChangeState(
    settingsChangePlan(snapshot),
    hasSourceFileChanges(snapshot),
  );
  return deriveSettingsActionState({
    snapshot,
    applyInFlight: state.applyInFlight,
    resetDraftInFlight: state.resetDraftInFlight,
    sourceMutationInFlight: state.sourceMutationInFlight,
    recordingStopInFlight: state.recordingStopInFlight,
    playbackControlInFlight: state.playbackControlInFlight,
    pendingChanges: pendingChangeState.pendingChanges,
    runtimeConfigChanged: pendingChangeState.runtimeConfigChanged,
  });
};

const hasLayerInclusionDraftChange = (layerId) => {
  if (!state.snapshot || !state.draft) return false;
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
  renderLayerControls();
  renderVoiceStackControls();
  renderRecordingPresets();
  renderRecordingControls();
};

const renderLayerControls = () => {
  renderLayerGroup("layerControls", ["mid", "low"]);
  renderLayerGroup("voiceLayerControls", ["voice"]);
};

const renderVoiceStackControls = () => {
  const container = $("voiceStackControls");
  container.innerHTML = "";
  renderStorageModeControls();
  const activeVoiceStack = state.snapshot?.settings.active.voice_stack || state.draft.voice_stack;
  voiceStackControlDefs.forEach((control) => {
    container.appendChild(
      rangeControl(
        control,
        getPath(state.draft.voice_stack, control.path),
        (value) => {
          commitDraftChange(() => {
            setPath(state.draft.voice_stack, control.path, value);
          });
        },
        getPath(activeVoiceStack, control.path),
      ),
    );
  });
};

const renderStorageModeControls = () => {
  if (!state.snapshot || !state.draft) return;
  const activeMode = state.snapshot.settings.active.voice_stack.mode;
  const draftMode = state.draft.voice_stack.mode;
  const activeDetails = storageModeDetails[activeMode] || storageModeDetails.live_ephemeral;
  const draftDetails = storageModeDetails[draftMode] || activeDetails;
  const pending = activeMode !== draftMode;
  $("storageModeSummary").textContent = pending
    ? `${activeDetails.label} · 재시작 시 적용: ${draftDetails.optionLabel}`
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
      applyInFlight: state.applyInFlight,
      resetDraftInFlight: state.resetDraftInFlight,
      recordingStopInFlight: state.recordingStopInFlight,
    });
    button.disabled = controlState.disabled;
    button.setAttribute("aria-pressed", controlState.ariaPressed);
    button.classList.toggle("active", controlState.active);
    button.classList.toggle("pending", controlState.pendingActive);
    button.title = controlState.title;
  });
};

const setStorageMode = (mode) => {
  const controlState = deriveStorageModeControlState({
    snapshot: state.snapshot,
    draft: state.draft,
    mode,
    applyInFlight: state.applyInFlight,
    resetDraftInFlight: state.resetDraftInFlight,
    recordingStopInFlight: state.recordingStopInFlight,
  });
  if (!controlState.canCommit) return;
  commitDraftChange(() => {
    state.draft.voice_stack.mode = mode;
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
  const draftLock = deriveDraftControlLockState(state);
  const draftLocked = draftLock.disabled;
  const draftLockTitle = draftLock.title;
  const card = document.createElement("section");
  card.className = "layer-card";
  const layerLabel = layerLabels[layerId];
  const pendingEnabled = hasLayerInclusionDraftChange(layerId);
  card.innerHTML = `
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
            { afterSync: () => updateLayerPresetButtons(card, layerId) },
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
    { afterSync: renderLayerControls },
  );
};

const resetLayerFilter = (layerId) => {
  const layer = state.draft?.layers?.[layerId];
  const filterGroup = layerControlGroups.find((group) => group.action === "reset-filter");
  if (!layer || !filterGroup) return;
  commitDraftChange(
    () => {
      filterGroup.controls.forEach((control) => {
        const resetValue = control.path.endsWith("highpass_hz") ? control.min : control.max;
        setPath(layer, control.path, resetValue);
      });
    },
    { afterSync: renderLayerControls },
  );
};

const renderRecordingControls = () => {
  const container = $("recordingControls");
  container.innerHTML = "";
  const activeRecording = state.snapshot?.settings.active.recording || state.draft.recording;
  recordingControlGroups.forEach((group) => {
    container.appendChild(
      controlGroup(group, state.draft.recording, activeRecording, (control, value) => {
        commitDraftChange(
          () => {
            setPath(state.draft.recording, control.path, value);
            clearRecordingPresetSelection();
          },
          { afterSync: renderRecordingPresets },
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

const groupActionsMarkup = (group, draftSource, activeSource = null) => {
  if (group.action !== "reset-filter") return "";
  const status = filterStatus(group, draftSource, activeSource);
  if (!status) return "";
  const draftLock = deriveDraftControlLockState(state);
  const actionDisabled = draftLock.disabled || status.bypassed;
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
        ${actionDisabled ? "disabled" : ""}
        ${draftLock.title ? `title="${escapeHtml(draftLock.title)}"` : ""}
      >
        필터 초기화
      </button>
    </div>
  `;
};

const controlGroup = (group, draftSource, activeSource, onInput, onGroupAction = null) => {
  const section = document.createElement(group.collapsible ? "details" : "section");
  section.className = `control-group ${group.className || ""}`;
  if (group.open) section.open = true;
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
  try {
    const payload = await api("/api/settings/draft", {
      method: "PUT",
      body: JSON.stringify(draftPayload),
    });
    if (!isCurrentDraftSave(request)) return payload;
    applySettingsPayload(payload.settings, { renderControlsOnSync: false });
    renderState();
    renderDevices();
    return payload;
  } catch (error) {
    if (isCurrentDraftSave(request)) {
      showError(error.message);
      throw error;
    }
    return null;
  }
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
  }
  if (startsStopRequest) {
    state.recordingStopInFlight = true;
    renderState();
  }
  if (playbackControlRequest) {
    state.playbackControlInFlight = true;
    renderState();
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
      state.recordingStopInFlight = false;
      renderState();
    }
    if (playbackControlRequest) {
      state.playbackControlInFlight = false;
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
  if (currentSettingsActionState().applyDisabled) return;
  let applyError = null;
  state.applyInFlight = true;
  renderState();
  renderControls();
  renderDevices();
  renderSourceLibrary();
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
    state.applyInFlight = false;
    renderState();
    renderControls();
    renderDevices();
    renderSourceLibrary();
    if (applyError) showError(applyError.message);
  }
};

const resetDraft = async () => {
  if (currentSettingsActionState().resetDisabled) return;
  if (!window.confirm("저장하지 않은 설정 변경을 취소할까요?")) return;
  let resetError = null;
  state.resetDraftInFlight = true;
  invalidatePendingDraftSaves();
  renderState();
  renderControls();
  renderSourceLibrary();
  try {
    const payload = await api("/api/settings/reset-draft", { method: "POST" });
    applySettingsPayload(payload.settings, { renderControlsOnSync: false });
    await requestDiagnostics();
    await requestSources();
  } catch (error) {
    resetError = error;
    await requestState({ syncDraft: false }).catch(() => {});
  } finally {
    state.resetDraftInFlight = false;
    renderState();
    renderControls();
    renderDevices();
    renderSourceLibrary();
    if (resetError) showError(resetError.message);
  }
};

const resetParticipants = async () => {
  if (
    !state.snapshot ||
    currentDashboardControlState().controlState.resetParticipantsDisabled
  ) {
    return;
  }
  if (!window.confirm("참여자 녹음 스택을 초기화할까요? 이 작업은 되돌릴 수 없습니다.")) return;
  let resetError = null;
  state.resetParticipantsInFlight = true;
  renderState();
  try {
    const payload = await api("/api/participants/reset", { method: "POST" });
    await applyResponseState(payload, { syncDraft: false });
    await requestDiagnostics();
    await requestSources();
  } catch (error) {
    resetError = error;
    await requestState({ syncDraft: false }).catch(() => {});
  } finally {
    state.resetParticipantsInFlight = false;
    renderState();
    if (resetError) showError(resetError.message);
  }
};

const toggleCaptureGate = () => {
  const snapshot = state.snapshot;
  if (!snapshot || state.recordingStopInFlight || snapshot.is_recording) return;
  control(snapshot.armed ? "/api/input/disarm" : "/api/input/arm");
};

const changeDevice = async (key, value) => {
  if (state.deviceChangeInFlight || state.applyInFlight) return;
  state.deviceChangeRequestId += 1;
  state.deviceChangeInFlight = true;
  renderDevices();
  try {
    const payload = await api("/api/devices", {
      method: "PUT",
      body: JSON.stringify({ [key]: value || null }),
    });
    await applyResponseState(payload, { syncDraft: false, mergeDraftSections: ["devices"] });
    state.devices = payload.devices;
    renderDevices();
    await requestDiagnostics();
  } catch (error) {
    await requestState({ syncDraft: false }).catch(() => {});
    await requestDevices({ allowDuringDeviceChange: true }).catch(() => {});
    showError(error.message);
  } finally {
    state.deviceChangeInFlight = false;
    renderDevices();
  }
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
      applyState(payload, { syncDraft: false });
      if (shouldRefreshSources) {
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
  document.querySelectorAll("[data-storage-mode]").forEach((button) => {
    button.addEventListener("click", () => setStorageMode(button.dataset.storageMode));
  });
  for (const select of [$("inputDeviceSelect"), $("outputDeviceSelect")]) {
    select.addEventListener("pointerdown", () => trackInteractiveControl(select));
    select.addEventListener("focus", () => trackInteractiveControl(select));
    select.addEventListener("blur", () => releaseInteractiveControl(select));
  }
  $("inputDeviceSelect").addEventListener("change", (event) => {
    releaseInteractiveControl(event.target);
    changeDevice("input_device_id", event.target.value);
  });
  $("outputDeviceSelect").addEventListener("change", (event) => {
    releaseInteractiveControl(event.target);
    changeDevice("output_device_id", event.target.value);
  });
  $("sourceLibraryList").addEventListener("pointerdown", (event) => {
    const select = event.target.closest("[data-source-select]");
    if (select) trackInteractiveControl(select);
  });
  $("sourceLibraryList").addEventListener("focusin", (event) => {
    const select = event.target.closest("[data-source-select]");
    if (select) trackInteractiveControl(select);
  });
  $("sourceLibraryList").addEventListener("focusout", (event) => {
    const select = event.target.closest("[data-source-select]");
    if (select) releaseInteractiveControl(select);
  });
  $("sourceLibraryList").addEventListener("change", (event) => {
    const select = event.target.closest("[data-source-select]");
    if (select) {
      releaseInteractiveControl(select);
      selectSourceFile(select.dataset.sourceSelect, select.value);
      return;
    }
    const fileInput = event.target.closest("[data-source-file]");
    if (fileInput) {
      rememberSourceUploadFile(fileInput.dataset.sourceFile, fileInput.files?.[0] || null);
      renderSourceLibrary();
      return;
    }
    const uploadMode = event.target.closest("[data-source-upload-select]");
    if (uploadMode) {
      rememberSourceUploadMode(uploadMode.dataset.sourceUploadSelect, uploadMode.checked);
      renderSourceLibrary();
    }
  });
  $("sourceLibraryList").addEventListener("dragover", (event) => {
    const dropZone = event.target.closest("[data-source-drop]");
    if (!dropZone) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    dropZone.classList.add("is-dragging");
  });
  $("sourceLibraryList").addEventListener("dragleave", (event) => {
    const dropZone = event.target.closest("[data-source-drop]");
    if (!dropZone || dropZone.contains(event.relatedTarget)) return;
    dropZone.classList.remove("is-dragging");
  });
  $("sourceLibraryList").addEventListener("drop", (event) => {
    const dropZone = event.target.closest("[data-source-drop]");
    if (!dropZone) return;
    handleSourceFileDrop(event, dropZone.dataset.sourceDrop);
  });
  $("sourceLibraryList").addEventListener("click", (event) => {
    const uploadButton = event.target.closest("[data-source-upload]");
    if (uploadButton) {
      if (uploadButton.disabled) return;
      uploadSourceFile(uploadButton.dataset.sourceUpload);
      return;
    }
    const deleteButton = event.target.closest("[data-source-delete]");
    if (deleteButton) {
      if (deleteButton.disabled) return;
      deleteSourceFile(deleteButton.dataset.sourceDelete, deleteButton.dataset.sourcePath);
    }
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
