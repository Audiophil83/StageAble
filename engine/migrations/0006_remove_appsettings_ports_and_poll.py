from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0005_alter_setlistentry_gap_seconds"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="appsettings",
            name="ableton_osc_send_port",
        ),
        migrations.RemoveField(
            model_name="appsettings",
            name="ableton_osc_recv_port",
        ),
        migrations.RemoveField(
            model_name="appsettings",
            name="engine_poll_hz",
        ),
    ]
