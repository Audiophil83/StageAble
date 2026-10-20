from unittest.mock import patch

from django.test import TestCase

from engine.models import ProjectCache, X32CaptureState, X32Operation, X32Snapshot
from engine.project_cache import timeline_from_data, timeline_to_data
from engine.timeline import ArrangementClip, Timeline
from engine.x32.parameters import BY_KEY, PARAMETERS, db_to_fader, fader_to_db
from engine.x32.service import X32Error, X32Service


class FakeX32Client:
    def __init__(self):
        self.values = {parameter.address: 0.5 for parameter in PARAMETERS}
        self.sent = []

    def query_many(self, addresses, **kwargs):
        return {address: self.values[address] for address in addresses if address in self.values}

    def send(self, address, *args):
        self.sent.append((address, args))
        if args:
            self.values[address] = args[0]


class X32ParameterTests(TestCase):
    def test_supported_parameter_set_contains_all_first_release_controls(self):
        self.assertEqual(len(PARAMETERS), 32 * (7 + 16) + 16 + 8 * 19)
        for key in ("level", "solo", "mute", "pan", "gain"):
            self.assertIn(f"ch.1.{key}", BY_KEY)
        self.assertIn("ch.32.send.16", BY_KEY)

    def test_fader_db_conversion_round_trips(self):
        for db in (-80, -50, -30, -10, 0, 10):
            self.assertAlmostEqual(fader_to_db(db_to_fader(db)), db, places=5)


class X32TimelineTests(TestCase):
    def test_x32_events_are_crossed_by_start_and_survive_cache(self):
        timeline = Timeline.build(
            [ArrangementClip("Song", 0, 20)],
            x32_clips=[
                ArrangementClip("chorus-on", 4, 0.01),
                ArrangementClip("chorus-off", 8, 1),
            ],
        )
        self.assertEqual(
            [event.name for event in timeline.x32_events_crossed(3.9, 4.1)],
            ["chorus-on"],
        )
        self.assertEqual(
            [
                event.name
                for event in timeline.x32_events_crossed(
                    4, 4.1, include_start=True
                )
            ],
            ["chorus-on"],
        )
        self.assertEqual(timeline.x32_events_crossed(4, 4.1), [])
        self.assertEqual(timeline.x32_events_crossed(9, 2), [])

        restored = timeline_from_data(timeline_to_data(timeline))
        self.assertEqual(
            [event.name for event in restored.x32_events],
            ["chorus-on", "chorus-off"],
        )


class X32CaptureTests(TestCase):
    def setUp(self):
        self.project = ProjectCache.objects.create(identity="x32-test", name="Test")
        self.client = FakeX32Client()
        self.service = X32Service()
        self.service._enabled = True
        self.service._online = True
        self.service._client = self.client

    def test_selected_operation_advances_full_baseline_and_rolls_back_only_selection(self):
        self.service.initialize_baseline(self.project.id)
        level = BY_KEY["ch.1.level"]
        pan = BY_KEY["ch.1.pan"]
        self.client.values[level.address] = 0.75
        self.client.values[pan.address] = 0.8

        row = self.service.save_operation(
            self.project.id,
            "Chorus",
            "chorus-on",
            "chorus-off",
            [level.key],
        )
        operation = X32Operation.objects.get(id=row["id"])
        self.assertEqual([change["key"] for change in operation.changes], [level.key])

        baseline = X32CaptureState.objects.get(project=self.project).baseline
        self.assertEqual(baseline[level.key], 0.75)
        self.assertEqual(baseline[pan.key], 0.8)

        self.client.sent.clear()
        self.service.execute_operation(operation, rollback=True)
        self.assertEqual(self.client.sent, [(level.address, (0.5,))])

    def test_snapshot_requires_and_stores_complete_supported_state(self):
        row = self.service.save_snapshot(self.project.id, "Start", "song-start")
        snapshot = X32Snapshot.objects.get(id=row["id"])
        self.assertEqual(len(snapshot.values), len(PARAMETERS))
        self.assertEqual(snapshot.project, self.project)

    def test_incomplete_capture_is_rejected(self):
        self.client.values.pop(PARAMETERS[0].address)
        with self.assertRaisesRegex(X32Error, "Incomplete X32 capture"):
            self.service.capture_all()

    def test_keyword_is_unique_across_snapshot_and_operation_directions(self):
        self.service.save_snapshot(self.project.id, "Start", "used")
        self.service.initialize_baseline(self.project.id)
        parameter = PARAMETERS[0]
        self.client.values[parameter.address] = 0.6
        with self.assertRaisesRegex(X32Error, "already in use"):
            self.service.save_operation(
                self.project.id, "Duplicate", "used", "unused", [parameter.key]
            )

