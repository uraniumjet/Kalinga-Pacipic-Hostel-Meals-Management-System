from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from organizations.models import Category, DietType, Hostel, Organization, Room, StaffProfile
from residents.models import Student
from residents.services import allocate_room


class QrTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org A", slug="a")
        cat = Category.objects.create(organization=self.org, name="National")
        diet = DietType.objects.create(organization=self.org, name="Veg")
        mine = Hostel.objects.create(organization=self.org, name="Mine", gender="male")
        theirs = Hostel.objects.create(organization=self.org, name="Theirs", gender="male")
        self.student = Student.objects.create(
            organization=self.org, roll_number="R1", name="Mine", gender="male", category=cat, diet=diet
        )
        self.hidden = Student.objects.create(
            organization=self.org, roll_number="R2", name="Hidden", gender="male", category=cat, diet=diet
        )
        allocate_room(self.student, Room.objects.create(hostel=mine, number="1", capacity=2), date(2026, 11, 1))
        allocate_room(self.hidden, Room.objects.create(hostel=theirs, number="1", capacity=2), date(2026, 11, 1))
        user = User.objects.create_user("w", password="pw12345!")
        StaffProfile.objects.create(user=user, organization=self.org, role="warden").hostels.set([mine])
        self.client.login(username="w", password="pw12345!")

    def test_qr_is_a_png(self):
        response = self.client.get(reverse("residents:qr", args=[self.student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_qr_of_student_outside_scope_is_404(self):
        self.assertEqual(self.client.get(reverse("residents:qr", args=[self.hidden.pk])).status_code, 404)

    def test_detail_page_shows_the_qr(self):
        page = self.client.get(reverse("residents:detail", args=[self.student.pk]))
        self.assertContains(page, reverse("residents:qr", args=[self.student.pk]))
