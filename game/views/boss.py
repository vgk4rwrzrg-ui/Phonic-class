"""Boss fight AJAX endpoints.

Eligibility, damage, and rewards are all validated server-side; the client's
word list is only ever used as a claim to be checked against the active list.
"""

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from ..jsonapi import json_body, json_fail, json_ok, require_kid, upper_param
from ..models import BossFight

BOSS_VICTORY_POINTS = 50


def _fight_for(kid, fight_id):
    """Fetch one of the kid's fights by id, or None."""
    try:
        return BossFight.objects.get(pk=fight_id, kid=kid)
    except BossFight.DoesNotExist:
        return None


def _current_fight(kid, classroom):
    """(version, fight-or-None) for the classroom's current word list."""
    version = classroom.active_word_list_version()
    fight = BossFight.objects.filter(kid=kid, word_list_version=version).first()
    return version, fight


def _create_fight(kid, version, max_hp):
    """Create the fight row, surviving a concurrent-create race."""
    try:
        with transaction.atomic():
            return BossFight.objects.create(
                kid=kid, word_list_version=version,
                boss_max_hp=max_hp, boss_hp=max_hp,
            )
    except IntegrityError:
        # Race: another request created it first
        return BossFight.objects.get(kid=kid, word_list_version=version)


@require_POST
@require_kid
def api_boss_eligible(request, kid):
    """
    Check/confirm boss eligibility for the signed-in kid.
    Client sends the list of words it believes the kid has completed.
    Server validates against the active word list and creates the BossFight row.
    """
    cr = kid.classroom
    if not cr.boss_enabled:
        return json_fail("boss disabled", status=200)

    active_words = set(cr.active_word_texts())
    if not active_words:
        return json_fail("no_words", status=200)

    version, fight = _current_fight(kid, cr)
    if fight and fight.completed:
        # Baron Blot is already beaten for this word list.  No rematch until
        # the teacher changes the active words (new version = new fight).
        return json_ok(eligible=False, reason="already_beaten")
    if fight:
        return json_ok(eligible=True, word_list_version=version,
                       **fight.summary())

    # Server-side validation: all active words must appear in the client claim
    data = json_body(request)
    client_spelled = {w.strip().upper() for w in data.get("words_spelled", []) if w}
    if not active_words.issubset(client_spelled):
        missing = active_words - client_spelled
        return JsonResponse({"ok": False, "eligible": False,
                             "missing_words": list(missing)[:5]})  # don't reveal all

    fight = _create_fight(kid, version, max_hp=len(active_words))
    return json_ok(eligible=True, word_list_version=version, **fight.summary())


def _apply_spell(fight_pk, word):
    """Atomically record a newly spelled word; return (fight, damage)."""
    with transaction.atomic():
        fight = BossFight.objects.select_for_update().get(pk=fight_pk)
        damage = 0
        if fight.add_spelled(word):
            # Reduce HP by 1 per new correctly spelled word
            fight.boss_hp = max(0, fight.boss_hp - 1)
            damage = 1
            fight.save()
    return fight, damage


@require_POST
@require_kid
def api_boss_spell(request, kid):
    """
    Record a spelling attempt against an active boss fight.
    Returns updated boss HP. Validates server-side; never trusts client HP.
    """
    data = json_body(request)
    word = upper_param(str(data.get("word", "")), 20)

    fight = _fight_for(kid, data.get("fight_id"))
    if not fight:
        return json_fail("fight not found", status=404)
    if fight.completed:
        return json_ok(already_completed=True, boss_hp=0,
                       boss_max_hp=fight.boss_max_hp,
                       words_spelled=list(fight.spelled_set()))
    if word not in set(kid.classroom.active_word_texts()):
        return json_fail("word not in active list", status=400)

    fight, damage = _apply_spell(fight.pk, word)
    return json_ok(correct=True, damage=damage,
                   boss_hp=fight.boss_hp, boss_max_hp=fight.boss_max_hp,
                   words_spelled=list(fight.spelled_set()),
                   completed=fight.boss_hp == 0)


@require_POST
@require_kid
def api_boss_victory(request, kid):
    """
    Claim boss victory reward. Idempotent: returns success even on duplicate.
    Boss HP must be 0 on the server before rewards are granted.
    """
    fight = _fight_for(kid, json_body(request).get("fight_id"))
    if not fight:
        return json_fail("fight not found", status=404)

    with transaction.atomic():
        fight = BossFight.objects.select_for_update().get(pk=fight.pk)
        if fight.boss_hp != 0:
            return json_fail("boss not defeated", status=400)
        if not fight.completed:
            fight.completed = True
            fight.save()
        if fight.reward_claimed:
            # Idempotent — already gave reward
            return json_ok(duplicate=True, points_week=kid.points_week,
                           points_total=kid.points_total)
        fight.reward_claimed = True
        fight.save()

        kid.refresh_from_db()
        kid.award_points(BOSS_VICTORY_POINTS)

    return json_ok(points_awarded=BOSS_VICTORY_POINTS, **kid.score_payload())


@require_kid
def api_boss_status(request, kid):
    """Return current boss fight status for the signed-in kid (GET)."""
    cr = kid.classroom
    version, fight = _current_fight(kid, cr)
    return json_ok(
        boss_enabled=cr.boss_enabled,
        balloon_enabled=cr.balloon_enabled,
        balloon_frequency=cr.balloon_frequency,
        active_words=cr.active_word_texts(),
        word_list_version=version,
        fight=fight.summary() if fight else None,
    )
