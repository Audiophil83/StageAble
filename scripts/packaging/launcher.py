"""
PyInstaller entry point for the RemoteAble macOS app bundle.

Supports a hidden --daphne-worker mode used by engine.serve to spawn Daphne
inside the frozen executable (no separate Python install required).
"""

from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path

# PyInstaller with console=False may omit the site module, leaving the
# exit/quit builtins undefined.  Daphne calls exit(1) on fatal errors,
# so we must ensure they exist.
if not hasattr(builtins, "exit"):
    builtins.exit = sys.exit  # type: ignore[attr-defined]
if not hasattr(builtins, "quit"):
    builtins.quit = sys.exit  # type: ignore[attr-defined]


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


def run_daphne_worker(argv: list[str]) -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "remoteable.settings")
    os.environ["REMOTEABLE_FROZEN"] = "1"
    os.chdir(resource_root())
    sys.argv = ["daphne", *argv]
    from daphne.cli import CommandLineInterface

    CommandLineInterface.entrypoint()
    return 0


def run_migrations() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "remoteable.settings")
    os.environ["REMOTEABLE_FROZEN"] = "1"
    os.environ["REMOTEABLE_NO_ENGINE"] = "1"
    os.chdir(resource_root())

    import django

    django.setup()
    from django.core.management import call_command

    call_command("migrate", verbosity=0, interactive=False)


def run_app(argv: list[str]) -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "remoteable.settings")
    os.environ["REMOTEABLE_FROZEN"] = "1"
    os.chdir(resource_root())

    run_migrations()
    os.environ.pop("REMOTEABLE_NO_ENGINE", None)

    from engine.serve import main

    return main(argv)


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "--daphne-worker":
        return run_daphne_worker(argv[1:])
    return run_app(argv)


if __name__ == "__main__":
    raise SystemExit(main())
