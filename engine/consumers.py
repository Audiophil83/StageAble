"""
WebSocket consumer — connects browser clients to the engine state stream.

Clients receive real-time state updates and can send transport commands.
"""

from __future__ import annotations

import json
import logging

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .client_lock import disconnect as client_lock_disconnect
from .client_lock import lock as client_lock
from .client_lock import unlock as client_unlock
from .client_lock import unlock_requires_warning
from .runtime import WS_GROUP

logger = logging.getLogger(__name__)


class EngineConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for the engine state stream.

    - Joins the ``engine`` group on connect.
    - Receives ``engine.state`` broadcasts from the runtime loop.
    - Accepts commands from clients: play, stop, seek, jump_to_song,
      jump_to_setlist_index (via setlist_index field), jump_to_section, rescan.
    """

    async def connect(self):
        await self.channel_layer.group_add(WS_GROUP, self.channel_name)
        await self.accept()
        logger.info("WebSocket client connected: %s", self.channel_name)

        # Send current state immediately on connect
        from .state import engine_state

        snapshot = engine_state.snapshot()
        await self.send_json({"type": "state", "data": snapshot})
        await self.send_json({"type": "lock_state", "locked": True})

        from .runtime import get_engine

        in_progress, messages = get_engine().get_scan_status()
        await self.send_json(
            {
                "type": "scan_status",
                "in_progress": in_progress,
                "messages": messages,
            }
        )

    async def disconnect(self, close_code):
        client_lock_disconnect(self.channel_name)
        await self.channel_layer.group_discard(WS_GROUP, self.channel_name)
        logger.info("WebSocket client disconnected: %s", self.channel_name)

    async def receive_json(self, content, **kwargs):
        """Handle incoming commands from clients."""
        cmd = content.get("command")
        if not cmd:
            await self.send_json({"type": "error", "message": "Missing 'command' field"})
            return

        # Import here to avoid circular imports at module level
        from .runtime import get_engine

        engine = get_engine()

        try:
            if cmd == "play":
                engine.cmd_play()
            elif cmd == "toggle_play":
                engine.actions.dispatch("transport.toggle_play")
            elif cmd == "stop":
                engine.cmd_stop()
            elif cmd == "previous_song":
                engine.actions.dispatch("song.previous")
            elif cmd == "next_song":
                engine.actions.dispatch("song.next")
            elif cmd == "seek":
                beat = float(content.get("beat", 0))
                engine.cmd_seek(beat)
            elif cmd == "jump_to_song":
                if "setlist_index" in content:
                    index = int(content.get("setlist_index", 0))
                    engine.cmd_jump_to_setlist_index(index)
                else:
                    index = int(content.get("index", 0))
                    engine.cmd_jump_to_song(index)
            elif cmd == "jump_to_section":
                beat = float(content.get("start_beat", 0))
                engine.cmd_jump_to_section(beat)
            elif cmd == "rehearse_play":
                start_beat = content.get("start_beat")
                if start_beat is None:
                    await self.send_json(
                        {"type": "error", "message": "Missing 'start_beat' field"}
                    )
                    return
                engine.cmd_rehearse_play(float(start_beat))
            elif cmd == "rehearse_loop":
                start_beats = content.get("start_beats")
                if not start_beats:
                    await self.send_json(
                        {"type": "error", "message": "Missing 'start_beats' field"}
                    )
                    return
                engine.cmd_rehearse_loop([float(b) for b in start_beats])
            elif cmd == "rehearse_stop":
                engine.cmd_rehearse_stop()
            elif cmd == "rehearse_exit":
                engine.cmd_rehearse_exit()
            elif cmd == "rescan":
                # Rescan loads the active setlist from the DB (sync ORM).
                await sync_to_async(engine.cmd_rescan)()
            elif cmd == "check_unlock":
                await self.send_json(
                    {
                        "type": "unlock_check",
                        "requires_warning": unlock_requires_warning(
                            self.channel_name
                        ),
                    }
                )
                return
            elif cmd == "unlock":
                if unlock_requires_warning(self.channel_name) and not content.get(
                    "confirmed"
                ):
                    await self.send_json(
                        {
                            "type": "unlock_check",
                            "requires_warning": True,
                        }
                    )
                    return
                client_unlock(self.channel_name)
                await self.send_json({"type": "lock_state", "locked": False})
                return
            elif cmd == "lock":
                client_lock(self.channel_name)
                await self.send_json({"type": "lock_state", "locked": True})
                return
            elif cmd == "set_track_mute":
                track_index = int(content.get("track_index", -1))
                muted = content.get("muted")
                if muted is None:
                    await self.send_json(
                        {"type": "error", "message": "Missing 'muted' field"}
                    )
                    return
                engine.cmd_set_track_mute(track_index, bool(muted))
                await self.send_json(
                    {
                        "type": "ack",
                        "command": cmd,
                        "tracks": engine.get_mixer_tracks(live=False),
                    }
                )
                return
            else:
                await self.send_json(
                    {"type": "error", "message": f"Unknown command: {cmd}"}
                )
                return

            await self.send_json({"type": "ack", "command": cmd})

        except Exception as e:
            logger.exception("Error handling command %s", cmd)
            await self.send_json(
                {"type": "error", "message": f"Command failed: {e}"}
            )

    # ── Group message handlers ────────────────────────────────────────

    async def engine_state(self, event):
        """Broadcast engine state to this client."""
        await self.send_json({"type": "state", "data": event["data"]})

    async def engine_scan_progress(self, event):
        """Broadcast arrangement scan progress to this client."""
        await self.send_json(
            {
                "type": "scan_progress",
                "in_progress": event.get("in_progress", False),
                "done": event.get("done", False),
                "messages": event.get("messages", []),
            }
        )

    async def engine_device_event(self, event):
        await self.send_json(
            {
                "type": event.get("event", "devices_changed"),
                "data": event.get("data", {}),
            }
        )
