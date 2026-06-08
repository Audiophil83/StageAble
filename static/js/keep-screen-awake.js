/**
 * Keep Screen Awake — cross-browser screen wake lock for Django SPAs.
 *
 * COMPATIBILITY MATRIX (expected behavior):
 *
 * | Browser                  | Wake Lock API | Fallback       | Notes |
 * |--------------------------|---------------|----------------|-------|
 * | iOS Safari 16.4+         | Yes           | —              | Requires user gesture; released when tab hidden or device locked |
 * | iOS Safari <16.4         | No            | Muted video    | Video loop prevents auto-lock during active playback |
 * | Chrome Android           | Yes           | Muted video    | Reacquire on visibilitychange; battery saver may block |
 * | Samsung Internet         | Yes           | Muted video    | Chromium-based; same as Chrome Android |
 * | Firefox Android          | Partial       | Muted video    | Wake Lock in recent versions; video fallback otherwise |
 * | Desktop Chrome / Edge    | Yes           | —              | Full support in secure contexts |
 * | Desktop Firefox          | Yes (126+)    | Muted video    | Older versions use video fallback |
 * | Desktop Safari (macOS)   | Yes (16.4+)   | Muted video    | Wake Lock may not block screen saver; use native API when server is local |
 *
 * macOS screen saver: browsers cannot reliably suppress it. When RemoteAble runs
 * on the same Mac as the browser, POST /api/keep-awake/ starts ``caffeinate
 * -dims`` on the server to disable screen saver and display sleep system-wide.
 * Battery: wake lock prevents display sleep only; fallback video is 8×8 px, muted,
 *          and paused immediately when disabled. No timer spam or page reloads.
 *
 * Security: requires HTTPS (or localhost). No server-side secrets involved.
 */
