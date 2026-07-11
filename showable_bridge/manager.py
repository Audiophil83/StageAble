from ableton.v2.control_surface import ControlSurface
import Live

from . import bridge
from .config import FAST_POLLING, FAST_POLL_INTERVAL_MS

import importlib
import traceback
import logging
import os
import time

logger = logging.getLogger("showable-bridge")


class Manager(ControlSurface):
    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)

        self.log_level = "info"

        self.handlers = []
        self.midi_mappings = {}
        self.recv_loop = None
        self._last_tick = time.time() * 1000

        try:
            self.osc_server = bridge.OSCServer()
            self.schedule_message(0, self.tick)

            if FAST_POLLING:
                self.recv_loop = Live.Base.Timer(
                    callback=self.osc_server.process,
                    interval=FAST_POLL_INTERVAL_MS,
                    repeat=True,
                )
                self.recv_loop.start()

            self.start_logging()
            self.init_api()

            self.show_message("ShowAble Bridge: Listening for OSC on port %d" % bridge.OSC_LISTEN_PORT)
            logger.info("Started ShowAble Bridge on address %s" % str(self.osc_server._local_addr))
        except OSError as msg:
            self.show_message("ShowAble Bridge: Couldn't bind to port %d (%s)" % (bridge.OSC_LISTEN_PORT, msg))
            logger.info("Couldn't bind to port %d (%s)" % (bridge.OSC_LISTEN_PORT, msg))

    def start_logging(self):
        """
        Start logging to a local logfile (logs/showable-bridge.log),
        and relay error messages via OSC.
        """
        module_path = os.path.dirname(os.path.realpath(__file__))
        log_dir = os.path.join(module_path, "logs")
        if not os.path.exists(log_dir):
            os.mkdir(log_dir, 0o755)
        log_path = os.path.join(log_dir, "showable-bridge.log")
        self.log_file_handler = logging.FileHandler(log_path)
        self.log_file_handler.setLevel(self.log_level.upper())
        formatter = logging.Formatter('(%(asctime)s) [%(levelname)s] %(message)s')
        self.log_file_handler.setFormatter(formatter)
        logger.addHandler(self.log_file_handler)

        class LiveOSCErrorLogHandler(logging.StreamHandler):
            def emit(handler, record):
                message = record.getMessage()
                message = message[message.index(":") + 2:]
                try:
                    self.osc_server.send("/live/error", (message,))
                except OSError:
                    # If the connection is dead, silently ignore errors as there's
                    # not much more we can do.
                    pass
        self.live_osc_error_handler = LiveOSCErrorLogHandler()
        self.live_osc_error_handler.setLevel(logging.ERROR)
        logger.addHandler(self.live_osc_error_handler)

    def stop_logging(self):
        logger.removeHandler(self.log_file_handler)
        logger.removeHandler(self.live_osc_error_handler)

    def init_api(self):
        def test_callback(params):
            self.show_message("Received OSC OK")
            self.osc_server.send("/live/test", ("ok",))
        def reload_callback(params):
            self.reload_imports()
        def get_log_level_callback(params):
            return (self.log_level,)
        def set_log_level_callback(params):
            log_level = params[0]
            assert log_level in ("debug", "info", "warning", "error", "critical")
            self.log_level = log_level
            self.log_file_handler.setLevel(self.log_level.upper())
        def show_message_callback(params):
            self.show_message(params[0])

        self.osc_server.add_handler("/live/test", test_callback)
        self.osc_server.add_handler("/live/api/reload", reload_callback)
        self.osc_server.add_handler("/live/api/get/log_level", get_log_level_callback)
        self.osc_server.add_handler("/live/api/set/log_level", set_log_level_callback)
        self.osc_server.add_handler("/live/api/show_message", show_message_callback)

        #--------------------------------------------------------------------------------
        # ShowAble only drives Song and Track. The other AbletonOSC handlers
        # (clip, clip_slot, device, scene, view, application, midimap) are omitted
        # to keep the OSC surface minimal.
        #--------------------------------------------------------------------------------
        with self.component_guard():
            self.handlers = [
                bridge.SongHandler(self),
                bridge.TrackHandler(self),
            ]

    def clear_api(self):
        self.osc_server.clear_handlers()
        for handler in self.handlers:
            handler.clear_api()

    def tick(self):
        """
        Called once per 100ms "tick".
        Live's embedded Python implementation does not appear to support threading,
        and beachballs when a thread is started. Instead, this approach allows
        long-running processes such as the OSC server to perform operations.

        When FAST_POLLING is enabled, osc_server.process() runs on a 10ms
        Live.Base.Timer; this tick monitors lag and keeps housekeeping.
        """
        tick_time = time.time() * 1000

        if tick_time - self._last_tick > 200:
            logger.warning(
                "UDP tick is lagging, delta: %dms",
                round(tick_time - self._last_tick),
            )

        self._last_tick = tick_time
        self.osc_server.process()

        process_time = time.time() * 1000
        if process_time - tick_time > 100:
            logger.warning(
                "UDP processing is taking long, delta: %dms",
                round(process_time - tick_time),
            )

        logger.debug("Tick...")
        self.schedule_message(1, self.tick)

    def reload_imports(self):
        try:
            from . import config
            importlib.reload(config)
            importlib.reload(bridge.handler)
            importlib.reload(bridge.osc_server)
            importlib.reload(bridge.song)
            importlib.reload(bridge.track)
            importlib.reload(bridge)
        except Exception:
            exc = traceback.format_exc()
            logging.warning(exc)

        self.clear_api()
        self.init_api()
        logger.info("Reloaded code")

    def disconnect(self):
        self.show_message("Disconnecting...")
        logger.info("Disconnecting...")
        if self.recv_loop is not None:
            self.recv_loop.stop()
            self.recv_loop = None
        self.stop_logging()
        self.osc_server.shutdown()
        super().disconnect()

    def build_midi_map(self, midi_map_handle):
        """
        Called by Live to build the MIDI map. ShowAble registers no MIDI
        mappings, so this is a no-op beyond satisfying the Live interface.
        """
        logger.debug("Building MIDI map...")

        for channel, cc in self.midi_mappings.keys():
            parameter = self.midi_mappings[(channel, cc)]
            Live.MidiMap.map_midi_cc(midi_map_handle, parameter, channel, cc, Live.MidiMap.MapMode.absolute, 1)
            logger.debug("Mapped CC %d on channel %d to parameter %s" % (cc, channel, parameter.name))
