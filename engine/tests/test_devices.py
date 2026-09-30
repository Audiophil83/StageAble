from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory

from engine.devices.base import InputAdapter, InputEvent, trigger_key
from engine.devices.manager import DeviceManager
from engine.devices.midi import normalize_midi
from engine.devices.macos_hid import normalize_hid_report
from engine.models import ControlDevice, ControlMapping
from engine.runtime import RuntimeEngine
from engine.views import IsLoopback


class MidiNormalizationTests(SimpleTestCase):
    def test_note_on_and_note_off(self):
        on = SimpleNamespace(type="note_on", channel=1, note=60, velocity=100)
        off = SimpleNamespace(type="note_on", channel=1, note=60, velocity=0)
        self.assertEqual(normalize_midi(on), ({"type": "note", "channel": 1, "note": 60}, True, 100))
        self.assertEqual(normalize_midi(off), ({"type": "note", "channel": 1, "note": 60}, False, 0))

    def test_cc_threshold_and_program(self):
        low = SimpleNamespace(type="control_change", channel=0, control=7, value=63)
        high = SimpleNamespace(type="control_change", channel=0, control=7, value=64)
        program = SimpleNamespace(type="program_change", channel=2, program=12)
        self.assertFalse(normalize_midi(low)[1])
        self.assertTrue(normalize_midi(high)[1])
        self.assertEqual(normalize_midi(program)[0], {"type": "program", "channel": 2, "program": 12})


class HidNormalizationTests(SimpleTestCase):
    def test_keyboard_report_emits_press_and_release(self):
        events, active = normalize_hid_report([1, 40, 0, 0], set())
        self.assertEqual(events, [(7, 40, True)])
        events, active = normalize_hid_report([1, 0, 0, 0], active)
        self.assertEqual(events, [(7, 40, False)])

    def test_consumer_report_uses_usage_value(self):
        events, active = normalize_hid_report([2, 0xE9, 0, 0, 0], set())
        self.assertEqual(events, [(12, 0xE9, True)])

    def test_vendor_reports_are_ignored(self):
        events, active = normalize_hid_report([0xF0, 1, 2, 3], set())
        self.assertEqual(events, [])


class FakeAdapter(InputAdapter):
    kind = "fake"


class DeviceManagerTests(TestCase):
    def setUp(self):
        self.engine = Mock()
        self.adapter = FakeAdapter(lambda event: None)
        self.manager = DeviceManager(self.engine, [self.adapter])
        self.adapter.callback = self.manager.handle_input
        self.device = ControlDevice.objects.create(adapter="fake", identifier="one", name="One")

    def tearDown(self):
        self.manager.stop()

    def test_learn_persists_mapping(self):
        self.manager.start_learn(self.device.id, "transport.stop")
        trigger = {"type": "note", "channel": 0, "note": 42}
        self.manager.handle_input(InputEvent("fake", "one", trigger, True, 100))
        mapping = ControlMapping.objects.get()
        self.assertEqual(mapping.action, "transport.stop")
        self.assertEqual(mapping.trigger_key, trigger_key(trigger))

    def test_press_fires_once_until_release(self):
        trigger = {"type": "note", "channel": 0, "note": 1}
        ControlMapping.objects.create(device=self.device, trigger=trigger, trigger_key=trigger_key(trigger), action="transport.stop")
        event = InputEvent("fake", "one", trigger, True, 100)
        self.manager.handle_input(event)
        self.manager.handle_input(event)
        self.assertEqual(self.engine.cmd_stop.call_count, 1)
        self.manager.handle_input(InputEvent("fake", "one", trigger, False, 0))
        self.manager._last_fired.clear()
        self.manager.handle_input(event)
        self.assertEqual(self.engine.cmd_stop.call_count, 2)

    def test_disabled_device_does_not_dispatch(self):
        self.device.enabled = False
        self.device.save()
        trigger = {"type": "hid", "usage_page": 7, "usage": 49}
        ControlMapping.objects.create(device=self.device, trigger=trigger, trigger_key=trigger_key(trigger), action="song.next")
        self.manager.handle_input(InputEvent("fake", "one", trigger, True, 1))
        self.engine.cmd_next_song.assert_not_called()


class NavigationTests(SimpleTestCase):
    def make_engine(self, *, current, length, active_setlist=False):
        engine = RuntimeEngine.__new__(RuntimeEngine)
        engine._lock = threading.RLock()
        entries = [{} for _ in range(length)]
        engine.state = SimpleNamespace(
            active_setlist={"entries": entries} if active_setlist else None,
            active_setlist_index=current if active_setlist else None,
            active_song_index=None if active_setlist else current,
            timeline=SimpleNamespace(all_songs=lambda: entries),
        )
        engine.cmd_jump_to_setlist_index = Mock()
        engine.cmd_jump_to_song = Mock()
        return engine

    def test_next_and_previous_use_arrangement(self):
        engine = self.make_engine(current=1, length=3)
        engine.cmd_previous_song()
        engine.cmd_next_song()
        engine.cmd_jump_to_song.assert_any_call(0)
        engine.cmd_jump_to_song.assert_any_call(2)

    def test_setlist_boundaries_and_no_current_are_noop(self):
        first = self.make_engine(current=0, length=2, active_setlist=True)
        first.cmd_previous_song()
        first.cmd_jump_to_setlist_index.assert_not_called()
        none = self.make_engine(current=None, length=2, active_setlist=True)
        none.cmd_next_song()
        none.cmd_jump_to_setlist_index.assert_not_called()


class LoopbackPermissionTests(SimpleTestCase):
    def test_allows_ipv4_and_ipv6_loopback(self):
        factory = APIRequestFactory()
        permission = IsLoopback()
        self.assertTrue(permission.has_permission(factory.get("/", REMOTE_ADDR="127.0.0.1"), None))
        self.assertTrue(permission.has_permission(factory.get("/", REMOTE_ADDR="::1"), None))

    def test_rejects_lan_address_and_forwarded_spoof(self):
        request = APIRequestFactory().get("/", REMOTE_ADDR="192.168.1.20", HTTP_X_FORWARDED_FOR="127.0.0.1")
        self.assertFalse(IsLoopback().has_permission(request, None))
