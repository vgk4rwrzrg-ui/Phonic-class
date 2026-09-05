"""Dashboard action tests: every POST returns {ok, message} for XHR and a
redirect carrying a django message for a plain form post -- never a JSON page."""
import json

from django.contrib.auth.models import User
from django.test import TestCase

from game.models import Class, Kid, Word

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class DashboardActionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("teacher", password="pw12345!")
        self.classroom = Class.objects.create(teacher=self.user, name="Class A")
        self.kid = Kid.objects.create(classroom=self.classroom, name="Ada",
                                      pin="1234", points_week=7)
        self.word = Word.objects.create(classroom=self.classroom, text="FROG",
                                       level=2, active=True)
        self.client.force_login(self.user)
        session = self.client.session
        session["classroom_id"] = self.classroom.pk
        session.save()

    def xhr(self, **data):
        response = self.client.post("/teacher/", data, **AJAX)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def test_dashboard_renders(self):
        self.assertEqual(self.client.get("/teacher/").status_code, 200)

    def test_actions_report_ok_and_message(self):
        for payload in (
            {"action": "set_goal", "goal": "120"},
            {"action": "toggle_word", "word_id": self.word.pk},
            {"action": "add_kid", "name": "Bo", "pin": "4321"},
            {"action": "reset_week"},
            {"action": "add_words", "words": "cat\ndog,3"},
        ):
            with self.subTest(action=payload["action"]):
                data = self.xhr(**payload)
                self.assertTrue(data["ok"], data)
                self.assertTrue(data["message"])

    def test_invalid_input_reports_error_message(self):
        for payload, expected in (
            ({"action": "set_pin", "kid_id": self.kid.pk, "pin": "12"}, "Invalid PIN"),
            ({"action": "add_kid", "name": "", "pin": "1234"}, "Invalid name or PIN"),
            ({"action": "set_goal", "goal": "abc"}, "Invalid goal"),
            ({"action": "nope"}, "Unknown action"),
        ):
            with self.subTest(action=payload["action"]):
                data = self.xhr(**payload)
                self.assertFalse(data["ok"])
                self.assertEqual(data["message"], expected)

    def test_reset_week_zeroes_points(self):
        self.xhr(action="reset_week")
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.points_week, 0)

    def test_add_words_counts_new_and_updated(self):
        data = self.xhr(action="add_words", words="cat\ndog,3\n99bad\nFROG,1")
        self.assertEqual((data["added"], data["updated"]), (2, 1))

    def test_plain_form_post_redirects_with_message(self):
        response = self.client.post("/teacher/", {"action": "set_goal", "goal": "55"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/teacher/")

        page = self.client.post("/teacher/", {"action": "set_goal", "goal": "55"},
                                follow=True).content.decode()
        self.assertIn('id="server-messages"', page)
        self.assertIn("Goal set to 55", page)
        self.assertFalse(page.lstrip().startswith("{"))

    def test_del_class_clears_stale_session_class(self):
        other = Class.objects.create(teacher=self.user, name="Class B")
        session = self.client.session
        session["classroom_id"] = other.pk
        session.save()
        self.assertTrue(self.xhr(action="del_class", class_id=other.pk)["ok"])
        self.assertIsNone(self.client.session.get("classroom_id"))

    def test_cannot_delete_last_class(self):
        data = self.xhr(action="del_class", class_id=self.classroom.pk)
        self.assertFalse(data["ok"])
        self.assertEqual(Class.objects.count(), 1)
