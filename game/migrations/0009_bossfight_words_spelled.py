from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0008_balloon_and_boss"),
    ]

    operations = [
        migrations.AddField(
            model_name="bossfight",
            name="words_spelled",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Comma-separated list of correctly spelled word texts for this fight.",
            ),
        ),
    ]