class X32ExtendedControlsTests(TestCase):
    setUp = X32CaptureTests.setUp

    def test_older_snapshot_restores_only_its_original_coverage(self):
        from types import SimpleNamespace
        snapshot = SimpleNamespace(values={'ch.1.level': 0.75}, coverage={'parameters': 1})
        self.service.restore_snapshot(snapshot)
        self.assertEqual(self.client.sent, [('/ch/01/mix/fader', (0.75,))])

    def test_links_restore_before_channel_values(self):
        self.service._execute_values({'ch.1.pan': 0.2, 'link.1': 1})
        self.assertEqual(self.client.sent[0], ('/config/chlink/01-02', (1,)))

    def test_names_sync_both_directions_and_clear(self):
        self.service.set_parameter('ch.1.name', 'Vocals')
        self.assertEqual(self.client.sent[-1], ('/ch/01/config/name', ('Vocals',)))
        self.assertEqual(self.service.mixer_state()['channels'][0]['name'], 'Vocals')
        self.service._on_update('/ch/01/config/name', 'Guitar')
        self.assertEqual(self.service._live['ch.1.name'], 'Guitar')
        self.assertEqual(self.service.mixer_state()['channels'][0]['name'], 'Guitar')
        self.service._on_update('/ch/01/config/name', '')
        self.assertEqual(self.service.mixer_state()['channels'][0]['name'], 'CH 01')

    def test_pair_link_and_polarity(self):
        self.service.set_parameter('link.1', True)
        self.assertEqual(self.client.sent[-1], ('/config/chlink/01-02', (1,)))
        self.assertTrue(all(ch['link'] for ch in self.service.mixer_state()['channels'][:2]))
        self.service.set_parameter('ch.2.polarity', True)
        self.assertEqual(self.client.sent[-1], ('/ch/02/preamp/invert', (1,)))

    def test_fx_values_and_mute_conversion(self):
        self.service.set_parameter('fxrtn.8.level', -10)
        self.service.set_parameter('fxrtn.8.mute', True)
        self.assertEqual(self.client.sent[-1], ('/fxrtn/08/mix/on', (0,)))
        item = self.service.mixer_state()['fx_returns'][7]
        self.assertEqual(item['level'], -10)
        self.assertTrue(item['mute'])

    def test_invalid_values_do_not_send(self):
        for key, value in [('ch.1.level', float('nan')), ('ch.1.pan', float('inf')),
                           ('ch.1.name', 'name too long!'), ('ch.1.name', 'bad\x00name'),
                           ('ch.1.polarity', 'false')]:
            with self.assertRaises(X32Error):
                self.service.set_parameter(key, value)
        self.assertFalse(self.client.sent)

    def test_phantom_resolves_current_headamp_not_channel_number(self):
        with patch.object(self.client, 'query', return_value=42, create=True):
            self.service.set_phantom(1, True)
        self.assertEqual(self.client.sent[-1], ('/headamp/042/phantom', (1,)))
        self.assertTrue(self.service.mixer_state()['channels'][0]['phantom'])
        with patch.object(self.client, 'query', return_value=-1, create=True):
            with self.assertRaises(X32Error):
                self.service.set_phantom(1, False)
        self.assertEqual(len(self.client.sent), 1)


class X32DesktopTests(TestCase):
    def test_remote_browser_cannot_launch_editor(self):
        from engine.x32.desktop import open_editor
        with patch('engine.x32.desktop.subprocess.Popen') as launch:
            with self.assertRaises(ValueError):
                open_editor('192.168.1.50')
        launch.assert_not_called()

    def test_local_browser_launches_fixed_command(self):
        from engine.x32.desktop import open_editor
        with patch('engine.x32.desktop.editor_command', return_value=['open', '/Applications/X32-Edit.app']), patch('engine.x32.desktop.subprocess.Popen') as launch:
            self.assertTrue(open_editor('::1')['opened'])
        launch.assert_called_once_with(['open', '/Applications/X32-Edit.app'], shell=False)
