import json
import mimetypes
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db.models import Sum
from django.http import FileResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import audio, tts
from .forms import TeacherSignupForm
from .models import Class, GraphemeSound, Kid, SoundMiss, Word, WordSound

mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/webm", ".webm")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/mp4", ".mp4")


def _content_type(name):
    mime, _ = mimetypes.guess_type(name or "")
    return mime or "audio/mpeg"


def _sound_rows(classroom):
    sound_map = {s.grapheme: s for s in classroom.grapheme_sounds.all()}
    rows = []
    for g in sorted(tts.GRAPHEME_IPA):
        s = sound_map.get(g)
        if s and s.source == "custom":
            label, css = "🎙 Custom", "custom"
        elif s:
            label, css = "🤖 Google", "google"
        else:
            label, css = "—", "none"
        rows.append({"grapheme": g, "has": bool(s),
                     "source": s.source if s else None,
                     "label": label, "css": css})
    return rows


def get_classroom(request):
    """Active classroom from session (kids or teacher session)."""
    cr_id = request.session.get("classroom_id")
    return Class.objects.filter(pk=cr_id).first() if cr_id else None


def get_kid(request):
    kid_id = request.session.get("kid_id")
    return Kid.objects.filter(pk=kid_id).first() if kid_id else None


def _teacher_classroom(request):
    """Active classroom owned by the signed-in teacher."""
    if not request.user.is_authenticated:
        return None
    cr_id = request.session.get("classroom_id")
    if cr_id:
        cr = Class.objects.filter(pk=cr_id, teacher=request.user).first()
        if cr:
            return cr
    return request.user.classes.order_by("name").first()


# -------- Teacher auth --------

def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = TeacherSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            cls = Class.objects.create(teacher=user, name=form.cleaned_data["class_name"])
            request.session["classroom_id"] = cls.pk
            login(request, user)
            return redirect("dashboard")
    else:
        form = TeacherSignupForm()
    return render(request, "game/signup.html", {"form": form})


# -------- Kids flow --------

def kids_root(request):
    """Landing page: join a class by code, or go to picker if class in session."""
    if get_classroom(request):
        return redirect("picker")
    return render(request, "game/kids_root.html")


@require_POST
def join_class(request):
    code = (request.POST.get("code") or "").strip().upper()
    cr = Class.objects.filter(code=code).first()
    if not cr:
        return render(request, "game/kids_root.html", {"error": "No class with that code."})
    request.session["classroom_id"] = cr.pk
    return redirect("picker")


def class_join(request, code):
    cr = Class.objects.filter(code=code.upper()).first()
    if not cr:
        return render(request, "game/kids_root.html", {"error": "No class with that code.", "bad_code": code})
    request.session["classroom_id"] = cr.pk
    return redirect("picker")


def picker(request):
    cr = get_classroom(request)
    if not cr:
        return redirect("kids_root")
    error = None
    if request.method == "POST":
        kid = cr.kids.filter(pk=request.POST.get("kid_id")).first()
        pin = (request.POST.get("pin") or "").strip()
        if kid and pin == kid.pin:
            request.session["kid_id"] = kid.pk
            return redirect("game")
        error = "Oops, wrong PIN. Try again!"
    return render(request, "game/picker.html", {
        "classroom": cr, "kids": cr.kids.order_by("name"), "error": error,
    })


def logout_kid(request):
    request.session.pop("kid_id", None)
    return redirect("picker")


def switch_class(request):
    request.session.pop("classroom_id", None)
    request.session.pop("kid_id", None)
    return redirect("kids_root")


def game(request):
    kid = get_kid(request)
    if not kid:
        return redirect("picker")
    words = list(kid.classroom.words.filter(active=True).values("text", "level"))
    return render(request, "game/game.html", {"kid": kid, "words": words, "classroom": kid.classroom})


# -------- APIs --------

