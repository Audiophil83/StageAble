from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("engine", "0018_controldevice_controlmapping")]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="x32_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="x32_host",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.CreateModel(
            name="X32CaptureState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("baseline", models.JSONField(blank=True, default=dict)),
                ("coverage", models.JSONField(blank=True, default=dict)),
                ("captured_at", models.DateTimeField(auto_now=True)),
                ("project", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="x32_capture_state", to="engine.projectcache")),
            ],
        ),
        migrations.CreateModel(
            name="X32Snapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("keyword", models.CharField(blank=True, default="", max_length=200)),
                ("values", models.JSONField(default=dict)),
                ("coverage", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="x32_snapshots", to="engine.projectcache")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="X32Operation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("apply_keyword", models.CharField(blank=True, default="", max_length=200)),
                ("rollback_keyword", models.CharField(blank=True, default="", max_length=200)),
                ("changes", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="x32_operations", to="engine.projectcache")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="x32snapshot",
            constraint=models.UniqueConstraint(fields=("project", "name"), name="unique_x32_snapshot_name"),
        ),
        migrations.AddConstraint(
            model_name="x32operation",
            constraint=models.UniqueConstraint(fields=("project", "name"), name="unique_x32_operation_name"),
        ),
    ]
