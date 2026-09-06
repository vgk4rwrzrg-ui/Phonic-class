"""Core gameplay AJAX endpoints: scoring, miss tracking, balloon rounds."""

from django.views.decorators.http import require_POST

from ..jsonapi import (clamp_int, json_body, json_fail, json_ok, read_nonce,
                       require_kid, require_kid_feature, store_nonce,
                       upper_param)
from ..models import SoundMiss

MAX_POINTS_PER_EVENT = 50
BALLOON_POINTS = 5


@require_POST
@require_kid
def api_score(request, kid):
    """Award clamped points for a completed word and bump the daily streak."""
    pts = clamp_int(json_body(request).get("points", 0),
                    0, MAX_POINTS_PER_EVENT, default=0)
    kid.award_points(pts)
    return json_ok(**kid.score_payload())


@require_POST
@require_kid
def api_miss(request, kid):
    """Record one missed sound for the teacher's trouble-sounds report."""
    sound = upper_param(str(json_body(request).get("sound", "")), 12)
    if sound:
        SoundMiss.objects.record(kid, sound)
    return json_ok()


@require_POST
@require_kid_feature("balloon_enabled", "balloon disabled")
def api_balloon_complete(request, kid):
    """
    Record a completed balloon round.  Returns the existing reward system points.
    Idempotent: duplicate posts within the same session key are silently ignored.
    """
    nonce, seen = read_nonce(request, "balloon", kid, json_body(request))
    if seen:
        return json_ok(duplicate=True, points_week=kid.points_week,
                       points_total=kid.points_total)
    store_nonce(request, "balloon", kid, nonce)
    kid.award_points(BALLOON_POINTS)
    return json_ok(**kid.score_payload())
