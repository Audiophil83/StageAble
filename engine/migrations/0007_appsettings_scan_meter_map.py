from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0006_remove_appsettings_ports_and_poll"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="scan_meter_map",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Pre-scan time signature and tempo at every song/section boundary. "
                    "Slow on large sets; rescan after changing."
                ),
            ),
        ),
    ]
