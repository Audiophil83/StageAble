"""
Django models for persistent setlist management and app configuration.

The canonical data source is always Ableton's arrangement — these models
provide a way to save/load named setlists that reference songs by name.
"""

import os

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class AppSettings(models.Model):
    """Singleton row storing engine configuration."""

    ableton_osc_host = models.CharField(max_length=255, default="127.0.0.1")
    sliding_animation_enabled = models.BooleanField(
        default=False,
        help_text="Beat-aligned section/chord/lyrics slide on web clients.",
    )
    sliding_animation_duration_ms = models.PositiveIntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(2000)],
        help_text="Milliseconds for slide-in; animation ends at each event beat.",
    )
    last_active_project = models.ForeignKey(
        "ProjectCache",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Last Ableton project loaded by the engine (offline fallback).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "App settings"
        verbose_name_plural = "App settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    def __str__(self):
        return "App settings"


class ProjectCache(models.Model):
    """Cached arrangement scan for one Ableton Live set."""

    name = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Live set filename from Ableton (song.name).",
    )
    file_path = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Full path to the .als file (song.file_path); empty if unsaved.",
    )
    identity = models.CharField(
        max_length=1100,
        unique=True,
        db_index=True,
        help_text="Stable lookup key derived from file_path or name.",
    )
    scanned_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the arrangement was last scanned from Ableton.",
    )
    tempo = models.FloatField(default=120.0)
    is_valid = models.BooleanField(default=False)
    timeline_errors = models.JSONField(default=list, blank=True)
    timeline_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Songs, sections, lyrics, chords, stops, and meter map.",
    )
    cue_points = models.JSONField(default=list, blank=True)
    mixer_tracks = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Project cache"
        verbose_name_plural = "Project cache"
        ordering = ["-updated_at"]

    def __str__(self):
        label = self.display_name
        if self.scanned_at:
            return f"{label} (scanned {self.scanned_at:%Y-%m-%d %H:%M})"
        return label

    @property
    def display_name(self) -> str:
        raw = ""
        if self.file_path:
            raw = os.path.basename(self.file_path)
        elif self.name:
            raw = self.name
        if raw:
            if raw.lower().endswith(".als"):
                return raw[:-4]
            return raw
        return "Untitled"


class Setlist(models.Model):
    """A named setlist — an ordered subset of songs."""

    project = models.ForeignKey(
        ProjectCache,
        on_delete=models.CASCADE,
        related_name="setlists",
    )
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(
        default=False,
        help_text="Only one setlist should be active per project.",
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_active and self.project_id:
            Setlist.objects.filter(
                is_active=True, project_id=self.project_id
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)


class MixerPreset(models.Model):
    """Saved mute states for [MIX] tracks in Ableton."""

    project = models.ForeignKey(
        ProjectCache,
        on_delete=models.CASCADE,
        related_name="mixer_presets",
    )
    name = models.CharField(max_length=200)
    tracks = models.JSONField(
        default=list,
        blank=True,
        help_text="List of {index, name, muted} for each [MIX] track.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name


class SetlistEntry(models.Model):
    """A single entry in a setlist, referencing a song by name."""

    setlist = models.ForeignKey(
        Setlist, on_delete=models.CASCADE, related_name="entries"
    )
    song_name = models.CharField(max_length=300)
    order = models.PositiveIntegerField(default=0)
    auto_cue_next = models.BooleanField(
        default=False,
        help_text="After this song's STOP, auto-play the next song after the gap (next song is always cued).",
    )
    gap_seconds = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0)],
        help_text="Seconds to wait after STOP before auto-playing the next song (when auto_cue_next is enabled).",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.order}. {self.song_name}"
