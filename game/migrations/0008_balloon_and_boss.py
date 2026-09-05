from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0007_alter_kid_options"),
    ]

    operations = [
        # ── Balloon challenge settings on Class ───────────────────────────
        migrations.AddField(
            model_name="class",
            name="balloon_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="class",
            name="balloon_frequency",
            field=models.PositiveSmallIntegerField(
                default=3,
                help_text="Show a balloon round every N normal rounds (0 = never).",
            ),
        ),
        # ── Boss fight settings on Class ──────────────────────────────────
        migrations.AddField(
            model_name="class",
            name="boss_enabled",
            field=models.BooleanField(default=True),
        ),
        # ── BossFight model ───────────────────────────────────────────────
        migrations.CreateModel(
            name="BossFight",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "kid",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="boss_fights",
                        to="game.kid",
                    ),
                ),
                # A hash of the active word-list at the time this fight was unlocked,
                # so we can detect when the teacher has changed the list.
                ("word_list_version", models.CharField(max_length=64)),
                # Max HP equals the number of active words when the fight was created.
                ("boss_max_hp", models.PositiveSmallIntegerField(default=1)),
                ("boss_hp", models.PositiveSmallIntegerField(default=1)),
                ("completed", models.BooleanField(default=False)),
                ("reward_claimed", models.BooleanField(default=False)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-created"]},
        ),
        migrations.AddConstraint(
            model_name="bossfight",
            constraint=models.UniqueConstraint(
                fields=["kid", "word_list_version"],
                name="unique_boss_per_kid_version",
            ),
        ),
    ]
