import json
import mimetypes
from datetime import date, timedelta

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
    cr = kid.classroom
    words = list(cr.words.filter(active=True).values("text", "level"))
    game_config = {
        "balloon_enabled": cr.balloon_enabled,
        "balloon_frequency": cr.balloon_frequency,
        "boss_enabled": cr.boss_enabled,
        "kid_id": kid.pk,
    }
    return render(request, "game/game.html",
                  {"kid": kid, "words": words, "classroom": cr,
                   "game_config": game_config})


# -------- APIs --------

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
    except Exception as exc:  # no credentials / network / quota
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)
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
    # No recording: fall back to Google TTS for whole words (same as graphemes).
    # Only synthesize words that belong to this class, so kids can't spend the
    # teacher's TTS quota on arbitrary text.
    if not cr.words.filter(text=w).exists():
        return JsonResponse({"ok": False, "error": "no word sound"}, status=404)
    try:
        raw = tts.synthesize_word(w)
    except Exception:  # no credentials / network / quota -> browser TTS fallback
        return JsonResponse({"ok": False, "error": "no word sound"}, status=404)
    obj = obj or WordSound(classroom=cr, word=w)
    obj.source = "google"
    obj.audio.save(f"{cr.pk}_{w.lower()}.mp3", ContentFile(raw), save=True)
    return FileResponse(obj.audio.open("rb"), content_type=_content_type(obj.audio.name))


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
        return JsonResponse({"ok": True, "grapheme": grapheme})
    if word:
        cleaned, ext = audio.clean_audio(f.read(), f.name)
        obj, _ = WordSound.objects.get_or_create(classroom=cr, word=word)
        obj.source = "custom"
        obj.audio.save(f"{cr.pk}_{word.lower()}.{ext}", ContentFile(cleaned), save=True)
        return JsonResponse({"ok": True, "word": word})
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
        return JsonResponse({"ok": True, "grapheme": grapheme})
    if word:
        WordSound.objects.filter(classroom=cr, word=word).delete()
        return JsonResponse({"ok": True, "word": word})
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

        # class management (works even with no active class yet)
        if action == "switch_class":
            try:
                new_id = int(request.POST.get("class_id"))
            except (TypeError, ValueError):
                new_id = None
            if any(c.pk == new_id for c in classes):
                request.session["classroom_id"] = new_id
                return JsonResponse({"success": True, "message": "Class switched"})
            return JsonResponse({"success": False, "message": "Invalid class"})

        if action == "add_class":
            name = (request.POST.get("name") or "").strip()[:60]
            if name:
                cls = Class.objects.create(teacher=user, name=name)
                request.session["classroom_id"] = cls.pk
                return JsonResponse({"success": True, "message": f"Class '{name}' created", "id": cls.pk, "code": cls.code})
            return JsonResponse({"success": False, "message": "Name required"})

        if action == "del_class":
            try:
                cid = int(request.POST.get("class_id"))
            except (TypeError, ValueError):
                return JsonResponse({"success": False, "message": "Invalid class ID"})
            cls = user.classes.filter(pk=cid).first()
            if cls and len(classes) > 1:  # never delete the last class
                cls.delete()
                if request.session.get("classroom_id") == cls.pk:
                    request.session.pop("classroom_id", None)
                return JsonResponse({"success": True, "message": "Class deleted"})
            return JsonResponse({"success": False, "message": "Cannot delete last class"})

        if not classroom:
            return JsonResponse({"success": False, "message": "No active class"})

        # class-scoped actions
        if action == "add_kid":
            name = (request.POST.get("name") or "").strip()[:30]
            pin = (request.POST.get("pin") or "").strip()[:4]
            icon = (request.POST.get("icon") or "🦊").strip()[:8]
            if name and pin.isdigit() and len(pin) == 4:
                kid, created = classroom.kids.get_or_create(name=name, defaults={"pin": pin, "icon": icon})
                if created:
                    return JsonResponse({"success": True, "message": f"Added {name}", "id": kid.pk, "name": name, "icon": icon, "pin": pin})
                return JsonResponse({"success": False, "message": "Kid already exists"})
            return JsonResponse({"success": False, "message": "Invalid name or PIN"})
        elif action == "del_kid":
            kid_id = request.POST.get("kid_id")
            kid = classroom.kids.filter(pk=kid_id).first()
            if kid:
                name = kid.name
                kid.delete()
                return JsonResponse({"success": True, "message": f"Deleted {name}"})
            return JsonResponse({"success": False, "message": "Kid not found"})
        elif action == "set_pin":
            pin = (request.POST.get("pin") or "").strip()[:4]
            kid_id = request.POST.get("kid_id")
            if pin.isdigit() and len(pin) == 4:
                classroom.kids.filter(pk=kid_id).update(pin=pin)
                return JsonResponse({"success": True, "message": "PIN updated"})
            return JsonResponse({"success": False, "message": "Invalid PIN"})
        elif action == "add_words":
            added = 0
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
                    _, created = classroom.words.update_or_create(text=text, defaults={"level": level, "active": True})
                    if created:
                        added += 1
            return JsonResponse({"success": True, "message": f"Added {added} words"})
        elif action == "toggle_word":
            w = classroom.words.filter(pk=request.POST.get("word_id")).first()
            if w:
                w.active = not w.active
                w.save()
                return JsonResponse({"success": True, "message": f"{w.text} {'activated' if w.active else 'deactivated'}", "active": w.active})
            return JsonResponse({"success": False, "message": "Word not found"})
        elif action == "del_word":
            word_id = request.POST.get("word_id")
            word = classroom.words.filter(pk=word_id).first()
            if word:
                text = word.text
                word.delete()
                return JsonResponse({"success": True, "message": f"Deleted {text}"})
            return JsonResponse({"success": False, "message": "Word not found"})
        elif action == "deactivate_all":
            count = classroom.words.filter(active=True).count()
            classroom.words.update(active=False)
            return JsonResponse({"success": True, "message": f"Deactivated {count} words"})
        elif action == "reset_week":
            classroom.kids.update(points_week=0)
            return JsonResponse({"success": True, "message": "Weekly points reset"})
        elif action == "reset_all":
            classroom.kids.update(points_week=0, points_total=0, streak=0, last_played=None)
            SoundMiss.objects.filter(kid__classroom=classroom).delete()
            return JsonResponse({"success": True, "message": "All stats reset"})
        elif action == "set_goal":
            try:
                goal = max(0, int(request.POST.get("goal", "")))
            except (TypeError, ValueError):
                goal = None
            if goal is not None:
                classroom.class_goal = goal
                classroom.save()
                return JsonResponse({"success": True, "message": f"Goal set to {goal}"})
            return JsonResponse({"success": False, "message": "Invalid goal"})
        elif action == "upload_sound":
            g = (request.POST.get("grapheme") or "").strip().upper()[:8]
            f = request.FILES.get("audio")
            if g and f:
                cleaned, ext = audio.clean_audio(f.read(), f.name)
                obj, _ = GraphemeSound.objects.get_or_create(classroom=classroom, grapheme=g)
                obj.source = "custom"
                obj.audio.save(f"{classroom.pk}_{g.lower()}.{ext}", ContentFile(cleaned), save=True)
                return JsonResponse({"success": True, "message": f"Uploaded {g}"})
            return JsonResponse({"success": False, "message": "Invalid upload"})
        elif action == "del_sound":
            grapheme = (request.POST.get("grapheme") or "").strip().upper()
            GraphemeSound.objects.filter(classroom=classroom, grapheme=grapheme).delete()
            return JsonResponse({"success": True, "message": f"Deleted {grapheme}"})
        elif action == "del_word_sound":
            word = (request.POST.get("word") or "").strip().upper()
            WordSound.objects.filter(classroom=classroom, word=word).delete()
            return JsonResponse({"success": True, "message": f"Deleted {word} sound"})
        return JsonResponse({"success": False, "message": "Unknown action"})

    trouble = (SoundMiss.objects.filter(kid__classroom=classroom)
               .values("sound").annotate(total=Sum("count")).order_by("-total")[:12]) if classroom else []
    boss_rows = []
    if classroom:
        current_version = classroom.active_word_list_version()
        for k in classroom.kids.order_by("name"):
            fight = (k.boss_fights.order_by("-created").first()
                     if hasattr(k, "boss_fights") else None)
            boss_rows.append({
                "kid": k,
                "fight": fight,
                "current": bool(fight and fight.word_list_version == current_version),
            })
    return render(request, "game/dashboard.html", {
        "classroom": classroom,
        "classes": classes,
        "kids": classroom.kids.order_by("name") if classroom else [],
        "words": classroom.words.all() if classroom else [],
        "trouble": trouble,
        "misses": (SoundMiss.objects.filter(kid__classroom=classroom)
                   .select_related("kid").order_by("kid__name", "-count")) if classroom else [],
        "sound_rows": _sound_rows(classroom) if classroom else [],
        "word_sounds": {ws.word for ws in classroom.word_sounds.all()} if classroom else set(),
        "boss_rows": boss_rows,
    })



