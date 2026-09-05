# Add Class model + nullable classroom FKs (data backfilled in 0005).
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import game.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("game", "0003_wordsound"),
    ]

    operations = [
        migrations.CreateModel(
            name="Class",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60)),
                ("code", models.CharField(default=game.models._new_class_code, max_length=12, unique=True)),
                ("class_goal", models.PositiveIntegerField(default=500)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("teacher", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="classes", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name_plural": "classes", "ordering": ["name"]},
        ),
        migrations.AddField(
            model_name="kid", name="classroom",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="kids", to="game.class"),
        ),
        migrations.AddField(
            model_name="word", name="classroom",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="words", to="game.class"),
        ),
        migrations.AddField(
            model_name="graphemesound", name="classroom",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="grapheme_sounds", to="game.class"),
        ),
        migrations.AddField(
            model_name="wordsound", name="classroom",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="word_sounds", to="game.class"),
        ),
    ]