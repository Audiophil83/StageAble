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
  let appSettings = {};
  let currentView = "performance";
  let reconnectTimer = null;
  const RECONNECT_DELAY = 2000;

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
  const $sectionList  = document.getElementById("section-list");
  const $btnPlay      = document.getElementById("btn-play");
  const $btnStop      = document.getElementById("btn-stop");
  const $btnPrev      = document.getElementById("btn-prev");
  const $btnNext      = document.getElementById("btn-next");
  const $btnRescan    = document.getElementById("btn-rescan");
  const $viewPerformance = document.getElementById("view-performance");
  const $viewSettings = document.getElementById("view-settings");
  const $navPerformance = document.getElementById("nav-performance");
  const $navSettings = document.getElementById("nav-settings");
  const $settingsForm = document.getElementById("settings-form");
  const $settingsStatus = document.getElementById("settings-status");

  // ── WebSocket ────────────────────────────────────────────────────

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/engine/`;

    ws = new WebSocket(url);

    ws.onopen = function () {
      clearTimeout(reconnectTimer);
      setBadge("connected");
      // Fetch song/section lists via REST
      fetchSongs();
      fetchSections();
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
    fetch("/api/songs/")
      .then((r) => r.json())
      .then((data) => {
        songs = data;
        renderSongList();
      })
      .catch(console.error);
  }

  function fetchSections() {
    fetch("/api/sections/")
      .then((r) => r.json())
      .then((data) => {
        sections = data;
        renderSectionList();
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

  function saveSettings(formData) {
    return fetch("/api/settings/", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify(formData),
    }).then((r) => {
      if (!r.ok) {
        return r.json().then((err) => Promise.reject(err));
      }
      return r.json();
    });
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

    if ($viewPerformance) {
      $viewPerformance.hidden = !isPerformance;
    }
    if ($viewSettings) {
      $viewSettings.hidden = isPerformance;
    }
    if ($navPerformance) {
      $navPerformance.classList.toggle("active", isPerformance);
    }
    if ($navSettings) {
      $navSettings.classList.toggle("active", !isPerformance);
    }
    if ($btnRescan) {
      $btnRescan.hidden = !isPerformance;
    }

    if (!isPerformance) {
      fetchSettings();
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
    renderSongListHighlight();
    renderSectionListHighlight();
  }

  function renderSongList() {
    $songList.innerHTML = "";
    songs.forEach(function (song, i) {
      const li = document.createElement("li");
      li.dataset.index = song.index;
      li.innerHTML = `
        <span class="song-index">${song.index + 1}</span>
        <span class="song-label">${escHtml(song.name)}</span>
        <span class="song-duration">${formatBeatDuration(song.duration_beats)}</span>
      `;
      li.addEventListener("click", function () {
        send({ command: "jump_to_song", index: song.index });
      });
      $songList.appendChild(li);
    });
  }

  function renderSongListHighlight() {
    const items = $songList.querySelectorAll("li");
    items.forEach(function (li) {
      const idx = parseInt(li.dataset.index, 10);
      if (idx === state.active_song_index) {
        li.classList.add("active");
        // Scroll into view if needed
        if (!isElementInViewport(li)) {
          li.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      } else {
        li.classList.remove("active");
      }
    });
  }

  function renderSectionList() {
    $sectionList.innerHTML = "";
    sections.forEach(function (sec) {
      const li = document.createElement("li");
      li.dataset.startBeat = sec.start_beat;
      li.innerHTML = `
        <span class="section-label">${escHtml(sec.name)}</span>
        <span class="section-beat">${formatBeat(sec.start_beat)}</span>
      `;
      li.addEventListener("click", function () {
        send({ command: "jump_to_section", start_beat: sec.start_beat });
      });
      $sectionList.appendChild(li);
    });
  }

  function renderSectionListHighlight() {
    const items = $sectionList.querySelectorAll("li");
    items.forEach(function (li) {
      const beat = parseFloat(li.dataset.startBeat);
      if (
        state.active_section &&
        Math.abs(beat - state.active_section.start_beat) < 0.01
      ) {
        li.classList.add("active");
      } else {
        li.classList.remove("active");
      }
    });
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

  function isElementInViewport(el) {
    const rect = el.getBoundingClientRect();
    return (
      rect.top >= 0 &&
      rect.bottom <=
        (window.innerHeight || document.documentElement.clientHeight)
    );
  }

  // ── Event handlers ───────────────────────────────────────────────

  $btnPlay.addEventListener("click", function () {
    send({ command: "play" });
  });

  $btnStop.addEventListener("click", function () {
    send({ command: "stop" });
  });

  $btnPrev.addEventListener("click", function () {
    const idx = (state.active_song_index || 0) - 1;
    if (idx >= 0) {
      send({ command: "jump_to_song", index: idx });
    }
  });

  $btnNext.addEventListener("click", function () {
    const idx = (state.active_song_index || 0) + 1;
    if (idx < songs.length) {
      send({ command: "jump_to_song", index: idx });
    }
  });

  $btnRescan.addEventListener("click", function () {
    send({ command: "rescan" });
    // Refresh lists after a short delay
    setTimeout(function () {
      fetchSongs();
      fetchSections();
    }, 1000);
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
