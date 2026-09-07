from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0017_alter_graphemesound_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="class",
            name="hd_cost",
            field=models.PositiveIntegerField(
                default=1000,
                help_text="Points needed to buy one HD pet egg (larger image + human sayings).",
            ),
        ),
        migrations.AddField(
            model_name="pet",
            name="tier",
            field=models.CharField(
                max_length=10,
                default="basic",
                choices=[("basic", "Basic"), ("hd", "HD")],
            ),
        ),
        migrations.AddField(
            model_name="pet",
            name="human_sayings_json",
            field=models.TextField(default="[]"),
        ),
    ]