def _json_body(request):
    try:
        return json.loads(request.body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def _wants_json(request):
    """True for fetch/XHR calls. Plain form posts get a redirect instead of raw JSON."""
    return (request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "application/json" in request.headers.get("accept", ""))


def _respond(request, ok, message="", to="dashboard", **extra):
    """One reply shape everywhere: JSON for XHR, message + redirect for plain form posts.

    Templates show `message` as a toast; the redirect path uses django.contrib.messages
    so a browser without JS never lands on a bare JSON page.
    """
    if _wants_json(request):
        return JsonResponse({"ok": ok, "message": message, **extra})
    if message:
        messages.add_message(request, messages.SUCCESS if ok else messages.ERROR, message)
    return redirect(to)


@require_POST
def api_score(request):
    kid = get_kid(request)
    if not kid:
        return JsonResponse({"ok": False, "error": "not signed in"}, status=403)
    data = _json_body(request)
    try:
        pts = int(data.get("points", 0))
    except (TypeError, ValueError):
        pts = 0
    pts = max(0, min(pts, 50))
    kid.points_total += pts
    kid.points_week += pts
    today = date.today()
    if kid.last_played != today:
        kid.streak = kid.streak + 1 if kid.last_played == today - timedelta(days=1) else 1
        kid.last_played = today
    kid.save()
    return JsonResponse({"ok": True, "points_week": kid.points_week,
                         "points_total": kid.points_total, "streak": kid.streak})


@require_POST
def api_miss(request):
    kid = get_kid(request)
    if not kid:
        return JsonResponse({"ok": False, "error": "not signed in"}, status=403)
    sound = str(_json_body(request).get("sound", ""))[:12].strip().upper()
    if sound:
        miss, _ = SoundMiss.objects.get_or_create(kid=kid, sound=sound)
        miss.count += 1
        miss.save()
    return JsonResponse({"ok": True})


# -------- Sound endpoints (scoped by kid's or teacher's class) --------

def sound(request, grapheme):
    g = (grapheme or "").strip().upper()[:8]
    if not g:
        return JsonResponse({"ok": False, "error": "missing sound"}, status=400)
    kid = get_kid(request)
    cr = kid.classroom if kid else _teacher_classroom(request)
    if not cr:
        return JsonResponse({"ok": False, "error": "not signed in"}, status=403)
    obj = GraphemeSound.objects.filter(classroom=cr, grapheme=g).first()
    if obj and obj.audio:
        return FileResponse(obj.audio.open("rb"), content_type=_content_type(obj.audio.name))
    try:
        raw = tts.synthesize(g)
    except Exception:  # no credentials / network / quota
        return JsonResponse({"ok": False, "error": "sound unavailable"}, status=503)
    obj = GraphemeSound(classroom=cr, grapheme=g, source="google")
    obj.audio.save(f"{cr.pk}_{g.lower()}.mp3", ContentFile(raw), save=True)
    return FileResponse(obj.audio.open("rb"), content_type=_content_type(obj.audio.name))


def word_sound(request, word):
    w = (word or "").strip().upper()[:20]
    kid = get_kid(request)
    cr = kid.classroom if kid else _teacher_classroom(request)
    if not cr:
        return JsonResponse({"ok": False, "error": "not signed in"}, status=403)
    obj = WordSound.objects.filter(classroom=cr, word=w).first()
    if obj and obj.audio:
        return FileResponse(obj.audio.open("rb"), content_type=_content_type(obj.audio.name))
    return JsonResponse({"ok": False, "error": "no word sound"}, status=404)


# -------- Teacher recording (scoped to active class) --------

@login_required
@require_POST
def teacher_record(request):
    cr = _teacher_classroom(request)
    if not cr:
        return JsonResponse({"ok": False, "error": "no class selected"}, status=400)
    grapheme = (request.POST.get("grapheme") or "").strip().upper()[:8]
    word = (request.POST.get("word") or "").strip().upper()[:20]
    f = request.FILES.get("audio")
    if not f:
        return JsonResponse({"ok": False, "error": "no audio"}, status=400)
    if grapheme:
        cleaned, ext = audio.clean_audio(f.read(), f.name)
        obj, _ = GraphemeSound.objects.get_or_create(classroom=cr, grapheme=grapheme)
        obj.source = "custom"
        obj.audio.save(f"{cr.pk}_{grapheme.lower()}.{ext}", ContentFile(cleaned), save=True)
        return JsonResponse({"ok": True, "grapheme": grapheme, "message": f"Saved {grapheme}"})
    if word:
        cleaned, ext = audio.clean_audio(f.read(), f.name)
        obj, _ = WordSound.objects.get_or_create(classroom=cr, word=word)
        obj.audio.save(f"{cr.pk}_{word.lower()}.{ext}", ContentFile(cleaned), save=True)
        return JsonResponse({"ok": True, "word": word, "message": f"Saved {word}"})
    return JsonResponse({"ok": False, "error": "need grapheme or word"}, status=400)


@login_required
@require_POST
def teacher_delete(request):
    cr = _teacher_classroom(request)
    if not cr:
        return JsonResponse({"ok": False, "error": "no class selected"}, status=400)
    grapheme = (request.POST.get("grapheme") or "").strip().upper()[:8]
    word = (request.POST.get("word") or "").strip().upper()[:20]
    if grapheme:
        GraphemeSound.objects.filter(classroom=cr, grapheme=grapheme).delete()
        return JsonResponse({"ok": True, "grapheme": grapheme, "message": f"Deleted {grapheme}"})
    if word:
        WordSound.objects.filter(classroom=cr, word=word).delete()
        return JsonResponse({"ok": True, "word": word, "message": f"Deleted {word} recording"})
    return JsonResponse({"ok": False, "error": "need grapheme or word"}, status=400)


# -------- Leaderboard (scoped to session class) --------

def leaderboard(request):
    cr = get_classroom(request)
    if not cr:
        return redirect("kids_root")
    kids = cr.kids.order_by("-points_week", "name")
    class_total = cr.kids.aggregate(t=Sum("points_week"))["t"] or 0
    pct = min(100, round(100 * class_total / cr.class_goal)) if cr.class_goal else 0
    return render(request, "game/leaderboard.html", {
        "classroom": cr, "kids": kids, "class_total": class_total,
        "goal": cr.class_goal, "pct": pct, "me": get_kid(request),
    })


# -------- Teacher dashboard (scoped to active class) --------
#
# Every action below returns _respond(...), so the browser gets JSON with a
# `message` for the toast (XHR) or a redirect carrying a django message (no JS).


def _dash_switch_class(request, user, classes, classroom):
    try:
        new_id = int(request.POST.get("class_id"))
    except (TypeError, ValueError):
        new_id = None
    if any(c.pk == new_id for c in classes):
        request.session["classroom_id"] = new_id
        return _respond(request, True, "Class switched", reload=True)
    return _respond(request, False, "Invalid class")


def _dash_add_class(request, user, classes, classroom):
    name = (request.POST.get("name") or "").strip()[:60]
    if not name:
        return _respond(request, False, "Name required")
    cls = Class.objects.create(teacher=user, name=name)
    request.session["classroom_id"] = cls.pk
    return _respond(request, True, f"Class '{name}' created",
                    id=cls.pk, code=cls.code, reload=True)


def _dash_del_class(request, user, classes, classroom):
    try:
        cid = int(request.POST.get("class_id"))
    except (TypeError, ValueError):
        return _respond(request, False, "Invalid class ID")
    cls = user.classes.filter(pk=cid).first()
    if not cls or len(classes) <= 1:  # never delete the last class
        return _respond(request, False, "Cannot delete last class")
    name = cls.name
    cls.delete()
    # delete() clears cls.pk, so compare against the id captured above.
    if request.session.get("classroom_id") == cid:
        request.session.pop("classroom_id", None)
    return _respond(request, True, f"Deleted class '{name}'", reload=True)


def _dash_add_kid(request, classroom):
    name = (request.POST.get("name") or "").strip()[:30]
    pin = (request.POST.get("pin") or "").strip()[:4]
    icon = (request.POST.get("icon") or "🦊").strip()[:8]
    if not (name and pin.isdigit() and len(pin) == 4):
        return _respond(request, False, "Invalid name or PIN")
    kid, created = classroom.kids.get_or_create(name=name, defaults={"pin": pin, "icon": icon})
    if not created:
        return _respond(request, False, "Kid already exists")
    return _respond(request, True, f"Added {name}",
                    id=kid.pk, name=kid.name, icon=kid.icon, pin=kid.pin)


def _dash_del_kid(request, classroom):
    kid = classroom.kids.filter(pk=request.POST.get("kid_id")).first()
    if not kid:
        return _respond(request, False, "Kid not found")
    name = kid.name
    kid.delete()
    return _respond(request, True, f"Deleted {name}")


def _dash_set_pin(request, classroom):
    pin = (request.POST.get("pin") or "").strip()[:4]
    if not (pin.isdigit() and len(pin) == 4):
        return _respond(request, False, "Invalid PIN")
    updated = classroom.kids.filter(pk=request.POST.get("kid_id")).update(pin=pin)
    if not updated:
        return _respond(request, False, "Kid not found")
    return _respond(request, True, "PIN updated")


def _parse_word_line(line):
    """'FROG,2' or 'frog\t2' -> ('FROG', 2). Returns None for unusable lines."""
    parts = [p.strip() for p in line.replace("\t", ",").split(",")]
    text = parts[0].upper()[:20]
    if not text.isalpha():
        return None
    try:
        level = min(3, max(1, int(parts[1]))) if len(parts) > 1 else 1
    except ValueError:
        level = 1
    return text, level


def _dash_add_words(request, classroom):
    added = updated = 0
    for line in (request.POST.get("words") or "").splitlines():
        parsed = _parse_word_line(line.strip()) if line.strip() else None
        if not parsed:
            continue
        text, level = parsed
        _, created = classroom.words.update_or_create(
            text=text, defaults={"level": level, "active": True})
        if created:
            added += 1
        else:
            updated += 1
    msg = f"Added {added} words" + (f", updated {updated}" if updated else "")
    return _respond(request, True, msg, added=added, updated=updated, reload=bool(added))


def _dash_toggle_word(request, classroom):
    w = classroom.words.filter(pk=request.POST.get("word_id")).first()
    if not w:
        return _respond(request, False, "Word not found")
    w.active = not w.active
    w.save(update_fields=["active"])
    state = "activated" if w.active else "deactivated"
    return _respond(request, True, f"{w.text} {state}", active=w.active)


def _dash_del_word(request, classroom):
    word = classroom.words.filter(pk=request.POST.get("word_id")).first()
    if not word:
        return _respond(request, False, "Word not found")
    text = word.text
    word.delete()
    return _respond(request, True, f"Deleted {text}")


def _dash_deactivate_all(request, classroom):
    count = classroom.words.filter(active=True).count()
    classroom.words.update(active=False)
    return _respond(request, True, f"Deactivated {count} words", count=count)


def _dash_reset_week(request, classroom):
    classroom.kids.update(points_week=0)
    return _respond(request, True, "Weekly points reset")


def _dash_reset_all(request, classroom):
    classroom.kids.update(points_week=0, points_total=0, streak=0, last_played=None)
    SoundMiss.objects.filter(kid__classroom=classroom).delete()
    return _respond(request, True, "All stats reset", reload=True)


def _dash_set_goal(request, classroom):
    try:
        goal = max(0, int(request.POST.get("goal", "")))
    except (TypeError, ValueError):
        return _respond(request, False, "Invalid goal")
    classroom.class_goal = goal
    classroom.save(update_fields=["class_goal"])
    return _respond(request, True, f"Goal set to {goal}", goal=goal)


def _dash_upload_sound(request, classroom):
    g = (request.POST.get("grapheme") or "").strip().upper()[:8]
    f = request.FILES.get("audio")
    if not (g and f):
        return _respond(request, False, "Pick a sound and a file")
    cleaned, ext = audio.clean_audio(f.read(), f.name)
    obj, _ = GraphemeSound.objects.get_or_create(classroom=classroom, grapheme=g)
    obj.source = "custom"
    obj.audio.save(f"{classroom.pk}_{g.lower()}.{ext}", ContentFile(cleaned), save=True)
    return _respond(request, True, f"Uploaded {g}", grapheme=g)


def _dash_del_sound(request, classroom):
    grapheme = (request.POST.get("grapheme") or "").strip().upper()[:8]
    deleted, _ = GraphemeSound.objects.filter(classroom=classroom, grapheme=grapheme).delete()
    if not deleted:
        return _respond(request, False, "No recording to delete")
    return _respond(request, True, f"Deleted {grapheme}", grapheme=grapheme)


def _dash_del_word_sound(request, classroom):
    word = (request.POST.get("word") or "").strip().upper()[:20]
    deleted, _ = WordSound.objects.filter(classroom=classroom, word=word).delete()
    if not deleted:
        return _respond(request, False, "No recording to delete")
    return _respond(request, True, f"Deleted {word} recording", word=word)


# Actions that work even before a class exists.
CLASS_ACTIONS = {
    "switch_class": _dash_switch_class,
    "add_class": _dash_add_class,
    "del_class": _dash_del_class,
}

# Actions that need an active classroom.
SCOPED_ACTIONS = {
    "add_kid": _dash_add_kid,
    "del_kid": _dash_del_kid,
    "set_pin": _dash_set_pin,
    "add_words": _dash_add_words,
    "toggle_word": _dash_toggle_word,
    "del_word": _dash_del_word,
    "deactivate_all": _dash_deactivate_all,
    "reset_week": _dash_reset_week,
    "reset_all": _dash_reset_all,
    "set_goal": _dash_set_goal,
    "upload_sound": _dash_upload_sound,
    "del_sound": _dash_del_sound,
    "del_word_sound": _dash_del_word_sound,
}


@login_required
def dashboard(request):
    user = request.user
    classes = list(user.classes.order_by("name"))

    # resolve active class
    cr_id = request.session.get("classroom_id")
    classroom = next((c for c in classes if c.pk == cr_id), None) if cr_id else None
    if classroom is None and classes:
        classroom = classes[0]
        request.session["classroom_id"] = classroom.pk

    if request.method == "POST":
        action = request.POST.get("action")
        if action in CLASS_ACTIONS:
            return CLASS_ACTIONS[action](request, user, classes, classroom)
        if action in SCOPED_ACTIONS:
            if not classroom:
                return _respond(request, False, "No active class")
            return SCOPED_ACTIONS[action](request, classroom)
        return _respond(request, False, "Unknown action")

    misses = (SoundMiss.objects.filter(kid__classroom=classroom)
              if classroom else SoundMiss.objects.none())
    trouble = misses.values("sound").annotate(total=Sum("count")).order_by("-total")[:12]
    return render(request, "game/dashboard.html", {
        "classroom": classroom,
        "classes": classes,
        "kids": classroom.kids.order_by("name") if classroom else [],
        "words": classroom.words.all() if classroom else [],
        "trouble": trouble,
        "misses": misses.select_related("kid").order_by("kid__name", "-count"),
        "sound_rows": _sound_rows(classroom) if classroom else [],
        "word_sounds": {ws.word for ws in classroom.word_sounds.all()} if classroom else set(),
    })