# ──────────────────────────────────────────────────────────────────────────────
# Balloon challenge & Boss fight APIs
# ──────────────────────────────────────────────────────────────────────────────

from django.db import transaction, IntegrityError
from .models import BossFight


# ---- Balloon ----------------------------------------------------------------

@require_POST
def api_balloon_complete(request):
    """
    Record a completed balloon round.  Returns the existing reward system points.
    Idempotent: duplicate posts within the same session key are silently ignored.
    """
    kid = get_kid(request)
    if not kid:
        return JsonResponse({"ok": False, "error": "not signed in"}, status=403)
    cr = kid.classroom
    if not cr.balloon_enabled:
        return JsonResponse({"ok": False, "error": "balloon disabled"}, status=403)

    data = _json_body(request)
    # Client sends a nonce so we can detect double-taps / retries
    nonce = str(data.get("nonce", ""))[:64]
    session_key = f"balloon_nonce_{kid.pk}_{nonce}"
    if nonce and request.session.get(session_key):
        # Already processed this exact nonce
        return JsonResponse({"ok": True, "duplicate": True,
                             "points_week": kid.points_week,
                             "points_total": kid.points_total})
    if nonce:
        request.session[session_key] = True

    # Award fixed 5 points for a balloon round
    pts = 5
    kid.points_total += pts
    kid.points_week += pts
    today = date.today()
    if kid.last_played != today:
        kid.streak = kid.streak + 1 if kid.last_played == today - timedelta(days=1) else 1
        kid.last_played = today
    kid.save()
    return JsonResponse({"ok": True, "points_week": kid.points_week,
                         "points_total": kid.points_total, "streak": kid.streak})


