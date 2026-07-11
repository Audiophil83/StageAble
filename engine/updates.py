"""Update checks via Sparkle-style appcast XML (no Sparkle.framework required)."""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

from engine.version import get_version

DEFAULT_APPCAST_URL = os.environ.get(
    "STAGEABLE_APPCAST_URL",
    "https://downloads.stageable.app/appcast-macos.xml",
)


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    download_url: str
    release_notes_url: str | None = None

    @property
    def update_available(self) -> bool:
        return _version_tuple(self.latest_version) > _version_tuple(self.current_version)


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version)
    if not parts:
        return (0,)
    return tuple(int(part) for part in parts)


def parse_appcast(xml_text: str, *, platform: str = "macos") -> UpdateInfo | None:
    root = ET.fromstring(xml_text)
    ns = {"sparkle": "http://www.andymatuschak.org/xml-namespaces/sparkle"}
    for item in root.findall("./channel/item"):
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue
        url = enclosure.get("url", "")
        if platform == "windows" and "windows" not in url.lower():
            continue
        if platform == "macos" and "windows" in url.lower():
            continue
        version = enclosure.get(f"{{{ns['sparkle']}}}version") or enclosure.get("sparkle:version")
        if not version:
            version = item.findtext("title", default="0.0.0")
        return UpdateInfo(
            current_version=get_version(),
            latest_version=version.strip(),
            download_url=url,
            release_notes_url=item.findtext("sparkle:releaseNotesLink", default=None, namespaces=ns),
        )
    return None


def check_for_updates(
    *,
    appcast_url: str | None = None,
    platform: str = "macos",
    opener: Callable[..., object] | None = None,
) -> UpdateInfo | None:
    url = appcast_url or DEFAULT_APPCAST_URL
    request = urllib.request.Request(url, headers={"User-Agent": "StageAble-Updater"})
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(request, timeout=15) as response:  # type: ignore[arg-type]
            xml_text = response.read().decode("utf-8")
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
    info = parse_appcast(xml_text, platform=platform)
    if info is None:
        return None
    return info if info.update_available else None
