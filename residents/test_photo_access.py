import shutil
import tempfile
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from PIL import Image

from organizations.models import Category, DietType, Organization, StaffProfile
from residents.models import Student

MEDIA = tempfile.mkdtemp()


def jpeg_bytes():
    buffer = BytesIO()
    Image.new("RGB", (40, 40), (20, 120, 20)).save(buffer, "JPEG")
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=MEDIA)
class PhotoAccessTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.addClassCleanup(shutil.rmtree, MEDIA, True)

    def setUp(self):
        self.org = Organization.objects.create(name="A", slug="a")
        self.other = Organization.objects.create(name="B", slug="b")
        self.student = self.make_student(self.org, "S1")
        self.foreign = self.make_student(self.other, "X1")
        self.mine = self.staff("mine", self.org)
        self.theirs = self.staff("theirs", self.other)

    def make_student(self, org, roll):
        cat = Category.objects.create(organization=org, name="Cat")
        diet = DietType.objects.create(organization=org, name="Diet")
        student = Student.objects.create(
            organization=org, roll_number=roll, name=roll, gender="male", category=cat, diet=diet
        )
        student.photo.save(f"{roll}.jpg", ContentFile(jpeg_bytes()), save=True)
        return student

    def staff(self, username, org):
        user = User.objects.create_user(username, password="pw12345!Xy")
        StaffProfile.objects.create(user=user, organization=org, role="warden")
        return user

    def test_the_photo_url_points_at_the_protected_view(self):
        self.assertTrue(self.student.photo.url.startswith("/media/student_photos/"))

    def test_signed_in_staff_of_the_same_organisation_can_see_it(self):
        self.client.login(username="mine", password="pw12345!Xy")
        response = self.client.get(self.student.photo.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertIn("private", response["Cache-Control"])
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\xff\xd8"))

    def test_anonymous_visitors_are_sent_to_login(self):
        response = self.client.get(self.student.photo.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_staff_of_another_organisation_get_404(self):
        self.client.login(username="theirs", password="pw12345!Xy")
        self.assertEqual(self.client.get(self.student.photo.url).status_code, 404)
        self.assertEqual(self.client.get(self.foreign.photo.url).status_code, 200)

    def test_paths_that_are_not_student_photos_get_404(self):
        self.client.login(username="mine", password="pw12345!Xy")
        for path in ("/media/../manage.py", "/media/student_photos/nope.jpg", "/media/db.sqlite3"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
