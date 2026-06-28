(function () {
  "use strict";

  const MIN_SECONDS = 3;
  const MAX_SECONDS = 600;
  const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
  const BITRATE = 128000;

  let mediaRecorder = null;
  let mediaStream = null;
  let chunks = [];
  let recordedBlob = null;
  let startedAt = 0;
  let timerId = null;
  let state = "idle";

  const byId = (id) => document.getElementById(id);

  function getToken() {
    const parts = String(window.location.pathname || "")
      .split("/")
      .filter(Boolean);
    return decodeURIComponent(parts[parts.length - 1] || "");
  }

  function formatElapsed(seconds) {
    const safeSeconds = Math.max(0, Math.floor(seconds));
    const minutes = Math.floor(safeSeconds / 60);
    const remainingSeconds = String(safeSeconds % 60).padStart(2, "0");
    return `${minutes}:${remainingSeconds}`;
  }

  function setStatus(message, tone = "") {
    const status = byId("statusMessage");
    if (!status) return;
    status.textContent = message;
    status.className = tone ? `status ${tone}` : "status";
  }

  function setRecordState(label) {
    const element = byId("recordState");
    if (element) element.textContent = label;
  }

  function setRecordedBlob(blob) {
    recordedBlob = blob;
    state = blob ? "ready" : "idle";
    updateButtons();
  }

  function updateButtons() {
    const startButton = byId("startButton");
    const stopButton = byId("stopButton");
    const rerecordButton = byId("rerecordButton");
    const addButton = byId("addButton");
    const isRecording = state === "recording";
    const isSubmitting = state === "submitting";
    const hasRecording = Boolean(recordedBlob);

    if (startButton) startButton.disabled = isRecording || isSubmitting;
    if (stopButton) stopButton.disabled = !isRecording;
    if (rerecordButton) {
      rerecordButton.hidden = !hasRecording || isSubmitting;
      rerecordButton.disabled = isSubmitting;
    }
    if (addButton) {
      addButton.hidden = !hasRecording;
      addButton.disabled = !hasRecording || isSubmitting;
    }
  }

  function updateElapsedSeconds(elapsedSeconds) {
    const elapsed = Math.max(0, elapsedSeconds);
    const elapsedElement = byId("elapsedTime");
    const stopButton = byId("stopButton");

    if (elapsedElement) elapsedElement.textContent = formatElapsed(elapsed);
    if (stopButton) stopButton.disabled = elapsed < MIN_SECONDS;
    if (state === "recording" && elapsed >= MAX_SECONDS) {
      stopRecording();
    }
  }

  function clearTimer() {
    if (timerId !== null) {
      clearInterval(timerId);
      timerId = null;
    }
  }

  function stopStream() {
    if (!mediaStream) return;
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }

  function chooseMimeType() {
    const recorder = window.MediaRecorder || globalThis.MediaRecorder;
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/aac"];
    if (!recorder || typeof recorder.isTypeSupported !== "function") return "";
    return candidates.find((candidate) => recorder.isTypeSupported(candidate)) || "";
  }

  function blobExtension(type) {
    if (type.includes("mp4")) return "m4a";
    if (type.includes("aac")) return "aac";
    if (type.includes("wav")) return "wav";
    return "webm";
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setStatus("이 브라우저에서는 녹음을 사용할 수 없습니다.", "error");
      return;
    }

    try {
      chunks = [];
      recordedBlob = null;
      state = "recording";
      setRecordState("녹음 중");
      updateButtons();
      updateElapsedSeconds(0);
      setStatus("녹음 중입니다. 3초 뒤부터 멈출 수 있고 최대 10분까지 녹음됩니다.");

      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = chooseMimeType();
      const options = { audioBitsPerSecond: BITRATE };
      if (mimeType) options.mimeType = mimeType;
      mediaRecorder = new MediaRecorder(mediaStream, options);
      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) chunks.push(event.data);
      };
      mediaRecorder.onstop = () => {
        clearTimer();
        stopStream();
        const type = mediaRecorder.mimeType || mimeType || "audio/webm";
        recordedBlob = new Blob(chunks, { type });
        state = "ready";
        setRecordState("확인 대기");
        updateElapsedSeconds((Date.now() - startedAt) / 1000);
        updateButtons();
        setStatus("녹음이 준비됐습니다. 추가하거나 다시 녹음할 수 있습니다.", "success");
      };
      startedAt = Date.now();
      mediaRecorder.start();
      timerId = setInterval(() => {
        updateElapsedSeconds((Date.now() - startedAt) / 1000);
      }, 250);
    } catch (_error) {
      clearTimer();
      stopStream();
      recordedBlob = null;
      state = "idle";
      setRecordState("대기");
      updateButtons();
      updateElapsedSeconds(0);
      setStatus("마이크 권한을 확인한 뒤 다시 시도해 주세요.", "error");
    }
  }

  function stopRecording() {
    if (state !== "recording") return;
    const elapsed = (Date.now() - startedAt) / 1000;
    if (elapsed < MIN_SECONDS) {
      updateElapsedSeconds(elapsed);
      setStatus("최소 3초가 지나야 녹음을 멈출 수 있습니다.", "error");
      return;
    }
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
  }

  function resetRecording() {
    if (state === "recording") return;
    chunks = [];
    recordedBlob = null;
    state = "idle";
    setRecordState("대기");
    updateElapsedSeconds(0);
    updateButtons();
    setStatus("다시 녹음할 수 있습니다.");
  }

  function mapUploadError(error) {
    const message = String(error?.message || "");
    if (message.includes("recording_too_short")) return "녹음이 3초보다 짧습니다.";
    if (message.includes("recording_too_long")) return "녹음이 10분보다 깁니다.";
    if (message.includes("file_too_large")) return "파일이 너무 큽니다. 최대 25MB까지 업로드할 수 있습니다.";
    if (message.includes("invalid_token")) return "링크가 유효하지 않습니다.";
    if (message.includes("decode_failed")) return "녹음 파일을 처리하지 못했습니다. 다시 녹음해 주세요.";
    return "Voice Stack에 추가하지 못했습니다. 다시 시도해 주세요.";
  }

  function submitRecording() {
    if (!recordedBlob) {
      setStatus("추가할 녹음이 없습니다.", "error");
      return Promise.resolve(false);
    }
    if (recordedBlob.size > MAX_UPLOAD_BYTES) {
      setStatus("파일이 너무 큽니다. 최대 25MB까지 업로드할 수 있습니다.", "error");
      return Promise.resolve(false);
    }

    state = "submitting";
    updateButtons();
    setStatus("Voice Stack에 추가하는 중입니다.");

    const formData = new FormData();
    formData.append(
      "file",
      recordedBlob,
      `voice-stack-recording.${blobExtension(recordedBlob.type || "")}`,
    );

    return fetch("/api/public/recordings", {
      method: "POST",
      headers: { "X-Public-Recording-Token": getToken() },
      body: formData,
    })
      .then(async (response) => {
        let payload = {};
        try {
          payload = await response.json();
        } catch (_error) {
          payload = {};
        }
        if (!response.ok) {
          throw new Error(payload.detail || payload.error || "upload_failed");
        }
        chunks = [];
        recordedBlob = null;
        state = "committed";
        setRecordState("추가 완료");
        updateButtons();
        setStatus(
          "Voice Stack에 추가되었습니다. 이후 다른 녹음이 추가되면 되돌릴 수 없습니다.",
          "success",
        );
        return payload;
      })
      .catch((error) => {
        state = "ready";
        updateButtons();
        setStatus(mapUploadError(error), "error");
        return false;
      });
  }

  function bind() {
    byId("startButton")?.addEventListener("click", startRecording);
    byId("stopButton")?.addEventListener("click", stopRecording);
    byId("rerecordButton")?.addEventListener("click", resetRecording);
    byId("addButton")?.addEventListener("click", submitRecording);
    updateButtons();
    updateElapsedSeconds(0);

    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      const startButton = byId("startButton");
      if (startButton) startButton.disabled = true;
      setStatus("이 브라우저에서는 녹음을 사용할 수 없습니다.", "error");
      return;
    }

    setStatus("녹음을 시작할 수 있습니다.");
  }

  document.addEventListener("DOMContentLoaded", bind);

  window.SecretPondPublicRecorder = {
    startRecording,
    stopRecording,
    submitRecording,
    _test: {
      updateElapsedSeconds,
      setRecordedBlob,
      submitRecording,
      constants: {
        minSeconds: MIN_SECONDS,
        maxSeconds: MAX_SECONDS,
        maxUploadBytes: MAX_UPLOAD_BYTES,
      },
    },
  };
})();
