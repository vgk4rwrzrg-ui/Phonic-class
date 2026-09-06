"""Shared helpers for AJAX endpoints.

Two JSON dialects exist in the frontend and must be preserved exactly:

* Kid-facing game APIs speak ``{"ok": bool, ...}`` (see :func:`json_ok` /
  :func:`json_fail`).
* Teacher dashboard actions speak ``{"success": bool, "message": str, ...}``
  (see :func:`teacher_ok` / :func:`teacher_fail`).

All endpoints should build responses through these helpers so payload shapes
never drift between views.
"""

import json
from functools import wraps

from django.http import JsonResponse

from .context import get_kid, teacher_classroom


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------

def json_body(request):
    """Parse a JSON request body, returning {} for empty/malformed bodies."""
    try:
        return json.loads(request.body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def parse_int(value, default=None):
    """int() that returns *default* instead of raising."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp_int(value, lo, hi, default=0):
    """Parse *value* as an int clamped to [lo, hi]; *default* if unparseable."""
    n = parse_int(value)
    if n is None:
        return default
    return max(lo, min(hi, n))


def upper_param(raw, max_len):
    """Normalize a user-supplied token: strip, uppercase, truncate."""
    return (raw or "").strip().upper()[:max_len]


# ---------------------------------------------------------------------------
# Standard response builders
# ---------------------------------------------------------------------------

def json_ok(**payload):
    """Kid-API success payload: {"ok": true, ...}."""
    return JsonResponse({"ok": True, **payload})


def json_fail(error, status=400, **payload):
    """Kid-API failure payload: {"ok": false, "error": ..., ...}."""
    return JsonResponse({"ok": False, "error": error, **payload}, status=status)


def teacher_ok(message, **payload):
    """Dashboard-API success payload: {"success": true, "message": ..., ...}."""
    return JsonResponse({"success": True, "message": message, **payload})


def teacher_fail(message, status=200, **payload):
    """Dashboard-API failure payload: {"success": false, "message": ...}."""
    return JsonResponse({"success": False, "message": message, **payload},
                        status=status)


# ---------------------------------------------------------------------------
# View guards (fail-safe auth for AJAX endpoints)
# ---------------------------------------------------------------------------

def require_kid(view):
    """Resolve the signed-in kid or fail 403; pass the kid to the view."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        kid = get_kid(request)
        if not kid:
            return json_fail("not signed in", status=403)
        return view(request, kid, *args, **kwargs)
    return wrapper


def require_kid_feature(flag, error):
    """Like require_kid, but also require a classroom feature flag."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            kid = get_kid(request)
            if not kid:
                return json_fail("not signed in", status=403)
            if not getattr(kid.classroom, flag):
                return json_fail(error, status=403)
            return view(request, kid, *args, **kwargs)
        return wrapper
    return decorator


def require_teacher_class(view):
    """Kid-dialect guard for teacher endpoints: 400 if no active class."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        cr = teacher_classroom(request)
        if not cr:
            return json_fail("no class selected", status=400)
        return view(request, cr, *args, **kwargs)
    return wrapper


def require_teacher_class_panel(view):
    """Teacher-dialect guard: {"success": false, "message": "No active class"}."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        cr = teacher_classroom(request)
        if not cr:
            return teacher_fail("No active class", status=400)
        return view(request, cr, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Idempotency nonces (session-backed double-tap protection)
# ---------------------------------------------------------------------------

def nonce_session_key(prefix, kid, nonce):
    """Session key used to remember a processed client nonce."""
    return f"{prefix}_nonce_{kid.pk}_{nonce}"


def read_nonce(request, prefix, kid, data):
    """Return (nonce, previously_stored_value_or_None) for this request."""
    nonce = str(data.get("nonce", ""))[:64]
    if not nonce:
        return "", None
    return nonce, request.session.get(nonce_session_key(prefix, kid, nonce))


def store_nonce(request, prefix, kid, nonce, value=True):
    """Mark a nonce as processed (no-op when the client sent none)."""
    if nonce:
        request.session[nonce_session_key(prefix, kid, nonce)] = value
