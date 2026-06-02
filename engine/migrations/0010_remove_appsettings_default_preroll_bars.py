from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0009_remove_appsettings_scan_meter_map"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="appsettings",
            name="default_preroll_bars",
        ),
    ]
