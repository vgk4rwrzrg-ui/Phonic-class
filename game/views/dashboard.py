"""Teacher dashboard page + its AJAX action endpoints.

Every POST carries an ``action`` field.  Actions are small handler functions
registered in two tables: CLASS_FREE_ACTIONS work before a class is selected,
CLASS_ACTIONS require the active classroom.
"""

from django.contrib.auth.decorators import login_required

from ..context import enter_classroom
from ..jsonapi import parse_int, teacher_fail, teacher_ok, upper_param
from ..models import Class, GraphemeSound, SoundMiss, WordSound
from .. import sound_services, tts


# ---------------------------------------------------------------------------
# Class management (usable even with no active class)
# ---------------------------------------------------------------------------

def _act_switch_class(request, user, classes):
    new_id = parse_int(request.POST.get("class_id"))
    if any(c.pk == new_id for c in classes):
        request.session["classroom_id"] = new_id
        return teacher_ok("Class switched")
    return teacher_fail("Invalid class")


def _act_add_class(request, user, classes):
    name = (request.POST.get("name") or "").strip()[:60]
    if not name:
        return teacher_fail("Name required")
    cls = Class.objects.create(teacher=user, name=name)
    enter_classroom(request, cls)
    return teacher_ok(f"Class '{name}' created", id=cls.pk, code=cls.code)


def _act_del_class(request, user, classes):
    cid = parse_int(request.POST.get("class_id"))
    if cid is None:
        return teacher_fail("Invalid class ID")
    cls = user.classes.filter(pk=cid).first()
    if not (cls and len(classes) > 1):  # never delete the last class
        return teacher_fail("Cannot delete last class")
    cls.delete()
    if request.session.get("classroom_id") == cls.pk:
        request.session.pop("classroom_id", None)
    return teacher_ok("Class deleted")


CLASS_FREE_ACTIONS = {
    "switch_class": _act_switch_class,
    "add_class": _act_add_class,
    "del_class": _act_del_class,
}


# ---------------------------------------------------------------------------
# Kid roster actions
# ---------------------------------------------------------------------------

def _valid_pin(pin):
    """PINs stay human-readable plain text by design: exactly 4 digits."""
    return pin.isdigit() and len(pin) == 4


def _act_add_kid(request, classroom):
    name = (request.POST.get("name") or "").strip()[:30]
    pin = (request.POST.get("pin") or "").strip()[:4]
    icon = (request.POST.get("icon") or "\U0001f98a").strip()[:8]
    if not (name and _valid_pin(pin)):
        return teacher_fail("Invalid name or PIN")
    kid, created = classroom.kids.get_or_create(
        name=name, defaults={"pin": pin, "icon": icon})
    if not created:
        return teacher_fail("Kid already exists")
    return teacher_ok(f"Added {name}", id=kid.pk, name=name, icon=icon, pin=pin)


def _act_del_kid(request, classroom):
    kid = classroom.kids.filter(pk=request.POST.get("kid_id")).first()
    if not kid:
        return teacher_fail("Kid not found")
    name = kid.name
    kid.delete()
    return teacher_ok(f"Deleted {name}")


def _act_set_pin(request, classroom):
    pin = (request.POST.get("pin") or "").strip()[:4]
    if not _valid_pin(pin):
        return teacher_fail("Invalid PIN")
    classroom.kids.filter(pk=request.POST.get("kid_id")).update(pin=pin)
    return teacher_ok("PIN updated")


# ---------------------------------------------------------------------------
# Word list actions
# ---------------------------------------------------------------------------

def _parse_word_line(line):
    """One pasted line -> (TEXT, level) or None.  Format: "word[, level]"."""
    line = line.strip()
    if not line:
        return None
    parts = [p.strip() for p in line.replace("\t", ",").split(",")]
    text = parts[0].upper()[:20]
    try:
        level = min(3, max(1, int(parts[1]))) if len(parts) > 1 else 1
    except ValueError:
        level = 1
    if not text.isalpha():
        return None
    return text, level


def _act_add_words(request, classroom):
    added = 0
    for line in (request.POST.get("words") or "").splitlines():
        parsed = _parse_word_line(line)
        if not parsed:
            continue
        text, level = parsed
        _, created = classroom.words.update_or_create(
            text=text, defaults={"level": level, "active": True})
        if created:
            added += 1
    return teacher_ok(f"Added {added} words")


def _act_toggle_word(request, classroom):
    w = classroom.words.filter(pk=request.POST.get("word_id")).first()
    if not w:
        return teacher_fail("Word not found")
    w.active = not w.active
    w.save()
    return teacher_ok(
        f"{w.text} {'activated' if w.active else 'deactivated'}", active=w.active)


def _act_del_word(request, classroom):
    word = classroom.words.filter(pk=request.POST.get("word_id")).first()
    if not word:
        return teacher_fail("Word not found")
    text = word.text
    word.delete()
    return teacher_ok(f"Deleted {text}")


def _act_deactivate_all(request, classroom):
    count = classroom.active_words().count()
    classroom.words.update(active=False)
    return teacher_ok(f"Deactivated {count} words")


# ---------------------------------------------------------------------------
# Stats / goal actions
# ---------------------------------------------------------------------------

def _act_reset_week(request, classroom):
    classroom.kids.update(points_week=0)
    return teacher_ok("Weekly points reset")


