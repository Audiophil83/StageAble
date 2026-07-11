"""Windows system tray UI for StageAble."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from subprocess import Popen


def app_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets" / "app-icon.png"
    return Path(__file__).resolve().parent.parent / "assets" / "app-icon.png"


class StageAbleTray:
    def __init__(
        self,
        url: str,
        display: str,
        process: Popen[str],
        bind_host: str,
        port: int,
    ) -> None:
        import pystray
        from PIL import Image

        self.url = url
        self.display = display
        self.process = process
        self.bind_host = bind_host
        self.port = port
        self._last_display = display
        self._stop_event = threading.Event()

        icon_path = app_icon_path()
        image = Image.open(icon_path) if icon_path.exists() else Image.new("RGB", (64, 64), color=(30, 30, 30))
        self._icon = pystray.Icon(
            "StageAble",
            image,
            f"StageAble — {display}",
            menu=pystray.Menu(
                pystray.MenuItem(lambda item: f"Running at {self.display}", None, enabled=False),
                pystray.MenuItem(lambda item: f"Version {self._version()}", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Open in Browser", self._open_url),
                pystray.MenuItem("Copy Address", self._copy_url),
                pystray.MenuItem("Refresh Address", self._refresh_address),
                pystray.MenuItem("Rescan Project", self._rescan_project),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Install Ableton Bridge…", self._install_bridge),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Activate License…", self._activate_license),
                pystray.MenuItem("Check for Updates…", self._check_updates),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("License Agreement…", self._open_eula),
                pystray.MenuItem("Third-Party Licenses…", self._open_third_party),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            ),
        )

    def _version(self) -> str:
        from engine.version import get_version

        return get_version()

    def _open_url(self, _icon: object, _item: object) -> None:
        webbrowser.open(self.url)

    def _copy_url(self, _icon: object, _item: object) -> None:
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(self.url)
            root.update()
            root.destroy()
        except Exception:
            pass

    def _refresh_address(self, _icon: object, _item: object) -> None:
        from engine.serve import build_urls

        display, url = build_urls(self.bind_host, self.port)
        self.display = display
        self.url = url
        self._last_display = display
        self._icon.title = f"StageAble — {display}"

    def _poll_address(self) -> None:
        from engine.serve import build_urls

        while not self._stop_event.wait(10):
            display, url = build_urls(self.bind_host, self.port)
            if display == self._last_display:
                continue
            self._last_display = display
            self.display = display
            self.url = url
            self._icon.title = f"StageAble — {display}"

    def _rescan_project(self, _icon: object, _item: object) -> None:
        endpoint = f"{self.url.rstrip('/')}/api/rescan/"
        req = urllib.request.Request(
            endpoint,
            data=json.dumps({}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status >= 400:
                    raise urllib.error.HTTPError(
                        endpoint, resp.status, resp.reason, resp.headers, None
                    )
        except Exception:
            return

    def _install_bridge(self, _icon: object, _item: object) -> None:
        from engine.bridge_installer import BridgeInstallError, install

        try:
            install()
        except BridgeInstallError:
            return

    def _activate_license(self, _icon: object, _item: object) -> None:
        import tkinter as tk
        from tkinter import messagebox, simpledialog

        from engine import licensing

        status = licensing.get_status()
        if status.mode == licensing.LicenseMode.LICENSED:
            messagebox.showinfo(
                "License active",
                f"StageAble is licensed ({status.license_key_masked}).",
            )
            return

        root = tk.Tk()
        root.withdraw()
        key = simpledialog.askstring(
            "Activate StageAble",
            "Enter your license key (STA-XXXX-XXXX-XXXX):",
        )
        root.destroy()
        if not key:
            return
        try:
            licensing.activate_license(key)
        except ValueError as exc:
            messagebox.showerror("Activation failed", str(exc))

    def _check_updates(self, _icon: object, _item: object) -> None:
        import tkinter as tk
        from tkinter import messagebox

        from engine.updates import check_for_updates

        info = check_for_updates(platform="windows")
        root = tk.Tk()
        root.withdraw()
        if info is None:
            messagebox.showinfo(
                "No updates",
                "StageAble is up to date, or the update server is unreachable.",
            )
            root.destroy()
            return
        webbrowser.open(info.download_url)
        messagebox.showinfo(
            "Update available",
            f"Version {info.latest_version} is available. Your browser will download it.",
        )
        root.destroy()

    def _open_eula(self, _icon: object, _item: object) -> None:
        from engine import eula

        eula.open_document(eula.eula_path())

    def _open_third_party(self, _icon: object, _item: object) -> None:
        from engine import eula

        eula.open_document(eula.third_party_licenses_path())

    def _watch_server(self) -> None:
        while not self._stop_event.wait(2):
            if self.process.poll() is None:
                continue
            self._icon.stop()
            return

    def _quit(self, _icon: object, _item: object) -> None:
        from engine.serve import stop_daphne

        self._stop_event.set()
        stop_daphne(self.process)
        self._icon.stop()

    def _ensure_eula_accepted(self) -> None:
        from engine import eula

        if eula.is_accepted():
            return
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        accepted = messagebox.askyesno(
            "StageAble License Agreement",
            eula.SUMMARY,
        )
        if accepted:
            eula.mark_accepted()
        else:
            self._quit(self._icon, None)
        root.destroy()

    def run(self) -> None:
        self._ensure_eula_accepted()
        threading.Thread(target=self._poll_address, daemon=True).start()
        threading.Thread(target=self._watch_server, daemon=True).start()
        self._icon.run()


def run(
    url: str,
    display: str,
    process: Popen[str],
    bind_host: str,
    port: int,
) -> None:
    StageAbleTray(url, display, process, bind_host, port).run()
