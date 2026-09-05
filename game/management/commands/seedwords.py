from django.core.management.base import BaseCommand

from game.models import Word

STARTERS = {
    1: ["CAT", "DOG", "SUN", "HAT", "PIG", "RED", "BUS", "MAP", "TEN", "BOX", "MUD", "LEG"],
    2: ["FROG", "STOP", "CLAP", "DRUM", "SWIM", "PLAN", "GRAB", "TWIN"],
    3: ["SHIP", "CHAT", "THIN", "FISH", "MATH", "RING", "DUCK", "BATH"],
}


class Command(BaseCommand):
    help = "Load a starter word list"

    def handle(self, *args, **opts):
        new = 0
        for level, words in STARTERS.items():
            for w in words:
                _, created = Word.objects.update_or_create(
                    text=w, defaults={"level": level, "active": True})
                new += created
        self.stdout.write(self.style.SUCCESS(f"Seeded words ({new} new)."))
