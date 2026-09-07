"""Kid-facing pages: join a class, pick a profile, play, leaderboard."""

from django.db.models import Sum
from django.shortcuts import redirect, render

from ..context import enter_classroom, get_classroom, get_kid
from ..models import Class


def _render_join_error(request, code=None):
    ctx = {"error": "No class with that code."}
    if code is not None:
        ctx["bad_code"] = code
    return render(request, "game/kids_root.html", ctx)


def _enter_class_by_code(request, code, bad_code=None):
    """Shared handler for both join-by-form and join-by-link."""
    cr = Class.objects.by_code(code)
    if not cr:
        return _render_join_error(request, bad_code)
    enter_classroom(request, cr)
    return redirect("picker")


def kids_root(request):
    """Landing page: join a class by code, or go to picker if class in session."""
    if get_classroom(request):
        return redirect("picker")
    return render(request, "game/kids_root.html")


def join_class(request):
    if request.method != "POST":
        return redirect("kids_root")
    return _enter_class_by_code(request, (request.POST.get("code") or "").strip())


def class_join(request, code):
    return _enter_class_by_code(request, code, bad_code=code)


# Maximum failed PIN attempts before a short lockout kicks in.
_MAX_PIN_ATTEMPTS = 5
_PIN_LOCKOUT_SECONDS = 60


def _pin_attempt_key(kid_id):
    return f"pin_attempts_{kid_id}"


def _pin_locked_out(request, kid_id):
    """Return True if this session has exceeded the failed-attempt threshold."""
    import time
    key = _pin_attempt_key(kid_id)
    attempts = request.session.get(key, [])
    cutoff = time.time() - _PIN_LOCKOUT_SECONDS
    # Drop attempts older than the lockout window
    recent = [t for t in attempts if t > cutoff]
    request.session[key] = recent
    return len(recent) >= _MAX_PIN_ATTEMPTS


def _record_pin_failure(request, kid_id):
    import time
    key = _pin_attempt_key(kid_id)
    attempts = request.session.get(key, [])
    attempts.append(time.time())
    request.session[key] = attempts


def _clear_pin_attempts(request, kid_id):
    request.session.pop(_pin_attempt_key(kid_id), None)


def _try_pin_login(request, classroom):
    """Attempt a kid PIN login from POST data; return an error string or None.

    PINs are intentionally plain text (see Kid model) — this is a simple
    equality check, not a credential hash.  Failed attempts are tracked per
    session/kid to limit brute-force guessing of 4-digit PINs.
    """
    kid = classroom.kids.filter(pk=request.POST.get("kid_id")).first()
    if not kid:
        return "Oops, wrong PIN. Try again!"

    if _pin_locked_out(request, kid.pk):
        return f"Too many wrong tries. Please wait {_PIN_LOCKOUT_SECONDS} seconds."

    pin = (request.POST.get("pin") or "").strip()
    if pin == kid.pin:
        _clear_pin_attempts(request, kid.pk)
        request.session["kid_id"] = kid.pk
        return None

    _record_pin_failure(request, kid.pk)
    return "Oops, wrong PIN. Try again!"


def picker(request):
    cr = get_classroom(request)
    if not cr:
        return redirect("kids_root")
    error = None
    if request.method == "POST":
        error = _try_pin_login(request, cr)
        if error is None:
            return redirect("game")
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


def _companion_payload(kid, classroom):
    """The hatched companion pet shown alongside the game, if any."""
    if not classroom.pets_enabled:
        return None
    p = kid.pets.filter(is_companion=True, hatched=True).first()
    if not p:
        return None
    return {"id": p.pk, "name": p.name, "image_url": f"/petimage/{p.pk}/"}


def _game_config(kid, classroom):
    """Config blob consumed by the AJAX game frontend."""
    return {
        "balloon_enabled": classroom.balloon_enabled,
        "balloon_frequency": classroom.balloon_frequency,
        "boss_enabled": classroom.boss_enabled,
        "kid_id": kid.pk,
        "companion": _companion_payload(kid, classroom),
    }


def game(request):
    kid = get_kid(request)
    if not kid:
        return redirect("picker")
    cr = kid.classroom
    words = list(cr.active_words().values("text", "level"))
    return render(request, "game/game.html", {
        "kid": kid, "words": words, "classroom": cr,
        "game_config": _game_config(kid, cr),
    })


def _class_progress(classroom):
    """(total weekly points, percent of class goal) for the leaderboard."""
    total = classroom.kids.aggregate(t=Sum("points_week"))["t"] or 0
    pct = (min(100, round(100 * total / classroom.class_goal))
           if classroom.class_goal else 0)
    return total, pct


def leaderboard(request):
    cr = get_classroom(request)
    if not cr:
        return redirect("kids_root")
    total, pct = _class_progress(cr)
    return render(request, "game/leaderboard.html", {
        "classroom": cr, "kids": cr.kids.order_by("-points_week", "name"),
        "class_total": total, "goal": cr.class_goal, "pct": pct,
        "me": get_kid(request),
    })
