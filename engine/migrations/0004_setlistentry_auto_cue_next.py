# Add optional auto-cue-next flag for setlist transitions

from django.db import migrations, models


def enable_auto_cue_for_existing_gaps(apps, schema_editor):
    SetlistEntry = apps.get_model("engine", "SetlistEntry")
    SetlistEntry.objects.filter(gap_seconds__gt=0).update(auto_cue_next=True)


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0003_setlistentry_gap_seconds"),
    ]

    operations = [
        migrations.AddField(
            model_name="setlistentry",
            name="auto_cue_next",
            field=models.BooleanField(
                default=False,
                help_text="After this song's STOP, wait then cue the next song automatically.",
            ),
        ),
        migrations.RunPython(
            enable_auto_cue_for_existing_gaps,
            migrations.RunPython.noop,
        ),
    ]
