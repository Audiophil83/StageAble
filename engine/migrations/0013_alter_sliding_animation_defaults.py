import django.core.validators
from django.db import migrations, models


def apply_sliding_defaults(apps, schema_editor):
    AppSettings = apps.get_model("engine", "AppSettings")
    AppSettings.objects.filter(pk=1).update(
        sliding_animation_enabled=False,
        sliding_animation_duration_ms=100,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0012_appsettings_sliding_animation_duration_ms"),
    ]

    operations = [
        migrations.AlterField(
            model_name="appsettings",
            name="sliding_animation_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Beat-aligned section/chord/lyrics slide on web clients.",
            ),
        ),
        migrations.AlterField(
            model_name="appsettings",
            name="sliding_animation_duration_ms",
            field=models.PositiveIntegerField(
                default=100,
                help_text="Milliseconds for slide-in; animation ends at each event beat.",
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(2000),
                ],
            ),
        ),
        migrations.RunPython(apply_sliding_defaults, migrations.RunPython.noop),
    ]
