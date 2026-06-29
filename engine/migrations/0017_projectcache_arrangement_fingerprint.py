from django.db import migrations, models


def backfill_arrangement_fingerprints(apps, schema_editor):
    ProjectCache = apps.get_model("engine", "ProjectCache")
    from engine.project_cache import compute_arrangement_fingerprint

    for project in ProjectCache.objects.all().iterator():
        if not project.timeline_data:
            continue
        fp = compute_arrangement_fingerprint(project.timeline_data)
        if fp and fp != project.arrangement_fingerprint:
            project.arrangement_fingerprint = fp
            project.save(update_fields=["arrangement_fingerprint"])


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0016_multi_project_support"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectcache",
            name="arrangement_fingerprint",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Hash of song/section names and start beats for rename/move detection.",
                max_length=64,
            ),
        ),
        migrations.RunPython(
            backfill_arrangement_fingerprints,
            migrations.RunPython.noop,
        ),
    ]
