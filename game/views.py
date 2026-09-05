import json
import mimetypes
from datetime import date, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.base import ContentFile
from django.db.models import Sum
from django.http import FileResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import tts
from .models import Config, GraphemeSound, Kid, SoundMiss, Word, WordSound

mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/webm", ".webm")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/mp4", ".mp4")


def _content_type(name):
    mime, _ = mimetypes.guess_type(name or "")
    return mime or "audio/mpeg"


def _sound_rows():
    sound_map = {s.grapheme: s for s in GraphemeSound.objects.all()}
    rows = []
    for g in sorted(tts.GRAPHEME_IPA):
        s = sound_map.get(g)
        if s and s.source == "custom":
            label, css = "🎙 Custom", "custom"
        elif s:
            label, css = "🤖 Google", "google"
        else:
            label, css = "—", "none"
        rows.append({
            "grapheme": g,
            "has": bool(s),
            "source": s.source if s else None,
            "label": label,
            "css": css,
        })
    return rows


def get_kid(request):
    kid_id = request.session.get("kid_id")
    return Kid.objects.filter(pk=kid_id).first() if kid_id else None


def picker(request):
    error = None
    if request.method == "POST":
        kid = Kid.objects.filter(pk=request.POST.get("kid_id")).first()
        pin = (request.POST.get("pin") or "").strip()
        if kid and pin == kid.pin:
            request.session["kid_id"] = kid.pk
            return redirect("game")
        error = "Oops, wrong PIN. Try again!"
    return render(request, "game/picker.html",
                  {"kids": Kid.objects.order_by("name"), "error": error})


def logout_kid(request):
    request.session.pop("kid_id", None)
    return redirect("picker")


def game(request):
    kid = get_kid(request)
    if not kid:
        return redirect("picker")
    words = list(Word.objects.filter(active=True).values("text", "level"))
    return render(request, "game/game.html", {"kid": kid, "words": words})


def _json_body(request):
    try:
        return json.loads(request.body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


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


def sound(request, grapheme):
    g = (grapheme or "").strip().upper()[:8]
    if not g:
        return JsonResponse({"ok": False, "error": "missing sound"}, status=400)
    if not (get_kid(request) or request.user.is_staff):
        return JsonResponse({"ok": False, "error": "not signed in"}, status=403)
    obj = GraphemeSound.objects.filter(grapheme=g).first()
    if obj and obj.audio:
        return FileResponse(obj.audio.open("rb"), content_type=_content_type(obj.audio.name))
    try:
        audio = tts.synthesize(g)
    except Exception as exc:  # no credentials / not installed / network / quota
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)
    obj = GraphemeSound(grapheme=g, source="google")
    obj.audio.save(f"{g.lower()}.mp3", ContentFile(audio), save=True)
    return FileResponse(obj.audio.open("rb"), content_type=_content_type(obj.audio.name))


def word_sound(request, word):
    w = (word or "").strip().upper()[:20]
    if not (get_kid(request) or request.user.is_staff):
        return JsonResponse({"ok": False, "error": "not signed in"}, status=403)
    obj = WordSound.objects.filter(word=w).first()
    if obj and obj.audio:
        return FileResponse(obj.audio.open("rb"), content_type=_content_type(obj.audio.name))
    return JsonResponse({"ok": False, "error": "no word sound"}, status=404)


@staff_member_required
@require_POST
def teacher_record(request):
    grapheme = (request.POST.get("grapheme") or "").strip().upper()[:8]
    word = (request.POST.get("word") or "").strip().upper()[:20]
    f = request.FILES.get("audio")
    if not f:
        return JsonResponse({"ok": False, "error": "no audio"}, status=400)
    if grapheme:
        obj, _ = GraphemeSound.objects.get_or_create(grapheme=grapheme)
        obj.source = "custom"
        obj.audio.save(f.name, f, save=True)
        return JsonResponse({"ok": True, "grapheme": grapheme})
    if word:
        obj, _ = WordSound.objects.get_or_create(word=word)
        obj.audio.save(f.name, f, save=True)
        return JsonResponse({"ok": True, "word": word})
    return JsonResponse({"ok": False, "error": "need grapheme or word"}, status=400)


