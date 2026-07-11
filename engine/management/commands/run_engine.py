"""
Management command to start the StageAble runtime engine.

Usage:
    python manage.py run_engine

This starts the OSC polling loop in a background thread.  It is designed
to be called from the ASGI server startup or as a standalone process.
When running under Daphne the engine starts automatically (see asgi.py).
"""

import signal
import sys
import time

from django.core.management.base import BaseCommand

from engine.runtime import get_engine


class Command(BaseCommand):
    help = "Start the StageAble runtime engine (OSC polling loop)"

    def handle(self, *args, **options):
        engine = get_engine()
        engine.start()
        self.stdout.write(self.style.SUCCESS("StageAble engine started"))
        self.stdout.write("Press Ctrl+C to stop...\n")

        def _shutdown(signum, frame):
            self.stdout.write("\nShutting down...")
            engine.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        # Keep main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            engine.stop()
