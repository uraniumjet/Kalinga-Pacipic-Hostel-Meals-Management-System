from django.apps import apps
from django.test import TestCase


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
