#!/usr/bin/env python3
"""
Build app icons and favicons from a simple, reproducible playback mark.

Outputs:
  assets/StageAble.icns          macOS app bundle icon
  assets/StageAble.iconset/      intermediate PNGs for iconutil
  assets/app-icon.png             128×128 for the desktop status window
  static/favicon.ico
  static/favicon-16x16.png
  static/favicon-32x32.png
  static/apple-touch-icon.png    180×180

Requires Pillow: pip install Pillow

Usage:
    python scripts/build_app_icon.py [source.png]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
STATIC = ROOT / "static"
DEFAULT_SOURCE = ASSETS / "StageAble.png"
OUT_ICNS = ASSETS / "StageAble.icns"
OUT_APP_ICON = ASSETS / "app-icon.png"
ICONSET = ASSETS / "StageAble.iconset"


def draw_mark(image: Image.Image, box: tuple[int, int, int, int], fill) -> None:
    """Four vertical bars and four stripes clipped to a symmetric play shape.

    Draw both groups on the same grid so their thickness and height match.
    """
    draw = ImageDraw.Draw(image)
    x, y, width, height = box
    scale = min(width / 720, height / 420)
    ox = x + (width - 720 * scale) / 2
    oy = y + (height - 420 * scale) / 2

    def polygon(points):
        draw.polygon(
            [(round(ox + px * scale), round(oy + py * scale))
             for px, py in points], fill=fill,
        )

    for index in range(4):
        left = index * 100
        polygon([(left, 0), (left + 60, 0),
                 (left + 60, 420), (left, 420)])

    def right_edge(py):
        return 420 + 300 * (1 - abs(py - 210) / 210)

    for index in range(4):
        top = index * 120
        bottom = top + 60
        polygon([(420, top), (right_edge(top), top),
                 (right_edge(bottom), bottom), (420, bottom)])


def build_master() -> Image.Image:
    image = Image.new("RGBA", (1024, 1024))
    ImageDraw.Draw(image).rounded_rectangle(
        (32, 32, 992, 992), radius=216, fill="#20212b",
    )
    draw_mark(image, (192, 325, 640, 374), "#ffffff")
    return image


def write_menu_bar_icon() -> None:
    # 2x artwork; rumps displays this at 20 points. Only alpha defines a
    # template image, letting AppKit choose the appropriate foreground color.
    image = Image.new("RGBA", (320, 320))
    draw_mark(image, (16, 76, 288, 168), "#000000")
    image.resize((40, 40), Image.Resampling.LANCZOS).save(
        ASSETS / "menu-bar-template.png"
    )


def load_square(source: Path) -> Image.Image:
    img = Image.open(source).convert("RGBA")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def write_iconset(master: Image.Image) -> None:
    ICONSET.mkdir(parents=True, exist_ok=True)
    sizes = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for name, px in sizes:
        resized = master.resize((px, px), Image.Resampling.LANCZOS)
        resized.save(ICONSET / name, format="PNG")

    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(OUT_ICNS)],
        check=True,
    )


def write_favicons(master: Image.Image) -> None:
    STATIC.mkdir(parents=True, exist_ok=True)

    base = master.resize((256, 256), Image.Resampling.LANCZOS)
    base.save(
        STATIC / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )

    master.resize((16, 16), Image.Resampling.LANCZOS).save(
        STATIC / "favicon-16x16.png", format="PNG"
    )
    master.resize((32, 32), Image.Resampling.LANCZOS).save(
        STATIC / "favicon-32x32.png", format="PNG"
    )
    master.resize((180, 180), Image.Resampling.LANCZOS).save(
        STATIC / "apple-touch-icon.png", format="PNG"
    )


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if source is not None and not source.exists():
        print(f"Source not found: {source}", file=sys.stderr)
        return 1

    master = load_square(source) if source else build_master()
    if master.width != 1024:
        master = master.resize((1024, 1024), Image.Resampling.LANCZOS)

    if source is None:
        master.save(DEFAULT_SOURCE)
    write_menu_bar_icon()
    master.resize((128, 128), Image.Resampling.LANCZOS).save(OUT_APP_ICON, format="PNG")
    write_favicons(master)

    if sys.platform != "darwin":
        print("Skipping .icns (requires macOS iconutil)", file=sys.stderr)
    else:
        try:
            write_iconset(master)
            print(f"Wrote {OUT_ICNS}")
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            print(f"iconutil unavailable; using Pillow ICNS encoder: {exc}", file=sys.stderr)
            master.save(OUT_ICNS, format="ICNS")

    print(f"Wrote {OUT_APP_ICON}")
    print(f"Wrote favicons in {STATIC}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
