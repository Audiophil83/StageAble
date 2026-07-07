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

from engine.version import get_version

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
    def __init__(
        self,
        url: str,
        display: str,
        process: Popen[str],
        bind_host: str,
        port: int,
    ) -> None:
        icon = app_icon_path()
        super().__init__(
            "RemoteAble",
            icon=str(icon) if icon.exists() else None,
            quit_button=None,
        )
        self.url = url
        self.display = display
        self.process = process
        self.bind_host = bind_host
        self.port = port

        self.address_item = rumps.MenuItem(f"Running at {display}")
        self.menu = [
            self.address_item,
            rumps.MenuItem(f"Version {get_version()}", callback=None),
            None,
            rumps.MenuItem("Open in Browser", callback=self._open_url),
            rumps.MenuItem("Copy Address", callback=self._copy_url),
            rumps.MenuItem("Refresh Address", callback=self._refresh_address),
            rumps.MenuItem("Rescan Project", callback=self._rescan_project),
            None,
            rumps.MenuItem("Install Ableton Bridge…", callback=self._install_bridge),
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

    def _refresh_address(self, _sender: object) -> None:
        from engine.serve import build_urls

        display, url = build_urls(self.bind_host, self.port)
        self.display = display
        self.url = url
        self.address_item.title = f"Running at {display}"
        rumps.notification("RemoteAble", "Address refreshed", url)

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

    def _install_bridge(self, _sender: object) -> None:
        from engine.bridge_installer import BridgeInstallError, install

        try:
            dest = install()
        except BridgeInstallError as exc:
            rumps.alert(
                title="Couldn't install Ableton Bridge",
                message=str(exc),
                ok="OK",
            )
            return
        except Exception as exc:  # pragma: no cover - unexpected filesystem errors
            rumps.alert(
                title="Couldn't install Ableton Bridge",
                message=f"Unexpected error: {exc}",
                ok="OK",
            )
            return

        rumps.alert(
            title="Ableton Bridge installed",
            message=(
                f"Installed to:\n{dest}\n\n"
                "Next steps:\n"
                "1. Restart Ableton Live.\n"
                "2. Preferences ▸ Link / Tempo / MIDI ▸ Control Surface: "
                "select 'RemoteAble'."
            ),
            ok="Done",
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


def run(
    url: str,
    display: str,
    process: Popen[str],
    bind_host: str,
    port: int,
) -> None:
    RemoteableStatusApp(url, display, process, bind_host, port).run()
