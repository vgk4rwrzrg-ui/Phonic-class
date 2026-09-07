"""Public view surface for the game app.

The old monolithic views.py is split into cohesive modules; this package
re-exports every URL-referenced view plus a few historical underscore names
that game.tasks and the test-suite resolve via ``game.views`` at call time
(so unittest.mock can patch them here).
"""

from .kids import (kids_root, join_class, class_join, picker, logout_kid,
                   switch_class, game, leaderboard)
from .gameplay import api_score, api_miss, api_balloon_complete
from .boss import (api_boss_eligible, api_boss_spell, api_boss_victory,
                   api_boss_status)
from .sounds import sound, word_sound, phrase_sound
from .teacher import (signup, teacher_record, teacher_delete,
                      teacher_google_word, teacher_audio_zip,
                      api_teacher_settings)
from .dashboard import dashboard
from .pets import (pet_area, api_pet_buy, api_pet_hatch, api_pet_hatch_status,
                   api_pet_companion, pet_image, pet_sound)

__all__ = [
    "kids_root", "join_class", "class_join", "picker", "logout_kid",
    "switch_class", "game", "leaderboard",
    "api_score", "api_miss", "api_balloon_complete",
    "api_boss_eligible", "api_boss_spell", "api_boss_victory",
    "api_boss_status",
    "sound", "word_sound", "phrase_sound",
    "signup", "teacher_record", "teacher_delete", "teacher_google_word",
    "teacher_audio_zip", "api_teacher_settings",
    "dashboard",
    "pet_area", "api_pet_buy", "api_pet_hatch", "api_pet_hatch_status",
    "api_pet_companion", "pet_image", "pet_sound",
    "get_classroom", "get_kid",
]

# Keep get_classroom / get_kid accessible via game.views for any external callers.
from ..context import get_classroom, get_kid  # noqa: E402
