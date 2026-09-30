from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("engine", "0017_projectcache_arrangement_fingerprint")]

    operations = [
        migrations.CreateModel(
            name="ControlDevice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("adapter", models.CharField(max_length=40)),
                ("identifier", models.CharField(max_length=500)),
                ("name", models.CharField(max_length=300)),
                ("enabled", models.BooleanField(default=True)),
                ("config", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["adapter", "name"]},
        ),
        migrations.CreateModel(
            name="ControlMapping",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("trigger", models.JSONField(default=dict)),
                ("trigger_key", models.CharField(max_length=500)),
                ("action", models.CharField(max_length=80)),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mappings", to="engine.controldevice")),
            ],
            options={"ordering": ["device_id", "action", "id"]},
        ),
        migrations.AddConstraint(
            model_name="controldevice",
            constraint=models.UniqueConstraint(fields=("adapter", "identifier"), name="unique_control_device"),
        ),
        migrations.AddConstraint(
            model_name="controlmapping",
            constraint=models.UniqueConstraint(fields=("device", "trigger_key"), name="unique_control_trigger"),
        ),
    ]
