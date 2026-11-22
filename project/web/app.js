"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const elements = {
    form: $("retrieval-form"), fieldset: $("source-fieldset"), sourcePanel: document.querySelector(".source-panel"),
    artInput: $("art-file"), videoInput: $("video-file"), artDrop: $("art-drop"), videoDrop: $("video-drop"),
    artPlaceholder: $("art-drop-placeholder"), artPreview: $("art-upload-preview"), artChange: $("art-change-label"), artLabel: $("art-file-label"),
    videoTitle: $("video-drop-title"), videoSubtitle: $("video-drop-subtitle"), method: $("method-select"), methodDescription: $("method-description"),
    interval: $("interval-input"), topK: $("top-k-input"), minGap: $("min-gap-input"), minScore: $("min-score-input"), minScoreDescription: $("min-score-description"), search: $("search-button"), demo: $("demo-button"), readyHint: $("ready-hint"),
    error: $("error-panel"), errorMessage: $("error-message"), errorTitle: $("error-title"), progress: $("progress-panel"), progressBar: $("progress-bar"),
    progressStage: $("progress-stage"), progressValue: $("progress-value"), progressMessage: $("progress-message"), badge: $("workspace-badge"),
    empty: $("empty-state"), results: $("results-state"), synthetic: $("synthetic-notice"), reference: $("reference-image"), referenceName: $("reference-name"),
    player: $("video-player"), videoName: $("video-name"), videoDuration: $("video-duration"), selectedTime: $("selected-timestamp"), selectedMomentLabel: $("selected-moment-label"),
    resultTitle: $("results-title"), resultCount: $("result-count"), resultSummary: $("results-summary"), grid: $("results-grid"), exportLink: $("export-link"), metadataLink: $("metadata-link"), noMatches: $("no-matches"), noMatchesDescription: $("no-matches-description"), announcement: $("announcement"),
  };
  const state = { capabilities: null, videoFile: null, artFile: null, previewUrl: null, mode: "upload", busy: false, run: 0, pollTimer: null, controller: null, selectedTimestamp: null, resultJob: null, pendingSeekHandler: null, thresholdMethod: null, thresholdByMethod: Object.create(null) };
  const METHOD_COPY = {
    colour: "Compare colour distributions across the image and its regions. A baseline for colour and layout.",
    clip: "Compare image features from a pretrained CLIP model. Explore the visual associations it retrieves.",
  };

  function announce(message) { elements.announcement.textContent = message; }
  function fileSize(bytes) { return `${(bytes / 1024 / 1024).toFixed(bytes < 1024 * 1024 ? 2 : 1)} MB`; }
  function formatTime(seconds) {
    if (!Number.isFinite(Number(seconds))) return "—";
    const value = Math.max(0, Number(seconds));
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor(value / 60) % 60;
    const rest = Math.floor(value % 60);
    return `${hours ? `${String(hours).padStart(2, "0")}:` : ""}${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }
  function setBadge(text, active = false) { elements.badge.textContent = text; elements.badge.classList.toggle("active", active); }
  function hideError() { elements.error.hidden = true; }
  function showError(message, title = "Something needs a second look") {
    elements.errorTitle.textContent = title;
    elements.errorMessage.textContent = message;
    elements.error.hidden = false;
    announce(message);
  }
  function methodIsAvailable() {
    return Boolean(state.capabilities?.methods?.find((method) => method.id === elements.method.value && method.available));
  }
  function updateReadiness() {
    const hasFiles = state.mode === "demo" || Boolean(state.artFile && state.videoFile);
    elements.search.disabled = state.busy || !hasFiles || !methodIsAvailable();
    elements.demo.disabled = state.busy || !state.capabilities?.demo?.available;
    elements.fieldset.disabled = state.busy;
    elements.method.disabled = state.busy || !state.capabilities;
    elements.sourcePanel.classList.toggle("busy", state.busy);
    if (state.busy) elements.readyHint.textContent = "Looking for connections in your footage…";
    else if (!state.capabilities) elements.readyHint.textContent = "Connecting to the local workspace…";
    else if (state.mode === "demo") elements.readyHint.textContent = "Synthetic sample selected. Adjust settings to explore.";
    else if (hasFiles) elements.readyHint.textContent = "Ready to explore your footage.";
    else elements.readyHint.textContent = "Add an artwork and a video to begin.";
    [elements.artDrop, elements.videoDrop].forEach((drop) => {
      drop.setAttribute("aria-disabled", String(state.busy));
      drop.tabIndex = state.busy ? -1 : 0;
    });
  }
  function updateMethodDescription() {
    const current = state.capabilities?.methods?.find((method) => method.id === elements.method.value);
    elements.methodDescription.textContent = current?.available ? (METHOD_COPY[current.id] || current.description || current.name) : (current?.reason || "This method is not available in this workspace.");
    elements.minScoreDescription.textContent = `Applies to ${current?.name || "the selected method"}. Leave blank to disable. Scores are not probabilities; each method needs its own calibrated setting.`;
  }
  function changeMethod() {
    if (state.thresholdMethod) state.thresholdByMethod[state.thresholdMethod] = elements.minScore.value;
    state.thresholdMethod = elements.method.value;
    elements.minScore.value = state.thresholdByMethod[state.thresholdMethod] ?? "";
    updateMethodDescription();
  }
  async function responseJson(response) {
    let data;
    try { data = await response.json(); } catch (_) {
      throw new Error(response.ok ? "The workspace returned an unreadable response. Please try again." : `The request could not be completed (HTTP ${response.status}).`);
    }
    if (!response.ok) {
      let message = data.detail || data.error || data.message || `The request could not be completed (HTTP ${response.status}).`;
      if (Array.isArray(message)) message = message.map((issue) => issue.msg || String(issue)).join(" ");
      if (typeof message !== "string") message = JSON.stringify(message);
      throw new Error(message);
    }
    return data;
  }
  async function loadCapabilities() {
    try {
      const response = await fetch("/api/capabilities", { cache: "no-store" });
      const data = await responseJson(response);
      state.capabilities = data;
      elements.method.replaceChildren();
      (data.methods || []).forEach((method) => {
        const option = document.createElement("option");
        option.value = method.id;
        option.textContent = `${method.name}${method.available ? "" : " — unavailable"}`;
        option.disabled = !method.available;
        if (method.reason) option.title = method.reason;
        elements.method.append(option);
      });
      const preferred = (data.methods || []).find((method) => method.id === data.default_method && method.available) || (data.methods || []).find((method) => method.available);
      if (preferred) elements.method.value = preferred.id;
      state.thresholdMethod = elements.method.value;
      elements.minScore.value = state.thresholdByMethod[state.thresholdMethod] ?? "";
      $("image-limit-label").textContent = `JPG, PNG or WebP · up to ${data.max_image_mb || 20} MB`;
      $("video-limit-label").textContent = `MP4 or MOV recommended · up to ${data.max_video_mb || 500} MB`;
      updateMethodDescription();
      updateReadiness();
      const unavailableClip = data.methods?.find((method) => method.id === "clip" && !method.available);
      if (unavailableClip?.reason) {
        const note = document.createElement("p");
        note.className = "setting-description";
        note.textContent = `CLIP: ${unavailableClip.reason}`;
        elements.methodDescription.after(note);
      }
    } catch (error) {
      elements.method.replaceChildren(new Option("Workspace unavailable", ""));
      elements.methodDescription.textContent = "Reload this page once the local workspace is running.";
      elements.readyHint.textContent = "The local workspace could not be reached.";
      showError(error.message || "The local workspace could not be reached. Reload this page to try again.", "Could not connect to the workspace");
    }
  }
  function releasePreview() {
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = null;
  }
  function clearPendingSeek() {
    if (state.pendingSeekHandler) elements.player.removeEventListener("loadedmetadata", state.pendingSeekHandler);
    state.pendingSeekHandler = null;
  }
  function clearResults() {
    clearPendingSeek();
    state.resultJob = null;
    state.selectedTimestamp = null;
    elements.results.hidden = true;
    elements.empty.hidden = false;
    elements.progress.hidden = true;
    elements.noMatches.hidden = true;
    elements.synthetic.hidden = true;
    elements.resultTitle.textContent = "Moments that resonate";
    elements.resultCount.textContent = "";
    elements.selectedTime.textContent = "—";
    elements.selectedMomentLabel.textContent = "THE SELECTED MOMENT";
    elements.exportLink.removeAttribute("href");
    elements.metadataLink.removeAttribute("href");
    elements.grid.replaceChildren();
    elements.player.pause();
    elements.player.removeAttribute("src");
    elements.player.load();
    elements.reference.removeAttribute("src");
    setBadge("READY TO EXPLORE", true);
  }
  function leaveDemo() {
    if (state.mode !== "demo") return;
    state.mode = "upload";
    state.artFile = null;
    state.videoFile = null;
    elements.videoTitle.textContent = "Drop your video here";
    elements.videoSubtitle.textContent = "or click to browse your files";
    elements.artPreview.hidden = true;
    elements.artPreview.removeAttribute("src");
    elements.artPlaceholder.hidden = false;
    elements.artChange.hidden = true;
    elements.artLabel.hidden = true;
  }
  function selectFile(kind, file) {
    if (!file || state.busy) return;
    const maxMb = kind === "art" ? (state.capabilities?.max_image_mb || 20) : (state.capabilities?.max_video_mb || 500);
    if (file.size > maxMb * 1024 * 1024) {
      showError(`Please choose ${kind === "art" ? "an artwork image" : "a video"} smaller than ${maxMb} MB. This file is ${fileSize(file.size)}.`);
      return;
    }
    const imageExtension = /\.(png|jpe?g|webp|bmp|tiff?)$/i;
    const videoExtension = /\.(mp4|mov|m4v|webm|avi|mkv)$/i;
    if (kind === "art" && !imageExtension.test(file.name)) {
      showError("Please choose an image for the artwork reference, such as a JPG, PNG or WebP file."); return;
    }
    if (kind === "video" && !videoExtension.test(file.name)) {
      showError("Please choose a video file for the footage, such as an MP4 or MOV file."); return;
    }
    hideError();
    leaveDemo();
    clearResults();
    if (kind === "art") {
      state.artFile = file;
      releasePreview();
      state.previewUrl = URL.createObjectURL(file);
      elements.artPreview.src = state.previewUrl;
      elements.artPreview.hidden = false;
      elements.artPlaceholder.hidden = true;
      elements.artChange.hidden = false;
      elements.artLabel.textContent = `${file.name} · ${fileSize(file.size)}`;
      elements.artLabel.title = file.name;
      elements.artLabel.hidden = false;
    } else {
      state.videoFile = file;
      elements.videoTitle.textContent = file.name;
      elements.videoTitle.title = file.name;
      elements.videoSubtitle.textContent = `${fileSize(file.size)} · click to change`;
    }
    updateReadiness();
    announce(`${kind === "art" ? "Artwork" : "Video"} selected: ${file.name}`);
  }
  function bindDropZone(drop, input, kind) {
    input.addEventListener("change", () => {
      const file = input.files?.[0];
      // Files are retained in state. Reset the picker so choosing the same file
      // again still triggers change, including after a failed validation.
      input.value = "";
      selectFile(kind, file);
    });
    drop.addEventListener("keydown", (event) => {
      if (event.target !== drop || state.busy) return;
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); input.click(); }
    });
    ["dragenter", "dragover"].forEach((name) => drop.addEventListener(name, (event) => {
      event.preventDefault();
      if (!state.busy) drop.classList.add("drag-over");
    }));
    ["dragleave", "dragend"].forEach((name) => drop.addEventListener(name, () => drop.classList.remove("drag-over")));
    drop.addEventListener("drop", (event) => {
      event.preventDefault();
      drop.classList.remove("drag-over");
      if (state.busy) return;
      const files = event.dataTransfer?.files;
      if (files?.length > 1) { showError("Please choose one artwork and one video for each search."); return; }
      selectFile(kind, files?.[0]);
    });
  }
  function settings() {
    if ([elements.interval, elements.topK, elements.minGap].some((input) => input.value.trim() === "")) throw new Error("Please fill in the sampling interval, number of results and spacing between matches.");
    if (elements.minScore.validity?.badInput) throw new Error("Enter a finite minimum similarity from -1 to 1, or leave it blank.");
    const rawMinScore = elements.minScore.value.trim();
    const values = { interval: Number(elements.interval.value), top_k: Number(elements.topK.value), min_gap: Number(elements.minGap.value), method: elements.method.value, min_score: rawMinScore === "" ? null : Number(rawMinScore) };
    if (!Number.isFinite(values.interval) || values.interval < 0.25 || values.interval > 10) throw new Error("Choose a sampling interval between 0.25 and 10 seconds.");
    if (!Number.isInteger(values.top_k) || values.top_k < 1 || values.top_k > 20) throw new Error("Choose a whole number of results between 1 and 20.");
    if (!Number.isFinite(values.min_gap) || values.min_gap < 0 || values.min_gap > 60) throw new Error("Choose a spacing between matches from 0 to 60 seconds.");
    if (values.min_score !== null && (!Number.isFinite(values.min_score) || values.min_score < -1 || values.min_score > 1)) throw new Error("Choose a minimum similarity between -1 and 1, or leave it blank. This score is not a probability.");
    if (!methodIsAvailable()) throw new Error("Please select an available retrieval method.");
    return values;
  }
  function updateProgress(job) {
    const value = Math.max(0, Math.min(100, Number(job.progress) || 0));
    const stageTitles = { queued: "Waiting to begin", reference: "Preparing your artwork", extracting: "Finding the frames", sampling: "Finding the frames", features: "Looking at visual features", encoding: "Looking at visual features", comparing: "Comparing with your artwork", ranking: "Choosing the closest connections", processing: "Exploring your footage", complete: "Your visual echoes are ready" };
    elements.progress.hidden = false;
    elements.progressBar.classList.remove("indeterminate");
    elements.progressBar.style.width = `${value}%`;
    elements.progressValue.textContent = `${Math.round(value)}%`;
    elements.progressStage.textContent = stageTitles[job.stage] || (typeof job.stage === "string" ? job.stage.replaceAll("_", " ") : "Exploring your footage");
    elements.progressMessage.textContent = job.message || "Your frames will appear here when the search is ready.";
  }
  function stopPolling() {
    if (state.pollTimer) clearTimeout(state.pollTimer);
    state.pollTimer = null;
    if (state.controller) state.controller.abort();
    state.controller = null;
  }
  async function startSearch(useDemo = false) {
    if (state.busy) return;
    hideError();
    let values;
    try { values = settings(); } catch (error) { showError(error.message); return; }
    if (!useDemo && state.mode !== "demo" && (!state.artFile || !state.videoFile)) { showError("Choose an artwork and a video before starting the search."); return; }
    if (useDemo) {
      state.mode = "demo";
      state.artFile = null;
      state.videoFile = null;
      elements.artInput.value = "";
      elements.videoInput.value = "";
      releasePreview();
      elements.artPreview.src = state.capabilities.demo.reference_url;
      elements.artPreview.hidden = false;
      elements.artPlaceholder.hidden = true;
      elements.artChange.hidden = false;
      elements.artLabel.textContent = "Synthetic reference image · generated test material";
      elements.artLabel.hidden = false;
      elements.videoTitle.textContent = "Synthetic sample footage";
      elements.videoSubtitle.textContent = "Generated test material · click to replace";
    }
    stopPolling();
    const run = ++state.run;
    const demoMode = state.mode === "demo";
    state.busy = true;
    updateReadiness();
    clearResults();
    elements.progress.hidden = false;
    elements.progressStage.textContent = demoMode ? "Preparing the synthetic sample" : "Bringing your source material together";
    elements.progressMessage.textContent = demoMode ? "Loading generated test imagery for this demonstration." : "Uploading your files to the local workspace. Larger videos may take a moment.";
    elements.progressValue.textContent = "";
    elements.progressBar.style.width = "30%";
    elements.progressBar.classList.add("indeterminate");
    setBadge("LOOKING FOR CONNECTIONS", true);
    elements.search.querySelector("span").textContent = "Finding visual echoes…";
    state.controller = new AbortController();
    try {
      let response;
      if (demoMode) {
        response = await fetch("/api/demo/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values), signal: state.controller.signal });
      } else {
        const form = new FormData();
        form.append("video_file", state.videoFile);
        form.append("art_file", state.artFile);
        Object.entries(values).forEach(([key, value]) => {
          if (value !== null && value !== undefined) form.append(key, String(value));
        });
        response = await fetch("/api/search", { method: "POST", body: form, signal: state.controller.signal });
      }
      const data = await responseJson(response);
      if (run !== state.run) return;
      if (!data.job_id) throw new Error("The workspace did not return a search identifier. Please try again.");
      await pollJob(data.job_id, run, demoMode);
    } catch (error) { handleSearchError(error, run); }
  }
  async function pollJob(jobId, run, demoMode) {
    if (run !== state.run) return;
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store", signal: state.controller?.signal });
      const job = await responseJson(response);
      if (run !== state.run) return;
      updateProgress(job);
      if (job.status === "error") throw new Error(job.error || job.message || "The search could not be completed. Please try another video or image.");
      if (job.status === "complete") {
        state.busy = false;
        state.controller = null;
        elements.progress.hidden = true;
        renderResults(job, demoMode);
        elements.search.querySelector("span").textContent = "Find visual echoes";
        updateReadiness();
        return;
      }
      state.pollTimer = setTimeout(() => pollJob(jobId, run, demoMode), 700);
    } catch (error) { handleSearchError(error, run); }
  }
  function handleSearchError(error, run) {
    if (run !== state.run || error.name === "AbortError") return;
    stopPolling();
    state.busy = false;
    elements.progress.hidden = true;
    elements.search.querySelector("span").textContent = "Find visual echoes";
    setBadge("TRY ANOTHER LOOK");
    updateReadiness();
    showError(error.message || "The workspace could not complete this search. Please try again.", "We couldn’t complete this search");
  }
  function selectResult(result, button, play = false) {
    if (!state.resultJob || !elements.grid.contains(button)) return;
    clearPendingSeek();
    document.querySelectorAll(".result-card").forEach((card) => {
      const selected = card === button;
      card.classList.toggle("selected", selected);
      card.setAttribute("aria-pressed", String(selected));
    });
    const timestamp = Number(result.timestamp);
    state.selectedTimestamp = Number.isFinite(timestamp) ? Math.max(0, timestamp) : 0;
    const selectedTimestamp = state.selectedTimestamp;
    const jobId = state.resultJob.job_id;
    const source = elements.player.getAttribute("src");
    elements.selectedTime.textContent = result.timestamp_label || formatTime(state.selectedTimestamp);
    const seek = () => {
      if (state.pendingSeekHandler === seek) state.pendingSeekHandler = null;
      if (state.resultJob?.job_id !== jobId || state.selectedTimestamp !== selectedTimestamp || elements.player.getAttribute("src") !== source) return;
      try { elements.player.currentTime = selectedTimestamp; } catch (_) { /* Wait for metadata before seeking. */ }
      if (play) elements.player.play().catch(() => announce("Use the video controls to play this moment."));
    };
    if (elements.player.readyState >= 1) seek();
    else {
      state.pendingSeekHandler = seek;
      elements.player.addEventListener("loadedmetadata", seek, { once: true });
    }
    announce(`Selected matching moment at ${result.timestamp_label || formatTime(state.selectedTimestamp)}.`);
  }
  function renderResults(job, demoMode) {
    clearPendingSeek();
    state.resultJob = job;
    elements.empty.hidden = true;
    elements.results.hidden = false;
    elements.synthetic.hidden = !demoMode;
    const matches = Array.isArray(job.results) ? job.results : [];
    const noMatches = matches.length === 0;
    state.selectedTimestamp = null;
    elements.selectedTime.textContent = "—";
    elements.selectedMomentLabel.textContent = noMatches ? "SOURCE VIDEO" : "THE SELECTED MOMENT";
    setBadge(noMatches ? "NO SUFFICIENT MATCH" : (demoMode ? "SYNTHETIC DEMO" : "CONNECTIONS FOUND"), !noMatches);
    elements.resultTitle.textContent = noMatches ? "No sufficiently similar frames found" : "Moments that resonate";
    elements.reference.src = job.reference.url;
    elements.referenceName.textContent = job.reference.filename || "Reference artwork";
    elements.referenceName.title = job.reference.filename || "Reference artwork";
    elements.player.src = job.video.url;
    elements.player.load();
    elements.videoName.textContent = job.video.filename || "Source video";
    elements.videoName.title = job.video.filename || "Source video";
    elements.videoDuration.textContent = formatTime(job.video.duration);
    elements.exportLink.href = job.export_url || `/api/jobs/${encodeURIComponent(job.job_id)}/export.csv`;
    elements.metadataLink.href = job.metadata_url || `/api/jobs/${encodeURIComponent(job.job_id)}/export.json`;
    elements.resultCount.textContent = String(matches.length).padStart(2, "0");
    const method = state.capabilities.methods.find((item) => item.id === job.settings.method)?.name || job.settings.method;
    const frameCount = Number(job.frames_total || 0).toLocaleString();
    const threshold = job.settings.min_score;
    const hasThreshold = threshold !== null && threshold !== undefined;
    const thresholdSummary = hasThreshold ? `minimum score ≥ ${threshold}` : "minimum score off";
    elements.resultSummary.textContent = `${frameCount} frames compared · ${method} · sampled every ${job.settings.interval} sec · matches at least ${job.settings.min_gap} sec apart · ${thresholdSummary}`;
    if (!noMatches && matches.length < Number(job.settings.top_k)) elements.resultSummary.textContent += `. ${matches.length} distinct ${matches.length === 1 ? "moment meets" : "moments meet"} these settings.`;
    elements.grid.replaceChildren();
    elements.noMatches.hidden = !noMatches;
    elements.noMatchesDescription.textContent = hasThreshold
      ? "No frames in this video meet the selected minimum similarity score."
      : "No frames meet the current search settings for this video.";
    const cards = matches.map((result, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "result-card";
      button.setAttribute("aria-pressed", "false");
      const time = result.timestamp_label || formatTime(Number(result.timestamp));
      button.setAttribute("aria-label", `Match ${result.rank || index + 1}, jump to ${time}, similarity ${Number(result.score).toFixed(3)}`);
      const imageWrap = document.createElement("div");
      imageWrap.className = "result-image-wrap";
      const image = document.createElement("img");
      image.src = result.thumbnail_url || result.frame_url;
      image.alt = `Matching video frame at ${time}`;
      image.loading = index < 6 ? "eager" : "lazy";
      const rank = document.createElement("span");
      rank.className = "result-rank";
      rank.textContent = String(result.rank || index + 1).padStart(2, "0");
      const play = document.createElement("span");
      play.className = "result-play";
      play.setAttribute("aria-hidden", "true");
      play.innerHTML = '<svg viewBox="0 0 12 12"><path d="m4 2 6 4-6 4z"/></svg>';
      imageWrap.append(image, rank, play);
      const meta = document.createElement("div");
      meta.className = "result-meta";
      const timestamp = document.createElement("span");
      timestamp.className = "result-time";
      timestamp.textContent = time;
      const score = document.createElement("span");
      score.className = "result-score";
      score.textContent = `score ${Number.isFinite(Number(result.score)) ? Number(result.score).toFixed(3) : "—"}`;
      meta.append(timestamp, score);
      button.append(imageWrap, meta);
      button.addEventListener("click", () => selectResult(result, button, true));
      elements.grid.append(button);
      return button;
    });
    if (matches.length) selectResult(matches[0], cards[0]);
    else elements.selectedTime.textContent = "—";
    announce(noMatches ? "No sufficiently similar frames found. Search complete. You can save this search record." : `${matches.length} matching moments found from ${frameCount} sampled frames.`);
  }

  bindDropZone(elements.artDrop, elements.artInput, "art");
  bindDropZone(elements.videoDrop, elements.videoInput, "video");
  elements.form.addEventListener("submit", (event) => { event.preventDefault(); startSearch(); });
  elements.demo.addEventListener("click", () => startSearch(true));
  elements.method.addEventListener("change", changeMethod);
  elements.minScore.addEventListener("input", () => {
    if (state.thresholdMethod) state.thresholdByMethod[state.thresholdMethod] = elements.minScore.value;
  });
  $("dismiss-error").addEventListener("click", hideError);
  elements.artPreview.addEventListener("error", () => {
    if (!state.artFile || state.mode === "demo") return;
    elements.artPreview.hidden = true;
    elements.artPlaceholder.hidden = false;
    elements.artPlaceholder.querySelector("strong").textContent = "Image selected";
    elements.artPlaceholder.querySelector("span:not(.upload-icon)").textContent = "Preview available after processing";
  });
  elements.player.addEventListener("error", () => {
    if (!state.resultJob || !elements.player.getAttribute("src")) return;
    showError("This browser could not play the original video format. You can try a browser-compatible MP4 video.", "This video format could not be played");
  });
  window.addEventListener("beforeunload", () => { stopPolling(); clearPendingSeek(); releasePreview(); });
  loadCapabilities();
})();
