from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ACTIONS = {
    "transport.toggle_play": "Play / pause",
    "transport.stop": "Stop",
    "song.previous": "Previous song",
    "song.next": "Next song",
}


class ActionDispatcher:
    def __init__(self, engine):
        self.engine = engine

    def dispatch(self, action: str) -> bool:
        commands = {
            "transport.toggle_play": self.engine.cmd_toggle_play,
            "transport.stop": self.engine.cmd_stop,
            "song.previous": self.engine.cmd_previous_song,
            "song.next": self.engine.cmd_next_song,
        }
        command = commands.get(action)
        if command is None:
            logger.warning("Unknown controller action: %s", action)
            return False
        command()
        return True
