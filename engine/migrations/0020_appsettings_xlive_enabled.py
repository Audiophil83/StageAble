from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("engine", "0019_x32_integration")]
    operations = [migrations.AddField(model_name="appsettings", name="xlive_enabled", field=models.BooleanField(default=False))]
