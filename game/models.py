import hashlib
import secrets
import string
from datetime import date, timedelta

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


class ClassManager(models.Manager):
    def by_code(self, code):
        """Look a class up by join code (case-insensitive), or None."""
        return self.filter(code=(code or "").upper()).first()

    def by_code_or_first(self, code):
        """Management-command convenience: --class CODE, else oldest class."""
        if code:
            return self.by_code(code)
        return self.order_by("id").first()


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

    objects = ClassManager()

    class Meta:
        verbose_name_plural = "classes"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def active_words(self):
        """Queryset of the currently active words for this class."""
        return self.words.filter(active=True)

    def active_word_texts(self):
        """Flat list of active word texts (uppercased in the DB)."""
        return list(self.active_words().values_list("text", flat=True))

    def active_word_list_version(self):
        """Stable hash of the current active word list, used to detect teacher edits."""
        words = sorted(self.active_words().values_list("text", flat=True))
        raw = ",".join(words)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


class Kid(models.Model):
    """A student.

    NOTE: PINs are deliberately stored as human-readable plain text so
    teachers can look them up for young children — do NOT hash them.
    """

    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="kids")
    name = models.CharField(max_length=30)
    icon = models.CharField(max_length=8, default="\U0001f98a")
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

    # ---- scoring ----------------------------------------------------------

    @property
    def spendable(self):
        """Points available for the egg shop (earned minus spent)."""
        return max(0, self.points_total - self.points_spent)

    def bump_streak(self, today=None):
        """Update the daily streak for a play event (idempotent per day)."""
        today = today or date.today()
        if self.last_played == today:
            return
        self.streak = (self.streak + 1
                       if self.last_played == today - timedelta(days=1) else 1)
        self.last_played = today

    def award_points(self, pts, save=True):
        """Add points to weekly/total tallies and bump the daily streak."""
        self.points_total += pts
        self.points_week += pts
        self.bump_streak()
        if save:
            self.save()

    def score_payload(self):
        """Standard JSON fragment returned by every scoring endpoint."""
        return {"points_week": self.points_week,
                "points_total": self.points_total,
                "streak": self.streak}


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


class SoundMissManager(models.Manager):
    def record(self, kid, sound):
        """Increment (creating if needed) the miss counter for one sound."""
        miss, _ = self.get_or_create(kid=kid, sound=sound)
        miss.count += 1
        miss.save()
        return miss

    def trouble_sounds(self, classroom, limit=12):
        """Most-missed sounds across a class, for the teacher dashboard."""
        return (self.filter(kid__classroom=classroom)
                .values("sound")
                .annotate(total=models.Sum("count"))
                .order_by("-total")[:limit])


class SoundMiss(models.Model):
    kid = models.ForeignKey(Kid, on_delete=models.CASCADE, related_name="misses")
    sound = models.CharField(max_length=12)
    count = models.PositiveIntegerField(default=0)

    objects = SoundMissManager()

    class Meta:
        unique_together = [("kid", "sound")]


class GraphemeSoundManager(models.Manager):
    def playable(self, classroom, grapheme):
        """The sound a class should hear for a grapheme.

        A teacher recording for this class wins; otherwise the shared Google
        sound (classroom=None) so every classroom hears the same voice.
        """
        obj = self.filter(classroom=classroom, grapheme=grapheme,
                          source="custom").first()
        return obj or self.filter(classroom__isnull=True,
                                  grapheme=grapheme).first()

    def shared_graphemes(self):
        """Set of grapheme texts that have a shared Google sound."""
        return set(self.filter(classroom__isnull=True)
                   .values_list("grapheme", flat=True))


class GraphemeSound(models.Model):
    """A letter/grapheme sound. classroom=None means a shared Google TTS sound
    used by every classroom; teacher recordings are always per-classroom."""

    SOURCES = [("google", "Google TTS"), ("custom", "Teacher upload"),
               ("bundled", "Bundled recording")]
    classroom = models.ForeignKey(Class, on_delete=models.CASCADE,
                                  related_name="grapheme_sounds",
                                  null=True, blank=True)
    grapheme = models.CharField(max_length=8)
    audio = models.FileField(upload_to="sounds/")
    source = models.CharField(max_length=10, choices=SOURCES, default="google")

    objects = GraphemeSoundManager()

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

    def summary(self):
        """JSON fragment shared by the eligibility and status endpoints."""
        return {
            "fight_id": self.pk,
            "boss_hp": self.boss_hp,
            "boss_max_hp": self.boss_max_hp,
            "completed": self.completed,
            "reward_claimed": self.reward_claimed,
            "words_spelled": list(self.spelled_set()),
        }


class Pet(models.Model):
    """A collectible pet bought with points.

    Created as an un-hatched egg with 42 random traits; hatching calls the
    DeepAI image API with a kid-safe grounded prompt and stores a 512x512
    image under MEDIA_ROOT/pets/.  Each pet has a fixed creature voice
    (Google TTS language/voice/pitch/rate) and five short gibberish phrases.
    """

    # In-flight hatch statuses, in pipeline order.
    HATCHING_STATUSES = ("cracking", "halfway", "hatching")

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
    hatch_status = models.CharField(
        max_length=20,
        default='unhatched',
        choices=[
            ('unhatched', 'Unhatched'),
            ('cracking', 'Cracking'),
            ('halfway', 'Halfway'),
            ('hatching', 'Hatching'),
            ('complete', 'Complete'),
            ('failed', 'Failed'),
        ]
    )
    hatch_task_id = models.CharField(max_length=100, blank=True, default='')
    hatch_updated = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        state = "hatched" if self.hatched else "egg"
        return f"{self.name} ({state}) - {self.kid.name}"

    def set_hatch_status(self, status, **extra_fields):
        """Persist a hatch pipeline status (plus any extra field updates)."""
        self.hatch_status = status
        for name, value in extra_fields.items():
            setattr(self, name, value)
        self.save(update_fields=["hatch_status", *extra_fields])

    def hatch_age_seconds(self):
        """Seconds since the hatch status last advanced (None if unknown)."""
        from django.utils import timezone
        if not self.hatch_updated:
            return None
        return (timezone.now() - self.hatch_updated).total_seconds()
