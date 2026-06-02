from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0008_projectcache"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="appsettings",
            name="scan_meter_map",
        ),
    ]
