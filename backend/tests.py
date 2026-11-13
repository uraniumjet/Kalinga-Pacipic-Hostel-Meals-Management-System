from unittest import mock

from django.apps import apps
from django.test import TestCase
from django.urls import reverse


class RetiredPrototypeTests(TestCase):
    def test_root_goes_to_the_new_home(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/accounts/", fetch_redirect_response=False)

    def test_old_prototype_urls_are_gone(self):
        for url in ("/student/", "/api/student/", "/api/meals/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_old_apps_are_not_installed(self):
        for label in ("student", "meals", "users", "rest_framework", "corsheaders"):
            self.assertFalse(apps.is_installed(label), label)


class HealthCheckTests(TestCase):
    def test_healthz_needs_no_login_and_says_ok(self):
        response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("no-cache", response["Cache-Control"])

    def test_healthz_reports_a_broken_database(self):
        with mock.patch("backend.views.connection") as connection:
            connection.cursor.side_effect = RuntimeError("database is down")
            with self.assertLogs("backend.views", level="ERROR"):
                response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "error"})

    def test_healthz_only_answers_get(self):
        self.assertEqual(self.client.post(reverse("healthz")).status_code, 405)
