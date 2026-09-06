from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from game import views

urlpatterns = [
    path("admin/", admin.site.urls),

    # Kids
    path("", views.kids_root, name="kids_root"),
    path("join/", views.join_class, name="join_class"),
    path("c/<str:code>/", views.class_join, name="class_join"),
    path("picker/", views.picker, name="picker"),
    path("play/", views.game, name="game"),
    path("bye/", views.logout_kid, name="logout_kid"),
    path("switch-class/", views.switch_class, name="switch_class"),
    path("leaderboard/", views.leaderboard, name="leaderboard"),

    # Game APIs
    path("api/score/", views.api_score, name="api_score"),
    path("api/miss/", views.api_miss, name="api_miss"),

    # Balloon APIs
    path("api/balloon/complete/", views.api_balloon_complete, name="api_balloon_complete"),

    # Boss fight APIs
    path("api/boss/eligible/", views.api_boss_eligible, name="api_boss_eligible"),
    path("api/boss/spell/", views.api_boss_spell, name="api_boss_spell"),
    path("api/boss/victory/", views.api_boss_victory, name="api_boss_victory"),
    path("api/boss/status/", views.api_boss_status, name="api_boss_status"),

    # Sound endpoints
    path("sound/<str:grapheme>/", views.sound, name="sound"),
    path("wordsound/<str:word>/", views.word_sound, name="word_sound"),

    # Teacher
    path("teacher/", views.dashboard, name="dashboard"),
    path("teacher/record/", views.teacher_record, name="teacher_record"),
    path("teacher/delete/", views.teacher_delete, name="teacher_delete"),
    path("teacher/settings/", views.api_teacher_settings, name="api_teacher_settings"),
    path("teacher/googleword/", views.teacher_google_word, name="teacher_google_word"),
    path("teacher/login/",
         auth_views.LoginView.as_view(template_name="game/teacher_login.html"),
         name="login"),
    path("teacher/signup/", views.signup, name="signup"),
    path("teacher/logout/",
         auth_views.LogoutView.as_view(next_page="kids_root"),
         name="logout"),
]
