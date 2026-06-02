from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0007_appsettings_scan_meter_map"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectCache",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "scanned_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When the arrangement was last scanned from Ableton.",
                        null=True,
                    ),
                ),
                ("tempo", models.FloatField(default=120.0)),
                ("is_valid", models.BooleanField(default=False)),
                ("timeline_errors", models.JSONField(blank=True, default=list)),
                (
                    "timeline_data",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Songs, sections, lyrics, chords, stops, and meter map.",
                    ),
                ),
                ("cue_points", models.JSONField(blank=True, default=list)),
                ("mixer_tracks", models.JSONField(blank=True, default=list)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Project cache",
                "verbose_name_plural": "Project cache",
            },
        ),
    ]
