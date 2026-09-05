import secrets
import string

from django.contrib.auth.models import User
from django.db import models


_CODE_ALPHABET = "".join(
    c for c in (string.ascii_uppercase + string.digits) if c not in "O0I1L"
)


def _new_class_code():
    """Generate a short, unique, URL-safe join code for a class."""
    while True:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not Class.objects.filter(code=code).exists():
            return code


class Class(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name="classes")
    name = models.CharField(max_length=60)
    code = models.CharField(max_length=12, unique=True, default=_new_class_code)
    class_goal = models.PositiveIntegerField(default=500)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "classes"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Kid(models.Model):
    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="kids")
    name = models.CharField(max_length=30)
    icon = models.CharField(max_length=8, default="🦊")
    pin = models.CharField(max_length=4, help_text="4-digit PIN")
    points_total = models.PositiveIntegerField(default=0)
    points_week = models.PositiveIntegerField(default=0)
    streak = models.PositiveIntegerField(default=0)
    last_played = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = [("classroom", "name")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.icon} {self.name}"


class Word(models.Model):
    LEVELS = [(1, "1 - CVC"), (2, "2 - Blends"), (3, "3 - Digraphs+")]
    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="words")
    text = models.CharField(max_length=20)
    level = models.PositiveSmallIntegerField(default=1, choices=LEVELS)
    active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("classroom", "text")]
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


class GraphemeSound(models.Model):
    SOURCES = [("google", "Google TTS"), ("custom", "Teacher upload")]
    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="grapheme_sounds")
    grapheme = models.CharField(max_length=8)
    audio = models.FileField(upload_to="sounds/")
    source = models.CharField(max_length=10, choices=SOURCES, default="google")

    class Meta:
        unique_together = [("classroom", "grapheme")]

    def __str__(self):
        return f"{self.grapheme} ({self.source})"


class WordSound(models.Model):
    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="word_sounds")
    word = models.CharField(max_length=20)
    audio = models.FileField(upload_to="word_sounds/")

    class Meta:
        unique_together = [("classroom", "word")]

    def __str__(self):
        return self.word
