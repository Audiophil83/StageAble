"""Menu bar UI showing the Remoteable server address."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

import rumps

if TYPE_CHECKING:
    from subprocess import Popen


def app_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets" / "app-icon.png"
    return Path(__file__).resolve().parent.parent / "assets" / "app-icon.png"


def copy_to_clipboard(text: str) -> None:
    from AppKit import NSPasteboard, NSStringPboardType

    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    pasteboard.setString_forType_(text, NSStringPboardType)


class RemoteableStatusApp(rumps.App):
    def __init__(self, url: str, display: str, process: Popen[str]) -> None:
        icon = app_icon_path()
        super().__init__(
            "RemoteAble",
            icon=str(icon) if icon.exists() else None,
            quit_button=None,
        )
        self.url = url
        self.display = display
        self.process = process

        self.address_item = rumps.MenuItem(f"Running at {display}")
        self.menu = [
            self.address_item,
            None,
            rumps.MenuItem("Open in Browser", callback=self._open_url),
            rumps.MenuItem("Copy Address", callback=self._copy_url),
            rumps.MenuItem("Rescan Project", callback=self._rescan_project),
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]

        self._watch_timer = rumps.Timer(self._watch_server, 2)
        self._watch_timer.start()

    def _open_url(self, _sender: object) -> None:
        webbrowser.open(self.url)

    def _copy_url(self, _sender: object) -> None:
        copy_to_clipboard(self.url)
        rumps.notification("RemoteAble", "Address copied", self.url)

    def _rescan_project(self, _sender: object) -> None:
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
        except Exception as exc:
            rumps.notification("RemoteAble", "Rescan failed", str(exc))
            return
        rumps.notification(
            "RemoteAble",
            "Rescan started",
            "Scanning arrangement from Ableton in the background.",
        )

    def _watch_server(self, _timer: object) -> None:
        if self.process.poll() is not None:
            code = self.process.returncode
            rumps.notification(
                "RemoteAble", "Server stopped", f"Exit code {code}"
            )
            rumps.quit_application()

    def _quit(self, _sender: object) -> None:
        from engine.serve import stop_daphne

        stop_daphne(self.process)
        rumps.quit_application()


def run(url: str, display: str, process: Popen[str]) -> None:
    RemoteableStatusApp(url, display, process).run()
