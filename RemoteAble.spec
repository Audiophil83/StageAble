# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the RemoteAble macOS app bundle."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
root = Path(SPECPATH)

project_datas = [
    (str(root / "templates"), "templates"),
    (str(root / "static"), "static"),
    (str(root / "assets"), "assets"),
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
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package)
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
    hookspath=[],
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
    info_plist={"LSUIElement": True},
)
