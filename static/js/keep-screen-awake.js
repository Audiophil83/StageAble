/**
 * Keep Screen Awake — cross-browser screen wake lock for Django SPAs.
 *
 * COMPATIBILITY MATRIX (expected behavior):
 *
 * | Browser                  | Wake Lock API | Fallback       | Notes |
 * |--------------------------|---------------|----------------|-------|
 * | iOS Safari 16.4+         | Yes           | Muted video    | Video + silent audio; random seek on iOS; PWA needs 18.4+ for Wake Lock |
 * | iOS Safari <16.4         | No            | Muted video    | Video loop prevents auto-lock during active playback |
 * | Chrome Android           | Yes           | Muted video    | Reacquire on visibilitychange; battery saver may block |
 * | Samsung Internet         | Yes           | Muted video    | Chromium-based; same as Chrome Android |
 * | Firefox Android          | Partial       | Muted video    | Wake Lock in recent versions; video fallback otherwise |
 * | Desktop Chrome / Edge    | Yes           | —              | Full support in secure contexts |
 * | Desktop Firefox          | Yes (126+)    | Muted video    | Older versions use video fallback |
 * | Desktop Safari (macOS)   | Yes (16.4+)   | Muted video    | Wake Lock may not block screen saver; use native API when server is local |
 *
 * macOS screen saver: browsers cannot reliably suppress it. When ShowAble runs
 * on the same Mac as the browser, POST /api/keep-awake/ starts ``caffeinate
 * -dims`` on the server to disable screen saver and display sleep system-wide.
 * Battery: wake lock prevents display sleep only; fallback video is 8×8 px, muted,
 *          and paused immediately when disabled. No timer spam or page reloads.
 *
 * Security: requires HTTPS (or localhost). No server-side secrets involved.
 */
