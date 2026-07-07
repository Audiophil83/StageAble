# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the RemoteAble macOS app bundle."""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
root = Path(SPECPATH)
version_file = root / "VERSION"
app_version = os.environ.get("REMOTEABLE_VERSION", "").strip()
if not app_version and version_file.is_file():
    app_version = version_file.read_text(encoding="utf-8").strip()
if not app_version:
    app_version = "0.0.0-dev"
hook_dir = str(root / "scripts" / "packaging" / "hooks")

# Optional/test-only subpackages that fail to import during analysis.
_SKIP_SUBMODULE_PREFIXES = (
    "django.contrib.postgres",
    "rest_framework.schemas",
    "twisted.trial",
    "twisted.internet.test",
    "autobahn.asyncio",
    "pythonosc.test",
)


def _include_submodule(name: str) -> bool:
    return not any(
        name == prefix or name.startswith(prefix + ".")
        for prefix in _SKIP_SUBMODULE_PREFIXES
    )

project_datas = [
    (str(root / "templates"), "templates"),
    (str(root / "static"), "static"),
    (str(root / "assets"), "assets"),
    (str(root / "VERSION"), "."),
    # End User License Agreement governing use of the app.
    (str(root / "EULA.md"), "."),
    # Third-party attribution notices required by the bundled dependencies'
    # licenses (MIT/BSD/Apache/etc.).
    (str(root / "THIRD-PARTY-LICENSES.txt"), "."),
    # The Ableton Live control surface, installed on demand via the menu bar.
    # Ships its own LICENSE + NOTICE (AbletonOSC MIT attribution) inside the folder.
    (str(root / "remoteable_bridge"), "remoteable_bridge"),
]

hiddenimports = collect_submodules("engine") + collect_submodules("remoteable")
binaries = []
datas = list(project_datas)

for package in (
    "django",
    "daphne",
    "channels",
    "rest_framework",
    "twisted",
    "autobahn",
    "asgiref",
    "sortedcontainers",
    "pythonosc",
    "rumps",
):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(
        package,
        filter_submodules=_include_submodule,
        on_error="ignore",
    )
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

hiddenimports += [
    "engine.apps",
    "engine.consumers",
    "engine.routing",
    "engine.startup",
    "engine.models",
    "engine.views",
    "engine.serializers",
    "engine.admin",
    "engine.management.commands.run_engine",
    "engine.management.commands.serve",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels.layers",
    "daphne.server",
    "daphne.cli",
    "twisted.internet.asyncioreactor",
    "autobahn.twisted.websocket",
    "rumps",
    "objc",
    "Foundation",
    "AppKit",
    "PyObjCTools",
]

a = Analysis(
    [str(root / "scripts" / "packaging" / "launcher.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[hook_dir],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RemoteAble",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root / "assets" / "RemoteAble.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RemoteAble",
)

app = BUNDLE(
    coll,
    name="RemoteAble.app",
    icon=str(root / "assets" / "RemoteAble.icns"),
    bundle_identifier="com.remoteable.app",
    info_plist={
        "LSUIElement": True,
        "CFBundleShortVersionString": app_version,
        "CFBundleVersion": app_version,
    },
)
