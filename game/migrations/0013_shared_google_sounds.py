from django.db import migrations


def promote_google_to_shared(apps, schema_editor):
    """Google grapheme sounds become shared (classroom=None). Keep the first
    row per grapheme, delete per-class duplicates. Customs are untouched.
    Old per-class google rows are removed entirely so the improved letter
    sounds (lengthened S and other continuants) regenerate on next play."""
    GraphemeSound = apps.get_model("game", "GraphemeSound")
    # Remove all per-class google rows; shared rows will be created on demand
    # (or by makevoices) with the corrected pronunciations.
    GraphemeSound.objects.filter(source="google", classroom__isnull=False).delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0012_alter_graphemesound_classroom"),
    ]

    operations = [
        migrations.RunPython(promote_google_to_shared, noop),
    ]
