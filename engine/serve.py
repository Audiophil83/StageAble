"""
Launch the Remoteable web server with an optional desktop status window.

    python -m engine.serve
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_local_ip() -> str:
    """Return the machine's LAN IP address, falling back to localhost."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def public_host(bind_host: str) -> str:
    """Map a bind address to the host clients should use."""
    if bind_host in ("0.0.0.0", ""):
        return get_local_ip()
    if bind_host == "::":
        return get_local_ip()
    return bind_host


def build_urls(bind_host: str, port: int) -> tuple[str, str]:
    """Return (display label, full URL) for the running server."""
    host = public_host(bind_host)
    display = f"{host}:{port}"
    url = f"http://{display}"
    return display, url


def python_for_subprocess() -> str:
    """Use pythonw on macOS so background server processes stay out of the dock."""
    if sys.platform != "darwin":
        return sys.executable
    pythonw = Path(sys.executable).with_name("pythonw")
    if pythonw.exists():
        return str(pythonw)
    return sys.executable


def _daphne_log_file() -> IO[str] | None:
    """Open a log file for Daphne output when running as a frozen .app bundle."""
    if not getattr(sys, "frozen", False):
        return None
    log_dir = Path.home() / "Library" / "Application Support" / "RemoteAble"
    log_dir.mkdir(parents=True, exist_ok=True)
    return open(log_dir / "daphne.log", "w")  # noqa: SIM115


def start_daphne(bind_host: str, port: int) -> subprocess.Popen[str]:
    """Start Daphne as a background subprocess."""
    root = project_root()
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        cmd = [
            sys.executable,
            "--daphne-worker",
            "-b",
            bind_host,
            "-p",
            str(port),
            "remoteable.asgi:application",
        ]
        env.setdefault("DJANGO_SETTINGS_MODULE", "remoteable.settings")
        env["REMOTEABLE_FROZEN"] = "1"
    else:
        cmd = [
            python_for_subprocess(),
            "-m",
            "daphne",
            "-b",
            bind_host,
            "-p",
            str(port),
            "remoteable.asgi:application",
        ]
    log_file = _daphne_log_file()
    return subprocess.Popen(
        cmd,
        cwd=root,
        env=env,
        stdout=log_file,
        stderr=log_file,
    )


def stop_daphne(process: subprocess.Popen[str]) -> None:
    """Terminate the Daphne subprocess."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_status_ui(url: str, display: str, process: subprocess.Popen[str]) -> None:
    """Show a small desktop window with the server address."""
    from engine.status_ui import run

    run(url, display, process)


def run_server(bind_host: str, port: int, *, status_ui: bool | None = None) -> int:
    """Start Remoteable and optionally show a desktop status window."""
    display, url = build_urls(bind_host, port)
    show_ui = status_ui if status_ui is not None else sys.platform == "darwin"

    process = start_daphne(bind_host, port)

    if show_ui:
        try:
            run_status_ui(url, display, process)
        finally:
            stop_daphne(process)
        return process.returncode or 0

    print(f"Remoteable running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        return process.wait()
    except KeyboardInterrupt:
        stop_daphne(process)
        return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start Remoteable with status window")
    parser.add_argument(
        "-b",
        "--bind",
        default=DEFAULT_HOST,
        help=f"Bind address (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-ui",
        action="store_true",
        help="Run without the desktop status window",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_server(
        args.bind,
        args.port,
        status_ui=False if args.no_ui else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