# ---- Boss eligibility -------------------------------------------------------

def _get_or_create_boss(kid, classroom):
    """
    Server-side boss eligibility check.
    Returns (fight, eligible, reason) where fight may be None.
    A new BossFight is created (but not saved) if the kid is newly eligible.
    """
    if not classroom.boss_enabled:
        return None, False, "boss_disabled"

    active_words = list(classroom.words.filter(active=True).values_list("text", flat=True))
    if not active_words:
        return None, False, "no_words"

    version = classroom.active_word_list_version()

    # Look up existing fight for this version
    fight = BossFight.objects.filter(kid=kid, word_list_version=version).first()
    if fight:
        return fight, True, "existing"

    # Check if all active words have been completed in the normal game.
    # We consider a word "done" if the kid has scored at least once AND the
    # word appears in any completed boss fight's words_spelled for THIS kid,
    # OR if the kid's total score implies they have played through the list.
    # Real check: the game frontend tracks completion; the server validates
    # by checking whether the client reports all words spelled (see api_boss_spell).
    # For eligibility we trust the dedicated check endpoint only.
    return None, False, "not_eligible"


@require_POST
def api_boss_eligible(request):
    """
    Check/confirm boss eligibility for the signed-in kid.
    Client sends the list of words it believes the kid has completed.
    Server validates against the active word list and creates the BossFight row.
    """
    kid = get_kid(request)
    if not kid:
        return JsonResponse({"ok": False, "error": "not signed in"}, status=403)
    cr = kid.classroom
    if not cr.boss_enabled:
        return JsonResponse({"ok": False, "error": "boss disabled"})

    active_words = set(cr.words.filter(active=True).values_list("text", flat=True))
    if not active_words:
        return JsonResponse({"ok": False, "error": "no_words"})

    data = _json_body(request)
    client_spelled = {w.strip().upper() for w in data.get("words_spelled", []) if w}

    version = cr.active_word_list_version()

    # Check if there's already a fight for this version
    fight = BossFight.objects.filter(kid=kid, word_list_version=version).first()
    if fight:
        return JsonResponse({
            "ok": True,
            "eligible": True,
            "fight_id": fight.pk,
            "boss_hp": fight.boss_hp,
            "boss_max_hp": fight.boss_max_hp,
            "completed": fight.completed,
            "reward_claimed": fight.reward_claimed,
            "words_spelled": list(fight.spelled_set()),
            "word_list_version": version,
        })

    # Server-side validation: all active words must appear in client_spelled
    if not active_words.issubset(client_spelled):
        missing = active_words - client_spelled
        return JsonResponse({
            "ok": False,
            "eligible": False,
            "missing_words": list(missing)[:5],  # don't reveal all
        })

    # Create the boss fight
    max_hp = len(active_words)
    try:
        with transaction.atomic():
            fight = BossFight.objects.create(
                kid=kid,
                word_list_version=version,
                boss_max_hp=max_hp,
                boss_hp=max_hp,
            )
    except IntegrityError:
        # Race: another request created it first
        fight = BossFight.objects.get(kid=kid, word_list_version=version)

    return JsonResponse({
        "ok": True,
        "eligible": True,
        "fight_id": fight.pk,
        "boss_hp": fight.boss_hp,
        "boss_max_hp": fight.boss_max_hp,
        "completed": fight.completed,
        "reward_claimed": fight.reward_claimed,
        "words_spelled": [],
        "word_list_version": version,
    })


