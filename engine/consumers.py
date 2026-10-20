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
from .client_lock import is_unlocked
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
            if cmd.startswith("x32_"):
                if not is_unlocked(self.channel_name):
                    await self.send_json(
                        {
                            "type": "error",
                            "command": cmd,
                            "message": "Unlock controls to change X32 state",
                        }
                    )
                    return
                await self._handle_x32_command(cmd, content)
                return
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
                {"type": "error", "command": cmd, "message": f"Command failed: {e}"}
            )

    async def _handle_x32_command(self, cmd, content):
        from .models import ProjectCache
        from .state import engine_state
        from .x32 import get_x32_service

        project = engine_state.active_project
        project_id = project.get("id") if project else None
        service = get_x32_service()
        if cmd == "x32_open_editor":
            from .x32.desktop import open_editor
            result = await sync_to_async(open_editor, thread_sensitive=False)(self.scope.get("client", ("",))[0])
        elif cmd == "x32_phantom":
            result = await sync_to_async(service.set_phantom, thread_sensitive=False)(
                content.get("channel"), content.get("value")
            )
        elif cmd == "x32_test":
            result = await sync_to_async(service.test_connection, thread_sensitive=False)()
        elif cmd == "x32_refresh":
            await sync_to_async(service.capture_all, thread_sensitive=False)()
            result = service.mixer_state()
        elif cmd == "x32_set":
            result = await sync_to_async(service.set_parameter, thread_sensitive=False)(
                str(content.get("key", "")), content.get("value")
            )
        else:
            if project_id is None or not await sync_to_async(
                ProjectCache.objects.filter(id=project_id).exists
            )():
                await self.send_json({"type": "error", "message": "No active Ableton project"})
                return
            result = await self._handle_x32_project_command(
                service, project_id, cmd, content
            )

        await self.send_json({"type": "x32_ack", "command": cmd, "data": result})

    async def _handle_x32_project_command(self, service, project_id, cmd, content):
        if cmd == "x32_initialize_baseline":
            result = await sync_to_async(service.initialize_baseline, thread_sensitive=False)(project_id)
        elif cmd == "x32_save_snapshot":
            result = await sync_to_async(service.save_snapshot, thread_sensitive=False)(
                project_id,
                str(content.get("name", "")),
                str(content.get("keyword", "")),
            )
        elif cmd == "x32_save_operation":
            result = await sync_to_async(service.save_operation, thread_sensitive=False)(
                project_id,
                str(content.get("name", "")),
                str(content.get("apply_keyword", "")),
                str(content.get("rollback_keyword", "")),
                list(content.get("selected_keys") or []),
            )
        elif cmd in {"x32_apply_operation", "x32_rollback_operation"}:
            result = await sync_to_async(service.execute_operation_id, thread_sensitive=False)(
                project_id,
                int(content.get("id")),
                rollback=cmd == "x32_rollback_operation",
            )
        elif cmd == "x32_restore_snapshot":
            result = await sync_to_async(service.restore_snapshot_id, thread_sensitive=False)(
                project_id, int(content.get("id"))
            )
        elif cmd == "x32_delete":
            await sync_to_async(service.delete_item, thread_sensitive=False)(
                project_id, str(content.get("kind", "")), int(content.get("id"))
            )
            result = {"status": "deleted"}
        else:
            raise ValueError(f"Unknown command: {cmd}")
        return result

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