@staff_member_required
@require_POST
def teacher_delete(request):
    grapheme = (request.POST.get("grapheme") or "").strip().upper()[:8]
    word = (request.POST.get("word") or "").strip().upper()[:20]
    if grapheme:
        GraphemeSound.objects.filter(grapheme=grapheme).delete()
        return JsonResponse({"ok": True, "grapheme": grapheme})
    if word:
        WordSound.objects.filter(word=word).delete()
        return JsonResponse({"ok": True, "word": word})
    return JsonResponse({"ok": False, "error": "need grapheme or word"}, status=400)


def leaderboard(request):
    kids = Kid.objects.order_by("-points_week", "name")
    cfg = Config.get()
    class_total = Kid.objects.aggregate(t=Sum("points_week"))["t"] or 0
    pct = min(100, round(100 * class_total / cfg.class_goal)) if cfg.class_goal else 0
    return render(request, "game/leaderboard.html",
                  {"kids": kids, "class_total": class_total,
                   "goal": cfg.class_goal, "pct": pct, "me": get_kid(request)})


@staff_member_required
def dashboard(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_kid":
            name = (request.POST.get("name") or "").strip()[:30]
            pin = (request.POST.get("pin") or "").strip()[:4]
            icon = (request.POST.get("icon") or "🦊").strip()[:8]
            if name and pin.isdigit() and len(pin) == 4:
                Kid.objects.get_or_create(name=name, defaults={"pin": pin, "icon": icon})
        elif action == "del_kid":
            Kid.objects.filter(pk=request.POST.get("kid_id")).delete()
        elif action == "set_pin":
            pin = (request.POST.get("pin") or "").strip()[:4]
            if pin.isdigit() and len(pin) == 4:
                Kid.objects.filter(pk=request.POST.get("kid_id")).update(pin=pin)
        elif action == "add_words":
            for line in (request.POST.get("words") or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.replace("\t", ",").split(",")]
                text = parts[0].upper()[:20]
                try:
                    level = min(3, max(1, int(parts[1]))) if len(parts) > 1 else 1
                except ValueError:
                    level = 1
                if text.isalpha():
                    Word.objects.update_or_create(text=text, defaults={"level": level, "active": True})
        elif action == "toggle_word":
            w = Word.objects.filter(pk=request.POST.get("word_id")).first()
            if w:
                w.active = not w.active
                w.save()
        elif action == "del_word":
            Word.objects.filter(pk=request.POST.get("word_id")).delete()
        elif action == "deactivate_all":
            Word.objects.update(active=False)
        elif action == "reset_week":
            Kid.objects.update(points_week=0)
        elif action == "reset_all":
            Kid.objects.update(points_week=0, points_total=0, streak=0, last_played=None)
            SoundMiss.objects.all().delete()
        elif action == "set_goal":
            try:
                goal = max(0, int(request.POST.get("goal", "")))
            except (TypeError, ValueError):
                goal = None
            if goal is not None:
                cfg = Config.get()
                cfg.class_goal = goal
                cfg.save()
        elif action == "upload_sound":
            g = (request.POST.get("grapheme") or "").strip().upper()[:8]
            f = request.FILES.get("audio")
            if g and f:
                obj, _ = GraphemeSound.objects.get_or_create(grapheme=g)
                obj.source = "custom"
                obj.audio.save(f.name, f, save=True)
        elif action == "del_sound":
            GraphemeSound.objects.filter(
                grapheme=(request.POST.get("grapheme") or "").strip().upper()
            ).delete()
        elif action == "del_word_sound":
            WordSound.objects.filter(
                word=(request.POST.get("word") or "").strip().upper()
            ).delete()
        return redirect("dashboard")

    trouble = (SoundMiss.objects.values("sound")
               .annotate(total=Sum("count")).order_by("-total")[:12])
    return render(request, "game/dashboard.html", {
        "kids": Kid.objects.order_by("name"),
        "words": Word.objects.all(),
        "trouble": trouble,
        "misses": SoundMiss.objects.select_related("kid").order_by("kid__name", "-count"),
        "config": Config.get(),
        "sound_rows": _sound_rows(),
        "word_sounds": {ws.word for ws in WordSound.objects.all()},
    })
