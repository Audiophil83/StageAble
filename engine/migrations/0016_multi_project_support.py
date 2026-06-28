from django.db import migrations, models
import django.db.models.deletion


LEGACY_IDENTITY = "legacy:imported"


def migrate_singleton_to_multi_project(apps, schema_editor):
    ProjectCache = apps.get_model("engine", "ProjectCache")
    Setlist = apps.get_model("engine", "Setlist")
    MixerPreset = apps.get_model("engine", "MixerPreset")
    AppSettings = apps.get_model("engine", "AppSettings")

    legacy = ProjectCache.objects.filter(pk=1).first()
    if legacy is None:
        legacy = ProjectCache.objects.first()

    if legacy is None:
        legacy = ProjectCache.objects.create(
            identity=LEGACY_IDENTITY,
            name="Imported cache",
            file_path="",
        )
    else:
        legacy.identity = LEGACY_IDENTITY
        legacy.name = legacy.name or "Imported cache"
        legacy.file_path = legacy.file_path or ""
        legacy.save(update_fields=["identity", "name", "file_path"])

    Setlist.objects.filter(project__isnull=True).update(project=legacy)
    MixerPreset.objects.filter(project__isnull=True).update(project=legacy)

    settings, _ = AppSettings.objects.get_or_create(pk=1)
    if settings.last_active_project_id is None:
        settings.last_active_project = legacy
        settings.save(update_fields=["last_active_project"])


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0015_alter_setlistentry_auto_cue_next_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectcache",
            name="file_path",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Full path to the .als file (song.file_path); empty if unsaved.",
                max_length=1024,
            ),
        ),
        migrations.AddField(
            model_name="projectcache",
            name="identity",
            field=models.CharField(
                db_index=True,
                help_text="Stable lookup key derived from file_path or name.",
                max_length=1100,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="projectcache",
            name="name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Live set filename from Ableton (song.name).",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name="setlist",
            name="project",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="setlists",
                to="engine.projectcache",
            ),
        ),
        migrations.AddField(
            model_name="mixerpreset",
            name="project",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="mixer_presets",
                to="engine.projectcache",
            ),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="last_active_project",
            field=models.ForeignKey(
                blank=True,
                help_text="Last Ableton project loaded by the engine (offline fallback).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="engine.projectcache",
            ),
        ),
        migrations.RunPython(
            migrate_singleton_to_multi_project,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="projectcache",
            name="identity",
            field=models.CharField(
                db_index=True,
                help_text="Stable lookup key derived from file_path or name.",
                max_length=1100,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="setlist",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="setlists",
                to="engine.projectcache",
            ),
        ),
        migrations.AlterField(
            model_name="mixerpreset",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="mixer_presets",
                to="engine.projectcache",
            ),
        ),
        migrations.AlterModelOptions(
            name="projectcache",
            options={
                "ordering": ["-updated_at"],
                "verbose_name": "Project cache",
                "verbose_name_plural": "Project cache",
            },
        ),
        migrations.AlterField(
            model_name="setlist",
            name="is_active",
            field=models.BooleanField(
                default=False,
                help_text="Only one setlist should be active per project.",
            ),
        ),
    ]
