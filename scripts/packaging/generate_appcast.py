#!/usr/bin/env python3
"""Generate a Sparkle appcast XML file for RemoteAble releases."""

from __future__ import annotations

import argparse
from pathlib import Path


def build_appcast(
    *,
    version: str,
    macos_url: str,
    windows_url: str | None,
    length: int,
    release_notes_url: str | None = None,
) -> str:
    notes = (
        f'      <sparkle:releaseNotesLink>{release_notes_url}</sparkle:releaseNotesLink>\n'
        if release_notes_url
        else ""
    )
    windows_item = ""
    if windows_url:
        windows_item = f"""
    <item>
      <title>RemoteAble {version} (Windows)</title>
{notes}      <enclosure url="{windows_url}"
                 sparkle:version="{version}"
                 length="{length}"
                 type="application/octet-stream" />
    </item>"""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>RemoteAble</title>
    <item>
      <title>RemoteAble {version} (macOS)</title>
{notes}      <enclosure url="{macos_url}"
                 sparkle:version="{version}"
                 length="{length}"
                 type="application/octet-stream" />
    </item>{windows_item}
  </channel>
</rss>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Sparkle appcast XML")
    parser.add_argument("--version", required=True)
    parser.add_argument("--macos-url", required=True)
    parser.add_argument("--windows-url")
    parser.add_argument("--length", type=int, default=0)
    parser.add_argument("--release-notes-url")
    parser.add_argument("-o", "--output", type=Path, default=Path("dist/appcast.xml"))
    args = parser.parse_args()

    xml = build_appcast(
        version=args.version,
        macos_url=args.macos_url,
        windows_url=args.windows_url,
        length=args.length,
        release_notes_url=args.release_notes_url,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(xml, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
