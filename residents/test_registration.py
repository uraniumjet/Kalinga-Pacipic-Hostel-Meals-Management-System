import shutil
import tempfile
from datetime import date
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from organizations.models import Category, DietType, Hostel, Organization, Room, StaffProfile
from residents.models import Student
from residents.services import allocate_room

MEDIA = tempfile.mkdtemp()


def jpeg(width=2000, height=1000, name="p.jpg"):
    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=MEDIA)
class RegistrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.addClassCleanup(shutil.rmtree, MEDIA, True)

    def setUp(self):
        self.org = Organization.objects.create(name="Org A", slug="a")
        self.cat = Category.objects.create(organization=self.org, name="National")
        self.diet = DietType.objects.create(organization=self.org, name="Veg")
        self.boys1 = Hostel.objects.create(organization=self.org, name="Boys 1", gender="male")
        self.boys2 = Hostel.objects.create(organization=self.org, name="Boys 2", gender="male")
        self.girls = Hostel.objects.create(organization=self.org, name="Girls 1", gender="female")
        self.r1 = Room.objects.create(hostel=self.boys1, number="101", capacity=2)
        self.r1b = Room.objects.create(hostel=self.boys1, number="102", capacity=2)
        self.r2 = Room.objects.create(hostel=self.boys2, number="201", capacity=2)
        self.rg = Room.objects.create(hostel=self.girls, number="G1", capacity=2)

        user = User.objects.create_user("warden", password="pw12345!")
        profile = StaffProfile.objects.create(user=user, organization=self.org, role="warden")
        profile.hostels.set([self.boys1, self.girls])  # not Boys 2
        self.client.login(username="warden", password="pw12345!")

    def payload(self, **overrides):
        data = {
            "roll_number": "R100", "name": "Alice Example", "gender": "male",
            "category": self.cat.pk, "diet": self.diet.pk, "religion": "", "room": "",
        }
        data.update(overrides)
        return data

    def student(self, roll, name, room=None, gender="male"):
        s = Student.objects.create(
            organization=self.org, roll_number=roll, name=name, gender=gender, category=self.cat, diet=self.diet
        )
        if room:
            allocate_room(s, room, date(2026, 11, 1))
        return s

    def edit_payload(self, student, **overrides):
        data = self.payload(roll_number=student.roll_number, name=student.name, gender=student.gender, status="active")
        data.update(overrides)
        return data

    # --- access ---
    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("residents:create"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    # --- registration ---
    def test_register_with_room(self):
        response = self.client.post(reverse("residents:create"), self.payload(room=self.r1.pk))
        student = Student.objects.get(roll_number="R100")
        self.assertRedirects(response, reverse("residents:detail", args=[student.pk]))
        self.assertEqual(student.organization, self.org)
        self.assertEqual(student.current_room, self.r1)

    def test_register_without_room_is_allowed(self):
        self.client.post(reverse("residents:create"), self.payload())
        student = Student.objects.get(roll_number="R100")
        self.assertIsNone(student.current_room)
        self.assertContains(self.client.get(reverse("residents:list")), "Alice Example")

    def test_photo_is_resized_and_stored_as_jpeg(self):
        self.client.post(reverse("residents:create"), self.payload(photo=jpeg(2000, 1000)))
        student = Student.objects.get(roll_number="R100")
        with Image.open(student.photo) as stored:
            self.assertEqual(stored.format, "JPEG")
            self.assertLessEqual(max(stored.size), 400)

    def test_non_image_upload_is_rejected(self):
        bad = SimpleUploadedFile("a.jpg", b"not an image", content_type="image/jpeg")
        response = self.client.post(reverse("residents:create"), self.payload(photo=bad))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Student.objects.exists())

    def test_duplicate_roll_number_is_rejected(self):
        self.student("R100", "Existing")
        response = self.client.post(reverse("residents:create"), self.payload())
        self.assertContains(response, "already exists")
        self.assertEqual(Student.objects.count(), 1)

    def test_same_roll_number_in_another_organization_is_fine(self):
        other = Organization.objects.create(name="Org B", slug="b")
        oc = Category.objects.create(organization=other, name="National")
        od = DietType.objects.create(organization=other, name="Veg")
        Student.objects.create(organization=other, roll_number="R100", name="Elsewhere", gender="male", category=oc, diet=od)
        self.client.post(reverse("residents:create"), self.payload())
        self.assertTrue(Student.objects.filter(organization=self.org, roll_number="R100").exists())

    def test_category_from_another_organization_is_rejected(self):
        other = Organization.objects.create(name="Org B", slug="b")
        foreign = Category.objects.create(organization=other, name="Foreign")
        response = self.client.post(reverse("residents:create"), self.payload(category=foreign.pk))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Student.objects.exists())

    # --- rooms ---
    def test_room_of_an_unassigned_hostel_is_rejected(self):
        response = self.client.post(reverse("residents:create"), self.payload(room=self.r2.pk))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Student.objects.exists())

    def test_wrong_gender_room_is_rejected(self):
        response = self.client.post(reverse("residents:create"), self.payload(gender="male", room=self.rg.pk))
        self.assertContains(response, "female hostel")
        self.assertFalse(Student.objects.exists())

    def test_full_room_is_not_accepted(self):
        self.student("A1", "A One", self.r1)
        self.student("A2", "A Two", self.r1)
        response = self.client.post(reverse("residents:create"), self.payload(room=self.r1.pk))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Student.objects.filter(roll_number="R100").exists())

    def test_form_shows_free_beds(self):
        self.student("A1", "A One", self.r1)
        response = self.client.get(reverse("residents:create"))
        self.assertContains(response, "Boys 1 / 101 - 1 free of 2")
        self.assertContains(response, "Boys 1 / 102 - 2 free of 2")
        self.assertNotContains(response, "Boys 2 / 201")

    # --- list, detail, edit ---
    def test_list_is_scoped_and_searchable(self):
        self.student("A1", "Visible Vic", self.r1)
        self.student("B1", "Hidden Harry", self.r2)
        page = self.client.get(reverse("residents:list"))
        self.assertContains(page, "Visible Vic")
        self.assertNotContains(page, "Hidden Harry")
        hit = self.client.get(reverse("residents:list"), {"q": "A1"})
        self.assertContains(hit, "Visible Vic")
        miss = self.client.get(reverse("residents:list"), {"q": "zzz"})
        self.assertNotContains(miss, "Visible Vic")

    def test_detail_of_student_outside_scope_is_404(self):
        hidden = self.student("B1", "Hidden Harry", self.r2)
        self.assertEqual(self.client.get(reverse("residents:detail", args=[hidden.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("residents:edit", args=[hidden.pk])).status_code, 404)

    def test_changing_room_keeps_history(self):
        s = self.student("A1", "A One", self.r1)
        self.client.post(reverse("residents:edit", args=[s.pk]), self.edit_payload(s, room=self.r1b.pk))
        self.assertEqual(s.current_room, self.r1b)
        self.assertEqual(s.allocations.count(), 2)

    def test_editing_without_changing_room_adds_no_allocation(self):
        s = self.student("A1", "A One", self.r1)
        self.client.post(reverse("residents:edit", args=[s.pk]), self.edit_payload(s, name="A Renamed", room=self.r1.pk))
        s.refresh_from_db()
        self.assertEqual(s.name, "A Renamed")
        self.assertEqual(s.allocations.count(), 1)

    def test_marking_student_as_left_vacates_the_room(self):
        s = self.student("A1", "A One", self.r1)
        self.client.post(reverse("residents:edit", args=[s.pk]), self.edit_payload(s, status="left", room=self.r1.pk))
        s.refresh_from_db()
        self.assertEqual(s.status, "left")
        self.assertIsNone(s.current_room)
