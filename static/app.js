/**
 * StageAble — Frontend application
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
  let currentAdminPanel = "projects";
  let controlDevices = [];
  let controlActions = {};
  let reconnectTimer = null;
  const RECONNECT_DELAY = 2000;

  // Setlist editor state
  let savedSetlists = [];
  let editorSetlist = { id: null, name: "", is_active: false, entries: [] };
  let dragSource = null;
  let lastSongListKey = null;
  let lastHighlightedListIndex = null;
  let editorDropZonesReady = false;

  // Mixer view state
  let mixerTracks = [];
  let mixerFetchId = 0;
  /** While set: ignore stale mixer_tracks from poll until server confirms. */
  let mixerPending = null;
  let savedMixerPresets = [];
  let editorMixerPreset = { id: null, name: "" };
  let mixerPresetApplying = false;

  // X32 view state
  let x32Mixer = { status: {}, channels: [] };
  let x32Control = { baseline_ready: false, changes: [], operations: [], snapshots: [] };
  let currentX32Panel = "mixer";
  let selectedX32Channel = 1;
  let x32PollTimer = null;
  let x32MixerEditing = false;

  // Rehearsal view state
  let rehearsalSelection = [];

  // Projects view state
  let savedProjects = [];
  let renamingProjectId = null;

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
  let slidingAnimationEnabled = false;
  let slidingAnimationDurationMs = 100;
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
  const $projectName  = document.getElementById("project-name");
  const $btnLock      = document.getElementById("btn-lock");
  const $transportControls = document.getElementById("transport-controls");
  const $viewPerformance = document.getElementById("view-performance");
  const $viewSetlist = document.getElementById("view-setlist");
  const $viewMixer = document.getElementById("view-mixer");
  const $viewX32 = document.getElementById("view-x32");
  const $viewRehearsal = document.getElementById("view-rehearsal");
  const $viewAdmin = document.getElementById("view-admin");
  const $adminPanelProjects = document.getElementById("admin-panel-projects");
  const $adminPanelSettings = document.getElementById("admin-panel-settings");
  const $adminPanelDevices = document.getElementById("admin-panel-devices");
  const $adminPanelRescan = document.getElementById("admin-panel-rescan");
  const $navPerformance = document.getElementById("nav-performance");
  const $navSetlist = document.getElementById("nav-setlist");
  const $navMixer = document.getElementById("nav-mixer");
  const $navX32 = document.getElementById("nav-x32");
  const $navRehearsal = document.getElementById("nav-rehearsal");
  const $navAdmin = document.getElementById("nav-admin");
  const $navAdminProjects = document.getElementById("nav-admin-projects");
  const $navAdminSettings = document.getElementById("nav-admin-settings");
  const $navAdminDevices = document.getElementById("nav-admin-devices");
  const $navAdminRescan = document.getElementById("nav-admin-rescan");
  const $x32Subnav = document.getElementById("x32-subnav");
  const $x32PanelMixer = document.getElementById("x32-panel-mixer");
  const $x32PanelEvents = document.getElementById("x32-panel-events");
  const $x32ConnectionStatus = document.getElementById("x32-connection-status");
  const $x32ChannelStrips = document.getElementById("x32-channel-strips");
  const $x32ChannelDetail = document.getElementById("x32-channel-detail");
  const $x32ChannelDetailTitle = document.getElementById("x32-channel-detail-title");
  const $x32ChannelControls = document.getElementById("x32-channel-controls");
  const $x32ChannelSends = document.getElementById("x32-channel-sends");
  const $x32MixerStatus = document.getElementById("x32-mixer-status");
  const $x32EventsStatus = document.getElementById("x32-events-status");
  const $x32ChangeList = document.getElementById("x32-change-list");
  const $x32SnapshotList = document.getElementById("x32-snapshot-list");
  const $x32OperationList = document.getElementById("x32-operation-list");
  const $adminSubnav = document.getElementById("admin-subnav");
  const $mixerTrackList = document.getElementById("mixer-track-list");
  const $mixerStatus = document.getElementById("mixer-status");
  const $mixerPresetName = document.getElementById("mixer-preset-name");
  const $mixerPresetLoad = document.getElementById("mixer-preset-load");
  const $mixerPresetStatus = document.getElementById("mixer-preset-status");
  const $btnMixerPresetNew = document.getElementById("btn-mixer-preset-new");
  const $btnMixerPresetSave = document.getElementById("btn-mixer-preset-save");
  const $btnMixerPresetDelete = document.getElementById("btn-mixer-preset-delete");
  const $rehearsalSectionList = document.getElementById("rehearsal-section-list");
  const $rehearsalSongContext = document.getElementById("rehearsal-song-context");
  const $btnRehearsalLoop = document.getElementById("btn-rehearsal-loop");
  const $btnRehearsalStop = document.getElementById("btn-rehearsal-stop");
  const $rehearsalStatus = document.getElementById("rehearsal-status");
  const $settingsForm = document.getElementById("settings-form");
  const $settingsStatus = document.getElementById("settings-status");
  const $deviceList = document.getElementById("device-list");
  const $devicesStatus = document.getElementById("devices-status");
  const $btnDeviceRefresh = document.getElementById("btn-device-refresh");
  const $btnBluetoothPair = document.getElementById("btn-bluetooth-pair");
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
  const $projectList = document.getElementById("project-list");
  const $projectsStatus = document.getElementById("projects-status");
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
    if (currentView === "rehearsal") {
      renderRehearsalList();
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

  function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  const CAROUSEL_MAX_PREV = 1;
  const CAROUSEL_MAX_NEXT = 3;

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

      var transition =
        slidingAnimationEnabled && playhead.playing && !rebuilt
          ? this.getBeatTransition(items, beat)
          : null;

      if (
        idx === this.activeIndex &&
        showNext === this.nextPreviewShown &&
        !transition
      ) {
        return;
      }

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
      this.targetCenterIndex = centerIdx;

      if (transition) {
        this.setTransitionClasses(
          transition.fromIdx,
          transition.toIdx,
          items,
          songStartBeat,
          songEndBeat
        );
        this.applyBeatTransition(transition);
        return;
      }

      this.setClasses(idx, items, beat, songStartBeat, songEndBeat, showNext, nextIdx);
      this.layoutDirty = true;
      this.snapToTarget(centerIdx);
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

    getBeatTransition(items, beat) {
      var bps = playhead.beatsPerSecond || (state.tempo || 120) / 60;
      if (!bps) return null;

      var leadBeats = (slidingAnimationDurationMs / 1000) * bps;
      if (leadBeats <= 0) return null;

      var nextIdx = this.findNext(items, beat);
      if (nextIdx < 0) return null;

      var nextStart = items[nextIdx].start_beat;
      var animStartBeat = nextStart - leadBeats;
      if (beat < animStartBeat || beat >= nextStart) return null;

      var fromIdx = this.findActive(items, beat);
      if (fromIdx < 0) return null;

      if (nextStart - items[fromIdx].start_beat < leadBeats) {
        return null;
      }

      var progress = (beat - animStartBeat) / leadBeats;
      return {
        fromIdx: fromIdx,
        toIdx: nextIdx,
        progress: Math.max(0, Math.min(1, progress)),
      };
    }

    isLimitedCarousel() {
      return (
        this.itemsArrayName === "sections" || this.itemsArrayName === "chords"
      );
    }

    nextRoleForOffset(offset) {
      if (offset === 1) return "next";
      if (offset === 2) return "next2";
      if (offset === 3) return "next3";
      return "offscreen";
    }

    resolveItemRole(i, activeIdx, items, songStartBeat, songEndBeat, opts) {
      opts = opts || {};
      var showNext = opts.showNext;
      var nextIdx = opts.nextIdx;
      var expandedLyrics =
        this.itemsArrayName === "lyrics" && this.$container.closest(".expanded");
      var limited = this.isLimitedCarousel();

      if (activeIdx >= 0 && i === activeIdx) return "current";

      if (
        activeIdx >= 0 &&
        i === activeIdx - 1 &&
        items[i].start_beat >= songStartBeat
      ) {
        return "prev";
      }

      if (limited && activeIdx >= 0) {
        if (
          i > activeIdx &&
          i <= activeIdx + CAROUSEL_MAX_NEXT &&
          items[i].start_beat < songEndBeat
        ) {
          return this.nextRoleForOffset(i - activeIdx);
        }
        return "offscreen";
      }

      if (
        activeIdx >= 0 &&
        i === activeIdx + 1 &&
        items[i].start_beat < songEndBeat
      ) {
        return "next";
      }
      if (
        expandedLyrics &&
        activeIdx >= 0 &&
        i === activeIdx + 2 &&
        items[i].start_beat < songEndBeat
      ) {
        return "next2";
      }
      if (activeIdx === -1 && showNext && i === nextIdx) return "next";
      return "offscreen";
    }

    trimNextItemsToFit(activeIdx) {
      if (!this.isLimitedCarousel() || activeIdx < 0 || !this.$container) {
        return;
      }

      var containerW = this.$container.getBoundingClientRect().width;
      if (!containerW) return;

      var gap = 40;
      var currentEl = this.elements[activeIdx];
      if (!currentEl) return;

      var currentW = currentEl.getBoundingClientRect().width;
      var rightBudget = Math.max(0, containerW / 2 - currentW / 2 - gap);
      var visibleOffsets = [];

      for (var offset = 1; offset <= CAROUSEL_MAX_NEXT; offset++) {
        var idx = activeIdx + offset;
        var el = this.elements[idx];
        if (!el || el.classList.contains("offscreen")) continue;
        visibleOffsets.push(offset);
      }

      var self = this;
      function nextWidth(offsets) {
        var total = 0;
        for (var k = 0; k < offsets.length; k++) {
          var nextEl = self.elements[activeIdx + offsets[k]];
          if (!nextEl) continue;
          total += nextEl.getBoundingClientRect().width;
          if (k > 0) total += gap;
        }
        return total;
      }

      while (visibleOffsets.length && nextWidth(visibleOffsets) > rightBudget) {
        var removed = visibleOffsets.pop();
        this.elements[activeIdx + removed].className = "sliding-item offscreen";
      }
    }

    setTransitionClasses(fromIdx, toIdx, items, songStartBeat, songEndBeat) {
      for (var i = 0; i < this.elements.length; i++) {
        var role = "offscreen";
        if (i === fromIdx) role = "current";
        else if (i === toIdx) role = "next";
        else if (
          fromIdx >= 0 &&
          i === fromIdx - 1 &&
          items[i].start_beat >= songStartBeat
        ) {
          role = "prev";
        } else if (this.isLimitedCarousel()) {
          if (
            i === toIdx + 1 &&
            toIdx + 1 < items.length &&
            items[i].start_beat < songEndBeat
          ) {
            role = "next2";
          } else if (
            i === toIdx + 2 &&
            toIdx + 2 < items.length &&
            items[i].start_beat < songEndBeat
          ) {
            role = "next3";
          }
        } else if (
          this.itemsArrayName === "lyrics" &&
          this.$container.closest(".expanded") &&
          fromIdx >= 0 &&
          i === fromIdx + 2 &&
          items[i].start_beat < songEndBeat
        ) {
          role = "next2";
        }
        this.elements[i].className = "sliding-item " + role;
      }
      if (this.isLimitedCarousel()) {
        this.trimNextItemsToFit(fromIdx);
      }
    }

    applyBeatTransition(transition) {
      var fromOff = this.measureTargetOffset(transition.fromIdx);
      var toOff = this.measureTargetOffset(transition.toIdx);
      if (!fromOff || !toOff) {
        this.snapToTarget(transition.toIdx);
        return;
      }

      var t = easeOutCubic(transition.progress);
      this.offsetX = fromOff.x + (toOff.x - fromOff.x) * t;
      this.offsetY = fromOff.y + (toOff.y - fromOff.y) * t;
      this.targetOffset = toOff;
      this.measuredIndex = transition.toIdx;
      this.layoutDirty = false;
      this.animating = transition.progress < 1;
      this.applyTransform();
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
      if (this.isLimitedCarousel() && activeIdx === -1 && showNext) {
        for (var i = 0; i < this.elements.length; i++) {
          var previewRole = "offscreen";
          if (
            i >= nextIdx &&
            i < nextIdx + CAROUSEL_MAX_NEXT &&
            items[i].start_beat < songEndBeat
          ) {
            previewRole =
              i === nextIdx
                ? "current"
                : this.nextRoleForOffset(i - nextIdx);
          }
          this.elements[i].className = "sliding-item " + previewRole;
        }
        this.trimNextItemsToFit(nextIdx);
        return;
      }

      for (var j = 0; j < this.elements.length; j++) {
        var role = this.resolveItemRole(
          j,
          activeIdx,
          items,
          songStartBeat,
          songEndBeat,
          { showNext: showNext, nextIdx: nextIdx }
        );
        this.elements[j].className = "sliding-item " + role;
      }

      if (this.isLimitedCarousel()) {
        this.trimNextItemsToFit(activeIdx);
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

      if (!slidingAnimationEnabled) {
        if (this.layoutDirty || this.measuredIndex !== this.targetCenterIndex) {
          this.snapToTarget(this.targetCenterIndex);
        }
        this.animating = false;
        return;
      }

      if (this.layoutDirty) {
        this.snapToTarget(this.targetCenterIndex);
      }
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
      } else if (msg.type === "x32_ack") {
        if (msg.command === "x32_test") {
          const result = msg.data || {};
          const identity = [result.model || "X32", result.firmware || ""]
            .filter(Boolean)
            .join(" · ");
          setSettingsStatus("Connected to " + identity, "success");
        } else {
          const messages = {
            x32_initialize_baseline: "Recording external changes from the captured baseline.",
            x32_save_operation: "Operation saved. Recording continues from the current mixer state.",
            x32_save_snapshot: "Snapshot saved. Recording continues from the current mixer state.",
            x32_apply_operation: "Operation applied.",
            x32_rollback_operation: "Operation rolled back.",
            x32_restore_snapshot: "Snapshot loaded.",
            x32_refresh: "Mixer state refreshed.",
            x32_set: "Mixer updated.",
            x32_phantom: "Phantom power updated.",
            x32_open_editor: "X32-Edit opened.",
            x32_delete: "Deleted.",
          };
          setX32Status(messages[msg.command] || "Completed.", "success");
        }
        fetchX32Data();
      } else if (msg.type === "error") {
        console.error("Server error:", msg.message);
        if (currentView === "mixer") {
          mixerPending = null;
          syncMixerFromState();
          setMixerStatus(msg.message, "error");
        }
        if (currentView === "x32") setX32Status(msg.message, "error");
        if (msg.command === "x32_test") setSettingsStatus(msg.message, "error");
      } else if (msg.type === "lock_state") {
        setClientLocked(!!msg.locked);
      } else if (msg.type === "unlock_check") {
        handleUnlockCheck(!!msg.requires_warning);
      } else if (msg.type === "scan_status" || msg.type === "scan_progress") {
        applyScanStatus(msg);
      } else if (msg.type === "devices_changed") {
        if (msg.data && msg.data.devices) {
          controlDevices = msg.data.devices;
          renderDevices();
        }
      } else if (msg.type === "device_learn") {
        handleDeviceLearn(msg.data || {});
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

  function applySlidingAnimationFromSettings() {
    slidingAnimationEnabled = appSettings.sliding_animation_enabled === true;
    const duration = parseInt(appSettings.sliding_animation_duration_ms, 10);
    slidingAnimationDurationMs = Number.isFinite(duration)
      ? Math.max(0, Math.min(2000, duration))
      : 100;
    if (currentView === "performance") {
      paintLiveVisuals();
      tickSlidingDisplays(16);
    }
  }

  function fetchSettings() {
    return fetch("/api/settings/")
      .then((r) => r.json())
      .then((data) => {
        appSettings = data;
        populateSettingsForm();
        applySlidingAnimationFromSettings();
        updateX32Availability();
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

  function setDevicesStatus(message, type) {
    if (!$devicesStatus) return;
    $devicesStatus.textContent = message || "";
    $devicesStatus.className = "settings-status" + (type ? " " + type : "");
  }

  function describeTrigger(trigger) {
    if (!trigger) return "Unknown input";
    if (trigger.type === "note") return "Note " + trigger.note + " · ch " + (trigger.channel + 1);
    if (trigger.type === "cc") return "CC " + trigger.control + " · ch " + (trigger.channel + 1);
    if (trigger.type === "program") return "Program " + trigger.program + " · ch " + (trigger.channel + 1);
    if (trigger.type === "hid") return "HID " + trigger.usage_page + ":" + trigger.usage;
    return JSON.stringify(trigger);
  }

  function renderDevices() {
    if (!$deviceList) return;
    $deviceList.innerHTML = "";
    if (!controlDevices.length) {
      $deviceList.innerHTML = '<p class="form-hint">No supported devices found. Connect a MIDI controller or pair a Bluetooth HID remote, then refresh.</p>';
      return;
    }
    controlDevices.forEach(function (device) {
      const card = document.createElement("article");
      card.className = "device-card";
      const options = Object.keys(controlActions).map(function (key) {
        return '<option value="' + escHtml(key) + '">' + escHtml(controlActions[key]) + "</option>";
      }).join("");
      const mappings = (device.mappings || []).map(function (mapping) {
        return '<li><span>' + escHtml(mapping.action_label || mapping.action) + ' ← ' + escHtml(describeTrigger(mapping.trigger)) + '</span>' +
          '<button class="btn btn-small btn-danger" data-delete-mapping="' + mapping.id + '" type="button">Delete</button></li>';
      }).join("");
      card.innerHTML =
        '<div class="device-card-heading"><div><strong>' + escHtml(device.name) + '</strong>' +
        '<span class="device-meta">' + escHtml(device.adapter) + ' · ' + (device.connected ? "Connected" : "Disconnected") + '</span></div>' +
        '<label><input data-device-toggle="' + device.id + '" type="checkbox" ' + (device.enabled ? "checked" : "") + '> Enabled</label></div>' +
        (device.adapter === "bluetooth_hid" ? '<p class="device-meta">Input Monitoring: ' + (device.details && device.details.input_monitoring ? "Allowed" : "Denied") + ' · Accessibility: ' + (device.details && device.details.accessibility ? "Allowed" : "Denied") + '</p>' : "") +
        (device.error ? '<p class="device-error">' + escHtml(device.error) + '</p>' : "") +
        (device.last_input ? '<p class="device-meta">Last input: ' + escHtml(describeTrigger(device.last_input.trigger)) + '</p>' : "") +
        '<div class="device-learn"><select data-action-for="' + device.id + '">' + options + '</select>' +
        '<button class="btn btn-play" data-learn-device="' + device.id + '" type="button" ' + (!device.connected || !device.enabled ? "disabled" : "") + '>Learn input</button></div>' +
        '<ul class="device-mappings">' + (mappings || '<li class="form-hint">No mappings yet.</li>') + '</ul>' +
        '<button class="btn btn-small btn-danger" data-delete-device="' + device.id + '" type="button">Clear configuration</button>';
      $deviceList.appendChild(card);
    });
  }

  function fetchDevices(refresh) {
    return apiFetch(refresh ? "/api/devices/refresh/" : "/api/devices/", refresh ? {method: "POST"} : {})
      .then(function (data) {
        controlDevices = data.devices || [];
        controlActions = data.actions || controlActions;
        if ($navAdminDevices) $navAdminDevices.hidden = false;
        renderDevices();
        return data;
      });
  }

  function handleDeviceLearn(data) {
    if (data.status === "listening") setDevicesStatus("Listening for input…", "");
    else if (data.status === "learned") { setDevicesStatus("Input learned", "success"); fetchDevices(false); }
    else if (data.status === "conflict") {
      if (confirm("That input is already mapped. Reassign it to the selected action?")) {
        apiFetch("/api/device-mappings/" + data.mapping_id + "/", {method: "PATCH", body: {action: data.requested_action}})
          .then(function () { setDevicesStatus("Input reassigned", "success"); return fetchDevices(false); });
      } else setDevicesStatus("Learn cancelled", "");
    } else if (data.status === "timeout") setDevicesStatus("Learn timed out", "error");
    else setDevicesStatus("Learn cancelled", "");
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

  const RENAME_PROJECT_WARNING =
    "Update project path?\n\n" +
    "Use this if you moved or renamed the .als file on disk. " +
    "StageAble will keep your setlists and mixer presets linked to this project.\n\n" +
    "This only updates StageAble's record — it does not move or rename the file on disk.";

  function setProjectsStatus(message, type) {
    if (!$projectsStatus) return;
    $projectsStatus.textContent = message || "";
    $projectsStatus.className =
      "setlist-editor-status" + (type ? " " + type : "");
  }

  function formatProjectDate(value) {
    if (!value) return "Never scanned";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Never scanned";
    return date.toLocaleString();
  }

  function fetchProjects() {
    return apiFetch("/api/projects/")
      .then(function (data) {
        savedProjects = data || [];
        renderProjectList();
      })
      .catch(function () {
        setProjectsStatus("Failed to load projects", "error");
      });
  }

  function renderProjectList() {
    if (!$projectList) return;
    $projectList.innerHTML = "";

    if (!savedProjects.length) {
      const empty = document.createElement("li");
      empty.className = "project-list-empty";
      empty.textContent = "No stored projects yet. Open a Live set and rescan to add one.";
      $projectList.appendChild(empty);
      return;
    }

    savedProjects.forEach(function (project) {
      const row = document.createElement("li");
      row.className = "project-row" + (project.is_active ? " is-active" : "");
      row.dataset.projectId = String(project.id);

      const main = document.createElement("div");
      main.className = "project-row-main";

      const title = document.createElement("div");
      title.className = "project-row-title";
      title.textContent = project.display_name || "Untitled";
      if (project.is_active) {
        const badge = document.createElement("span");
        badge.className = "project-active-badge";
        badge.textContent = "Active";
        title.appendChild(badge);
      }

      const path = document.createElement("div");
      path.className = "project-row-path";
      path.textContent = project.file_path || project.identity || "Unsaved project";
      path.title = project.file_path || project.identity || "";

      const meta = document.createElement("div");
      meta.className = "project-row-meta";
      meta.textContent =
        "Last scanned: " +
        formatProjectDate(project.scanned_at) +
        " · " +
        project.setlist_count +
        " setlist" +
        (project.setlist_count === 1 ? "" : "s") +
        " · " +
        project.mixer_preset_count +
        " mixer preset" +
        (project.mixer_preset_count === 1 ? "" : "s");

      main.appendChild(title);
      main.appendChild(path);
      main.appendChild(meta);
      row.appendChild(main);

      const actions = document.createElement("div");
      actions.className = "project-row-actions";

      const btnRename = document.createElement("button");
      btnRename.className = "btn btn-secondary";
      btnRename.type = "button";
      btnRename.textContent = "Rename";
      btnRename.addEventListener("click", function () {
        startProjectRename(project);
      });

      const btnDelete = document.createElement("button");
      btnDelete.className = "btn btn-stop";
      btnDelete.type = "button";
      btnDelete.textContent = "Delete";
      btnDelete.addEventListener("click", function () {
        deleteProject(project);
      });

      actions.appendChild(btnRename);
      actions.appendChild(btnDelete);
      row.appendChild(actions);

      if (renamingProjectId === project.id) {
        row.appendChild(buildProjectRenameForm(project));
      }

      $projectList.appendChild(row);
    });
  }

  function buildProjectRenameForm(project) {
    const form = document.createElement("div");
    form.className = "project-rename-form";

    const input = document.createElement("input");
    input.type = "text";
    input.className = "setlist-name-input";
    input.placeholder = "Full path to .als file";
    input.value = project.file_path || "";
    input.setAttribute("aria-label", "Project file path");

    const btnSave = document.createElement("button");
    btnSave.className = "btn btn-play";
    btnSave.type = "button";
    btnSave.textContent = "Save path";
    btnSave.addEventListener("click", function () {
      saveProjectRename(project, input.value.trim());
    });

    const btnCancel = document.createElement("button");
    btnCancel.className = "btn btn-secondary";
    btnCancel.type = "button";
    btnCancel.textContent = "Cancel";
    btnCancel.addEventListener("click", function () {
      renamingProjectId = null;
      renderProjectList();
    });

    form.appendChild(input);
    form.appendChild(btnSave);
    form.appendChild(btnCancel);
    return form;
  }

  function startProjectRename(project) {
    if (!confirm(RENAME_PROJECT_WARNING)) return;
    renamingProjectId = project.id;
    renderProjectList();
    const row = $projectList
      ? $projectList.querySelector('[data-project-id="' + project.id + '"]')
      : null;
    if (row) {
      const input = row.querySelector(".project-rename-form input");
      if (input) input.focus();
    }
  }

  function saveProjectRename(project, filePath) {
    if (!filePath) {
      setProjectsStatus("Enter the full path to the .als file", "error");
      return;
    }
    setProjectsStatus("Saving path…", "");
    apiFetch("/api/projects/" + project.id + "/rename/", {
      method: "POST",
      body: { file_path: filePath },
    })
      .then(function () {
        renamingProjectId = null;
        return fetchProjects();
      })
      .then(function () {
        setProjectsStatus("Project path updated", "success");
      })
      .catch(function (err) {
        const message =
          err && typeof err === "object"
            ? Object.values(err).flat().join(" ")
            : "Failed to update project path";
        setProjectsStatus(message, "error");
      });
  }

  function deleteProject(project) {
    const label = project.display_name || "this project";
    let message =
      'Delete project "' +
      label +
      '"?\n\nThis removes the cached scan, setlists, and mixer presets for this project.';
    if (project.is_active) {
      message +=
        "\n\nThis is the active project — the live display will clear until you rescan.";
    }
    if (!confirm(message)) return;

    setProjectsStatus("Deleting…", "");
    apiFetch("/api/projects/" + project.id + "/", { method: "DELETE" })
      .then(function () {
        if (renamingProjectId === project.id) {
          renamingProjectId = null;
        }
        return fetchProjects();
      })
      .then(function () {
        setProjectsStatus("Project deleted", "success");
      })
      .catch(function () {
        setProjectsStatus("Failed to delete project", "error");
      });
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
        (slidingAnimationEnabled && slidingDisplaysAnimating());
      if (shouldPaint) {
        paintLiveVisuals();
        if (slidingAnimationEnabled) {
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
    if ($settingsForm.x32_enabled) {
      $settingsForm.x32_enabled.checked = appSettings.x32_enabled === true;
    }
    if ($settingsForm.x32_host) {
      $settingsForm.x32_host.value = appSettings.x32_host || "";
    }
    if ($settingsForm.sliding_animation_enabled) {
      $settingsForm.sliding_animation_enabled.checked =
        appSettings.sliding_animation_enabled === true;
    }
    if ($settingsForm.sliding_animation_duration_ms) {
      $settingsForm.sliding_animation_duration_ms.value =
        appSettings.sliding_animation_duration_ms != null
          ? appSettings.sliding_animation_duration_ms
          : 100;
    }
  }

  function rehearsalLoopWasCreated() {
    return !!(state.rehearsal && state.rehearsal.loop_enabled);
  }

  function confirmExitRehearsal() {
    if (!rehearsalLoopWasCreated()) {
      return true;
    }
    return confirm(
      "Leave Rehearsal mode?\n\nThis will turn off the arrangement loop in Ableton and reset the loop bracket to the full project length."
    );
  }

  function exitRehearsalMode() {
    send({ command: "rehearse_exit" });
    rehearsalSelection = [];
  }

  function setAdminPanel(panel) {
    currentAdminPanel = panel;
    const isProjects = panel === "projects";
    const isSettings = panel === "settings";
    const isDevices = panel === "devices";
    const isRescan = panel === "rescan";

    if ($adminPanelProjects) {
      $adminPanelProjects.hidden = !isProjects;
    }
    if ($adminPanelSettings) {
      $adminPanelSettings.hidden = !isSettings;
    }
    if ($adminPanelDevices) $adminPanelDevices.hidden = !isDevices;
    if ($adminPanelRescan) {
      $adminPanelRescan.hidden = !isRescan;
    }
    if ($navAdminProjects) {
      $navAdminProjects.classList.toggle("active", isProjects);
    }
    if ($navAdminSettings) {
      $navAdminSettings.classList.toggle("active", isSettings);
    }
    if ($navAdminDevices) $navAdminDevices.classList.toggle("active", isDevices);
    if ($navAdminRescan) {
      $navAdminRescan.classList.toggle("active", isRescan);
    }

    if (isSettings) {
      fetchSettings();
    }
    if (isProjects) {
      fetchProjects();
    }
    if (isDevices) fetchDevices(false).catch(function () { setDevicesStatus("Device administration is only available on the server Mac.", "error"); });
  }

  function setView(view, options) {
    options = options || {};
    if (clientLocked && view !== "performance") {
      return;
    }
    if (
      currentView === "rehearsal" &&
      view !== "rehearsal" &&
      !options.skipRehearsalExit
    ) {
      if (!confirmExitRehearsal()) {
        return;
      }
      exitRehearsalMode();
    }
    currentView = view;
    const isPerformance = view === "performance";
    const isSetlist = view === "setlist";
    const isMixer = view === "mixer";
    const isX32 = view === "x32";
    const isRehearsal = view === "rehearsal";
    const isAdmin = view === "admin";

    if ($viewPerformance) {
      $viewPerformance.hidden = !isPerformance;
    }
    if ($viewSetlist) {
      $viewSetlist.hidden = !isSetlist;
    }
    if ($viewMixer) {
      $viewMixer.hidden = !isMixer;
    }
    if ($viewX32) $viewX32.hidden = !isX32;
    if ($viewRehearsal) {
      $viewRehearsal.hidden = !isRehearsal;
    }
    if ($viewAdmin) {
      $viewAdmin.hidden = !isAdmin;
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
    if ($navX32) $navX32.classList.toggle("active", isX32);
    if ($navRehearsal) {
      $navRehearsal.classList.toggle("active", isRehearsal);
    }
    if ($navAdmin) {
      $navAdmin.classList.toggle("active", isAdmin);
    }
    if ($btnFullscreen) {
      $btnFullscreen.hidden = !isPerformance;
    }

    ensureProgressLoop();

    if (isSetlist) {
      fetchSetlists();
      fetchSongs().then(function () {
        renderSetlistEditor();
      });
    }
    if (isMixer) {
      fetchMixerPresets();
      fetchMixerTracks();
    }
    if (isX32) {
      fetchX32Data();
      startX32Polling();
    } else {
      stopX32Polling();
    }
    if (isRehearsal) {
      fetchSections().then(function () {
        renderRehearsalList();
      });
    }
    if (isAdmin) {
      setAdminPanel(options.adminPanel || currentAdminPanel);
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
    if ($navX32) {
      $navX32.hidden = clientLocked || appSettings.x32_enabled !== true;
    }
    if ($navRehearsal) {
      $navRehearsal.hidden = clientLocked;
    }
    if ($navAdmin) {
      $navAdmin.hidden = clientLocked;
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
    if (mixerPresetApplying) {
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

  function fetchMixerPresets() {
    return apiFetch("/api/mixer-presets/")
      .then(function (data) {
        savedMixerPresets = data;
        populateMixerPresetLoadSelect();
      })
      .catch(console.error);
  }

  function populateMixerPresetLoadSelect() {
    if (!$mixerPresetLoad) return;
    const current = $mixerPresetLoad.value;
    $mixerPresetLoad.innerHTML = '<option value="">Load preset…</option>';
    savedMixerPresets.forEach(function (preset) {
      const opt = document.createElement("option");
      opt.value = preset.id;
      opt.textContent = preset.name;
      $mixerPresetLoad.appendChild(opt);
    });
    if (current) $mixerPresetLoad.value = current;
  }

  function resetEditorMixerPreset() {
    editorMixerPreset = { id: null, name: "" };
    if ($mixerPresetName) $mixerPresetName.value = "";
    if ($mixerPresetLoad) $mixerPresetLoad.value = "";
  }

  function loadEditorMixerPreset(data) {
    editorMixerPreset = { id: data.id, name: data.name };
    if ($mixerPresetName) $mixerPresetName.value = data.name;
    if ($mixerPresetLoad) $mixerPresetLoad.value = String(data.id);
  }

  function setMixerPresetStatus(message, type) {
    if (!$mixerPresetStatus) return;
    $mixerPresetStatus.textContent = message || "";
    $mixerPresetStatus.className =
      "setlist-editor-status" + (type ? " " + type : "");
  }

  function buildMixerPresetPayload() {
    return {
      name: ($mixerPresetName && $mixerPresetName.value.trim()) || "Untitled",
      tracks: mixerTracks.map(function (t) {
        return {
          index: t.index,
          name: t.name,
          muted: !!t.muted,
        };
      }),
    };
  }

  function applyMixerPreset(id) {
    if (!id) return Promise.resolve();
    if (!isMixerConnected()) {
      setMixerPresetStatus("Not connected to Ableton", "error");
      return Promise.reject(new Error("not connected"));
    }
    mixerPresetApplying = true;
    setMixerPresetStatus("Applying...", "");
    return apiFetch("/api/mixer-presets/" + id + "/apply/", { method: "POST" })
      .then(function (data) {
        mixerPending = null;
        if (data.tracks) {
          applyMixerTracks(data.tracks);
        }
        const preset = savedMixerPresets.find(function (p) {
          return String(p.id) === String(id);
        });
        if (preset) {
          loadEditorMixerPreset(preset);
        }
        setMixerPresetStatus("Applied", "success");
      })
      .catch(function (err) {
        const message =
          err && err.error
            ? err.error
            : err && typeof err === "object"
              ? Object.values(err).flat().join(" ")
              : "Failed to apply preset";
        setMixerPresetStatus(message, "error");
        throw err;
      })
      .finally(function () {
        mixerPresetApplying = false;
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

  function setRehearsalStatus(message) {
    if (!$rehearsalStatus) return;
    $rehearsalStatus.textContent = message || "";
  }

  function getRehearsalSections() {
    const song = state.active_song;
    if (!song || song.start_beat == null) {
      return [];
    }
    const songEnd = song.end_beat != null ? song.end_beat : Infinity;
    return sections.filter(function (sec) {
      return sec.start_beat >= song.start_beat && sec.start_beat < songEnd;
    });
  }

  function rehearsalBeatKey(beat) {
    return String(Math.round(beat * 10000) / 10000);
  }

  function isRehearsalBeatSelected(beat) {
    const key = rehearsalBeatKey(beat);
    return rehearsalSelection.some(function (b) {
      return rehearsalBeatKey(b) === key;
    });
  }

  function toggleRehearsalSelection(startBeat) {
    const list = getRehearsalSections();
    const beats = list.map(function (s) {
      return s.start_beat;
    });
    let idx = -1;
    for (let i = 0; i < beats.length; i++) {
      if (rehearsalBeatKey(beats[i]) === rehearsalBeatKey(startBeat)) {
        idx = i;
        break;
      }
    }
    if (idx < 0) return;

    if (rehearsalSelection.length === 0) {
      rehearsalSelection = [startBeat];
      updateRehearsalToolbar();
      renderRehearsalList();
      return;
    }

    const selIndices = rehearsalSelection
      .map(function (b) {
        for (let i = 0; i < beats.length; i++) {
          if (rehearsalBeatKey(beats[i]) === rehearsalBeatKey(b)) return i;
        }
        return -1;
      })
      .filter(function (i) {
        return i >= 0;
      })
      .sort(function (a, b) {
        return a - b;
      });

    if (isRehearsalBeatSelected(startBeat)) {
      if (selIndices.length === 1) {
        rehearsalSelection = [];
      } else if (
        idx === selIndices[0] ||
        idx === selIndices[selIndices.length - 1]
      ) {
        rehearsalSelection = selIndices
          .filter(function (i) {
            return i !== idx;
          })
          .map(function (i) {
            return beats[i];
          });
      }
      updateRehearsalToolbar();
      renderRehearsalList();
      return;
    }

    const minIdx = selIndices[0];
    const maxIdx = selIndices[selIndices.length - 1];
    if (idx === minIdx - 1 || idx === maxIdx + 1) {
      rehearsalSelection = selIndices
        .concat([idx])
        .sort(function (a, b) {
          return a - b;
        })
        .map(function (i) {
          return beats[i];
        });
    } else {
      rehearsalSelection = [startBeat];
    }
    updateRehearsalToolbar();
    renderRehearsalList();
  }

  function updateRehearsalToolbar() {
    if ($btnRehearsalLoop) {
      $btnRehearsalLoop.disabled = rehearsalSelection.length === 0;
    }
  }

  function renderRehearsalList() {
    if (!$rehearsalSectionList) return;

    const song = state.active_song;
    if ($rehearsalSongContext) {
      if (song && song.name) {
        $rehearsalSongContext.textContent = "Sections in: " + song.name;
      } else {
        $rehearsalSongContext.textContent =
          "Play or cue a song to see its sections.";
      }
    }

    const list = getRehearsalSections();
    const loopingBeats = {};
    if (state.rehearsal && state.rehearsal.sections) {
      state.rehearsal.sections.forEach(function (sec) {
        loopingBeats[rehearsalBeatKey(sec.start_beat)] = true;
      });
    }

    $rehearsalSectionList.innerHTML = "";
    if (!list.length) {
      const empty = document.createElement("li");
      empty.className = "rehearsal-empty";
      empty.textContent =
        song && song.name
          ? "No sections in this song."
          : "No sections to show.";
      $rehearsalSectionList.appendChild(empty);
      updateRehearsalToolbar();
      return;
    }

    list.forEach(function (sec) {
      const li = document.createElement("li");
      li.className = "rehearsal-section-row";
      const beatKey = rehearsalBeatKey(sec.start_beat);
      if (isRehearsalBeatSelected(sec.start_beat)) {
        li.classList.add("is-selected");
      }
      if (loopingBeats[beatKey]) {
        li.classList.add("is-looping");
      }
      if (
        state.active_section &&
        rehearsalBeatKey(state.active_section.start_beat) === beatKey
      ) {
        li.classList.add("is-active");
      }

      const check = document.createElement("input");
      check.type = "checkbox";
      check.className = "rehearsal-section-check";
      check.checked = isRehearsalBeatSelected(sec.start_beat);
      check.addEventListener("change", function () {
        toggleRehearsalSelection(sec.start_beat);
      });

      const info = document.createElement("div");
      info.className = "rehearsal-section-info";
      const durationBeats =
        sec.end_beat != null ? sec.end_beat - sec.start_beat : null;
      info.innerHTML =
        '<div class="rehearsal-section-name">' +
        escHtml(sec.name) +
        "</div>" +
        '<div class="rehearsal-section-duration">' +
        formatBeatDuration(durationBeats) +
        "</div>";

      const playBtn = document.createElement("button");
      playBtn.type = "button";
      playBtn.className = "btn btn-secondary btn-rehearsal-play";
      playBtn.textContent = "Play";
      playBtn.addEventListener("click", function () {
        send({ command: "rehearse_play", start_beat: sec.start_beat });
      });

      li.appendChild(check);
      li.appendChild(info);
      li.appendChild(playBtn);
      $rehearsalSectionList.appendChild(li);
    });

    if (state.rehearsal && state.rehearsal.loop_enabled) {
      const names = (state.rehearsal.sections || [])
        .map(function (s) {
          return s.name;
        })
        .join(", ");
      setRehearsalStatus("Looping: " + (names || "selected sections"));
    } else {
      setRehearsalStatus("");
    }
    updateRehearsalToolbar();
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

  // ── X32 ─────────────────────────────────────────────────────────

  function updateX32Availability() {
    if ($navX32) {
      $navX32.hidden = clientLocked || appSettings.x32_enabled !== true;
    }
    if (appSettings.x32_enabled !== true && currentView === "x32") {
      setView("performance");
    }
  }

  function setX32Status(message, type) {
    [$x32MixerStatus, $x32EventsStatus, document.getElementById("x32-fx-status")].forEach(function (element) {
      if (!element) return;
      element.textContent = message || "";
      element.className = "mixer-status" + (type ? " " + type : "");
    });
  }

  function startX32Polling() {
    stopX32Polling();
    x32PollTimer = setInterval(fetchX32Data, 1000);
  }

  function stopX32Polling() {
    if (x32PollTimer) clearInterval(x32PollTimer);
    x32PollTimer = null;
  }

  function fetchX32Data() {
    if (appSettings.x32_enabled !== true) return Promise.resolve();
    return Promise.all([
      apiFetch("/api/x32/mixer/"),
      apiFetch("/api/x32/control-events/").catch(function () { return null; }),
    ]).then(function (data) {
      x32Mixer = data[0] || { status: {}, channels: [] };
      if (data[1]) x32Control = data[1];
      renderX32();
    }).catch(function (err) {
      setX32Status((err && (err.error || err.detail)) || "Could not load X32 state", "error");
    });
  }

  function setX32Panel(panel) {
    currentX32Panel = panel;
    document.getElementById("x32-panel-fx").hidden = panel !== "fx";
    if ($x32PanelMixer) $x32PanelMixer.hidden = panel !== "mixer";
    if ($x32PanelEvents) $x32PanelEvents.hidden = panel !== "events";
    if ($x32Subnav) {
      $x32Subnav.querySelectorAll("[data-x32-panel]").forEach(function (button) {
        button.classList.toggle("active", button.dataset.x32Panel === panel);
      });
    }
    fetchX32Data();
  }

  function sendX32(command, data, busyText) {
    if (clientLocked) return;
    setX32Status(busyText || "Working…", "");
    send(Object.assign({ command: command }, data || {}));
  }

  function x32Number(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function renderX32() {
    const status = x32Mixer.status || {};
    if ($x32ConnectionStatus) {
      $x32ConnectionStatus.textContent = status.online
        ? ((status.model || "X32") + (status.firmware ? " · " + status.firmware : ""))
        : "Offline";
      $x32ConnectionStatus.classList.toggle("online", !!status.online);
    }
    const editorButton = document.getElementById("btn-x32-open-editor");
    if (editorButton) editorButton.hidden = !x32Mixer.desktop_local;
    const focused = $viewX32 && $viewX32.contains(document.activeElement) && document.activeElement.matches("input");
    if (!x32MixerEditing && !focused) { renderX32Mixer(); renderX32FX(); }
    renderX32ControlEvents();
  }

  function renderX32Mixer() {
    if (!$x32ChannelStrips) return;
    const channels = x32Mixer.channels || [];
    $x32ChannelStrips.innerHTML = channels.map(function (channel) {
      const level = channel.level == null ? -90 : channel.level;
      const meter = Math.max(0, Math.min(100, (channel.meter || 0) * 100));
      return '<article class="x32-strip' + (channel.channel === selectedX32Channel ? ' selected' : '') + '" data-x32-channel="' + channel.channel + '">' +
        '<button class="x32-channel-number" type="button" data-x32-select="' + channel.channel + '" aria-label="Select channel ' + channel.channel + ' sends">' + String(channel.channel).padStart(2, '0') + '</button>' +
        '<input class="x32-strip-name" type="text" maxlength="12" value="' + escAttr(channel.name) + '" data-x32-key="ch.' + channel.channel + '.name" aria-label="Channel ' + channel.channel + ' name">' +
        x32RangeControl("Trim", "ch." + channel.channel + ".gain", -18, 18, 0.5, channel.gain == null ? 0 : channel.gain) +
        x32RangeControl("Pan", "ch." + channel.channel + ".pan", -100, 100, 1, channel.pan == null ? 0 : channel.pan) +
        '<div class="x32-level-controls"><div class="x32-fader-scale" aria-hidden="true"><span>+10</span><span>0</span><span>−30</span><span>−∞</span></div><div class="x32-meter"><span style="height:' + meter + '%"></span></div>' +
        '<input class="x32-fader" type="range" min="-90" max="10" step="0.5" value="' + level + '" data-x32-key="ch.' + channel.channel + '.level" aria-label="' + escAttr(channel.name) + ' level"></div>' +
        x32Numeric("Level (dB)", "ch." + channel.channel + ".level", -90, 10, 0.5, level) +
        '<div class="x32-strip-switches">' +
        x32Toggle("Ø", "ch." + channel.channel + ".polarity", channel.polarity) +
        x32Toggle("Link", "link." + (channel.channel % 2 ? channel.channel : channel.channel - 1), channel.link) +
        '<button type="button" class="btn x32-state' + (channel.phantom ? ' active danger' : '') + '" data-x32-phantom="' + channel.channel + '" data-value="' + !!channel.phantom + '" ' + (channel.phantom == null ? 'disabled title="No available physical headamp"' : 'title="48 V phantom power on headamp ' + channel.headamp + '"') + '>48V</button></div><div class="x32-strip-actions">' +
        '<button class="btn x32-state' + (channel.solo ? ' active' : '') + '" type="button" data-x32-toggle="solo" data-channel="' + channel.channel + '">Solo</button>' +
        '<button class="btn x32-state' + (channel.mute ? ' active danger' : '') + '" type="button" data-x32-toggle="mute" data-channel="' + channel.channel + '">Mute</button>' +
        '</div></article>';
    }).join("");

    const channel = channels.find(function (item) { return item.channel === selectedX32Channel; });
    if (!$x32ChannelDetail || !channel) {
      if ($x32ChannelDetail) $x32ChannelDetail.hidden = true;
      return;
    }
    $x32ChannelDetail.hidden = false;
    $x32ChannelDetailTitle.textContent = channel.name + " · Bus sends";
    $x32ChannelControls.innerHTML = "";
    $x32ChannelSends.innerHTML = (channel.sends || []).map(function (value, index) {
      return x32RangeControl("Bus " + (index + 1), "ch." + channel.channel + ".send." + (index + 1), -90, 10, 0.5, value == null ? -90 : value);
    }).join("");
  }

  function x32RangeControl(label, key, min, max, step, value) {
    return '<label class="x32-range-control"><span>' + escHtml(label) + '</span>' +
      '<input type="range" min="' + min + '" max="' + max + '" step="' + step + '" value="' + value + '" data-x32-key="' + escHtml(key) + '">' +
      '<input class="x32-number" type="text" inputmode="decimal" data-x32-number data-min="' + min + '" data-max="' + max + '" value="' + Number(value).toFixed(step < 1 ? 1 : 0) + '" data-x32-key="' + escHtml(key) + '" aria-label="' + escHtml(label) + ' numeric value"></label>';
  }

  function x32Numeric(label, key, min, max, step, value) {
    return '<label class="x32-numeric"><span>' + escHtml(label) + '</span><input class="x32-number" type="text" inputmode="decimal" data-x32-number data-min="' + min + '" data-max="' + max + '" value="' + Number(value).toFixed(1) + '" data-x32-key="' + escHtml(key) + '"></label>';
  }

  function x32Toggle(label, key, value) {
    return '<button class="btn x32-state' + (value ? ' active' : '') + '" type="button" data-x32-bool="' + escHtml(key) + '" aria-pressed="' + !!value + '" title="' + (label === 'Ø' ? 'Invert polarity' : label === 'Link' ? 'Stereo link with adjacent channel' : escAttr(label)) + '" data-value="' + !!value + '"' + (value == null ? ' disabled' : '') + '>' + escHtml(label) + '</button>';
  }

  function renderX32FX() {
    const container = document.getElementById("x32-fx-returns");
    if (!container) return;
    const expanded = new Set(Array.from(container.querySelectorAll("details[open]")).map(function (item) { return item.dataset.fxReturn; }));
    const returns = x32Mixer.fx_returns || [];
    container.innerHTML = Array.from({length: 4}, function (_, slot) {
      return '<section class="x32-fx-slot"><header><span class="x32-eyebrow">STEREO RETURN</span><h3>FX ' + (slot + 1) + '</h3></header><div class="x32-fx-pair">' + returns.slice(slot * 2, slot * 2 + 2).map(function (item) {
      const prefix = "fxrtn." + item.channel + ".";
      return '<article class="x32-fx-return"><h4>' + (item.channel % 2 ? 'Left' : 'Right') + '</h4>' +
        x32RangeControl("Level (dB)", prefix + "level", -90, 10, 0.5, item.level == null ? -90 : item.level) +
        x32RangeControl("Pan", prefix + "pan", -100, 100, 1, item.pan == null ? 0 : item.pan) +
        x32Toggle("Mute", prefix + "mute", item.mute) +
        '<details data-fx-return="' + item.channel + '"' + (expanded.has(String(item.channel)) ? ' open' : '') + '><summary>Bus sends</summary><div class="x32-fx-sends">' + Array.from({length: 16}, function (_, i) {
          const value = item["send." + (i + 1)];
          return x32RangeControl("Bus " + (i + 1), prefix + "send." + (i + 1), -90, 10, 0.5, value == null ? -90 : value);
        }).join("") + '</div></details></article>';
      }).join("") + '</div></section>';
    }).join("");
  }

  function renderX32ControlEvents() {
    if (!$x32ChangeList) return;
    const changes = x32Control.changes || [];
    const priorSelection = new Map(Array.from(
      $x32ChangeList.querySelectorAll('input[type="checkbox"]')
    ).map(function (input) { return [input.value, input.checked]; }));
    const baselineButton = document.getElementById("btn-x32-baseline");
    if (baselineButton) baselineButton.textContent = x32Control.baseline_ready ? "Reset recording baseline" : "Start recording changes";
    $x32ChangeList.innerHTML = changes.length ? changes.map(function (change) {
      const checked = !priorSelection.has(change.key) || priorSelection.get(change.key);
      return '<label class="x32-change"><input type="checkbox" value="' + escHtml(change.key) + '"' + (checked ? ' checked' : '') + '>' +
        '<span><strong>' + escHtml(change.label) + '</strong><small>' + escHtml(change.before.text) + ' → ' + escHtml(change.after.text) + '</small></span></label>';
    }).join("") : '<div class="x32-empty"><span class="x32-empty-symbol" aria-hidden="true">◎</span><strong>' + (x32Control.baseline_ready ? 'Listening for changes' : 'Ready to record') + '</strong><p>' + (x32Control.baseline_ready ? 'Mixer edits will appear here. Select the changes you want to keep.' : 'Start a recording, then adjust your mixer to create an operation.') + '</p></div>';

    $x32SnapshotList.innerHTML = (x32Control.snapshots || []).map(function (snapshot) {
      return '<article class="x32-saved-item"><div><strong>' + escHtml(snapshot.name) + '</strong><small>' + escHtml(snapshot.keyword || 'No keyword') + '</small></div>' +
        '<div><button class="btn btn-secondary" data-x32-restore-snapshot="' + snapshot.id + '">Load</button><button class="btn btn-stop" data-x32-delete="snapshot:' + snapshot.id + '">Delete</button></div></article>';
    }).join("") || '<p class="mixer-intro">No snapshots saved.</p>';

    $x32OperationList.innerHTML = (x32Control.operations || []).map(function (operation) {
      return '<article class="x32-saved-item"><div><strong>' + escHtml(operation.name) + '</strong><small>' + escHtml(operation.apply_keyword || 'No apply keyword') + ' · ' + escHtml(operation.rollback_keyword || 'No rollback keyword') + ' · ' + operation.changes.length + ' changes</small></div>' +
        '<div><button class="btn btn-secondary" data-x32-apply-operation="' + operation.id + '">Apply</button><button class="btn btn-stop" data-x32-rollback-operation="' + operation.id + '">Rollback</button><button class="btn btn-stop" data-x32-delete="operation:' + operation.id + '">Delete</button></div></article>';
    }).join("") || '<p class="mixer-intro">No operations saved.</p>';
  }

  // ── Rendering ────────────────────────────────────────────────────

  function render() {
    if (currentView === "mixer") {
      syncMixerFromState();
    }
    if (currentView === "rehearsal") {
      renderRehearsalList();
    }
    if (currentView === "admin" && currentAdminPanel === "projects" && savedProjects.length) {
      const activeId =
        state.active_project && state.active_project.id != null
          ? state.active_project.id
          : null;
      let changed = false;
      savedProjects.forEach(function (project) {
        const nextActive = project.id === activeId;
        if (project.is_active !== nextActive) {
          project.is_active = nextActive;
          changed = true;
        }
      });
      if (changed) {
        renderProjectList();
      }
    }
    // Connection badge (scanning takes precedence while project scan runs)
    if (!scanInProgress) {
      setBadge(state.connection_status || "disconnected");
    }

    if ($projectName) {
      const project = state.active_project;
      const label = project && project.display_name ? project.display_name : "—";
      $projectName.textContent = label;
      $projectName.title = project && project.file_path
        ? project.file_path
        : "Active Ableton project";
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
      lastHighlightedListIndex = null;
      renderSongList();
    }
  }

  function renderAutoAdvance() {
    if (!$autoAdvanceInfo) return;
    const aa = state.auto_advance;
    if (aa && aa.active) {
      $autoAdvanceInfo.textContent =
        "Auto-playing " +
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
        '</span><span class="song-status-badge">Cued</span>' +
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
    const isPlaying = !!state.is_playing;
    let activeLi = null;
    items.forEach(function (li) {
      const idx = parseInt(li.dataset.index, 10);
      const isActive = idx === activeIdx;
      li.classList.toggle("active", isActive);
      li.classList.toggle("playing", isActive && isPlaying);
      const badge = li.querySelector(".song-status-badge");
      if (badge) {
        badge.textContent = isActive && isPlaying ? "Playing" : "Cued";
      }
      if (isActive) {
        activeLi = li;
      }
    });
    if (activeLi && activeIdx !== lastHighlightedListIndex) {
      lastHighlightedListIndex = activeIdx;
      activeLi.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } else if (activeIdx == null) {
      lastHighlightedListIndex = null;
    }
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
        "> Auto-play next song</label>" +
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

  function escAttr(s) {
    return escHtml(s).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function escHtml(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  // ── Event handlers ───────────────────────────────────────────────

  $btnPlay.addEventListener("click", function () {
    send({ command: "toggle_play" });
  });

  $btnStop.addEventListener("click", function () {
    send({ command: "stop" });
  });

  $btnPrev.addEventListener("click", function () {
    send({ command: "previous_song" });
  });

  $btnNext.addEventListener("click", function () {
    send({ command: "next_song" });
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

  if ($adminSubnav) {
    $adminSubnav.addEventListener("click", function (e) {
      const btn = e.target.closest("[data-admin-panel]");
      if (!btn) return;
      setAdminPanel(btn.dataset.adminPanel);
    });
  }

  if ($x32Subnav) {
    $x32Subnav.addEventListener("click", function (e) {
      const button = e.target.closest("[data-x32-panel]");
      if (button) setX32Panel(button.dataset.x32Panel);
    });
  }

  if ($viewX32) {
    $viewX32.addEventListener("pointerdown", function (e) {
      if (e.target.closest("[data-x32-key]")) x32MixerEditing = true;
    });
    $viewX32.addEventListener("click", function (e) {
      const select = e.target.closest("[data-x32-select]");
      if (select) {
        selectedX32Channel = parseInt(select.dataset.x32Select, 10);
        renderX32Mixer();
        return;
      }
      const boolean = e.target.closest("[data-x32-bool]");
      if (boolean) return sendX32("x32_set", {key: boolean.dataset.x32Bool, value: boolean.dataset.value !== "true"});
      const phantom = e.target.closest("[data-x32-phantom]");
      if (phantom) return sendX32("x32_phantom", {channel: Number(phantom.dataset.x32Phantom), value: phantom.dataset.value !== "true"});
      const toggle = e.target.closest("[data-x32-toggle]");
      if (toggle) {
        const channel = parseInt(toggle.dataset.channel, 10);
        const item = (x32Mixer.channels || []).find(function (entry) { return entry.channel === channel; });
        if (item) sendX32("x32_set", { key: "ch." + channel + "." + toggle.dataset.x32Toggle, value: !item[toggle.dataset.x32Toggle] });
        return;
      }
      const apply = e.target.closest("[data-x32-apply-operation]");
      if (apply) return sendX32("x32_apply_operation", { id: parseInt(apply.dataset.x32ApplyOperation, 10) }, "Applying operation…");
      const rollback = e.target.closest("[data-x32-rollback-operation]");
      if (rollback) return sendX32("x32_rollback_operation", { id: parseInt(rollback.dataset.x32RollbackOperation, 10) }, "Rolling back operation…");
      const restore = e.target.closest("[data-x32-restore-snapshot]");
      if (restore) return sendX32("x32_restore_snapshot", { id: parseInt(restore.dataset.x32RestoreSnapshot, 10) }, "Loading snapshot…");
      const remove = e.target.closest("[data-x32-delete]");
      if (remove) {
        const parts = remove.dataset.x32Delete.split(":");
        if (confirm("Delete this X32 " + parts[0] + "?")) sendX32("x32_delete", { kind: parts[0], id: parseInt(parts[1], 10) }, "Deleting…");
      }
    });
    $viewX32.addEventListener("focusin", function (e) {
      if (e.target.matches("[data-x32-number]")) e.target.select();
    });
    $viewX32.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && e.target.matches("input[data-x32-key]")) {
        e.preventDefault();
        if (e.target.checkValidity()) e.target.blur();
        else e.target.reportValidity();
      }
    });
    $viewX32.addEventListener("change", function (e) {
      const input = e.target.closest("[data-x32-key]");
      if (!input) return;
      const numeric = input.hasAttribute("data-x32-number");
      if (numeric) {
        const value = Number(input.value.trim());
        input.setCustomValidity(input.value.trim() === "" || !Number.isFinite(value) || value < Number(input.dataset.min) || value > Number(input.dataset.max)
          ? "Enter a value from " + input.dataset.min + " to " + input.dataset.max : "");
      }
      if (!input.checkValidity()) {
        input.reportValidity();
        return;
      }
      sendX32("x32_set", { key: input.dataset.x32Key, value: input.type === "text" && !numeric ? input.value : Number(input.value) }, "Updating mixer…");
    });
    $viewX32.addEventListener("input", function (e) {
      const input = e.target.closest("input[data-x32-key]");
      if (!input || (input.type === "text" && !input.hasAttribute("data-x32-number"))) return;
      if (input.hasAttribute("data-x32-number")) {
        const value = Number(input.value.trim());
        if (!Number.isFinite(value) || value < Number(input.dataset.min) || value > Number(input.dataset.max)) return;
      }
      input.setCustomValidity("");
      $viewX32.querySelectorAll("input[data-x32-key]").forEach(function (other) {
        if (other !== input && other.dataset.x32Key === input.dataset.x32Key) other.value = input.value;
      });
    });
  }
  window.addEventListener("pointerup", function () { x32MixerEditing = false; });
  window.addEventListener("pointercancel", function () { x32MixerEditing = false; });

  const $btnX32Editor = document.getElementById("btn-x32-open-editor");
  if ($btnX32Editor) $btnX32Editor.addEventListener("click", function () { sendX32("x32_open_editor", {}, "Opening X32-Edit…"); });
  const $btnX32Refresh = document.getElementById("btn-x32-refresh");
  if ($btnX32Refresh) $btnX32Refresh.addEventListener("click", function () { sendX32("x32_refresh", {}, "Refreshing all supported settings…"); });
  const $btnX32Baseline = document.getElementById("btn-x32-baseline");
  if ($btnX32Baseline) $btnX32Baseline.addEventListener("click", function () { sendX32("x32_initialize_baseline", {}, "Capturing complete baseline…"); });
  const $btnX32SaveSnapshot = document.getElementById("btn-x32-save-snapshot");
  if ($btnX32SaveSnapshot) $btnX32SaveSnapshot.addEventListener("click", function () {
    sendX32("x32_save_snapshot", {
      name: document.getElementById("x32-snapshot-name").value.trim(),
      keyword: document.getElementById("x32-snapshot-keyword").value.trim(),
    }, "Capturing complete snapshot…");
  });
  const $btnX32SaveOperation = document.getElementById("btn-x32-save-operation");
  if ($btnX32SaveOperation) $btnX32SaveOperation.addEventListener("click", function () {
    const selected = Array.from($x32ChangeList.querySelectorAll('input[type="checkbox"]:checked')).map(function (input) { return input.value; });
    sendX32("x32_save_operation", {
      name: document.getElementById("x32-operation-name").value.trim(),
      apply_keyword: document.getElementById("x32-operation-apply-keyword").value.trim(),
      rollback_keyword: document.getElementById("x32-operation-rollback-keyword").value.trim(),
      selected_keys: selected,
    }, "Saving operation and advancing baseline…");
  });

  if ($btnLock) {
    $btnLock.addEventListener("click", toggleClientLock);
  }

  if ($settingsForm) {
    $settingsForm.addEventListener("submit", function (e) {
    e.preventDefault();
    setSettingsStatus("Saving...", "");

    const durationRaw = parseInt(
      $settingsForm.sliding_animation_duration_ms.value,
      10
    );
    const payload = {
      ableton_osc_host: $settingsForm.ableton_osc_host.value.trim(),
      x32_enabled: !!$settingsForm.x32_enabled.checked,
      x32_host: $settingsForm.x32_host.value.trim(),
      sliding_animation_enabled: !!$settingsForm.sliding_animation_enabled.checked,
      sliding_animation_duration_ms: Number.isFinite(durationRaw)
        ? Math.max(0, Math.min(2000, durationRaw))
        : 100,
    };

    saveSettings(payload)
      .then(function (data) {
        appSettings = data;
        populateSettingsForm();
        applySlidingAnimationFromSettings();
        updateX32Availability();
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

  const $btnX32Test = document.getElementById("btn-x32-test");
  if ($btnX32Test) {
    $btnX32Test.addEventListener("click", function () {
      if (!appSettings.x32_enabled) {
        setSettingsStatus("Save and enable the X32 connection first.", "error");
        return;
      }
      setSettingsStatus("Testing X32 connection…", "");
      send({ command: "x32_test" });
    });
  }

  if ($btnDeviceRefresh) {
    $btnDeviceRefresh.addEventListener("click", function () {
      setDevicesStatus("Refreshing…", "");
      fetchDevices(true).then(function () { setDevicesStatus("Devices refreshed", "success"); })
        .catch(function () { setDevicesStatus("Could not refresh devices", "error"); });
    });
  }

  if ($btnBluetoothPair) {
    $btnBluetoothPair.addEventListener("click", function () {
      apiFetch("/api/devices/pair-bluetooth/", {method: "POST"})
        .then(function () {
          setDevicesStatus("Bluetooth Settings opened on this Mac. Pair the remote there, then refresh.", "success");
          setTimeout(function () { fetchDevices(true).catch(function () {}); }, 5000);
        })
        .catch(function (err) { setDevicesStatus((err && (err.error || err.detail)) || "Could not open Bluetooth Settings", "error"); });
    });
  }

  document.querySelectorAll("[data-device-permission]").forEach(function (button) {
    button.addEventListener("click", function () {
      apiFetch("/api/devices/open-device-permission/", {method: "POST", body: {kind: button.dataset.devicePermission}})
        .then(function () { setDevicesStatus("Permission Settings opened. Enable StageAble, then restart it.", "success"); })
        .catch(function () { setDevicesStatus("Could not open Permission Settings", "error"); });
    });
  });

  if ($deviceList) {
    $deviceList.addEventListener("change", function (e) {
      const id = e.target.dataset.deviceToggle;
      if (!id) return;
      apiFetch("/api/devices/" + id + "/", {method: "PATCH", body: {enabled: e.target.checked}})
        .then(function () { return fetchDevices(false); })
        .catch(function () { setDevicesStatus("Could not update device", "error"); });
    });
    $deviceList.addEventListener("click", function (e) {
      const learnId = e.target.dataset.learnDevice;
      const mappingId = e.target.dataset.deleteMapping;
      const deviceId = e.target.dataset.deleteDevice;
      if (learnId) {
        const select = $deviceList.querySelector('[data-action-for="' + learnId + '"]');
        apiFetch("/api/devices/" + learnId + "/learn/", {method: "POST", body: {action: select.value}})
          .then(function () { setDevicesStatus("Listening for input…", ""); })
          .catch(function (err) { setDevicesStatus((err && (err.error || err.detail)) || "Could not start learn", "error"); });
      } else if (mappingId) {
        apiFetch("/api/device-mappings/" + mappingId + "/", {method: "DELETE"}).then(function () { return fetchDevices(false); });
      } else if (deviceId && confirm("Clear all mappings and disable this device?")) {
        apiFetch("/api/devices/" + deviceId + "/", {method: "DELETE"}).then(function () { return fetchDevices(false); });
      }
    });
  }

  if ($mixerPresetLoad) {
    $mixerPresetLoad.addEventListener("change", function () {
      const id = $mixerPresetLoad.value;
      if (!id) return;
      applyMixerPreset(id).catch(console.error);
    });
  }

  if ($btnRehearsalLoop) {
    $btnRehearsalLoop.addEventListener("click", function () {
      if (rehearsalSelection.length === 0) return;
      send({
        command: "rehearse_loop",
        start_beats: rehearsalSelection.slice(),
      });
    });
  }

  if ($btnRehearsalStop) {
    $btnRehearsalStop.addEventListener("click", function () {
      send({ command: "rehearse_stop" });
      rehearsalSelection = [];
    });
  }

  if ($btnMixerPresetNew) {
    $btnMixerPresetNew.addEventListener("click", function () {
      resetEditorMixerPreset();
      setMixerPresetStatus("New preset", "");
    });
  }

  if ($btnMixerPresetSave) {
    $btnMixerPresetSave.addEventListener("click", function () {
      if (!isMixerConnected()) {
        setMixerPresetStatus("Not connected to Ableton", "error");
        return;
      }
      setMixerPresetStatus("Saving...", "");
      fetchMixerTracks()
        .then(function () {
          if (!mixerTracks.length) {
            setMixerPresetStatus("No mixer tracks to save", "error");
            return;
          }
          const payload = buildMixerPresetPayload();
          const req = editorMixerPreset.id
            ? apiFetch("/api/mixer-presets/" + editorMixerPreset.id + "/", {
                method: "PUT",
                body: payload,
              })
            : apiFetch("/api/mixer-presets/", { method: "POST", body: payload });
          return req
            .then(function (data) {
              loadEditorMixerPreset(data);
              return fetchMixerPresets();
            })
            .then(function () {
              setMixerPresetStatus("Saved", "success");
            });
        })
        .catch(function (err) {
          const message =
            err && typeof err === "object"
              ? Object.values(err).flat().join(" ")
              : "Failed to save";
          setMixerPresetStatus(message, "error");
        });
    });
  }

  if ($btnMixerPresetDelete) {
    $btnMixerPresetDelete.addEventListener("click", function () {
      if (!editorMixerPreset.id) {
        resetEditorMixerPreset();
        return;
      }
      if (!confirm('Delete preset "' + editorMixerPreset.name + '"?')) return;
      apiFetch("/api/mixer-presets/" + editorMixerPreset.id + "/", {
        method: "DELETE",
      })
        .then(function () {
          resetEditorMixerPreset();
          return fetchMixerPresets();
        })
        .then(function () {
          setMixerPresetStatus("Deleted", "success");
        })
        .catch(function () {
          setMixerPresetStatus("Failed to delete", "error");
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
          lastHighlightedListIndex = null;
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
        send({ command: "toggle_play" });
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
    fetchSettings();
    fetchDevices(false).catch(function () {
      if ($navAdminDevices) $navAdminDevices.hidden = true;
    });
    loadCachedArrangement();
    connect();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
