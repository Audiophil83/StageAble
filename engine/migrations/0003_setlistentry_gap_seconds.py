# Generated manually for setlist transition gaps

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0002_appsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="setlistentry",
            name="gap_seconds",
            field=models.FloatField(
                default=0.0,
                help_text="Seconds to wait after this song's STOP before cueing the next song.",
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
    ]