(function (global) {
  "use strict";

  var STORAGE_KEY = "keepScreenAwake";
  var LOG_PREFIX = "[KeepScreenAwake]";
  var STATUS_HIDE_MS = 4000;

  /* Minimal silent MP4 — also served at /static/media/wake-lock-silent.mp4 */
  var FALLBACK_VIDEO_SRC = "/static/media/wake-lock-silent.mp4";
  var NATIVE_API_URL = "/api/keep-awake/";

  // ── Capability detection ───────────────────────────────────────

  function detectCapabilities() {
    var ua = navigator.userAgent || "";
    var isIOS = /iPad|iPhone|iPod/.test(ua) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    var isAndroid = /Android/.test(ua);
    var isSafari = /Safari/.test(ua) && !/Chrome|CriOS|FxiOS|Edg/.test(ua);
    var isSamsung = /SamsungBrowser/.test(ua);
    var isFirefox = /Firefox|FxiOS/.test(ua);

    var isMacOS = !isIOS && (/Mac/.test(navigator.platform || "") ||
      /Mac OS X/.test(ua));

    var wakeLockSupported = "wakeLock" in navigator &&
      typeof navigator.wakeLock.request === "function";

    return {
      isIOS: isIOS,
      isAndroid: isAndroid,
      isSafari: isSafari,
      isSamsung: isSamsung,
      isFirefox: isFirefox,
      isMacOS: isMacOS,
      wakeLockSupported: wakeLockSupported,
      secureContext: global.isSecureContext === true,
      platform: isIOS ? "ios" : isAndroid ? "android" : "desktop",
    };
  }

  // ── Module ───────────────────────────────────────────────────────

  function KeepScreenAwake(options) {
    options = options || {};

    this._button = options.button || document.getElementById("btn-keep-awake");
    this._statusEl = options.statusEl || document.getElementById("keep-awake-status");
    this._videoSrc = options.videoSrc || FALLBACK_VIDEO_SRC;
    this._caps = detectCapabilities();

    this._preferred = false;   // user wants screen awake (localStorage)
    this._active = false;      // lock/video currently holding screen
    this._wakeLock = null;
    this._video = null;
    this._statusTimer = null;
    this._usingFallback = false;
    this._nativeActive = false;
    this._destroyed = false;

    this._onButtonClick = this._onButtonClick.bind(this);
    this._onVisibilityChange = this._onVisibilityChange.bind(this);
    this._onPageShow = this._onPageShow.bind(this);
    this._onPageHide = this._onPageHide.bind(this);
    this._onWakeLockRelease = this._onWakeLockRelease.bind(this);

    this._log("Initialized", this._caps);
  }

  KeepScreenAwake.prototype._log = function (msg, detail) {
    if (detail !== undefined) {
      console.log(LOG_PREFIX, msg, detail);
    } else {
      console.log(LOG_PREFIX, msg);
    }
  };

  KeepScreenAwake.prototype._warn = function (msg, detail) {
    if (detail !== undefined) {
      console.warn(LOG_PREFIX, msg, detail);
    } else {
      console.warn(LOG_PREFIX, msg);
    }
  };

  // ── User feedback ────────────────────────────────────────────────

  KeepScreenAwake.prototype._showStatus = function (message, type) {
    if (!this._statusEl || !message) return;
    this._statusEl.textContent = message;
    this._statusEl.classList.remove("hidden", "is-error", "is-info", "is-success");
    this._statusEl.classList.add(type === "error" ? "is-error" : type === "success" ? "is-success" : "is-info");
    clearTimeout(this._statusTimer);
    this._statusTimer = setTimeout(function () {
      this._statusEl.classList.add("hidden");
    }.bind(this), STATUS_HIDE_MS);
  };

  // ── UI state ─────────────────────────────────────────────────────

  KeepScreenAwake.prototype._updateButton = function () {
    if (!this._button) return;

    var awake = this._preferred;
    this._button.classList.toggle("is-active", awake);
    this._button.classList.toggle("is-pending", awake && !this._active);
    this._button.setAttribute("aria-pressed", awake ? "true" : "false");

    var label = awake ? "Allow Screen Sleep" : "Keep Screen Awake";
    this._button.setAttribute("aria-label", label);
    this._button.title = label;

    var labelEl = this._button.querySelector(".btn-keep-awake-label");
    if (labelEl) {
      labelEl.textContent = label;
    }

    document.body.classList.toggle("keep-screen-awake-active", awake && this._active);
  };

  KeepScreenAwake.prototype._syncActive = function () {
    this._active = !!(this._wakeLock || this._usingFallback || this._nativeActive);
    this._updateButton();
  };

  // ── CSRF + native macOS API ──────────────────────────────────────

  KeepScreenAwake.prototype._getCsrfToken = function () {
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  };

  KeepScreenAwake.prototype._nativeFetch = function (enabled) {
    return fetch(NATIVE_API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": this._getCsrfToken(),
      },
      body: JSON.stringify({ enabled: !!enabled }),
      keepalive: !enabled,
    }).then(function (r) {
      return r.ok ? r.json() : null;
    }).catch(function (err) {
      console.warn(LOG_PREFIX, "Native keep-awake API unavailable", err);
      return null;
    });
  };

  KeepScreenAwake.prototype._acquireNative = function () {
    var self = this;
    return this._nativeFetch(true).then(function (data) {
      if (data && data.native && data.active) {
        self._nativeActive = true;
        self._log("Native macOS keep-awake enabled (caffeinate -dims)");
        self._syncActive();
        return true;
      }
      if (data && data.supported === false) {
        self._log("Native keep-awake not supported on this server OS");
      }
      return false;
    });
  };

  KeepScreenAwake.prototype._releaseNative = function () {
    var self = this;
    if (!this._nativeActive) return Promise.resolve();
    return this._nativeFetch(false).then(function () {
      self._nativeActive = false;
      self._log("Native macOS keep-awake disabled");
    });
  };

  // ── Persistence ──────────────────────────────────────────────────

  KeepScreenAwake.prototype._loadPreference = function () {
    try {
      return localStorage.getItem(STORAGE_KEY) === "true";
    } catch (e) {
      this._warn("localStorage unavailable", e);
      return false;
    }
  };

  KeepScreenAwake.prototype._savePreference = function (enabled) {
    try {
      localStorage.setItem(STORAGE_KEY, enabled ? "true" : "false");
    } catch (e) {
      this._warn("Could not persist preference", e);
    }
  };

  // ── Wake Lock API ────────────────────────────────────────────────

  KeepScreenAwake.prototype._requestWakeLock = function () {
    var self = this;
    if (!this._caps.wakeLockSupported || !this._caps.secureContext) {
      return Promise.resolve(false);
    }
    if (document.hidden) {
      this._log("Skipping wake lock request — document hidden");
      return Promise.resolve(false);
    }

    return navigator.wakeLock.request("screen").then(function (sentinel) {
      if (self._destroyed || !self._preferred) {
        return sentinel.release().catch(function () {}).then(function () { return false; });
      }
      self._wakeLock = sentinel;
      self._usingFallback = false;
      sentinel.addEventListener("release", self._onWakeLockRelease);
      self._log("Wake Lock acquired");
      self._syncActive();
      return true;
    }).catch(function (err) {
      self._warn("Wake Lock request failed", err.name + ": " + err.message);
      if (err.name === "NotAllowedError") {
        self._showStatus("Screen wake permission denied. Tap the button to try again.", "error");
      } else if (err.name === "NotSupportedError") {
        self._showStatus("Wake Lock not supported on this device.", "info");
      }
      return false;
    });
  };

  KeepScreenAwake.prototype._releaseWakeLock = function () {
    var lock = this._wakeLock;
    this._wakeLock = null;
    if (!lock) return Promise.resolve();
    lock.removeEventListener("release", this._onWakeLockRelease);
    return lock.release().then(function () {
      this._log("Wake Lock released");
    }.bind(this)).catch(function (err) {
      this._warn("Wake Lock release error", err);
    });
  };

  KeepScreenAwake.prototype._onWakeLockRelease = function () {
    this._wakeLock = null;
    this._log("Wake Lock released unexpectedly");
    this._syncActive();
    if (this._preferred && !document.hidden) {
      this._log("Reacquiring wake lock after unexpected release");
      this._acquire();
    }
  };

  // ── Video fallback (iOS Safari <16.4, unsupported browsers) ────────

  KeepScreenAwake.prototype._ensureVideo = function () {
    if (this._video) return this._video;

    var video = document.createElement("video");
    video.setAttribute("playsinline", "");
    video.setAttribute("webkit-playsinline", "");
    video.muted = true;
    video.loop = true;
    video.preload = "auto";
    video.className = "keep-awake-fallback-video";
    video.setAttribute("aria-hidden", "true");
    video.tabIndex = -1;

    var source = document.createElement("source");
    source.src = this._videoSrc;
    source.type = "video/mp4";
    video.appendChild(source);

    document.body.appendChild(video);
    this._video = video;
    return video;
  };

  KeepScreenAwake.prototype._startVideoFallback = function () {
    var self = this;
    var video = this._ensureVideo();
    video.muted = true;

    return video.play().then(function () {
      self._usingFallback = true;
      self._log("Video fallback active");
      self._syncActive();
      return true;
    }).catch(function (err) {
      self._warn("Video fallback failed", err);
      self._showStatus("Could not keep screen awake. Try tapping the button again.", "error");
      return false;
    });
  };

  KeepScreenAwake.prototype._stopVideoFallback = function () {
    if (!this._video) return;
    this._video.pause();
    this._video.currentTime = 0;
    if (this._usingFallback) {
      this._log("Video fallback stopped");
    }
    this._usingFallback = false;
  };

  // ── Acquire / release orchestration ──────────────────────────────

  KeepScreenAwake.prototype._acquire = function () {
    var self = this;
    if (!this._preferred || this._destroyed) return Promise.resolve(false);

    function maybeVideo(wakeLockOk) {
      if (self._caps.isMacOS || !wakeLockOk) {
        return self._startVideoFallback().then(function (videoOk) {
          return wakeLockOk || videoOk || self._nativeActive;
        });
      }
      return Promise.resolve(wakeLockOk);
    }

    return this._acquireNative().then(function () {
      if (self._caps.wakeLockSupported && self._caps.secureContext) {
        return self._requestWakeLock().then(maybeVideo);
      }
      return maybeVideo(false);
    }).then(function (ok) {
      self._syncActive();
      return ok;
    });
  };

  KeepScreenAwake.prototype._release = function () {
    var self = this;
    this._stopVideoFallback();
    return Promise.all([
      this._releaseWakeLock(),
      this._releaseNative(),
    ]).then(function () {
      self._active = false;
      self._updateButton();
    });
  };

  // ── Public API ───────────────────────────────────────────────────

  KeepScreenAwake.prototype.isEnabled = function () {
    return this._preferred;
  };

  KeepScreenAwake.prototype.isActive = function () {
    return this._active;
  };

  KeepScreenAwake.prototype.enable = function () {
    this._preferred = true;
    this._savePreference(true);
    this._updateButton();
    return this._acquire().then(function (ok) {
      if (ok) {
        var msg = "Screen will stay awake.";
        if (this._nativeActive) {
          msg = "Screen and screen saver suppressed (macOS).";
        } else if (this._caps.isMacOS) {
          msg = "Screen awake enabled. For screen saver, open this page on the Mac running RemoteAble, or set Screen Saver to Never in System Settings.";
        }
        this._showStatus(msg, "success");
      }
      return ok;
    }.bind(this));
  };

  KeepScreenAwake.prototype.disable = function () {
    this._preferred = false;
    this._savePreference(false);
    this._updateButton();
    return this._release().then(function () {
      this._showStatus("Screen may sleep normally.", "info");
    }.bind(this));
  };

  KeepScreenAwake.prototype.toggle = function () {
    if (this._preferred && !this._active) {
      return this._acquire().then(function (ok) {
        if (ok) {
          this._showStatus("Screen will stay awake.", "success");
        }
        return ok;
      }.bind(this));
    }
    if (this._preferred) {
      return this.disable();
    }
    return this.enable();
  };

  // ── Lifecycle (PWA, background tabs, device lock) ──────────────

  KeepScreenAwake.prototype._onVisibilityChange = function () {
    if (document.hidden) {
      this._log("Document hidden — browser wake lock will be released");
      this._wakeLock = null;
      this._stopVideoFallback();
      this._syncActive();
      return;
    }
    this._log("Document visible — reacquiring browser layers if preference enabled");
    if (this._preferred) {
      this._acquire();
    }
  };

  KeepScreenAwake.prototype._onPageShow = function (event) {
    if (event.persisted) {
      this._log("Page restored from bfcache (PWA/back navigation)");
    }
    if (this._preferred && !document.hidden) {
      this._acquire();
    }
  };

  KeepScreenAwake.prototype._onPageHide = function () {
    if (this._preferred) {
      this._log("Page unloading — releasing native keep-awake");
      this._releaseNative();
    }
  };

  KeepScreenAwake.prototype._onButtonClick = function () {
    this.toggle();
  };

  // ── Init / destroy ───────────────────────────────────────────────

  KeepScreenAwake.prototype.init = function () {
    if (!this._button) {
      this._warn("Toggle button #btn-keep-awake not found — module idle");
      return this;
    }

    this._preferred = this._loadPreference();
    this._updateButton();

    this._button.addEventListener("click", this._onButtonClick);
    document.addEventListener("visibilitychange", this._onVisibilityChange);
    window.addEventListener("pageshow", this._onPageShow);
    window.addEventListener("pagehide", this._onPageHide);

    if (typeof document.addEventListener === "function") {
      document.addEventListener("resume", this._onPageShow, false);
    }

    if (!this._caps.secureContext) {
      this._warn("Not a secure context — Wake Lock API unavailable");
    }

    if (this._preferred) {
      this._log("Stored preference enabled — attempting acquire");
      this._acquire().then(function (ok) {
        if (!ok) {
          this._showStatus("Tap the button to keep the screen awake.", "info");
        }
      }.bind(this));
    }

    return this;
  };

  KeepScreenAwake.prototype.destroy = function () {
    this._destroyed = true;
    if (this._button) {
      this._button.removeEventListener("click", this._onButtonClick);
    }
    document.removeEventListener("visibilitychange", this._onVisibilityChange);
    window.removeEventListener("pageshow", this._onPageShow);
    window.removeEventListener("pagehide", this._onPageHide);
    clearTimeout(this._statusTimer);
    this._release();
    if (this._video && this._video.parentNode) {
      this._video.parentNode.removeChild(this._video);
    }
    this._video = null;
  };

  // ── Auto-init ────────────────────────────────────────────────────

  function autoInit() {
    var instance = new KeepScreenAwake();
    instance.init();
    global.KeepScreenAwake = KeepScreenAwake;
    global.keepScreenAwake = instance;
    return instance;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit);
  } else {
    autoInit();
  }

}(typeof window !== "undefined" ? window : this));
