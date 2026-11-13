from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from engine.models import AppSettings, MixerPreset, ProjectCache, Setlist
from engine.project_cache import timeline_to_data
from engine.state import engine_state
from engine.tests.test_project_relocation import _sample_timeline
from engine.timeline import Timeline


def _sample_timeline_data() -> dict:
    return timeline_to_data(_sample_timeline())


class ProjectApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        engine_state.update(active_project=None)

    def _create_project(self, identity: str, *, name: str = "") -> ProjectCache:
        data = _sample_timeline_data()
        return ProjectCache.objects.create(
            identity=identity,
            name=name or identity.rsplit("/", 1)[-1],
            file_path=identity if identity.startswith("/") else "",
            arrangement_fingerprint="fp-" + identity,
            timeline_data=data,
        )

    def test_list_projects_includes_counts_and_active_flag(self):
        active = self._create_project("/sets/Active.als")
        other = self._create_project("/sets/Other.als")
        Setlist.objects.create(project=active, name="Tonight")
        MixerPreset.objects.create(project=active, name="Verse", tracks=[])
        engine_state.update(
            active_project={
                "id": active.id,
                "name": active.name,
                "file_path": active.file_path,
                "identity": active.identity,
                "display_name": active.display_name,
            }
        )

        response = self.client.get(reverse("project-list"))

        self.assertEqual(response.status_code, 200)
        by_id = {row["id"]: row for row in response.data}
        self.assertIn(active.id, by_id)
        self.assertIn(other.id, by_id)
        self.assertTrue(by_id[active.id]["is_active"])
        self.assertFalse(by_id[other.id]["is_active"])
        self.assertEqual(by_id[active.id]["setlist_count"], 1)
        self.assertEqual(by_id[active.id]["mixer_preset_count"], 1)

    def test_delete_project_cascades_related_data(self):
        project = self._create_project("/sets/Show.als")
        Setlist.objects.create(project=project, name="Tonight")
        MixerPreset.objects.create(project=project, name="Verse", tracks=[])

        response = self.client.delete(
            reverse("project-detail", kwargs={"pk": project.id})
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(ProjectCache.objects.filter(pk=project.id).exists())
        self.assertEqual(Setlist.objects.count(), 0)
        self.assertEqual(MixerPreset.objects.count(), 0)

    def test_delete_active_project_clears_engine_state_and_last_active(self):
        project = self._create_project("/sets/Show.als")
        settings, _ = AppSettings.objects.get_or_create(pk=1)
        settings.last_active_project = project
        settings.save(update_fields=["last_active_project"])
        engine_state.update(
            active_project={
                "id": project.id,
                "name": project.name,
                "file_path": project.file_path,
                "identity": project.identity,
                "display_name": project.display_name,
            },
            timeline=_sample_timeline(),
            active_setlist={"id": 1, "name": "Tonight", "entries": []},
        )

        response = self.client.delete(
            reverse("project-detail", kwargs={"pk": project.id})
        )

        self.assertEqual(response.status_code, 204)
        settings.refresh_from_db()
        self.assertIsNone(settings.last_active_project_id)
        self.assertIsNone(engine_state.active_project)
        self.assertIsNone(engine_state.timeline)
        self.assertIsNone(engine_state.active_setlist)

    def test_delete_project_suppresses_auto_recreate_from_open_live_set(self):
        """Deleting while Ableton still has the set open must not recreate it."""
        from engine.runtime import get_engine

        project = self._create_project("/sets/Show.als")
        engine = get_engine()
        engine._current_project_identity = project.identity
        engine._suppressed_project_identities.clear()
        engine_state.update(
            active_project={
                "id": project.id,
                "name": project.name,
                "file_path": project.file_path,
                "identity": project.identity,
                "display_name": project.display_name,
            },
            timeline=_sample_timeline(),
        )

        response = self.client.delete(
            reverse("project-detail", kwargs={"pk": project.id})
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(ProjectCache.objects.filter(identity=project.identity).exists())
        self.assertTrue(engine._is_project_suppressed(project.identity))
        self.assertIsNone(engine._current_project_identity)

        # Simulate the slow-poll project check while the same Live set is open.
        engine.osc.get_project_identity = lambda: (
            project.identity,
            project.name,
            project.file_path,
        )
        loaded = engine._apply_project_from_osc(broadcast=False)

        self.assertFalse(loaded)
        self.assertFalse(ProjectCache.objects.filter(identity=project.identity).exists())
        self.assertIsNone(engine_state.active_project)

    def test_rescan_clears_delete_suppression(self):
        from engine.runtime import get_engine

        project = self._create_project("/sets/Show.als")
        identity = project.identity
        engine = get_engine()
        engine.forget_stored_project(identity)
        self.assertTrue(engine._is_project_suppressed(identity))

        engine._clear_project_suppression(identity)
        self.assertFalse(engine._is_project_suppressed(identity))

    def test_rename_updates_identity_and_preserves_setlists(self):
        project = self._create_project("/old/Show.als")
        setlist = Setlist.objects.create(project=project, name="Tonight")

        response = self.client.post(
            reverse("project-rename", kwargs={"pk": project.id}),
            {"file_path": "/new/Show.als"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        setlist.refresh_from_db()
        self.assertEqual(project.identity, "/new/Show.als")
        self.assertEqual(project.file_path, "/new/Show.als")
        self.assertEqual(setlist.project_id, project.id)
        self.assertEqual(response.data["display_name"], "Show")

    def test_rename_rejects_duplicate_identity(self):
        self._create_project("/sets/Show.als")
        other = self._create_project("/sets/Other.als")

        response = self.client.post(
            reverse("project-rename", kwargs={"pk": other.id}),
            {"file_path": "/sets/Show.als"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("file_path", response.data)

    def test_rename_updates_active_project_in_engine_state(self):
        project = self._create_project("/old/Show.als")
        engine_state.update(
            active_project={
                "id": project.id,
                "name": project.name,
                "file_path": project.file_path,
                "identity": project.identity,
                "display_name": project.display_name,
            }
        )

        response = self.client.post(
            reverse("project-rename", kwargs={"pk": project.id}),
            {"file_path": "/new/Show.als"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(engine_state.active_project["file_path"], "/new/Show.als")
        self.assertEqual(engine_state.active_project["identity"], "/new/Show.als")


class ProjectRecoveryApiTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        from engine.project_cache import project_to_state_dict
        self.client = APIClient()
        self.path = '/sets/Show.als'
        self.saved = ProjectCache.objects.create(
            identity='unsaved:unknown', name='Show', file_path=self.path,
            scanned_at=timezone.now(), timeline_data=_sample_timeline_data(),
        )
        self.duplicate = ProjectCache.objects.create(identity=self.path, file_path=self.path)
        self.setlist = Setlist.objects.create(project=self.saved, name='Tonight', is_active=True)
        self.preset = MixerPreset.objects.create(project=self.saved, name='Live', tracks=[])
        settings, _ = AppSettings.objects.get_or_create(pk=1)
        settings.last_active_project = self.duplicate
        settings.save()
        engine_state.update(active_project=project_to_state_dict(self.duplicate), timeline=None)

    def tearDown(self):
        engine_state.update(active_project=None, timeline=None, active_setlist=None)

    def recover(self, **data):
        return self.client.post(reverse('project-recover', kwargs={'pk': self.saved.pk}),
            data or {'active_project_id': self.duplicate.pk}, format='json')

    def test_recovery_keeps_original_ids_and_restores_runtime_without_transport(self):
        from unittest.mock import patch
        from engine.runtime import get_engine
        engine = get_engine()
        with patch.object(engine.osc, 'send') as send:
            response = self.recover()
        self.assertEqual(response.status_code, 200, response.data)
        send.assert_not_called()
        self.saved.refresh_from_db()
        self.setlist.refresh_from_db()
        self.preset.refresh_from_db()
        self.assertEqual(self.saved.identity, self.path)
        self.assertEqual(self.setlist.project_id, self.saved.pk)
        self.assertEqual(self.preset.project_id, self.saved.pk)
        self.assertFalse(ProjectCache.objects.filter(pk=self.duplicate.pk).exists())
        self.assertEqual(AppSettings.objects.get(pk=1).last_active_project_id, self.saved.pk)
        self.assertEqual(engine_state.active_project['id'], self.saved.pk)
        self.assertIsNotNone(engine_state.timeline)
        self.assertEqual(engine_state.active_setlist['id'], self.setlist.pk)
        self.assertEqual(engine._current_project_identity, self.path)
        self.assertEqual(self.client.get(reverse('mixer-preset-list')).data[0]['id'], self.preset.pk)

    def test_recovery_rejects_duplicate_with_user_data_and_leaves_everything_intact(self):
        Setlist.objects.create(project=self.duplicate, name='Do not delete')
        response = self.recover()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ProjectCache.objects.exclude(identity="legacy:imported").count(), 2)
        self.saved.refresh_from_db()
        self.assertEqual(self.saved.identity, 'unsaved:unknown')
        self.assertEqual(Setlist.objects.count(), 2)

    def test_recovery_rejects_duplicate_with_scan_or_x32_data(self):
        from engine.models import X32CaptureState
        capture = X32CaptureState.objects.create(project=self.duplicate)
        self.assertEqual(self.recover().status_code, 400)
        capture.delete()
        self.duplicate.timeline_data = _sample_timeline_data()
        self.duplicate.save()
        self.assertEqual(self.recover().status_code, 400)
        self.assertEqual(ProjectCache.objects.exclude(identity="legacy:imported").count(), 2)

    def test_recovery_rejects_changed_active_project_different_paths_and_invalid_ids(self):
        self.assertEqual(self.recover(active_project_id='invalid').status_code, 400)
        self.duplicate.file_path = '/sets/Other.als'
        self.duplicate.save()
        self.assertEqual(self.recover().status_code, 400)
        engine_state.update(active_project=None)
        self.assertEqual(self.recover().status_code, 400)
        self.assertEqual(ProjectCache.objects.exclude(identity="legacy:imported").count(), 2)
