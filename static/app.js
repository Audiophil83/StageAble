/**
 * Remoteable — Frontend application
 *
 * Connects to the backend via WebSocket, renders live state,
 * and sends transport commands.
 */

(function () {
  "use strict";

  // ── State ────────────────────────────────────────────────────────
  let ws = null;
  let state = {};
  let songs = [];
  let sections = [];
  let chords = [];
  let lyrics = [];
  let appSettings = {};
  let currentView = "performance";
  let reconnectTimer = null;
  const RECONNECT_DELAY = 2000;

  // Setlist editor state
  let savedSetlists = [];
  let editorSetlist = { id: null, name: "", is_active: false, entries: [] };
  let dragSource = null;
  let lastSongListKey = null;
  let editorDropZonesReady = false;

  // Mixer view state
  let mixerTracks = [];
  let mixerFetchId = 0;
  /** While set: ignore stale mixer_tracks from poll until server confirms. */
  let mixerPending = null;

  // Client lock — locked by default; only Performance view when locked
  let clientLocked = true;
  let pendingUnlock = false;

  // Project scan progress (inline banner; page stays usable)
  let scanInProgress = false;

  // Client-side playhead smoothing (extrapolates between server polls)
  const PLAYHEAD_SOFT_CORRECT_BEATS = 0.1;
  const PLAYHEAD_HARD_SNAP_BEATS = 4;
  const PLAYHEAD_SOFT_CORRECT_BLEND = 0.5;
  const MESSAGE_AGE_MAX_MS = 500;
  // Debug: snap only. Re-enable after beat-aligned animation (ends at start_beat).
  const SLIDING_ANIMATION_ENABLED = false;
  const debugSyncEnabled =
    /(?:\?|&)debug=sync(?:&|$)/.test(location.search) ||
    localStorage.getItem("debugSync") === "1";
  let $syncDebugOverlay = null;
  const syncDebug = {
    sectionLagMs: null,
    chordLagMs: null,
  };
  let progressLoopActive = false;
  let progressRafId = 0;
  let lastFrameTime = 0;
  const playhead = {
    anchorBeat: 0,
    anchorTime: 0,
    beatsPerSecond: 2,
    playing: false,
    contextKey: "",
  };

  // ── DOM refs ─────────────────────────────────────────────────────
  const $badge        = document.getElementById("connection-badge");
  const $errorBanner  = document.getElementById("error-banner");
  const $songName     = document.getElementById("song-name");
  const $sectionProgressFill = document.querySelector(
    "#section-display .progress-bar-fill"
  );
  const $position     = document.getElementById("transport-position");
  const $tempo        = document.getElementById("transport-tempo");
  const $timeSig      = document.getElementById("transport-time-sig");
  const $songList     = document.getElementById("song-list");
  const $btnPlay      = document.getElementById("btn-play");
  const $btnStop      = document.getElementById("btn-stop");
  const $btnPrev      = document.getElementById("btn-prev");
  const $btnNext      = document.getElementById("btn-next");
  const $btnFullscreen = document.getElementById("btn-fullscreen");
  const $btnRescan    = document.getElementById("btn-rescan");
  const $btnLock      = document.getElementById("btn-lock");
  const $transportControls = document.getElementById("transport-controls");
  const $viewPerformance = document.getElementById("view-performance");
  const $viewSetlist = document.getElementById("view-setlist");
  const $viewSettings = document.getElementById("view-settings");
  const $viewMixer = document.getElementById("view-mixer");
  const $navPerformance = document.getElementById("nav-performance");
  const $navSetlist = document.getElementById("nav-setlist");
  const $navMixer = document.getElementById("nav-mixer");
  const $navSettings = document.getElementById("nav-settings");
  const $mixerTrackList = document.getElementById("mixer-track-list");
  const $mixerStatus = document.getElementById("mixer-status");
  const $settingsForm = document.getElementById("settings-form");
  const $settingsStatus = document.getElementById("settings-status");
  const $autoAdvanceInfo = document.getElementById("auto-advance-info");
  const $setlistName = document.getElementById("setlist-name");
  const $setlistLoad = document.getElementById("setlist-load");
  const $setlistActiveBadge = document.getElementById("setlist-active-badge");
  const $setlistEditorStatus = document.getElementById("setlist-editor-status");
  const $availableSongs = document.getElementById("available-songs");
  const $editorSetlist = document.getElementById("editor-setlist");
  const $btnSetlistNew = document.getElementById("btn-setlist-new");
  const $btnSetlistSave = document.getElementById("btn-setlist-save");
  const $btnSetlistDelete = document.getElementById("btn-setlist-delete");
  const $btnSetlistActivate = document.getElementById("btn-setlist-activate");
  const $scanOverlay = document.getElementById("scan-overlay");
  const $scanOverlayTitle = document.getElementById("scan-overlay-title");
  const $scanProgressStatus = document.getElementById("scan-progress-status");
  const $scanProgressLog = document.getElementById("scan-progress-log");
  const $app = document.getElementById("app");

  // ── Scan overlay (boot + rescan; blocks UI) ──────────────────────

  function setScanProgressStatus(text) {
    if ($scanProgressStatus) {
      $scanProgressStatus.textContent = text;
    }
  }

  function renderScanProgressLog(messages) {
    if (!$scanProgressLog) return;
    $scanProgressLog.innerHTML = "";
    (messages || []).forEach(function (msg) {
      const li = document.createElement("li");
      li.textContent = msg;
      $scanProgressLog.appendChild(li);
    });
    const last = $scanProgressLog.lastElementChild;
    if (last) {
      last.scrollIntoView({ block: "nearest" });
    }
  }

  function showScanProgress(options) {
    options = options || {};
    scanInProgress = true;
    document.body.classList.add("scan-blocking");
    if ($app) {
      $app.setAttribute("aria-hidden", "true");
    }
    if ($scanOverlay) {
      $scanOverlay.classList.remove("hidden");
    }
    if ($scanOverlayTitle && options.title) {
      $scanOverlayTitle.textContent = options.title;
    }
    if (options.clear !== false) {
      renderScanProgressLog([]);
    }
    setScanProgressStatus(options.status || "Scanning project…");
    setBadge("scanning");
  }

  function hideScanProgress() {
    scanInProgress = false;
    document.body.classList.remove("scan-blocking");
    if ($app) {
      $app.removeAttribute("aria-hidden");
    }
    if ($scanOverlay) {
      $scanOverlay.classList.add("hidden");
    }
    if ($scanOverlayTitle) {
      $scanOverlayTitle.textContent = "Scanning project";
    }
  }

  function refreshAfterScan() {
    fetchSongs();
    fetchSections();
    fetchChords();
    fetchLyrics();
    if (currentView === "mixer") {
      fetchMixerTracks();
    }
  }

  function applyScanStatus(msg) {
    const wasScanning = scanInProgress;
    const messages = msg.messages || [];
    if (messages.length) {
      renderScanProgressLog(messages);
      setScanProgressStatus(messages[messages.length - 1]);
    }
    if (msg.in_progress) {
      showScanProgress({
        clear: false,
        title: "Scanning project",
        status: messages.length
          ? messages[messages.length - 1]
          : "Scanning project…",
      });
      return;
    }
    scanInProgress = false;
    if (msg.done || msg.in_progress === false) {
      hideScanProgress();
      if (wasScanning) {
        refreshAfterScan();
      }
      if (state.connection_status) {
        setBadge(state.connection_status);
      }
    }
  }

  // ── Sliding Display Class ───────────────────────────────────────

  class SlidingDisplay {
    constructor(containerId, trackId, itemsArrayName) {
      this.$container = document.getElementById(containerId);
      this.$track = document.getElementById(trackId);
      this.itemsArrayName = itemsArrayName;
      this.activeIndex = -2;
      this.nextPreviewShown = false;
      this.elements = [];
      this.dataKey = "";
      this.targetCenterIndex = 0;
      this.measuredIndex = -1;
      this.isVertical = false;
      this.offsetX = 0;
      this.offsetY = 0;
      this.targetOffset = null;
      this.layoutDirty = false;
      this.lastIndexChangeTime = 0;
      this.lastCenterIndex = -1;
      this.animating = false;
    }

    update(beat) {
      if (!this.$container || !this.$track) return;

      var items = this.getItems();
      if (!items || items.length === 0) {
        if (this.dataKey !== "") {
          this.$track.innerHTML = '<div class="sliding-item current">--</div>';
          this.$track.style.transform = "";
          this.elements = [];
          this.activeIndex = -2;
          this.dataKey = "";
        }
        return;
      }

      var key = items.length + ":" + items[0].name;
      var rebuilt = false;
      if (key !== this.dataKey) {
        this.rebuild(items);
        this.dataKey = key;
        this.activeIndex = -2;
        rebuilt = true;
      }

      var idx = this.findActive(items, beat);

      var songStartBeat = (state.active_song && state.active_song.start_beat != null)
        ? state.active_song.start_beat : -Infinity;
      var songEndBeat = (state.active_song && state.active_song.end_beat != null)
        ? state.active_song.end_beat : Infinity;

      var showNext = false;
      var nextIdx = -1;
      if (idx < 0) {
        nextIdx = this.findNext(items, beat);
        showNext = nextIdx >= 0
          && (items[nextIdx].start_beat - beat) <= 16
          && items[nextIdx].start_beat >= songStartBeat
          && items[nextIdx].start_beat < songEndBeat;
      }

      if (idx === this.activeIndex && showNext === this.nextPreviewShown) return;

      var centerIdx = idx;
      if (idx < 0) {
        centerIdx = showNext ? nextIdx : 0;
      }

      var indexChanged = idx >= 0 && idx !== this.activeIndex;
      if (indexChanged) {
        this.lastIndexChangeTime = performance.now();
        this.lastCenterIndex = idx;
        recordIndexChangeLag(this, items, idx, beat);
      }

      this.activeIndex = idx;
      this.nextPreviewShown = showNext;
      this.setClasses(idx, items, beat, songStartBeat, songEndBeat, showNext, nextIdx);
      this.targetCenterIndex = centerIdx;
      this.layoutDirty = true;

      if (!SLIDING_ANIMATION_ENABLED || rebuilt || indexChanged) {
        this.snapToTarget(centerIdx);
      }
    }

    getItems() {
      if (this.itemsArrayName === "sections") return sections;
      if (this.itemsArrayName === "chords") return chords;
      if (this.itemsArrayName === "lyrics") return lyrics;
      return [];
    }

    findActive(items, beat) {
      for (var i = items.length - 1; i >= 0; i--) {
        if (items[i].start_beat <= beat) {
          return (items[i].end_beat == null || beat < items[i].end_beat) ? i : -1;
        }
      }
      return -1;
    }

    findNext(items, beat) {
      for (var i = 0; i < items.length; i++) {
        if (items[i].start_beat > beat) return i;
      }
      return -1;
    }

    rebuild(items) {
      this.$track.innerHTML = "";
      this.elements = [];
      for (var i = 0; i < items.length; i++) {
        var el = document.createElement("div");
        el.className = "sliding-item offscreen";
        el.textContent = items[i].name;
        this.$track.appendChild(el);
        this.elements.push(el);
      }
    }

    setClasses(activeIdx, items, beat, songStartBeat, songEndBeat, showNext, nextIdx) {
      var expandedLyrics =
        this.itemsArrayName === "lyrics" && this.$container.closest(".expanded");
      for (var i = 0; i < this.elements.length; i++) {
        var role;
        if (i === activeIdx) role = "current";
        else if (activeIdx >= 0 && i === activeIdx - 1
          && items[i].start_beat >= songStartBeat) role = "prev";
        else if (activeIdx >= 0 && i === activeIdx + 1
          && items[i].start_beat < songEndBeat) role = "next";
        else if (expandedLyrics && activeIdx >= 0 && i === activeIdx + 2
          && items[i].start_beat < songEndBeat) role = "next2";
        else if (activeIdx === -1 && showNext && i === nextIdx) role = "next";
        else role = "offscreen";
        this.elements[i].className = "sliding-item " + role;
      }
    }

    measureTargetOffset(index) {
      if (index < 0 || index >= this.elements.length) return null;
      var el = this.elements[index];
      if (!this.$track || !this.$container || !el.parentNode) return null;

      this.isVertical = this.$container.closest(".expanded") != null;
      var trackRect = this.$track.getBoundingClientRect();
      var itemRect = el.getBoundingClientRect();

      if (this.isVertical) {
        var cRect = this.$container.getBoundingClientRect();
        var yCenterInTrack =
          itemRect.top + itemRect.height / 2 - trackRect.top;
        return { x: 0, y: cRect.height / 2 - yCenterInTrack };
      }

      var xCenterInTrack =
        itemRect.left + itemRect.width / 2 - trackRect.left;
      return { x: -xCenterInTrack, y: 0 };
    }

    snapToTarget(index) {
      var target = this.measureTargetOffset(index);
      if (!target) return;
      this.offsetX = target.x;
      this.offsetY = target.y;
      this.targetOffset = target;
      this.measuredIndex = index;
      this.layoutDirty = false;
      this.animating = false;
      this.applyTransform();
    }

    applyTransform() {
      if (!this.$track) return;
      if (this.isVertical) {
        this.$track.style.transform =
          "translate3d(-50%, " + this.offsetY + "px, 0)";
      } else {
        this.$track.style.transform =
          "translate3d(" + this.offsetX + "px, 0, 0)";
      }
    }

    refreshTargetOffset() {
      var target = this.measureTargetOffset(this.targetCenterIndex);
      if (!target) return;
      this.targetOffset = target;
      this.measuredIndex = this.targetCenterIndex;
      this.layoutDirty = false;
    }

    tick(dt) {
      if (!this.elements.length) {
        this.animating = false;
        return;
      }

      if (!SLIDING_ANIMATION_ENABLED) {
        if (this.layoutDirty || this.measuredIndex !== this.targetCenterIndex) {
          this.snapToTarget(this.targetCenterIndex);
        }
        this.animating = false;
        return;
      }

      if (this.layoutDirty || this.measuredIndex !== this.targetCenterIndex) {
        this.refreshTargetOffset();
      }
      if (!this.targetOffset) {
        this.animating = false;
        return;
      }

      var sinceChange = performance.now() - this.lastIndexChangeTime;
      var tau;
      if (sinceChange < 200) {
        tau = 0.035;
      } else if (sinceChange < 500) {
        tau = 0.07;
      } else {
        tau = 0.13;
      }

      var alpha = 1 - Math.exp(-dt / 1000 / tau);
      var dx = this.targetOffset.x - this.offsetX;
      var dy = this.targetOffset.y - this.offsetY;
      this.offsetX += dx * alpha;
      this.offsetY += dy * alpha;
      this.applyTransform();

      this.animating = Math.abs(dx) > 0.35 || Math.abs(dy) > 0.35;
    }
  }

  let sectionSlidingDisplay = null;
  let chordsSlidingDisplay = null;
  let lyricsSlidingDisplay = null;

  // ── WebSocket ────────────────────────────────────────────────────

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/engine/`;

    ws = new WebSocket(url);

    ws.onopen = function () {
      clearTimeout(reconnectTimer);
      setBadge("connecting");
    };

    ws.onmessage = function (event) {
      const msg = JSON.parse(event.data);
      if (msg.type === "state") {
        state = msg.data;
        render();
      } else if (msg.type === "ack") {
        if (msg.command === "set_track_mute" && msg.tracks) {
          mixerPending = null;
          applyMixerTracks(msg.tracks);
        }
      } else if (msg.type === "error") {
        console.error("Server error:", msg.message);
        if (currentView === "mixer") {
          mixerPending = null;
          syncMixerFromState();
          setMixerStatus(msg.message, "error");
        }
      } else if (msg.type === "lock_state") {
        setClientLocked(!!msg.locked);
      } else if (msg.type === "unlock_check") {
        handleUnlockCheck(!!msg.requires_warning);
      } else if (msg.type === "scan_status" || msg.type === "scan_progress") {
        applyScanStatus(msg);
      }
    };

    ws.onclose = function () {
      pendingUnlock = false;
      setClientLocked(true);
      setBadge("disconnected");
      scheduleReconnect();
    };

    ws.onerror = function () {
      setBadge("error");
    };
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
  }

  function send(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data));
    }
  }

  // ── REST helpers ─────────────────────────────────────────────────

  function fetchSongs() {
    return fetch("/api/songs/")
      .then((r) => r.json())
      .then((data) => {
        songs = data;
        renderSongList();
        if (currentView === "setlist") {
          renderSetlistEditor();
        }
      })
      .catch(console.error);
  }

  function fetchSections() {
    return fetch("/api/sections/")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        sections = data;
        refreshSlidingDisplays();
      })
      .catch(console.error);
  }

  function fetchChords() {
    return fetch("/api/chords/")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        chords = data;
        refreshSlidingDisplays();
      })
      .catch(console.error);
  }

  function fetchLyrics() {
    return fetch("/api/lyrics/")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        lyrics = data;
        refreshSlidingDisplays();
      })
      .catch(console.error);
  }

  function invalidateSlidingLayouts() {
    [sectionSlidingDisplay, chordsSlidingDisplay, lyricsSlidingDisplay].forEach(
      function (display) {
        if (!display) return;
        display.layoutDirty = true;
        display.measuredIndex = -1;
        display.activeIndex = -2;
      }
    );
  }

  function refreshSlidingDisplays() {
    if (currentView !== "performance") return;
    var beat = getDisplayBeat();
    if (sectionSlidingDisplay) sectionSlidingDisplay.update(beat);
    if (chordsSlidingDisplay) chordsSlidingDisplay.update(beat);
    if (lyricsSlidingDisplay) lyricsSlidingDisplay.update(beat);
  }

  function fetchSettings() {
    return fetch("/api/settings/")
      .then((r) => r.json())
      .then((data) => {
        appSettings = data;
        populateSettingsForm();
      })
      .catch(console.error);
  }

  function getCsrfToken() {
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function apiFetch(url, options) {
    options = options || {};
    options.headers = options.headers || {};
    if (options.method && options.method !== "GET") {
      options.headers["X-CSRFToken"] = getCsrfToken();
    }
    if (options.body && typeof options.body === "object") {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    return fetch(url, options).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (text) {
          try {
            return Promise.reject(JSON.parse(text));
          } catch (e) {
            return Promise.reject({ detail: text || r.statusText });
          }
        });
      }
      if (r.status === 204) return null;
      return r.json();
    });
  }

  function saveSettings(formData) {
    return apiFetch("/api/settings/", {
      method: "PATCH",
      body: formData,
    });
  }

  function fetchSetlists() {
    return apiFetch("/api/setlists/")
      .then(function (data) {
        savedSetlists = data;
        populateSetlistLoadSelect();
      })
      .catch(console.error);
  }

  function populateSetlistLoadSelect() {
    if (!$setlistLoad) return;
    const current = $setlistLoad.value;
    $setlistLoad.innerHTML = '<option value="">Load setlist…</option>';
    savedSetlists.forEach(function (sl) {
      const opt = document.createElement("option");
      opt.value = sl.id;
      opt.textContent = sl.name + (sl.is_active ? " (active)" : "");
      $setlistLoad.appendChild(opt);
    });
    if (current) $setlistLoad.value = current;
  }

  function resetEditorSetlist() {
    editorSetlist = { id: null, name: "", is_active: false, entries: [] };
    if ($setlistName) $setlistName.value = "";
    if ($setlistLoad) $setlistLoad.value = "";
    updateSetlistActiveBadge();
    renderSetlistEditor();
  }

  function loadEditorSetlist(data) {
    editorSetlist = {
      id: data.id,
      name: data.name,
      is_active: data.is_active,
      entries: (data.entries || []).map(function (e) {
        return {
          song_name: e.song_name,
          auto_cue_next: !!e.auto_cue_next,
          gap_seconds: e.gap_seconds != null ? e.gap_seconds : 0,
          notes: e.notes || "",
        };
      }),
    };
    if ($setlistName) $setlistName.value = data.name;
    if ($setlistLoad) $setlistLoad.value = String(data.id);
    updateSetlistActiveBadge();
    renderSetlistEditor();
  }

  function updateSetlistActiveBadge() {
    if (!$setlistActiveBadge) return;
    $setlistActiveBadge.classList.toggle("hidden", !editorSetlist.is_active);
  }

  function setSetlistEditorStatus(message, type) {
    if (!$setlistEditorStatus) return;
    $setlistEditorStatus.textContent = message || "";
    $setlistEditorStatus.className =
      "setlist-editor-status" + (type ? " " + type : "");
  }

  function songNameExists(name) {
    return songs.some(function (s) {
      return s.name === name;
    });
  }

  function findSongByName(name) {
    return songs.find(function (s) {
      return s.name === name;
    });
  }

  function findActiveEvent(items, beat) {
    if (!items || !items.length) return null;
    for (var i = items.length - 1; i >= 0; i--) {
      if (items[i].start_beat <= beat) {
        if (items[i].end_beat == null || beat < items[i].end_beat) {
          return items[i];
        }
        return null;
      }
    }
    return null;
  }

  function beatProgressPercent(position, startBeat, endBeat) {
    if (
      position == null ||
      startBeat == null ||
      endBeat == null ||
      endBeat <= startBeat
    ) {
      return 0;
    }
    const span = endBeat - startBeat;
    const frac = (position - startBeat) / span;
    return Math.max(0, Math.min(100, frac * 100));
  }

  function setProgressFill(fillEl, percent) {
    if (!fillEl) return;
    const scale = Math.max(0, Math.min(1, percent / 100));
    fillEl.style.transform = "scaleX(" + scale + ")";
  }

  function playheadContextKey() {
    return state.active_song ? state.active_song.name : "";
  }

  function beatWithMessageAge(serverBeat) {
    const lastUpdate = state.last_update || 0;
    if (!lastUpdate) return serverBeat;
    const ageMs = Math.max(
      0,
      Math.min(MESSAGE_AGE_MAX_MS, Date.now() - lastUpdate * 1000)
    );
    const bps = (state.tempo || 120) / 60;
    return serverBeat + (ageMs / 1000) * bps;
  }

  function syncPlayheadFromState() {
    const rawBeat = state.transport_position || 0;
    const serverBeat = state.is_playing ? beatWithMessageAge(rawBeat) : rawBeat;
    const now = performance.now();
    const key = playheadContextKey();

    if (key !== playhead.contextKey) {
      playhead.contextKey = key;
      playhead.anchorBeat = serverBeat;
      playhead.anchorTime = now;
    }

    playhead.beatsPerSecond = (state.tempo || 120) / 60;
    playhead.playing = !!state.is_playing;

    if (!playhead.playing) {
      playhead.anchorBeat = rawBeat;
      playhead.anchorTime = now;
      return;
    }

    const extrapolated =
      playhead.anchorBeat +
      ((now - playhead.anchorTime) / 1000) * playhead.beatsPerSecond;

    const drift = serverBeat - extrapolated;
    if (Math.abs(drift) > PLAYHEAD_SOFT_CORRECT_BEATS) {
      if (Math.abs(drift) > PLAYHEAD_HARD_SNAP_BEATS) {
        playhead.anchorBeat = serverBeat;
      } else {
        playhead.anchorBeat =
          extrapolated + drift * PLAYHEAD_SOFT_CORRECT_BLEND;
      }
      playhead.anchorTime = now;
    }
  }

  function getDisplayBeat() {
    if (!playhead.playing) {
      return state.transport_position || 0;
    }
    const now = performance.now();
    return (
      playhead.anchorBeat +
      ((now - playhead.anchorTime) / 1000) * playhead.beatsPerSecond
    );
  }

  function getMessageAgeMs() {
    const lastUpdate = state.last_update || 0;
    if (!lastUpdate) return 0;
    return Math.max(
      0,
      Math.min(MESSAGE_AGE_MAX_MS, Date.now() - lastUpdate * 1000)
    );
  }

  function getPlayheadDriftBeats() {
    if (!playhead.playing) return 0;
    const rawBeat = state.transport_position || 0;
    const serverBeat = beatWithMessageAge(rawBeat);
    const now = performance.now();
    const extrapolated =
      playhead.anchorBeat +
      ((now - playhead.anchorTime) / 1000) * playhead.beatsPerSecond;
    return serverBeat - extrapolated;
  }

  function recordIndexChangeLag(display, items, idx, beat) {
    if (!debugSyncEnabled || idx < 0) return;
    const bps = (state.tempo || 120) / 60;
    if (!bps) return;
    const lagMs = ((beat - items[idx].start_beat) / bps) * 1000;
    if (display.itemsArrayName === "sections") {
      syncDebug.sectionLagMs = lagMs;
    } else if (display.itemsArrayName === "chords") {
      syncDebug.chordLagMs = lagMs;
    }
  }

  function ensureSyncDebugOverlay() {
    if (!debugSyncEnabled) return;
    if ($syncDebugOverlay) return;
    $syncDebugOverlay = document.createElement("div");
    $syncDebugOverlay.id = "sync-debug-overlay";
    $syncDebugOverlay.style.cssText =
      "position:fixed;bottom:8px;left:8px;z-index:9999;padding:8px 10px;" +
      "font:11px/1.45 monospace;background:rgba(0,0,0,0.82);color:#9f9;" +
      "border:1px solid #363;border-radius:6px;pointer-events:none;white-space:pre;";
    document.body.appendChild($syncDebugOverlay);
  }

  function updateSyncDebugOverlay() {
    if (!debugSyncEnabled) return;
    ensureSyncDebugOverlay();
    const beat = getDisplayBeat();
    const serverBeat = state.transport_position || 0;
    const sectionIdx = sectionSlidingDisplay
      ? sectionSlidingDisplay.findActive(sections, beat)
      : -1;
    const chordIdx = chordsSlidingDisplay
      ? chordsSlidingDisplay.findActive(chords, beat)
      : -1;
    const fmtLag = function (ms) {
      return ms == null ? "--" : ms.toFixed(0) + "ms";
    };
    $syncDebugOverlay.textContent =
      "sync debug\n" +
      "displayBeat: " + beat.toFixed(3) + "\n" +
      "serverBeat:  " + serverBeat.toFixed(3) + "\n" +
      "messageAge:  " + getMessageAgeMs().toFixed(0) + "ms\n" +
      "drift:       " + getPlayheadDriftBeats().toFixed(3) + " beats\n" +
      "sectionIdx:  " + sectionIdx + "  lag@change: " + fmtLag(syncDebug.sectionLagMs) + "\n" +
      "chordIdx:    " + chordIdx + "  lag@change: " + fmtLag(syncDebug.chordLagMs);
  }

  function tickSlidingDisplays(dt) {
    if (sectionSlidingDisplay) sectionSlidingDisplay.tick(dt);
    if (chordsSlidingDisplay) chordsSlidingDisplay.tick(dt);
    if (lyricsSlidingDisplay) lyricsSlidingDisplay.tick(dt);
  }

  function paintLiveVisuals() {
    const beat = getDisplayBeat();
    updateProgressBars(beat);

    if (sectionSlidingDisplay) sectionSlidingDisplay.update(beat);
    if (chordsSlidingDisplay) chordsSlidingDisplay.update(beat);
    if (lyricsSlidingDisplay) lyricsSlidingDisplay.update(beat);

    if (debugSyncEnabled) {
      updateSyncDebugOverlay();
    }
  }

  function scheduleProgressFrame() {
    if (!progressLoopActive) return;
    progressRafId = requestAnimationFrame(progressFrame);
  }

  function slidingDisplaysAnimating() {
    return (
      (sectionSlidingDisplay && sectionSlidingDisplay.animating) ||
      (chordsSlidingDisplay && chordsSlidingDisplay.animating) ||
      (lyricsSlidingDisplay && lyricsSlidingDisplay.animating)
    );
  }

  function progressFrame(now) {
    progressRafId = 0;
    if (!progressLoopActive) return;

    var dt = lastFrameTime ? now - lastFrameTime : 16;
    lastFrameTime = now;

    if (currentView === "performance" && !document.hidden) {
      const shouldPaint =
        playhead.playing ||
        (SLIDING_ANIMATION_ENABLED && slidingDisplaysAnimating());
      if (shouldPaint) {
        paintLiveVisuals();
        if (SLIDING_ANIMATION_ENABLED) {
          tickSlidingDisplays(dt);
        }
      }
      if (debugSyncEnabled) {
        updateSyncDebugOverlay();
      }
    }
    scheduleProgressFrame();
  }

  function ensureProgressLoop() {
    const want = currentView === "performance";
    if (want && !progressLoopActive) {
      progressLoopActive = true;
      scheduleProgressFrame();
      return;
    }
    if (!want && progressLoopActive) {
      progressLoopActive = false;
      if (progressRafId) {
        cancelAnimationFrame(progressRafId);
        progressRafId = 0;
      }
    }
  }

  function updateProgressBars(position) {

    if ($sectionProgressFill) {
      const sec = findActiveEvent(sections, position);
      const sectionPct = sec
        ? beatProgressPercent(position, sec.start_beat, sec.end_beat)
        : 0;
      setProgressFill($sectionProgressFill, sectionPct);
    }

    if (!$songList) return;
    const activeSong = findActiveEvent(songs, position);
    const activeName = activeSong ? activeSong.name : null;
    $songList.querySelectorAll("li").forEach(function (li) {
      const fill = li.querySelector(".song-progress .progress-bar-fill");
      if (!fill) return;
      let pct = 0;
      if (activeName && li.dataset.songName === activeName) {
        const start =
          activeSong.start_beat != null
            ? activeSong.start_beat
            : parseFloat(li.dataset.startBeat);
        const end =
          activeSong.end_beat != null
            ? activeSong.end_beat
            : parseFloat(li.dataset.endBeat);
        pct = beatProgressPercent(position, start, end);
      }
      setProgressFill(fill, pct);
    });
  }

  function getPerformanceSongs() {
    if (state.active_setlist && state.active_setlist.entries) {
      return state.active_setlist.entries
        .map(function (e, i) {
          return {
            song_name: e.song_name,
            gap_seconds: e.gap_seconds,
            missing: e.missing,
            setlist_index: i,
          };
        })
        .filter(function (e) {
          return !e.missing;
        });
    }
    return songs;
  }

  function findPerformanceListIndex(setlistIndex) {
    if (setlistIndex == null) return null;
    const list = getPerformanceSongs();
    for (let i = 0; i < list.length; i++) {
      if (list[i].setlist_index === setlistIndex) return i;
    }
    return null;
  }

  function jumpToPerformanceIndex(index) {
    if (state.active_setlist) {
      const list = getPerformanceSongs();
      const entry = list[index];
      if (entry) {
        send({ command: "jump_to_song", setlist_index: entry.setlist_index });
      }
    } else {
      const song = songs[index];
      if (song) send({ command: "jump_to_song", index: song.index });
    }
  }

  function populateSettingsForm() {
    if (!$settingsForm || !appSettings) return;
    $settingsForm.ableton_osc_host.value = appSettings.ableton_osc_host || "";
  }

  function setView(view) {
    if (clientLocked && view !== "performance") {
      return;
    }
    currentView = view;
    const isPerformance = view === "performance";
    const isSetlist = view === "setlist";
    const isMixer = view === "mixer";
    const isSettings = view === "settings";

    if ($viewPerformance) {
      $viewPerformance.hidden = !isPerformance;
    }
    if ($viewSetlist) {
      $viewSetlist.hidden = !isSetlist;
    }
    if ($viewMixer) {
      $viewMixer.hidden = !isMixer;
    }
    if ($viewSettings) {
      $viewSettings.hidden = !isSettings;
    }
    if ($navPerformance) {
      $navPerformance.classList.toggle("active", isPerformance);
    }
    if ($navSetlist) {
      $navSetlist.classList.toggle("active", isSetlist);
    }
    if ($navMixer) {
      $navMixer.classList.toggle("active", isMixer);
    }
    if ($navSettings) {
      $navSettings.classList.toggle("active", isSettings);
    }
    if ($btnRescan) {
      $btnRescan.hidden = clientLocked || !isPerformance;
    }
    if ($btnFullscreen) {
      $btnFullscreen.hidden = !isPerformance;
    }

    ensureProgressLoop();

    if (isSettings) {
      fetchSettings();
    }
    if (isSetlist) {
      fetchSetlists();
      fetchSongs().then(function () {
        renderSetlistEditor();
      });
    }
    if (isMixer) {
      fetchMixerTracks();
    }
  }

  function setClientLocked(locked) {
    clientLocked = locked;
    applyLockState();
  }

  function applyLockState() {
    if ($btnLock) {
      $btnLock.classList.toggle("is-unlocked", !clientLocked);
      $btnLock.title = clientLocked ? "Unlock controls" : "Lock controls";
      $btnLock.setAttribute("aria-pressed", clientLocked ? "false" : "true");
    }
    if ($navSetlist) {
      $navSetlist.hidden = clientLocked;
    }
    if ($navMixer) {
      $navMixer.hidden = clientLocked;
    }
    if ($navSettings) {
      $navSettings.hidden = clientLocked;
    }
    if ($btnRescan) {
      $btnRescan.hidden = clientLocked || currentView !== "performance";
    }
    if ($btnFullscreen) {
      $btnFullscreen.hidden = currentView !== "performance";
    }
    if ($transportControls) {
      $transportControls.hidden = clientLocked;
    }
    if ($songList) {
      $songList.classList.toggle("is-locked", clientLocked);
    }
    if (clientLocked && currentView !== "performance") {
      setView("performance");
    }
  }

  function handleUnlockCheck(requiresWarning) {
    if (!pendingUnlock) {
      return;
    }
    pendingUnlock = false;
    if (requiresWarning) {
      if (
        !confirm(
          "Another client already has controls unlocked. Unlock on this device anyway?"
        )
      ) {
        return;
      }
      send({ command: "unlock", confirmed: true });
      return;
    }
    send({ command: "unlock" });
  }

  function toggleClientLock() {
    if (!clientLocked) {
      send({ command: "lock" });
      return;
    }
    pendingUnlock = true;
    send({ command: "check_unlock" });
  }

  function setMixerStatus(message, type) {
    if (!$mixerStatus) return;
    $mixerStatus.textContent = message || "";
    $mixerStatus.className = "mixer-status" + (type ? " " + type : "");
  }

  function isMixerConnected() {
    return state.connection_status === "connected";
  }

  function applyMixerTracks(tracks) {
    mixerTracks = (tracks || []).map(function (t) {
      return {
        index: t.index,
        name: t.name,
        display_name: t.display_name,
        muted: !!t.muted,
      };
    });
    renderMixer();
  }

  function syncMixerFromState() {
    if (!Array.isArray(state.mixer_tracks)) {
      return;
    }

    let tracks = state.mixer_tracks;
    if (mixerPending) {
      const serverTrack = tracks.find(function (t) {
        return t.index === mixerPending.index;
      });
      if (serverTrack && serverTrack.muted === mixerPending.muted) {
        mixerPending = null;
      } else {
        tracks = tracks.map(function (t) {
          if (t.index === mixerPending.index) {
            return Object.assign({}, t, { muted: mixerPending.muted });
          }
          return t;
        });
      }
    }
    applyMixerTracks(tracks);
  }

  function fetchMixerTracks() {
    const fetchId = ++mixerFetchId;
    setMixerStatus("Loading...", "");
    return apiFetch("/api/mixer/tracks/")
      .then(function (tracks) {
        if (fetchId !== mixerFetchId) {
          return;
        }
        applyMixerTracks(tracks);
        setMixerStatus("", "");
      })
      .catch(function (err) {
        if (fetchId !== mixerFetchId) {
          return;
        }
        mixerTracks = [];
        renderMixer();
        const message =
          err && err.error
            ? err.error
            : err && err.detail
              ? err.detail
              : "Failed to load mixer tracks";
        setMixerStatus(message, "error");
      });
  }

  function renderMixer() {
    if (!$mixerTrackList) return;

    const connected = isMixerConnected();
    $mixerTrackList.innerHTML = "";

    if (!mixerTracks.length) {
      const empty = document.createElement("li");
      empty.className = "mixer-empty";
      empty.textContent = connected
        ? "No [MIX] tracks found. Prefix track names in Ableton with [MIX] and rescan."
        : "Connect to Ableton to load mixer tracks.";
      $mixerTrackList.appendChild(empty);
      return;
    }

    mixerTracks.forEach(function (track) {
      const active = !track.muted;
      const label = track.display_name || track.name;

      const li = document.createElement("li");
      li.className = "mixer-track-row" + (active ? " is-active" : " is-inactive");
      li.dataset.trackIndex = String(track.index);

      const name = document.createElement("span");
      name.className = "mixer-track-name";
      name.textContent = label;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "btn btn-mixer-state" + (active ? " is-active" : " is-inactive");
      btn.textContent = active ? "Active" : "Inactive";
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      btn.setAttribute(
        "aria-label",
        (active ? "Set " : "Activate ") + label + (active ? " to inactive" : "")
      );
      btn.disabled = !connected;
      btn.addEventListener("click", function () {
        toggleMixerMute(track.index, !track.muted);
      });

      li.appendChild(name);
      li.appendChild(btn);
      $mixerTrackList.appendChild(li);
    });
  }

  function toggleMixerMute(trackIndex, muted) {
    if (!isMixerConnected()) {
      setMixerStatus("Not connected to Ableton", "error");
      return;
    }

    mixerFetchId += 1;
    mixerPending = { index: trackIndex, muted: muted };
    setMixerStatus("", "");
    applyMixerTracks(
      mixerTracks.map(function (t) {
        if (t.index === trackIndex) {
          return Object.assign({}, t, { muted: muted });
        }
        return t;
      })
    );
    send({ command: "set_track_mute", track_index: trackIndex, muted: muted });
  }

  function setSettingsStatus(message, type) {
    $settingsStatus.textContent = message || "";
    $settingsStatus.className = "settings-status" + (type ? " " + type : "");
  }

  // ── Rendering ────────────────────────────────────────────────────

  function render() {
    if (currentView === "mixer") {
      syncMixerFromState();
    }
    // Connection badge (scanning takes precedence while project scan runs)
    if (!scanInProgress) {
      setBadge(state.connection_status || "disconnected");
    }

    // Error banner
    if (state.timeline_errors && state.timeline_errors.length > 0) {
      $errorBanner.textContent = state.timeline_errors.join(" | ");
      $errorBanner.classList.remove("hidden");
    } else {
      $errorBanner.classList.add("hidden");
    }

    // Now playing
    $songName.textContent = state.active_song ? state.active_song.name : "--";

    // Transport info
    $position.textContent = formatBeat(state.transport_position || 0);
    $tempo.textContent = (state.tempo || 120) + " BPM";
    $timeSig.textContent =
      (state.signature_numerator || 4) + "/" + (state.signature_denominator || 4);

    // Play button state
    if (state.is_playing) {
      $btnPlay.classList.add("playing");
      $btnPlay.textContent = "Playing";
    } else {
      $btnPlay.classList.remove("playing");
      $btnPlay.textContent = "Play";
    }

    // Active song highlight in list
    syncPlayheadFromState();
    renderSongListIfNeeded();
    renderSongListHighlight();
    if (!state.is_playing) {
      paintLiveVisuals();
      tickSlidingDisplays(16);
    }
    ensureProgressLoop();
    renderAutoAdvance();
  }

  function renderSongListIfNeeded() {
    if (currentView !== "performance") return;
    const key = state.active_setlist
      ? "sl-" +
        state.active_setlist.id +
        "-" +
        (state.active_setlist.entries || []).length
      : "tl-" + songs.length;
    if (key !== lastSongListKey) {
      lastSongListKey = key;
      renderSongList();
    }
  }

  function renderAutoAdvance() {
    if (!$autoAdvanceInfo) return;
    const aa = state.auto_advance;
    if (aa && aa.active) {
      $autoAdvanceInfo.textContent =
        "Next: " +
        (aa.next_song_name || "?") +
        " in " +
        aa.seconds_remaining +
        "s";
      $autoAdvanceInfo.classList.remove("hidden");
    } else {
      $autoAdvanceInfo.textContent = "";
      $autoAdvanceInfo.classList.add("hidden");
    }
  }

  function renderSongList() {
    if (!$songList) return;
    $songList.innerHTML = "";
    const list = getPerformanceSongs();
    list.forEach(function (song, i) {
      const li = document.createElement("li");
      li.dataset.index = i;
      const name = song.song_name || song.name;
      li.dataset.songName = name;
      const timeline = findSongByName(name) || song;
      if (timeline.start_beat != null) {
        li.dataset.startBeat = timeline.start_beat;
      }
      if (timeline.end_beat != null) {
        li.dataset.endBeat = timeline.end_beat;
      }
      let durationHtml = "";
      const durationBeats =
        timeline.duration_beats != null ? timeline.duration_beats : null;
      if (durationBeats != null) {
        durationHtml =
          '<span class="song-duration">' +
          formatBeatDuration(durationBeats) +
          "</span>";
      }
      li.innerHTML =
        '<div class="song-row">' +
        '<span class="song-index">' +
        (i + 1) +
        '</span><span class="song-label">' +
        escHtml(name) +
        "</span>" +
        durationHtml +
        "</div>" +
        '<div class="progress-bar song-progress" aria-hidden="true">' +
        '<div class="progress-bar-fill"></div>' +
        "</div>";
      li.addEventListener("click", function () {
        if (clientLocked) return;
        jumpToPerformanceIndex(i);
      });
      $songList.appendChild(li);
    });
    paintLiveVisuals();
  }

  function renderSongListHighlight() {
    const items = $songList.querySelectorAll("li");
    let activeIdx = state.active_song_index;
    if (state.active_setlist) {
      activeIdx = findPerformanceListIndex(state.active_setlist_index);
    }
    items.forEach(function (li) {
      const idx = parseInt(li.dataset.index, 10);
      if (idx === activeIdx) {
        li.classList.add("active");
      } else {
        li.classList.remove("active");
      }
    });
  }

  function renderSetlistEditor() {
    if (!$availableSongs || !$editorSetlist) return;

    const usedNames = {};
    editorSetlist.entries.forEach(function (e) {
      usedNames[e.song_name] = true;
    });

    $availableSongs.innerHTML = "";
    songs.forEach(function (song) {
      if (usedNames[song.name]) return;
      const li = document.createElement("li");
      li.draggable = true;
      li.dataset.songName = song.name;
      li.textContent = song.name;
      li.addEventListener("click", function () {
        addSongToEditor(song.name);
      });
      li.addEventListener("dragstart", onAvailableDragStart);
      $availableSongs.appendChild(li);
    });
    if (!$availableSongs.children.length) {
      const empty = document.createElement("li");
      empty.className = "editor-setlist-empty";
      empty.textContent = "All songs are in the setlist";
      empty.style.border = "none";
      empty.style.background = "transparent";
      $availableSongs.appendChild(empty);
    }

    $editorSetlist.innerHTML = "";
    if (!editorSetlist.entries.length) {
      const empty = document.createElement("li");
      empty.className = "editor-setlist-empty";
      empty.textContent = "Drag songs here or click to add";
      $editorSetlist.appendChild(empty);
    } else {
      editorSetlist.entries.forEach(function (entry, i) {
        appendEditorEntry(entry, i);
      });
    }

    setupEditorDropZones();
  }

  function appendEditorEntry(entry, index) {
    const row = document.createElement("li");
    row.className = "setlist-entry-row";
    row.draggable = true;
    row.dataset.index = index;
    if (!songNameExists(entry.song_name)) {
      row.classList.add("missing");
    }
    row.innerHTML =
      '<span class="drag-handle">⠿</span>' +
      '<span class="setlist-entry-label">' +
      escHtml(entry.song_name) +
      (songNameExists(entry.song_name) ? "" : " (missing)") +
      '</span><button type="button" class="btn btn-secondary btn-remove-entry">Remove</button>';
    row.querySelector(".btn-remove-entry").addEventListener("click", function (e) {
      e.stopPropagation();
      editorSetlist.entries.splice(index, 1);
      renderSetlistEditor();
    });
    row.addEventListener("dragstart", onEntryDragStart);
    row.addEventListener("dragover", onEntryDragOver);
    row.addEventListener("drop", onEntryDrop);
    row.addEventListener("dragend", onDragEnd);
    $editorSetlist.appendChild(row);

    if (index < editorSetlist.entries.length - 1) {
      const transitionRow = document.createElement("li");
      transitionRow.className = "setlist-transition-row";
      transitionRow.dataset.gapIndex = index;
      const autoCue = !!entry.auto_cue_next;
      transitionRow.innerHTML =
        '<label class="auto-cue-label">' +
        '<input type="checkbox" class="auto-cue-checkbox"' +
        (autoCue ? " checked" : "") +
        "> Auto-cue next song</label>" +
        '<span class="gap-control' +
        (autoCue ? "" : " hidden") +
        '"><label>Wait (s)</label>' +
        '<input type="number" class="gap-seconds-input" min="0" step="0.5" value="' +
        (entry.gap_seconds != null ? entry.gap_seconds : 0) +
        '"></span>';
      const checkbox = transitionRow.querySelector(".auto-cue-checkbox");
      const gapControl = transitionRow.querySelector(".gap-control");
      const gapInput = transitionRow.querySelector(".gap-seconds-input");
      checkbox.addEventListener("change", function (e) {
        editorSetlist.entries[index].auto_cue_next = e.target.checked;
        gapControl.classList.toggle("hidden", !e.target.checked);
      });
      gapInput.addEventListener("change", function (e) {
        editorSetlist.entries[index].gap_seconds = Math.max(
          0,
          parseFloat(e.target.value) || 0
        );
      });
      $editorSetlist.appendChild(transitionRow);
    }
  }

  function addSongToEditor(songName) {
    if (
      editorSetlist.entries.some(function (e) {
        return e.song_name === songName;
      })
    ) {
      return;
    }
    editorSetlist.entries.push({
      song_name: songName,
      auto_cue_next: false,
      gap_seconds: 0,
      notes: "",
    });
    renderSetlistEditor();
  }

  function setupEditorDropZones() {
    if (editorDropZonesReady || !$availableSongs || !$editorSetlist) return;
    editorDropZonesReady = true;
    [$availableSongs, $editorSetlist].forEach(function (el) {
      el.addEventListener("dragover", function (e) {
        e.preventDefault();
        el.classList.add("drag-over");
      });
      el.addEventListener("dragleave", function () {
        el.classList.remove("drag-over");
      });
      el.addEventListener("drop", function (e) {
        e.preventDefault();
        el.classList.remove("drag-over");
        if (dragSource && dragSource.type === "available") {
          addSongToEditor(dragSource.songName);
        }
      });
    });
  }

  function onAvailableDragStart(e) {
    dragSource = { type: "available", songName: e.target.dataset.songName };
    e.dataTransfer.effectAllowed = "copy";
  }

  function onEntryDragStart(e) {
    dragSource = { type: "entry", index: parseInt(e.currentTarget.dataset.index, 10) };
    e.currentTarget.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
  }

  function onEntryDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }

  function onEntryDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    if (!dragSource || dragSource.type !== "entry") return;
    const targetIndex = parseInt(e.currentTarget.dataset.index, 10);
    if (targetIndex === dragSource.index) return;
    const entries = editorSetlist.entries;
    const item = entries.splice(dragSource.index, 1)[0];
    entries.splice(targetIndex, 0, item);
    renderSetlistEditor();
  }

  function onDragEnd(e) {
    if (e.currentTarget.classList) {
      e.currentTarget.classList.remove("dragging");
    }
    dragSource = null;
  }

  function buildEditorPayload() {
    return {
      name: ($setlistName && $setlistName.value.trim()) || "Untitled",
      entries: editorSetlist.entries.map(function (e, i) {
        return {
          song_name: e.song_name,
          order: i,
          auto_cue_next: !!e.auto_cue_next,
          gap_seconds: e.gap_seconds != null ? e.gap_seconds : 0,
          notes: e.notes || "",
        };
      }),
    };
  }

  function setBadge(status) {
    $badge.textContent = status;
    $badge.className = "badge badge-" + status;
  }

  // ── Helpers ──────────────────────────────────────────────────────

  function formatBeat(beats) {
    if (beats == null) return "--";
    const bar = Math.floor(beats / 4) + 1;
    const beat = (beats % 4) + 1;
    return bar + "." + beat.toFixed(1);
  }

  function formatBeatDuration(beats) {
    if (beats == null) return "--";
    const bars = Math.round(beats / 4);
    return bars + " bars";
  }

  function escHtml(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  // ── Event handlers ───────────────────────────────────────────────

  $btnPlay.addEventListener("click", function () {
    send({ command: "play" });
  });

  $btnStop.addEventListener("click", function () {
    send({ command: "stop" });
  });

  $btnPrev.addEventListener("click", function () {
    const list = getPerformanceSongs();
    if (state.active_setlist) {
      const currentIdx = findPerformanceListIndex(state.active_setlist_index);
      if (currentIdx != null && currentIdx > 0) {
        jumpToPerformanceIndex(currentIdx - 1);
      }
      return;
    }
    const idx = (state.active_song_index != null ? state.active_song_index : 0) - 1;
    if (idx >= 0) {
      jumpToPerformanceIndex(idx);
    }
  });

  $btnNext.addEventListener("click", function () {
    const list = getPerformanceSongs();
    if (state.active_setlist) {
      const currentIdx = findPerformanceListIndex(state.active_setlist_index);
      if (currentIdx != null && currentIdx + 1 < list.length) {
        jumpToPerformanceIndex(currentIdx + 1);
      }
      return;
    }
    const idx = (state.active_song_index != null ? state.active_song_index : 0) + 1;
    if (idx < list.length) {
      jumpToPerformanceIndex(idx);
    }
  });

  $btnRescan.addEventListener("click", function () {
    if (
      !confirm(
        "Re-scan the arrangement from Ableton? This can take several minutes on large projects."
      )
    ) {
      return;
    }
    showScanProgress({
      title: "Re-scanning project",
      status: "Re-scanning arrangement from Ableton…",
      clear: true,
    });
    send({ command: "rescan" });
  });

  const $viewNav = document.getElementById("view-nav");
  if ($viewNav) {
    $viewNav.addEventListener("click", function (e) {
      const btn = e.target.closest("[data-view]");
      if (!btn) return;
      setView(btn.dataset.view);
    });
  }

  if ($btnLock) {
    $btnLock.addEventListener("click", toggleClientLock);
  }

  if ($settingsForm) {
    $settingsForm.addEventListener("submit", function (e) {
    e.preventDefault();
    setSettingsStatus("Saving...", "");

    const payload = {
      ableton_osc_host: $settingsForm.ableton_osc_host.value.trim(),
    };

    saveSettings(payload)
      .then(function (data) {
        appSettings = data;
        populateSettingsForm();
        setSettingsStatus("Saved", "success");
      })
      .catch(function (err) {
        const message =
          err && typeof err === "object"
            ? Object.values(err).flat().join(" ")
            : "Failed to save settings";
        setSettingsStatus(message, "error");
      });
    });
  }

  if ($setlistLoad) {
    $setlistLoad.addEventListener("change", function () {
      const id = $setlistLoad.value;
      if (!id) return;
      apiFetch("/api/setlists/" + id + "/")
        .then(loadEditorSetlist)
        .catch(function (err) {
          setSetlistEditorStatus("Failed to load setlist", "error");
          console.error(err);
        });
    });
  }

  if ($btnSetlistNew) {
    $btnSetlistNew.addEventListener("click", function () {
      resetEditorSetlist();
      setSetlistEditorStatus("New setlist", "");
    });
  }

  if ($btnSetlistSave) {
    $btnSetlistSave.addEventListener("click", function () {
      const payload = buildEditorPayload();
      if (!payload.entries.length) {
        setSetlistEditorStatus("Add at least one song", "error");
        return;
      }
      setSetlistEditorStatus("Saving...", "");
      const req = editorSetlist.id
        ? apiFetch("/api/setlists/" + editorSetlist.id + "/", {
            method: "PUT",
            body: payload,
          })
        : apiFetch("/api/setlists/", { method: "POST", body: payload });
      req
        .then(function (data) {
          loadEditorSetlist(data);
          return fetchSetlists();
        })
        .then(function () {
          setSetlistEditorStatus("Saved", "success");
        })
        .catch(function (err) {
          const message =
            err && typeof err === "object"
              ? Object.values(err).flat().join(" ")
              : "Failed to save";
          setSetlistEditorStatus(message, "error");
        });
    });
  }

  if ($btnSetlistDelete) {
    $btnSetlistDelete.addEventListener("click", function () {
      if (!editorSetlist.id) {
        resetEditorSetlist();
        return;
      }
      if (!confirm("Delete setlist \"" + editorSetlist.name + "\"?")) return;
      apiFetch("/api/setlists/" + editorSetlist.id + "/", { method: "DELETE" })
        .then(function () {
          resetEditorSetlist();
          return fetchSetlists();
        })
        .then(function () {
          setSetlistEditorStatus("Deleted", "success");
        })
        .catch(function () {
          setSetlistEditorStatus("Failed to delete", "error");
        });
    });
  }

  if ($btnSetlistActivate) {
    $btnSetlistActivate.addEventListener("click", function () {
      if (!editorSetlist.id) {
        setSetlistEditorStatus("Save the setlist first", "error");
        return;
      }
      apiFetch("/api/setlists/" + editorSetlist.id + "/activate/", {
        method: "POST",
      })
        .then(function (data) {
          loadEditorSetlist(data);
          return fetchSetlists();
        })
        .then(function () {
          setSetlistEditorStatus("Activated", "success");
          lastSongListKey = null;
          renderSongListIfNeeded();
        })
        .catch(function () {
          setSetlistEditorStatus("Failed to activate", "error");
        });
    });
  }

  // Keyboard shortcuts
  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    switch (e.code) {
      case "Space":
        if (clientLocked) return;
        e.preventDefault();
        send({ command: state.is_playing ? "stop" : "play" });
        break;
      case "ArrowRight":
        if (clientLocked) return;
        e.preventDefault();
        $btnNext.click();
        break;
      case "ArrowLeft":
        if (clientLocked) return;
        e.preventDefault();
        $btnPrev.click();
        break;
      case "Escape":
        if (document.body.classList.contains("fullscreen-mode")) {
          exitFullscreen();
        }
        break;
      case "KeyF":
        if (currentView === "performance" && !document.body.classList.contains("fullscreen-mode")) {
          enterFullscreen();
        }
        break;
    }
  });

  // Expand lyrics toggle
  var $btnLyricsExpand = document.getElementById("btn-lyrics-expand");
  var $lyricsDisplayWrapper = document.getElementById("lyrics-display-wrapper");
  if ($btnLyricsExpand && $lyricsDisplayWrapper) {
    $btnLyricsExpand.addEventListener("click", function () {
      $lyricsDisplayWrapper.classList.toggle("expanded");
      if (lyricsSlidingDisplay) {
        lyricsSlidingDisplay.layoutDirty = true;
        lyricsSlidingDisplay.measuredIndex = -1;
        lyricsSlidingDisplay.activeIndex = -2;
        paintLiveVisuals();
        tickSlidingDisplays(16);
        setTimeout(function () {
          if (lyricsSlidingDisplay) {
            lyricsSlidingDisplay.layoutDirty = true;
            lyricsSlidingDisplay.measuredIndex = -1;
            lyricsSlidingDisplay.activeIndex = -2;
            paintLiveVisuals();
            tickSlidingDisplays(16);
          }
        }, 750);
      }
    });
  }

  // Fullscreen mode
  var $btnExitFullscreen = document.getElementById("btn-exit-fullscreen");

  function enterFullscreen() {
    document.body.classList.add("fullscreen-mode");
    $btnExitFullscreen.classList.remove("hidden");
    var el = document.documentElement;
    if (el.requestFullscreen) {
      el.requestFullscreen().catch(function () {});
    } else if (el.webkitRequestFullscreen) {
      el.webkitRequestFullscreen();
    }
    invalidateSlidingLayouts();
    paintLiveVisuals();
    tickSlidingDisplays(16);
  }

  function exitFullscreen() {
    document.body.classList.remove("fullscreen-mode");
    $btnExitFullscreen.classList.add("hidden");
    if (document.fullscreenElement || document.webkitFullscreenElement) {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(function () {});
      } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen();
      }
    }
    invalidateSlidingLayouts();
    paintLiveVisuals();
    tickSlidingDisplays(16);
  }

  if ($btnFullscreen) {
    $btnFullscreen.addEventListener("click", enterFullscreen);
  }

  if ($btnExitFullscreen) {
    $btnExitFullscreen.addEventListener("click", exitFullscreen);
  }

  document.addEventListener("fullscreenchange", function () {
    if (!document.fullscreenElement && !document.webkitFullscreenElement) {
      document.body.classList.remove("fullscreen-mode");
      $btnExitFullscreen.classList.add("hidden");
    }
  });

  document.addEventListener("webkitfullscreenchange", function () {
    if (!document.fullscreenElement && !document.webkitFullscreenElement) {
      document.body.classList.remove("fullscreen-mode");
      $btnExitFullscreen.classList.add("hidden");
    }
  });

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      syncPlayheadFromState();
      paintLiveVisuals();
    }
  });

  // ── Init ─────────────────────────────────────────────────────────
  function loadCachedArrangement() {
    return Promise.all([
      fetchSongs(),
      fetchSections(),
      fetchChords(),
      fetchLyrics(),
    ]);
  }

  function init() {
    sectionSlidingDisplay = new SlidingDisplay("section-sliding-container", "section-sliding-track", "sections");
    chordsSlidingDisplay = new SlidingDisplay("chords-sliding-container", "chords-sliding-track", "chords");
    lyricsSlidingDisplay = new SlidingDisplay("lyrics-sliding-container", "lyrics-sliding-track", "lyrics");

    if (debugSyncEnabled) {
      ensureSyncDebugOverlay();
      updateSyncDebugOverlay();
    }

    setView("performance");
    applyLockState();
    loadCachedArrangement();
    connect();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
