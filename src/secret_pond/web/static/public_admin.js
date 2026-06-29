(function () {
  const state = {
    versions: [],
  };

  function init() {
    const refreshButton = document.getElementById("refreshButton");
    const uploadButton = document.getElementById("uploadStackButton");
    if (refreshButton) refreshButton.addEventListener("click", loadVersions);
    if (uploadButton) uploadButton.addEventListener("click", uploadStack);
    loadVersions();
  }

  async function loadVersions() {
    setStatus("Loading versions...");
    try {
      const response = await fetch("/admin/versions");
      if (!response.ok) throw new Error("versions_failed");
      const payload = await response.json();
      state.versions = Array.isArray(payload.versions) ? payload.versions : [];
      renderVersions();
      setStatus("");
    } catch (error) {
      setStatus("버전 목록을 불러오지 못했습니다.");
    }
  }

  function renderVersions() {
    const list = document.getElementById("versionsList");
    const summary = document.getElementById("summaryText");
    if (!list || !summary) return;

    const activeCount = state.versions.filter((version) => !version.deleted_at).length;
    summary.textContent = `${state.versions.length} versions, ${activeCount} active`;
    list.innerHTML = "";
    if (state.versions.length === 0) {
      const empty = document.createElement("p");
      empty.textContent = "저장된 Voice Stack 버전이 없습니다.";
      list.appendChild(empty);
      return;
    }

    state.versions.forEach((version, index) => {
      list.appendChild(renderVersionCard(version, state.versions.length - index));
    });
  }

  function renderVersionCard(version, displayIndex) {
    const deleted = Boolean(version.deleted_at);
    const card = document.createElement("article");
    card.className = `version-card${deleted ? " deleted" : ""}`;
    card.dataset.versionId = version.id;
    card.innerHTML = `
      <div class="version-heading">
        <div>
          <h2>#${displayIndex} ${labelKind(version.kind)}</h2>
          <p>${formatDate(version.created_at)}</p>
        </div>
        <strong>${deleted ? "Deleted" : "Active"}</strong>
      </div>
      <div class="version-meta">
        <span><span class="meta-label">Duration</span>${formatSeconds(version.duration_seconds)}</span>
        <span><span class="meta-label">Size</span>${formatBytes(version.file_size)}</span>
        <span><span class="meta-label">Added chunks</span>${version.added_chunks ?? 0}</span>
        <span><span class="meta-label">Gain reduction</span>${formatDb(version.gain_reduction_db)}</span>
        <span><span class="meta-label">Level guard</span>${formatDb(version.level_guard_gain_db)}</span>
      </div>
      <div class="version-actions"></div>
    `;

    const actions = card.querySelector(".version-actions");
    if (!deleted) {
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.preload = "none";
      audio.src = `/admin/versions/${encodeURIComponent(version.id)}/preview`;
      actions.appendChild(audio);
    }

    const download = document.createElement("a");
    download.className = "button-link secondary";
    download.href = `/admin/versions/${encodeURIComponent(version.id)}/download`;
    download.textContent = "Download";
    if (deleted) download.setAttribute("aria-disabled", "true");
    actions.appendChild(download);

    const deleteButton = document.createElement("button");
    deleteButton.className = "danger";
    deleteButton.type = "button";
    deleteButton.textContent = "Delete";
    deleteButton.disabled = deleted;
    deleteButton.addEventListener("click", () => deleteVersion(version.id));
    actions.appendChild(deleteButton);

    return card;
  }

  async function deleteVersion(versionId) {
    const confirmed = window.confirm(
      "이 버전을 삭제할까요? 삭제 후 미리듣기/다운로드는 불가능합니다.",
    );
    if (!confirmed) return;

    setStatus("Deleting version...");
    const response = await fetch(`/admin/versions/${encodeURIComponent(versionId)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      setStatus("버전을 삭제하지 못했습니다.");
      return;
    }
    await loadVersions();
    setStatus("삭제했습니다.");
  }

  async function uploadStack() {
    const input = document.getElementById("stackUploadInput");
    const uploadButton = document.getElementById("uploadStackButton");
    const file = input?.files?.[0];
    if (!file) {
      setStatus("업로드할 WAV 파일을 선택해 주세요.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    if (uploadButton) uploadButton.disabled = true;
    setStatus("Uploading stack...");
    try {
      const response = await fetch("/admin/versions/upload", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error("upload_failed");
      if (input) input.value = "";
      await loadVersions();
      setStatus("업로드했습니다.");
    } catch (error) {
      setStatus("스택을 업로드하지 못했습니다. WAV 파일인지 확인해 주세요.");
    } finally {
      if (uploadButton) uploadButton.disabled = false;
    }
  }

  function setStatus(message) {
    const element = document.getElementById("statusMessage");
    if (element) element.textContent = message;
  }

  function labelKind(kind) {
    if (kind === "upload") return "Upload";
    return kind === "seed" ? "Seed" : "Submission";
  }

  function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
  }

  function formatSeconds(value) {
    const seconds = Number(value || 0);
    return `${seconds.toFixed(1)}s`;
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
  }

  function formatDb(value) {
    if (value === null || value === undefined) return "-";
    return `${Number(value).toFixed(1)} dB`;
  }

  window.SecretPondPublicAdmin = {
    _test: {
      deleteVersion,
      loadVersions,
      renderVersions,
      uploadStack,
      state,
    },
  };

  document.addEventListener("DOMContentLoaded", init);
})();