# ---- Boss spell attempt -----------------------------------------------------

@require_POST
def api_boss_spell(request):
    """
    Record a spelling attempt against an active boss fight.
    Returns updated boss HP. Validates server-side; never trusts client HP.
    """
    kid = get_kid(request)
    if not kid:
        return JsonResponse({"ok": False, "error": "not signed in"}, status=403)

    data = _json_body(request)
    fight_id = data.get("fight_id")
    word = str(data.get("word", "")).strip().upper()[:20]

    try:
        fight = BossFight.objects.get(pk=fight_id, kid=kid)
    except BossFight.DoesNotExist:
        return JsonResponse({"ok": False, "error": "fight not found"}, status=404)

    if fight.completed:
        return JsonResponse({
            "ok": True, "already_completed": True,
            "boss_hp": 0, "boss_max_hp": fight.boss_max_hp,
            "words_spelled": list(fight.spelled_set()),
        })

    cr = kid.classroom
    # Validate the word is in the active list for this fight's version
    active_words = set(cr.words.filter(active=True).values_list("text", flat=True))
    if word not in active_words:
        return JsonResponse({"ok": False, "error": "word not in active list"}, status=400)

    with transaction.atomic():
        fight = BossFight.objects.select_for_update().get(pk=fight.pk)
        is_new = fight.add_spelled(word)
        damage = 0
        if is_new:
            # Reduce HP by 1 per new correctly spelled word
            fight.boss_hp = max(0, fight.boss_hp - 1)
            damage = 1
            fight.save()

    return JsonResponse({
        "ok": True,
        "correct": True,
        "damage": damage,
        "boss_hp": fight.boss_hp,
        "boss_max_hp": fight.boss_max_hp,
        "words_spelled": list(fight.spelled_set()),
        "completed": fight.boss_hp == 0,
    })


