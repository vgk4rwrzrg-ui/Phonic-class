from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from game import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.picker, name="picker"),
    path("play/", views.game, name="game"),
    path("bye/", views.logout_kid, name="logout_kid"),
    path("leaderboard/", views.leaderboard, name="leaderboard"),
    path("api/score/", views.api_score, name="api_score"),
    path("api/miss/", views.api_miss, name="api_miss"),
    path("sound/<str:grapheme>/", views.sound, name="sound"),
    path("wordsound/<str:word>/", views.word_sound, name="word_sound"),
    path("teacher/record/", views.teacher_record, name="teacher_record"),
    path("teacher/delete/", views.teacher_delete, name="teacher_delete"),
    path("teacher/", views.dashboard, name="dashboard"),
    path("teacher/login/", auth_views.LoginView.as_view(template_name="game/teacher_login.html"), name="login"),
    path("teacher/logout/", auth_views.LogoutView.as_view(next_page="picker"), name="logout"),
]
