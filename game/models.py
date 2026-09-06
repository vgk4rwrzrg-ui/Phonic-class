import hashlib
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

    # Balloon challenge settings
    balloon_enabled = models.BooleanField(default=True)
    balloon_frequency = models.PositiveSmallIntegerField(
        default=3,
        help_text="Show a balloon round every N normal rounds (0 = never).",
    )

    # Boss fight settings
    boss_enabled = models.BooleanField(default=True)

    # Pet egg shop settings
    pets_enabled = models.BooleanField(default=True)
    egg_cost = models.PositiveIntegerField(
        default=50, help_text="Points needed to buy one pet egg."
    )

    class Meta:
        verbose_name_plural = "classes"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def active_word_list_version(self):
        """Stable hash of the current active word list, used to detect teacher edits."""
        words = sorted(
            self.words.filter(active=True).values_list("text", flat=True)
        )
        raw = ",".join(words)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


class Kid(models.Model):
    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="kids")
    name = models.CharField(max_length=30)
    icon = models.CharField(max_length=8, default="🦊")
    pin = models.CharField(max_length=4, help_text="4-digit PIN")
    points_total = models.PositiveIntegerField(default=0)
    points_week = models.PositiveIntegerField(default=0)
    streak = models.PositiveIntegerField(default=0)
    points_spent = models.PositiveIntegerField(default=0)
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
    """A letter/grapheme sound. classroom=None means a shared Google TTS sound
    used by every classroom; teacher recordings are always per-classroom."""

    SOURCES = [("google", "Google TTS"), ("custom", "Teacher upload")]
    classroom = models.ForeignKey(Class, on_delete=models.CASCADE,
                                  related_name="grapheme_sounds",
                                  null=True, blank=True)
    grapheme = models.CharField(max_length=8)
    audio = models.FileField(upload_to="sounds/")
    source = models.CharField(max_length=10, choices=SOURCES, default="google")

    class Meta:
        unique_together = [("classroom", "grapheme")]

    def __str__(self):
        return f"{self.grapheme} ({self.source})"


class WordSound(models.Model):
    SOURCES = [("custom", "custom"), ("google", "google")]

    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="word_sounds")
    word = models.CharField(max_length=20)
    audio = models.FileField(upload_to="word_sounds/")
    source = models.CharField(max_length=10, choices=SOURCES, default="custom")

    class Meta:
        unique_together = [("classroom", "word")]

    def __str__(self):
        return self.word


class BossFight(models.Model):
    """
    Tracks one boss-fight instance per kid per active word-list version.

    word_list_version is the sha256[:32] of the sorted active word texts at the
    time the fight was created (or checked for eligibility).  If the teacher
    changes the active list the hash changes, a NEW BossFight row is created,
    and the old one is left intact so history is preserved.
    """

    kid = models.ForeignKey(Kid, on_delete=models.CASCADE, related_name="boss_fights")
    word_list_version = models.CharField(max_length=64)
    boss_max_hp = models.PositiveSmallIntegerField(default=1)
    boss_hp = models.PositiveSmallIntegerField(default=1)
    # words_spelled tracks which active words the kid has beaten in this fight
    # stored as a comma-separated list so we don't need a M2M just for this
    words_spelled = models.TextField(default="", blank=True)
    completed = models.BooleanField(default=False)
    reward_claimed = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]
        constraints = [
            models.UniqueConstraint(
                fields=["kid", "word_list_version"],
                name="unique_boss_per_kid_version",
            )
        ]

    def __str__(self):
        return f"Boss({self.kid} v{self.word_list_version[:8]} hp={self.boss_hp}/{self.boss_max_hp})"

    def spelled_set(self):
        """Return a set of already-spelled word texts for this fight."""
        if not self.words_spelled:
            return set()
        return set(w for w in self.words_spelled.split(",") if w)

    def add_spelled(self, word_text):
        """Record a correctly spelled word; return True if it was new."""
        s = self.spelled_set()
        upper = word_text.strip().upper()
        if upper in s:
            return False
        s.add(upper)
        self.words_spelled = ",".join(sorted(s))
        return True


class Pet(models.Model):
    """A collectible pet bought with points.

    Created as an un-hatched egg with 42 random traits; hatching calls the
    DeepAI image API with a kid-safe grounded prompt and stores a 512x512
    image under MEDIA_ROOT/pets/.  Each pet has a fixed creature voice
    (Google TTS language/voice/pitch/rate) and five short gibberish phrases.
    """

    kid = models.ForeignKey(Kid, on_delete=models.CASCADE, related_name="pets")
    name = models.CharField(max_length=30)
    traits_json = models.TextField()          # dict of the 42 traits
    prompt = models.TextField()               # exact prompt sent to DeepAI
    phrases_json = models.TextField()         # list of 5 creature phrases
    voice_json = models.TextField()           # language/voice/pitch/rate
    hatched = models.BooleanField(default=False)
    image_path = models.CharField(max_length=200, blank=True, default="")
    is_companion = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        state = "hatched" if self.hatched else "egg"
        return f"{self.name} ({state}) - {self.kid.name}"
