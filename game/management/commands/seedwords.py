from django.core.management.base import BaseCommand

from game.models import Class, Word

STARTERS = {
    1: ["CAT", "DOG", "SUN", "HAT", "PIG", "RED", "BUS", "MAP", "TEN", "BOX", "MUD", "LEG"],
    2: ["FROG", "STOP", "CLAP", "DRUM", "SWIM", "PLAN", "GRAB", "TWIN"],
    3: ["SHIP", "CHAT", "THIN", "FISH", "MATH", "RING", "DUCK", "BATH"],
}


class Command(BaseCommand):
    help = "Load a starter word list into a class"

    def add_arguments(self, parser):
        parser.add_argument("--class", dest="code", help="Class code (e.g. ABC123). Defaults to first class.")

    def handle(self, *args, **opts):
        if opts["code"]:
            classroom = Class.objects.filter(code=opts["code"].upper()).first()
        else:
            classroom = Class.objects.order_by("id").first()
        if not classroom:
            self.stderr.write("No class found. Sign up first or pass --class CODE.")
            return
        new = 0
        for level, words in STARTERS.items():
            for w in words:
                _, created = classroom.words.update_or_create(
                    text=w, defaults={"level": level, "active": True})
                new += created
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {new} words into {classroom.name} ({classroom.code})."))
