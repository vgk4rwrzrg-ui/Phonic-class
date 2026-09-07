"""Teacher endpoints: signup, recording management, settings, audio export."""

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from ..forms import TeacherSignupForm
from ..jsonapi import (json_body, json_fail, json_ok, parse_int,
                       require_teacher_class, require_teacher_class_panel,
                       teacher_fail, teacher_ok, upper_param)
from ..models import Class, GraphemeSound, WordSound
from .. import sound_services, tts


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = TeacherSignupForm(request.POST) if request.method == "POST" else TeacherSignupForm()
    if request.method == "POST" and form.is_valid():
        user = form.save()
        cls = Class.objects.create(teacher=user,
                                   name=form.cleaned_data["class_name"])
        request.session["classroom_id"] = cls.pk
        login(request, user)
        return redirect("dashboard")
    return render(request, "game/signup.html", {"form": form})


def _recording_targets(request):
    """(grapheme, word) params for the record/delete endpoints."""
    return (upper_param(request.POST.get("grapheme"), 8),
            upper_param(request.POST.get("word"), 20))


@login_required
@require_POST
@require_teacher_class
def teacher_record(request, cr):
    """Store a teacher voice recording (ffmpeg-cleaned) for a grapheme/word."""
    grapheme, word = _recording_targets(request)
    f = request.FILES.get("audio")
    if not f:
        return json_fail("no audio", status=400)
    if grapheme:
        sound_services.save_custom_grapheme(cr, grapheme, f.read(), f.name)
        return json_ok(grapheme=grapheme)
    if word:
        sound_services.save_custom_word(cr, word, f.read(), f.name)
        return json_ok(word=word)
    return json_fail("need grapheme or word", status=400)


@login_required
@require_POST
@require_teacher_class
def teacher_delete(request, cr):
    """Delete a class recording so playback falls back to Google TTS."""
    grapheme, word = _recording_targets(request)
    if grapheme:
        GraphemeSound.objects.filter(classroom=cr, grapheme=grapheme).delete()
        return json_ok(grapheme=grapheme)
    if word:
        WordSound.objects.filter(classroom=cr, word=word).delete()
        return json_ok(word=word)
    return json_fail("need grapheme or word", status=400)


@login_required
@require_POST
@require_teacher_class_panel
def teacher_google_word(request, cr):
    """Generate (or regenerate) Google TTS audio for one of this class's words."""
    word = upper_param(request.POST.get("word"), 20)
    if not word or not cr.words.filter(text=word).exists():
        return teacher_fail("Word not found", status=404)
    existing = WordSound.objects.filter(classroom=cr, word=word).first()
    if existing and existing.source == "custom":
        return teacher_fail(f"{word} has a custom recording — delete it first")
    try:
        sound_services.synthesize_class_word(cr, word, existing=existing)
    except Exception as exc:
        return teacher_fail("Google TTS unavailable: " + str(exc)[:160]
                            + " (run: python manage.py ttscheck)", status=503)
    return teacher_ok(f"Google audio ready for {word}")


@login_required
@require_teacher_class_panel
def teacher_audio_zip(request, cr):
    """Download every generated/recorded audio file as one zip."""
    buf = sound_services.build_audio_zip(cr)
    resp = HttpResponse(buf.read(), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="phonics_audio_{cr.code}.zip"'
    return resp


# ---- Balloon / boss / pets settings from the dashboard ----------------------

def _apply_bool_setting(cr, data, field):
    if field not in data:
        return None
    setattr(cr, field, bool(data[field]))
    return field


def _apply_clamped_setting(cr, data, field, lo, hi, error):
    """Apply an int setting clamped to [lo, hi]; return error message if bad."""
    if field not in data:
        return None, None
    n = parse_int(data[field])
    if n is None:
        return None, error
    setattr(cr, field, max(lo, min(hi, n)))
    return field, None


@login_required
@require_POST
@require_teacher_class_panel
def api_teacher_settings(request, cr):
    """Save balloon/boss/pet settings from the teacher dashboard."""
    data = json_body(request)
    changed = []

    field = _apply_bool_setting(cr, data, "balloon_enabled")
    if field:
        changed.append(field)
    field, err = _apply_clamped_setting(cr, data, "balloon_frequency", 0, 20,
                                        "Invalid frequency")
    if err:
        return teacher_fail(err)
    if field:
        changed.append(field)
    for name in ("boss_enabled", "pets_enabled"):
        field = _apply_bool_setting(cr, data, name)
        if field:
            changed.append(field)
    field, err = _apply_clamped_setting(cr, data, "egg_cost", 5, 5000,
                                        "Invalid egg cost")
    if err:
        return teacher_fail(err)
    if field:
        changed.append(field)
    field, err = _apply_clamped_setting(cr, data, "hd_cost", 5, 5000,
                                        "Invalid HD egg cost")
    if err:
        return teacher_fail(err)
    if field:
        changed.append(field)

    if changed:
        cr.save(update_fields=changed)
    return teacher_ok("Settings saved")
