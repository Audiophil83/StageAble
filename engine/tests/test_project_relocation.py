from django.test import TestCase

from engine.models import ProjectCache, Setlist
from engine.project_cache import (
    compute_arrangement_fingerprint,
    compute_cue_fingerprint,
    find_relocation_candidate,
    fingerprint_from_timeline,
    relocate_project_record,
    resolve_or_relocate_project_record,
    timeline_to_data,
)
from engine.timeline import EventType, Timeline, TimelineEvent


def _sample_timeline() -> Timeline:
    tl = Timeline()
    tl.songs.add(TimelineEvent(start_beat=0.0, type=EventType.SONG, name="Intro"))
    tl.songs.add(TimelineEvent(start_beat=32.0, type=EventType.SONG, name="Verse"))
    tl.sections.add(
        TimelineEvent(start_beat=0.0, type=EventType.SECTION, name="A")
    )
    return tl


def _sample_timeline_data() -> dict:
    return timeline_to_data(_sample_timeline())


class ArrangementFingerprintTests(TestCase):
    def test_fingerprint_is_stable_for_identical_data(self):
        data = _sample_timeline_data()
        fp1 = compute_arrangement_fingerprint(data)
        fp2 = compute_arrangement_fingerprint(data)
        self.assertEqual(fp1, fp2)
        self.assertEqual(len(fp1), 32)

    def test_fingerprint_changes_when_arrangement_changes(self):
        data = _sample_timeline_data()
        other = dict(data)
        other["songs"] = list(data["songs"]) + [
            {"type": "SONG", "name": "Chorus", "start_beat": 64.0, "end_beat": None}
        ]
        self.assertNotEqual(
            compute_arrangement_fingerprint(data),
            compute_arrangement_fingerprint(other),
        )

    def test_fingerprint_from_timeline_matches_data(self):
        tl = _sample_timeline()
        self.assertEqual(
            fingerprint_from_timeline(tl),
            compute_arrangement_fingerprint(timeline_to_data(tl)),
        )


class RelocateProjectRecordTests(TestCase):
    def test_relocate_updates_identity_and_preserves_setlists(self):
        fp = compute_arrangement_fingerprint(_sample_timeline_data())
        project = ProjectCache.objects.create(
            identity="/old/path/Show.als",
            name="Show.als",
            file_path="/old/path/Show.als",
            arrangement_fingerprint=fp,
            timeline_data=_sample_timeline_data(),
        )
        setlist = Setlist.objects.create(project=project, name="Tonight")

        relocated = relocate_project_record(
            project,
            identity="/new/path/Show.als",
            name="Show.als",
            file_path="/new/path/Show.als",
        )

        self.assertEqual(relocated.identity, "/new/path/Show.als")
        self.assertEqual(relocated.file_path, "/new/path/Show.als")
        setlist.refresh_from_db()
        self.assertEqual(setlist.project_id, project.id)
        self.assertFalse(
            ProjectCache.objects.filter(identity="/old/path/Show.als").exists()
        )


