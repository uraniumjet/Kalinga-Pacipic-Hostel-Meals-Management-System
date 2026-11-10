from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="timezone",
            field=models.CharField(default="UTC", max_length=64),
        ),
    ]