def _act_reset_all(request, classroom):
    classroom.kids.update(points_week=0, points_total=0, streak=0,
                          last_played=None)
    SoundMiss.objects.filter(kid__classroom=classroom).delete()
    return teacher_ok("All stats reset")


def _act_set_goal(request, classroom):
    goal = parse_int(request.POST.get("goal", ""))
    if goal is None:
        return teacher_fail("Invalid goal")
    goal = max(0, goal)
    classroom.class_goal = goal
    classroom.save()
    return teacher_ok(f"Goal set to {goal}")


# ---------------------------------------------------------------------------
# Sound actions
# ---------------------------------------------------------------------------

def _act_upload_sound(request, classroom):
    g = upper_param(request.POST.get("grapheme"), 8)
    f = request.FILES.get("audio")
    if not (g and f):
        return teacher_fail("Invalid upload")
    sound_services.save_custom_grapheme(classroom, g, f.read(), f.name)
    return teacher_ok(f"Uploaded {g}")


def _act_del_sound(request, classroom):
    grapheme = (request.POST.get("grapheme") or "").strip().upper()
    GraphemeSound.objects.filter(classroom=classroom, grapheme=grapheme).delete()
    return teacher_ok(f"Deleted {grapheme}")


def _act_del_word_sound(request, classroom):
    word = (request.POST.get("word") or "").strip().upper()
    WordSound.objects.filter(classroom=classroom, word=word).delete()
    return teacher_ok(f"Deleted {word} sound")


CLASS_ACTIONS = {
    "add_kid": _act_add_kid,
    "del_kid": _act_del_kid,
    "set_pin": _act_set_pin,
    "add_words": _act_add_words,
    "toggle_word": _act_toggle_word,
    "del_word": _act_del_word,
    "deactivate_all": _act_deactivate_all,
    "reset_week": _act_reset_week,
    "reset_all": _act_reset_all,
    "set_goal": _act_set_goal,
    "upload_sound": _act_upload_sound,
    "del_sound": _act_del_sound,
    "del_word_sound": _act_del_word_sound,
}


def _dispatch_action(request, user, classes, classroom):
    """Route a dashboard POST to its action handler."""
    action = request.POST.get("action")
    handler = CLASS_FREE_ACTIONS.get(action)
    if handler:
        return handler(request, user, classes)
    if not classroom:
        return teacher_fail("No active class")
    handler = CLASS_ACTIONS.get(action)
    if handler:
        return handler(request, classroom)
    return teacher_fail("Unknown action")


# ---------------------------------------------------------------------------
# Dashboard page
# ---------------------------------------------------------------------------

def _resolve_active_class(request, classes):
    """The teacher's active class, defaulting (and persisting) the first one."""
    cr_id = request.session.get("classroom_id")
    classroom = next((c for c in classes if c.pk == cr_id), None) if cr_id else None
    if classroom is None and classes:
        classroom = classes[0]
        request.session["classroom_id"] = classroom.pk
    return classroom


def _sound_rows(classroom):
    """Per-grapheme status rows for the dashboard sound grid."""
    sound_map = {s.grapheme: s for s in classroom.grapheme_sounds.all()}
    shared = GraphemeSound.objects.shared_graphemes()
    rows = []
    for g in sorted(tts.GRAPHEME_IPA):
        s = sound_map.get(g)
        if s and s.source == "custom":
            label, css = "\U0001f399 Custom", "custom"
        elif (s and s.source == "google") or g in shared:
            s = s or True
            label, css = "\U0001f916 Google", "google"
        else:
            label, css = "—", "none"
        rows.append({"grapheme": g, "has": bool(s),
                     "source": (s.source if hasattr(s, "source") else
                                ("google" if s else None)),
                     "label": label, "css": css})
    return rows


def _boss_rows(classroom):
    """Latest boss-fight standing per kid, flagged if for the current list."""
    current_version = classroom.active_word_list_version()
    rows = []
    for k in classroom.kids.order_by("name"):
        fight = k.boss_fights.order_by("-created").first()
        rows.append({
            "kid": k,
            "fight": fight,
            "current": bool(fight and fight.word_list_version == current_version),
        })
    return rows


def _dashboard_context(classes, classroom):
    if not classroom:
        return {"classroom": None, "classes": classes, "kids": [], "words": [],
                "trouble": [], "misses": [], "sound_rows": [],
                "word_sounds": set(), "boss_rows": []}
    return {
        "classroom": classroom,
        "classes": classes,
        "kids": classroom.kids.order_by("name"),
        "words": classroom.words.all(),
        "trouble": SoundMiss.objects.trouble_sounds(classroom),
        "misses": (SoundMiss.objects.filter(kid__classroom=classroom)
                   .select_related("kid").order_by("kid__name", "-count")),
        "sound_rows": _sound_rows(classroom),
        "word_sounds": {ws.word for ws in classroom.word_sounds.all()},
        "boss_rows": _boss_rows(classroom),
    }


@login_required
def dashboard(request):
    from django.shortcuts import render

    user = request.user
    classes = list(user.classes.order_by("name"))
    classroom = _resolve_active_class(request, classes)
    if request.method == "POST":
        return _dispatch_action(request, user, classes, classroom)
    return render(request, "game/dashboard.html",
                  _dashboard_context(classes, classroom))
