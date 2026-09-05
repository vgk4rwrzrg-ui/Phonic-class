# Finalize: classroom FKs non-null, composite uniques, drop Config.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [("game", "0005_backfill_class")]

    operations = [
        # classroom FKs → non-null
        migrations.AlterField(
            model_name="kid", name="classroom",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="kids", to="game.class"),
        ),
        migrations.AlterField(
            model_name="word", name="classroom",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="words", to="game.class"),
        ),
        migrations.AlterField(
            model_name="graphemesound", name="classroom",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="grapheme_sounds", to="game.class"),
        ),
        migrations.AlterField(
            model_name="wordsound", name="classroom",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="word_sounds", to="game.class"),
        ),
        # drop single-column unique (replaced by composite unique_together)
        migrations.AlterField(model_name="kid", name="name", field=models.CharField(max_length=30)),
        migrations.AlterField(model_name="word", name="text", field=models.CharField(max_length=20)),
        migrations.AlterField(model_name="graphemesound", name="grapheme", field=models.CharField(max_length=8)),
        migrations.AlterField(model_name="wordsound", name="word", field=models.CharField(max_length=20)),
        # composite uniques
        migrations.AlterUniqueTogether(name="kid", unique_together={("classroom", "name")}),
        migrations.AlterUniqueTogether(name="word", unique_together={("classroom", "text")}),
        migrations.AlterUniqueTogether(name="graphemesound", unique_together={("classroom", "grapheme")}),
        migrations.AlterUniqueTogether(name="wordsound", unique_together={("classroom", "word")}),
        # class goal now lives on Class.class_goal
        migrations.DeleteModel(name="Config"),
    ]