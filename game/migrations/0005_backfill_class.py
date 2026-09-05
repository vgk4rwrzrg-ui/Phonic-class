# Backfill existing kids/words/sounds into a default class owned by the first teacher.
from django.conf import settings
from django.db import migrations

_CODE_ALPHABET = "".join(c for c in "ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def _pick_code(Class):
    import random
    code = "ABC123"
    n = 0
    while Class.objects.filter(code=code).exists():
        n += 1
        code = "".join(random.choice(_CODE_ALPHABET) for _ in range(6))
    return code


def forward(apps, schema_editor):
    Class = apps.get_model("game", "Class")
    Kid = apps.get_model("game", "Kid")
    Word = apps.get_model("game", "Word")
    GraphemeSound = apps.get_model("game", "GraphemeSound")
    WordSound = apps.get_model("game", "WordSound")
    Config = apps.get_model("game", "Config")
    User = apps.get_model(settings.AUTH_USER_MODEL)

    teacher = User.objects.filter(is_superuser=True).order_by("id").first()
    if teacher is None:
        teacher = User.objects.order_by("id").first()
    if teacher is None:
        # No users yet (fresh install) — nothing to backfill. The first signup
        # will create the initial class, so there's no orphan data to rescue.
        return

    cfg = Config.objects.filter(pk=1).first()
    goal = cfg.class_goal if cfg else 500
    cls = Class.objects.create(
        teacher_id=teacher.id,
        name="My Class",
        code=_pick_code(Class),
        class_goal=goal,
    )
    Kid.objects.filter(classroom__isnull=True).update(classroom_id=cls.id)
    Word.objects.filter(classroom__isnull=True).update(classroom_id=cls.id)
    GraphemeSound.objects.filter(classroom__isnull=True).update(classroom_id=cls.id)
    WordSound.objects.filter(classroom__isnull=True).update(classroom_id=cls.id)


def backward(apps, schema_editor):
    pass  # data migration is not reversible without loss


class Migration(migrations.Migration):

    dependencies = [("game", "0004_class_and_scoping")]

    operations = [
        migrations.RunPython(forward, backward),
    ]