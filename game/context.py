"""Resolve the acting kid/classroom from the session.

Kids are identified purely by session state (``kid_id`` / ``classroom_id``);
teachers by ``request.user`` plus the active ``classroom_id``.  Every view
must use these helpers instead of poking at the session directly.
"""

from .models import Class, Kid


def get_classroom(request):
    """Active classroom from session (kids or teacher session)."""
    cr_id = request.session.get("classroom_id")
    return Class.objects.filter(pk=cr_id).first() if cr_id else None


def get_kid(request):
    """Signed-in kid, or None."""
    kid_id = request.session.get("kid_id")
    return Kid.objects.filter(pk=kid_id).first() if kid_id else None


def teacher_classroom(request):
    """Active classroom owned by the signed-in teacher, or None."""
    if not request.user.is_authenticated:
        return None
    cr_id = request.session.get("classroom_id")
    if cr_id:
        cr = Class.objects.filter(pk=cr_id, teacher=request.user).first()
        if cr:
            return cr
    return request.user.classes.order_by("name").first()


def playback_classroom(request):
    """Classroom whose sounds this request may play: kid's, else teacher's."""
    kid = get_kid(request)
    return kid.classroom if kid else teacher_classroom(request)


def enter_classroom(request, classroom):
    """Put a classroom into the kid session."""
    request.session["classroom_id"] = classroom.pk
