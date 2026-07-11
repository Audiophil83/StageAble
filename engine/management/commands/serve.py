"""
Start ShowAble with the web UI and optional desktop status window.

Usage:
    python manage.py serve
    python manage.py serve --port 8080
    python manage.py serve --no-ui
"""

from django.core.management.base import BaseCommand

from engine.serve import DEFAULT_HOST, DEFAULT_PORT, run_server


class Command(BaseCommand):
    help = "Start the ShowAble web server (with a desktop status window on macOS)"

    def add_arguments(self, parser):
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

    def handle(self, *args, **options):
        exit_code = run_server(
            options["bind"],
            options["port"],
            status_ui=False if options["no_ui"] else None,
        )
        if exit_code:
            self.stderr.write(self.style.ERROR(f"Server exited with code {exit_code}"))
