from django.db import models


class Kid(models.Model):
    name = models.CharField(max_length=30, unique=True)
    icon = models.CharField(max_length=8, default="🦊")
    pin = models.CharField(max_length=4, help_text="4-digit PIN")
    points_total = models.PositiveIntegerField(default=0)
    points_week = models.PositiveIntegerField(default=0)
    streak = models.PositiveIntegerField(default=0)
    last_played = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.icon} {self.name}"


class Word(models.Model):
    LEVELS = [(1, "1 - CVC"), (2, "2 - Blends"), (3, "3 - Digraphs+")]
    text = models.CharField(max_length=20, unique=True)
    level = models.PositiveSmallIntegerField(default=1, choices=LEVELS)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["level", "text"]

    def save(self, *args, **kwargs):
        self.text = self.text.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.text


class SoundMiss(models.Model):
    kid = models.ForeignKey(Kid, on_delete=models.CASCADE, related_name="misses")
    sound = models.CharField(max_length=12)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("kid", "sound")]


class Config(models.Model):
    class_goal = models.PositiveIntegerField(default=500)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"Class goal: {self.class_goal}"
