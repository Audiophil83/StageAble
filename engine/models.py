"""
Django models for persistent setlist management and app configuration.

The canonical data source is always Ableton's arrangement — these models
provide a way to save/load named setlists that reference songs by name.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class AppSettings(models.Model):
    """Singleton row storing engine configuration."""

    ableton_osc_host = models.CharField(max_length=255, default="127.0.0.1")
    default_preroll_bars = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(0), MaxValueValidator(16)],
    )
    scan_meter_map = models.BooleanField(
        default=False,
        help_text=(
            "Pre-scan time signature and tempo at every song/section boundary. "
            "Slow on large sets; rescan after changing."
        ),
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
    """Singleton snapshot of the last Ableton arrangement scan."""

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

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    def __str__(self):
        if self.scanned_at:
            return f"Project cache (scanned {self.scanned_at:%Y-%m-%d %H:%M})"
        return "Project cache (empty)"


class Setlist(models.Model):
    """A named setlist — an ordered subset of songs."""

    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(
        default=False,
        help_text="Only one setlist should be active at a time.",
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Enforce single active setlist
        if self.is_active:
            Setlist.objects.filter(is_active=True).exclude(pk=self.pk).update(
                is_active=False
            )
        super().save(*args, **kwargs)


class SetlistEntry(models.Model):
    """A single entry in a setlist, referencing a song by name."""

    setlist = models.ForeignKey(
        Setlist, on_delete=models.CASCADE, related_name="entries"
    )
    song_name = models.CharField(max_length=300)
    order = models.PositiveIntegerField(default=0)
    auto_cue_next = models.BooleanField(
        default=False,
        help_text="After this song's STOP, wait then cue the next song automatically.",
    )
    gap_seconds = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0)],
        help_text="Seconds to wait after STOP before cueing the next song (when auto_cue_next is enabled).",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.order}. {self.song_name}"
