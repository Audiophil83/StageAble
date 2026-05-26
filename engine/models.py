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
    ableton_osc_send_port = models.PositiveIntegerField(
        default=11000,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )
    ableton_osc_recv_port = models.PositiveIntegerField(
        default=11001,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )
    engine_poll_hz = models.PositiveIntegerField(
        default=20,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
    )
    default_preroll_bars = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(0), MaxValueValidator(16)],
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
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.order}. {self.song_name}"