(function (global) {
  "use strict";

  var LOG_PREFIX = "[KeepScreenAwake]";
  var STATUS_HIDE_MS = 4000;

  /* Minimal silent MP4 — also served at /static/media/wake-lock-silent.mp4 */
  var FALLBACK_VIDEO_SRC = "/static/media/wake-lock-silent.mp4";
  var NATIVE_API_URL = "/api/keep-awake/";
  var IOS_WATCHDOG_MS = 15000;

  function parseIOSVersion(ua) {
    var match = ua.match(/OS (\d+)[_.](\d+)(?:[_.](\d+))?/);
    if (!match) return null;
    return {
      major: parseInt(match[1], 10),
      minor: parseInt(match[2], 10),
      patch: parseInt(match[3] || "0", 10),
    };
  }

  function iosSupportsPwaWakeLock(iosVersion) {
    if (!iosVersion) return false;
    return iosVersion.major > 18 ||
      (iosVersion.major === 18 && iosVersion.minor >= 4);
  }

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
    var isStandalone = !!(global.matchMedia &&
      global.matchMedia("(display-mode: standalone)").matches) ||
      global.navigator.standalone === true;
    var iosVersion = isIOS ? parseIOSVersion(ua) : null;
    // Wake Lock in iOS home-screen PWAs was broken until iOS 18.4; rely on video there.
    var useWakeLock = wakeLockSupported &&
      (!isIOS || !isStandalone || iosSupportsPwaWakeLock(iosVersion));

    return {
      isIOS: isIOS,
      isAndroid: isAndroid,
      isSafari: isSafari,
      isSamsung: isSamsung,
      isFirefox: isFirefox,
      isMacOS: isMacOS,
      isStandalone: isStandalone,
      iosVersion: iosVersion,
      wakeLockSupported: wakeLockSupported,
      useWakeLock: useWakeLock,
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

    this._preferred = false;   // user wants screen awake (session only; default off)
    this._active = false;      // lock/video currently holding screen
    this._wakeLock = null;
    this._video = null;
    this._audioCtx = null;
    this._audioSource = null;
    this._audioActive = false;
    this._statusTimer = null;
    this._usingFallback = false;
    this._nativeActive = false;
    this._iosWatchdog = null;
    this._destroyed = false;

    this._onButtonClick = this._onButtonClick.bind(this);
    this._onVisibilityChange = this._onVisibilityChange.bind(this);
    this._onPageShow = this._onPageShow.bind(this);
    this._onPageHide = this._onPageHide.bind(this);
    this._onWakeLockRelease = this._onWakeLockRelease.bind(this);
    this._onVideoPause = this._onVideoPause.bind(this);
    this._onVideoEnded = this._onVideoEnded.bind(this);

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
    this._active = !!(
      this._wakeLock ||
      this._usingFallback ||
      this._audioActive ||
      this._nativeActive
    );
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

  // ── Wake Lock API ────────────────────────────────────────────────

  KeepScreenAwake.prototype._requestWakeLock = function () {
    var self = this;
    if (!this._caps.useWakeLock || !this._caps.secureContext) {
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
    if (!this._preferred || document.hidden) return;
    this._log("Reacquiring wake lock after unexpected release");
    this._requestWakeLock();
    this._ensureVideoPlaying();
    this._ensureSilentAudioPlaying();
  };

  KeepScreenAwake.prototype._onVideoPause = function () {
    if (!this._preferred || document.hidden || !this._video) return;
    this._log("Video paused while keep-awake enabled — attempting resume");
    this._ensureVideoPlaying();
  };

  KeepScreenAwake.prototype._onVideoEnded = function () {
    if (!this._preferred || !this._video) return;
    this._video.currentTime = 0;
    this._ensureVideoPlaying();
  };

  KeepScreenAwake.prototype._bindVideoKeepalive = function (video) {
    video.addEventListener("pause", this._onVideoPause);
    video.addEventListener("ended", this._onVideoEnded);
    if (this._caps.isIOS) {
      // iOS often ignores loop= on silent MP4; random seek keeps playback alive (NoSleep.js).
      video.loop = false;
      video.addEventListener("timeupdate", function () {
        if (!video.paused && video.currentTime > 0.5) {
          video.currentTime = Math.random() * 0.25;
        }
      });
    }
  };

  KeepScreenAwake.prototype._ensureVideoPlaying = function () {
    if (!this._preferred || !this._video) return Promise.resolve(false);
    if (!this._video.paused && !this._video.ended) {
      this._usingFallback = true;
      this._syncActive();
      return Promise.resolve(true);
    }
    this._video.muted = true;
    var self = this;
    return this._video.play().then(function () {
      self._usingFallback = true;
      self._syncActive();
      return true;
    }).catch(function (err) {
      self._warn("Video resume failed", err);
      self._usingFallback = false;
      self._syncActive();
      return false;
    });
  };

  KeepScreenAwake.prototype._startIOSWatchdog = function () {
    var self = this;
    if (!this._caps.isIOS || this._iosWatchdog) return;
    this._iosWatchdog = setInterval(function () {
      if (!self._preferred || document.hidden || self._destroyed) return;
      if (self._video && (self._video.paused || self._video.ended)) {
        self._log("iOS watchdog: video not playing");
        self._ensureVideoPlaying();
      }
      if (self._caps.useWakeLock && !self._wakeLock) {
        self._requestWakeLock();
      }
      self._ensureSilentAudioPlaying();
    }, IOS_WATCHDOG_MS);
  };

  KeepScreenAwake.prototype._stopIOSWatchdog = function () {
    if (!this._iosWatchdog) return;
    clearInterval(this._iosWatchdog);
    this._iosWatchdog = null;
  };

  KeepScreenAwake.prototype._ensureSilentAudio = function () {
    if (this._audioCtx) return this._audioCtx;
    var AudioCtx = global.AudioContext || global.webkitAudioContext;
    if (!AudioCtx) return null;
    try {
      var ctx = new AudioCtx();
      var buffer = ctx.createBuffer(1, 1, 22050);
      var source = ctx.createBufferSource();
      source.buffer = buffer;
      source.loop = true;
      source.connect(ctx.destination);
      source.start(0);
      this._audioCtx = ctx;
      this._audioSource = source;
      return ctx;
    } catch (err) {
      this._warn("Silent audio setup failed", err);
      return null;
    }
  };

  KeepScreenAwake.prototype._ensureSilentAudioPlaying = function () {
    if (!this._preferred || !this._caps.isIOS) return Promise.resolve(false);
    var ctx = this._ensureSilentAudio();
    if (!ctx) return Promise.resolve(false);
    if (ctx.state === "running") {
      this._audioActive = true;
      this._syncActive();
      return Promise.resolve(true);
    }
    var self = this;
    return ctx.resume().then(function () {
      self._audioActive = true;
      self._syncActive();
      return true;
    }).catch(function (err) {
      self._warn("Silent audio resume failed", err);
      self._audioActive = false;
      self._syncActive();
      return false;
    });
  };

  KeepScreenAwake.prototype._startSilentAudio = function () {
    return this._ensureSilentAudioPlaying();
  };

  KeepScreenAwake.prototype._stopSilentAudio = function () {
    this._audioActive = false;
    if (this._audioSource) {
      try {
        this._audioSource.stop();
      } catch (e) {
        /* ignore */
      }
      this._audioSource.disconnect();
      this._audioSource = null;
    }
    if (!this._audioCtx) return Promise.resolve();
    var ctx = this._audioCtx;
    this._audioCtx = null;
    return ctx.close().catch(function () {});
  };

  // ── Video fallback (iOS Safari <16.4, unsupported browsers) ────────

  KeepScreenAwake.prototype._ensureVideo = function () {
    if (this._video) return this._video;

    var video = document.createElement("video");
    video.setAttribute("playsinline", "true");
    video.setAttribute("webkit-playsinline", "true");
    video.playsInline = true;
    video.muted = true;
    video.defaultMuted = true;
    video.loop = !this._caps.isIOS;
    video.preload = "auto";
    video.autoplay = false;
    video.controls = false;
    video.disablePictureInPicture = true;
    video.setAttribute("disablepictureinpicture", "");
    video.className = "keep-awake-fallback-video";
    video.setAttribute("aria-hidden", "true");
    video.tabIndex = -1;

    var source = document.createElement("source");
    source.src = this._videoSrc;
    source.type = "video/mp4";
    video.appendChild(source);

    this._bindVideoKeepalive(video);
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
    this._video.removeEventListener("pause", this._onVideoPause);
    this._video.pause();
    this._video.currentTime = 0;
    this._video.addEventListener("pause", this._onVideoPause);
    if (this._usingFallback) {
      this._log("Video fallback stopped");
    }
    this._usingFallback = false;
  };

  // ── Acquire / release orchestration ──────────────────────────────

  KeepScreenAwake.prototype._acquireBrowserLayers = function () {
    var self = this;
    var canWakeLock = this._caps.useWakeLock && this._caps.secureContext;
    // iOS/iPadOS and macOS need muted video; start it in parallel with Wake Lock so
    // video.play() stays inside the tap gesture (iOS rejects deferred play()).
    var parallelVideo = this._caps.isMacOS || this._caps.isIOS;

    if (parallelVideo) {
      var wakeLockPromise = canWakeLock
        ? this._requestWakeLock()
        : Promise.resolve(false);
      var videoPromise = this._startVideoFallback();
      var audioPromise = this._caps.isIOS
        ? this._startSilentAudio()
        : Promise.resolve(false);
      return Promise.all([wakeLockPromise, videoPromise, audioPromise]).then(function (results) {
        if (self._caps.isIOS && self._preferred) {
          self._startIOSWatchdog();
        }
        return results[0] || results[1] || results[2];
      });
    }

    if (canWakeLock) {
      return this._requestWakeLock().then(function (wakeLockOk) {
        if (wakeLockOk) return true;
        return self._startVideoFallback();
      });
    }

    return this._startVideoFallback();
  };

  KeepScreenAwake.prototype._acquire = function () {
    var self = this;
    if (!this._preferred || this._destroyed) return Promise.resolve(false);

    // iOS Safari requires wakeLock.request() and video.play() inside the user
    // gesture. Do not await the macOS native API fetch before starting them.
    var browserPromise = this._acquireBrowserLayers();
    var nativePromise = this._caps.isMacOS
      ? this._acquireNative()
      : Promise.resolve(false);

    return Promise.all([browserPromise, nativePromise]).then(function (results) {
      self._syncActive();
      return results[0] || results[1] || self._nativeActive;
    });
  };

  KeepScreenAwake.prototype._release = function () {
    var self = this;
    this._stopIOSWatchdog();
    this._stopVideoFallback();
    return Promise.all([
      this._releaseWakeLock(),
      this._releaseNative(),
      this._stopSilentAudio(),
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
    this._updateButton();
    return this._acquire().then(function (ok) {
      if (ok) {
        var msg = "Screen will stay awake.";
        if (this._nativeActive) {
          msg = "Screen and screen saver suppressed (macOS).";
        } else if (this._caps.isMacOS) {
          msg = "Screen awake enabled. For screen saver, open this page on the Mac running ShowAble, or set Screen Saver to Never in System Settings.";
        }
        this._showStatus(msg, "success");
      }
      return ok;
    }.bind(this));
  };

  KeepScreenAwake.prototype.disable = function () {
    this._preferred = false;
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

    this._preferred = false;
    this._updateButton();

    try {
      localStorage.removeItem("keepScreenAwake");
    } catch (e) {
      /* ignore */
    }

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

    if (this._caps.isIOS) {
      this._ensureVideo();
      if (this._video) {
        this._video.load();
      }
    }

    return this;
  };

  KeepScreenAwake.prototype.destroy = function () {
    this._destroyed = true;
    this._stopIOSWatchdog();
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