# ---- Boss victory -----------------------------------------------------------

@require_POST
def api_boss_victory(request):
    """
    Claim boss victory reward. Idempotent: returns success even on duplicate.
    Boss HP must be 0 on the server before rewards are granted.
    """
    kid = get_kid(request)
    if not kid:
        return JsonResponse({"ok": False, "error": "not signed in"}, status=403)

    data = _json_body(request)
    fight_id = data.get("fight_id")

    try:
        fight = BossFight.objects.get(pk=fight_id, kid=kid)
    except BossFight.DoesNotExist:
        return JsonResponse({"ok": False, "error": "fight not found"}, status=404)

    with transaction.atomic():
        fight = BossFight.objects.select_for_update().get(pk=fight.pk)
        if fight.boss_hp != 0:
            return JsonResponse({"ok": False, "error": "boss not defeated"}, status=400)

        if not fight.completed:
            fight.completed = True
            fight.save()

        if fight.reward_claimed:
            # Idempotent — already gave reward
            return JsonResponse({
                "ok": True, "duplicate": True,
                "points_week": kid.points_week,
                "points_total": kid.points_total,
            })

        # Grant reward: 50 points for boss victory
        pts = 50
        fight.reward_claimed = True
        fight.save()

        kid.refresh_from_db()
        kid.points_total += pts
        kid.points_week += pts
        today = date.today()
        if kid.last_played != today:
            kid.streak = kid.streak + 1 if kid.last_played == today - timedelta(days=1) else 1
            kid.last_played = today
        kid.save()

    return JsonResponse({
        "ok": True,
        "points_awarded": pts,
        "points_week": kid.points_week,
        "points_total": kid.points_total,
        "streak": kid.streak,
    })


# ---- Boss status (GET, for page reload recovery) ----------------------------

def api_boss_status(request):
    """Return current boss fight status for the signed-in kid."""
    kid = get_kid(request)
    if not kid:
        return JsonResponse({"ok": False, "error": "not signed in"}, status=403)
    cr = kid.classroom
    version = cr.active_word_list_version()
    fight = BossFight.objects.filter(kid=kid, word_list_version=version).first()
    active_words = list(cr.words.filter(active=True).values_list("text", flat=True))
    return JsonResponse({
        "ok": True,
        "boss_enabled": cr.boss_enabled,
        "balloon_enabled": cr.balloon_enabled,
        "balloon_frequency": cr.balloon_frequency,
        "active_words": active_words,
        "word_list_version": version,
        "fight": {
            "fight_id": fight.pk,
            "boss_hp": fight.boss_hp,
            "boss_max_hp": fight.boss_max_hp,
            "completed": fight.completed,
            "reward_claimed": fight.reward_claimed,
            "words_spelled": list(fight.spelled_set()),
        } if fight else None,
    })


# ---- Teacher dashboard boss/balloon settings --------------------------------

@login_required
@require_POST
def api_teacher_settings(request):
    """Save balloon/boss settings from the teacher dashboard."""
    cr = _teacher_classroom(request)
    if not cr:
        return JsonResponse({"success": False, "message": "No active class"}, status=400)
    data = _json_body(request)
    changed = []
    if "balloon_enabled" in data:
        cr.balloon_enabled = bool(data["balloon_enabled"])
        changed.append("balloon_enabled")
    if "balloon_frequency" in data:
        try:
            freq = max(0, min(20, int(data["balloon_frequency"])))
            cr.balloon_frequency = freq
            changed.append("balloon_frequency")
        except (TypeError, ValueError):
            return JsonResponse({"success": False, "message": "Invalid frequency"})
    if "boss_enabled" in data:
        cr.boss_enabled = bool(data["boss_enabled"])
        changed.append("boss_enabled")
    if changed:
        cr.save(update_fields=changed)
    return JsonResponse({"success": True, "message": "Settings saved"})
