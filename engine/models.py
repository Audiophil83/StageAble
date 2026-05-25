"""
Django models for persistent setlist management.

The canonical data source is always Ableton's arrangement — these models
provide a way to save/load named setlists that reference songs by name.
"""

from django.db import models


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
