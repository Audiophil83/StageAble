import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0011_appsettings_sliding_animation_enabled"),
    ]

    operations = [
        migrations.AddField(
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
    ]
