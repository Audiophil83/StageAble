from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0010_remove_appsettings_default_preroll_bars"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="sliding_animation_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Beat-aligned section/chord/lyrics slide on web clients.",
            ),
        ),
    ]
