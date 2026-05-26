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

  // ── DOM refs ─────────────────────────────────────────────────────
  const $badge        = document.getElementById("connection-badge");
  const $errorBanner  = document.getElementById("error-banner");
  const $songName     = document.getElementById("song-name");
  const $sectionName  = document.getElementById("section-name");
  const $lyricsText   = document.getElementById("lyrics-text");
  const $position     = document.getElementById("transport-position");
  const $tempo        = document.getElementById("transport-tempo");
  const $timeSig      = document.getElementById("transport-time-sig");
  const $songList     = document.getElementById("song-list");
  const $btnPlay      = document.getElementById("btn-play");
  const $btnStop      = document.getElementById("btn-stop");
  const $btnPrev      = document.getElementById("btn-prev");
  const $btnNext      = document.getElementById("btn-next");
  const $btnRescan    = document.getElementById("btn-rescan");
  const $viewPerformance = document.getElementById("view-performance");
  const $viewSetlist = document.getElementById("view-setlist");
  const $viewSettings = document.getElementById("view-settings");
  const $navPerformance = document.getElementById("nav-performance");
  const $navSetlist = document.getElementById("nav-setlist");
  const $navSettings = document.getElementById("nav-settings");
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

  // ── WebSocket ────────────────────────────────────────────────────

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/engine/`;

    ws = new WebSocket(url);

    ws.onopen = function () {
      clearTimeout(reconnectTimer);
      setBadge("connected");
      // Fetch song list via REST
      fetchSongs();
    };

    ws.onmessage = function (event) {
      const msg = JSON.parse(event.data);
      if (msg.type === "state") {
        state = msg.data;
        render();
      } else if (msg.type === "error") {
        console.error("Server error:", msg.message);
      }
    };

    ws.onclose = function () {
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
    $settingsForm.ableton_osc_send_port.value = appSettings.ableton_osc_send_port || "";
    $settingsForm.ableton_osc_recv_port.value = appSettings.ableton_osc_recv_port || "";
    $settingsForm.engine_poll_hz.value = appSettings.engine_poll_hz || "";
    $settingsForm.default_preroll_bars.value = appSettings.default_preroll_bars || "";
  }

  function setView(view) {
    currentView = view;
    const isPerformance = view === "performance";
    const isSetlist = view === "setlist";
    const isSettings = view === "settings";

    if ($viewPerformance) {
      $viewPerformance.hidden = !isPerformance;
    }
    if ($viewSetlist) {
      $viewSetlist.hidden = !isSetlist;
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
    if ($navSettings) {
      $navSettings.classList.toggle("active", isSettings);
    }
    if ($btnRescan) {
      $btnRescan.hidden = !isPerformance;
    }

    if (isSettings) {
      fetchSettings();
    }
    if (isSetlist) {
      fetchSetlists();
      fetchSongs().then(function () {
        renderSetlistEditor();
      });
    }
  }

  function setSettingsStatus(message, type) {
    $settingsStatus.textContent = message || "";
    $settingsStatus.className = "settings-status" + (type ? " " + type : "");
  }

  // ── Rendering ────────────────────────────────────────────────────

  function render() {
    // Connection badge
    setBadge(state.connection_status || "disconnected");

    // Error banner
    if (state.timeline_errors && state.timeline_errors.length > 0) {
      $errorBanner.textContent = state.timeline_errors.join(" | ");
      $errorBanner.classList.remove("hidden");
    } else {
      $errorBanner.classList.add("hidden");
    }

    // Now playing
    $songName.textContent = state.active_song ? state.active_song.name : "--";
    $sectionName.textContent = state.active_section
      ? state.active_section.name
      : "--";

    // Lyrics
    if (state.active_lyrics && state.active_lyrics.length > 0) {
      $lyricsText.textContent = state.active_lyrics
        .map((l) => l.name)
        .join("\n");
    } else {
      $lyricsText.textContent = "--";
    }

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
    renderSongListIfNeeded();
    renderSongListHighlight();
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
      li.innerHTML =
        '<span class="song-index">' +
        (i + 1) +
        '</span><span class="song-label">' +
        escHtml(name) +
        "</span>";
      if (song.duration_beats != null) {
        li.innerHTML +=
          '<span class="song-duration">' +
          formatBeatDuration(song.duration_beats) +
          "</span>";
      }
      li.addEventListener("click", function () {
        jumpToPerformanceIndex(i);
      });
      $songList.appendChild(li);
    });
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
    send({ command: "rescan" });
    // Refresh lists after a short delay
    setTimeout(fetchSongs, 1000);
  });

  const $viewNav = document.getElementById("view-nav");
  if ($viewNav) {
    $viewNav.addEventListener("click", function (e) {
      const btn = e.target.closest("[data-view]");
      if (!btn) return;
      setView(btn.dataset.view);
    });
  }

  if ($settingsForm) {
    $settingsForm.addEventListener("submit", function (e) {
    e.preventDefault();
    setSettingsStatus("Saving...", "");

    const payload = {
      ableton_osc_host: $settingsForm.ableton_osc_host.value.trim(),
      ableton_osc_send_port: parseInt($settingsForm.ableton_osc_send_port.value, 10),
      ableton_osc_recv_port: parseInt($settingsForm.ableton_osc_recv_port.value, 10),
      engine_poll_hz: parseInt($settingsForm.engine_poll_hz.value, 10),
      default_preroll_bars: parseInt($settingsForm.default_preroll_bars.value, 10),
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
        e.preventDefault();
        send({ command: state.is_playing ? "stop" : "play" });
        break;
      case "ArrowRight":
        e.preventDefault();
        $btnNext.click();
        break;
      case "ArrowLeft":
        e.preventDefault();
        $btnPrev.click();
        break;
    }
  });

  // ── Init ─────────────────────────────────────────────────────────
  function init() {
    setView("performance");
    connect();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