class FindRelocationCandidateTests(TestCase):
    def _create_project(
        self,
        identity: str,
        *,
        timeline_data: dict | None = None,
        cue_points: list[dict] | None = None,
    ) -> ProjectCache:
        data = timeline_data or _sample_timeline_data()
        return ProjectCache.objects.create(
            identity=identity,
            name=identity.rsplit("/", 1)[-1],
            file_path=identity if identity.startswith("/") else "",
            arrangement_fingerprint=compute_arrangement_fingerprint(data),
            timeline_data=data,
            cue_points=cue_points or [],
        )

    def test_in_session_move_matches_previous_project(self):
        old = self._create_project("/sets/Show.als")
        tl = _sample_timeline()
        candidate = find_relocation_candidate(
            new_identity="/archive/Show.als",
            new_name="Show.als",
            new_file_path="/archive/Show.als",
            previous_identity=old.identity,
            in_memory_timeline=tl,
        )
        self.assertEqual(candidate, old)

    def test_in_session_rename_matches_via_cue_points(self):
        cues = [{"name": "Intro", "time": 0.0}, {"name": "Verse", "time": 16.0}]
        old = self._create_project(
            "/sets/Show.als",
            cue_points=cues,
        )
        cue_set = frozenset((cp["name"], round(cp["time"], 4)) for cp in cues)
        candidate = find_relocation_candidate(
            new_identity="/sets/Renamed.als",
            new_name="Renamed.als",
            new_file_path="/sets/Renamed.als",
            previous_identity=old.identity,
            cue_points=cue_set,
        )
        self.assertEqual(candidate, old)

    def test_no_relocate_when_new_identity_already_exists(self):
        self._create_project("/sets/Show.als")
        other = self._create_project("/sets/Other.als")
        candidate = find_relocation_candidate(
            new_identity="/sets/Other.als",
            new_name="Other.als",
            new_file_path="/sets/Other.als",
            previous_identity="/sets/Show.als",
            in_memory_timeline=_sample_timeline(),
        )
        self.assertIsNone(candidate)
        self.assertEqual(other.identity, "/sets/Other.als")

    def test_no_relocate_when_fingerprint_is_ambiguous(self):
        data = _sample_timeline_data()
        fp = compute_arrangement_fingerprint(data)
        self._create_project("/sets/CopyA.als", timeline_data=data)
        self._create_project("/sets/CopyB.als", timeline_data=data)
        self.assertEqual(
            ProjectCache.objects.filter(arrangement_fingerprint=fp).count(),
            2,
        )
        candidate = find_relocation_candidate(
            new_identity="/sets/CopyC.als",
            new_name="CopyC.als",
            new_file_path="/sets/CopyC.als",
            previous_identity=None,
            in_memory_timeline=_sample_timeline(),
        )
        self.assertIsNone(candidate)

    def test_save_as_from_unsaved_matches(self):
        data = _sample_timeline_data()
        old = ProjectCache.objects.create(
            identity="unsaved:MySet",
            name="MySet",
            file_path="",
            arrangement_fingerprint=compute_arrangement_fingerprint(data),
            timeline_data=data,
        )
        candidate = find_relocation_candidate(
            new_identity="/music/MySet.als",
            new_name="MySet.als",
            new_file_path="/music/MySet.als",
            previous_identity=old.identity,
            in_memory_timeline=_sample_timeline(),
        )
        self.assertEqual(candidate, old)

    def test_unique_fingerprint_match_for_later_reopen(self):
        old = self._create_project("/old/Show.als")
        candidate = find_relocation_candidate(
            new_identity="/new/Show.als",
            new_name="Show.als",
            new_file_path="/new/Show.als",
            previous_identity=None,
            in_memory_timeline=_sample_timeline(),
        )
        self.assertEqual(candidate, old)


class ResolveOrRelocateTests(TestCase):
    def test_resolve_relocates_instead_of_creating_duplicate(self):
        data = _sample_timeline_data()
        old = ProjectCache.objects.create(
            identity="/old/Show.als",
            name="Show.als",
            file_path="/old/Show.als",
            arrangement_fingerprint=compute_arrangement_fingerprint(data),
            timeline_data=data,
        )
        project, relocated = resolve_or_relocate_project_record(
            identity="/new/Show.als",
            name="Show.als",
            file_path="/new/Show.als",
            previous_identity=old.identity,
            in_memory_timeline=_sample_timeline(),
        )
        self.assertTrue(relocated)
        self.assertEqual(project.id, old.id)
        self.assertFalse(ProjectCache.objects.filter(identity="/old/Show.als").exists())
        self.assertEqual(
            ProjectCache.objects.filter(identity="/new/Show.als").count(), 1
        )

    def test_resolve_creates_new_when_no_match(self):
        project, relocated = resolve_or_relocate_project_record(
            identity="/brand/new.als",
            name="new.als",
            file_path="/brand/new.als",
            previous_identity="/old/other.als",
        )
        self.assertFalse(relocated)
        self.assertEqual(project.identity, "/brand/new.als")


class CueFingerprintTests(TestCase):
    def test_cue_fingerprint_is_stable(self):
        cues = [("Intro", 0.0), ("Verse", 16.5)]
        self.assertEqual(
            compute_cue_fingerprint(cues),
            compute_cue_fingerprint(list(reversed(cues))),
        )
