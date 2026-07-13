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
