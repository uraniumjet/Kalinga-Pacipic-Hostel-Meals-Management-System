from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from mess.models import Counter, MealCollection, MealType, MealWindow
from organizations.models import Category, DietType, Organization, StaffProfile
from residents.models import Student

IST = ZoneInfo("Asia/Kolkata")


def at(h, m=0, day=12):
    return datetime(2026, 11, day, h, m, tzinfo=IST)


def now_is(moment):
    return patch("django.utils.timezone.now", return_value=moment)


class CounterTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org A", slug="a", timezone="Asia/Kolkata")
        self.intl = Category.objects.create(organization=self.org, name="International")
        self.natl = Category.objects.create(organization=self.org, name="National")
        self.diet = DietType.objects.create(organization=self.org, name="Veg")
        self.breakfast = MealType.objects.create(organization=self.org, name="Breakfast", sort_order=1)
        MealWindow.objects.create(meal_type=self.breakfast, start_time=time(7, 30), end_time=time(9, 0))
        self.counter = Counter.objects.create(organization=self.org, name="Main")
        self.intl_counter = Counter.objects.create(organization=self.org, name="Intl")
        self.intl_counter.categories.add(self.intl)

        self.alice = self.student("R1", "Alice Anand")
        self.alan = self.student("R2", "Alan Anand")

        user = User.objects.create_user("warden", password="pw12345!")
        StaffProfile.objects.create(user=user, organization=self.org, role="warden")
        self.warden = user
        self.client.login(username="warden", password="pw12345!")

        self.other = Organization.objects.create(name="Org B", slug="b")
        oc = Category.objects.create(organization=self.other, name="National")
        od = DietType.objects.create(organization=self.other, name="Veg")
        self.foreign_counter = Counter.objects.create(organization=self.other, name="Foreign counter")
        self.foreign = Student.objects.create(
            organization=self.other, roll_number="R1", name="Foreign Fred", gender="male", category=oc, diet=od
        )

    def student(self, roll, name, category=None, status="active"):
        return Student.objects.create(
            organization=self.org, roll_number=roll, name=name, gender="male",
            category=category or self.intl, diet=self.diet, status=status,
        )

    def url(self, counter=None):
        return reverse("mess:counter", args=[(counter or self.counter).pk])

    def serve(self, student, counter=None):
        return self.client.post(self.url(counter), {"student": student.pk}, follow=True)

    # --- access ---
    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_counter_list_shows_only_own_organization(self):
        page = self.client.get(reverse("mess:counters"))
        self.assertContains(page, "Main")
        self.assertNotContains(page, "Foreign counter")

    def test_counter_of_another_organization_is_404(self):
        self.assertEqual(self.client.get(self.url(self.foreign_counter)).status_code, 404)

    # --- finding students ---
    def test_find_by_roll_number(self):
        with now_is(at(8)):
            page = self.client.get(self.url(), {"q": "r1"})
        self.assertContains(page, "Alice Anand")
        self.assertContains(page, "Serve Breakfast")

    def test_find_by_scanned_qr_token(self):
        with now_is(at(8)):
            page = self.client.get(self.url(), {"q": str(self.alice.qr_token)})
        self.assertContains(page, "Alice Anand")
        self.assertNotContains(page, "Alan Anand")

    def test_find_by_part_of_name_lists_all_matches(self):
        with now_is(at(8)):
            page = self.client.get(self.url(), {"q": "anand"})
        self.assertContains(page, "Alice Anand")
        self.assertContains(page, "Alan Anand")

    def test_students_of_other_organizations_are_never_found(self):
        with now_is(at(8)):
            page = self.client.get(self.url(), {"q": str(self.foreign.qr_token)})
            by_name = self.client.get(self.url(), {"q": "Fred"})
        self.assertNotContains(page, "Foreign Fred")
        self.assertNotContains(by_name, "Foreign Fred")

    def test_unknown_student_shows_message(self):
        page = self.client.get(self.url(), {"q": "nobody"})
        self.assertContains(page, "No student found")

    # --- serving ---
    def test_serve_records_the_collection(self):
        with now_is(at(8)):
            page = self.serve(self.alice)
        self.assertContains(page, "Breakfast served to Alice Anand")
        collection = MealCollection.objects.get()
        self.assertEqual(collection.student, self.alice)
        self.assertEqual(collection.counter, self.counter)
        self.assertEqual(collection.recorded_by, self.warden)
        self.assertIsNone(collection.collected_by)
        self.assertEqual(str(collection.date), "2026-11-12")

    def test_second_serve_is_refused(self):
        with now_is(at(8)):
            self.serve(self.alice)
        with now_is(at(8, 20)):
            page = self.serve(self.alice)
        self.assertContains(page, "already collected")
        self.assertEqual(MealCollection.objects.count(), 1)

    def test_card_shows_the_reason_when_already_collected(self):
        with now_is(at(8)):
            self.serve(self.alice)
            page = self.client.get(self.url(), {"q": "R1"})
        self.assertContains(page, "already collected")
        self.assertNotContains(page, "Serve Breakfast")

    def test_outside_meal_time_is_refused(self):
        with now_is(at(11)):
            card = self.client.get(self.url(), {"q": "R1"})
            posted = self.serve(self.alice)
        self.assertContains(card, "No meal is being served")
        self.assertNotContains(card, "Serve Breakfast")
        self.assertContains(posted, "No meal is being served")
        self.assertFalse(MealCollection.objects.exists())

    def test_wrong_counter_is_refused(self):
        national = self.student("R3", "Nina National", category=self.natl)
        with now_is(at(8)):
            page = self.serve(national, self.intl_counter)
        self.assertContains(page, "is not served at the Intl counter")
        self.assertFalse(MealCollection.objects.exists())

    def test_inactive_student_is_refused(self):
        gone = self.student("R4", "Gone Gary", status="left")
        with now_is(at(8)):
            page = self.serve(gone)
        self.assertContains(page, "not active")
        self.assertFalse(MealCollection.objects.exists())

    def test_cannot_serve_a_student_of_another_organization(self):
        with now_is(at(8)):
            response = self.client.post(self.url(), {"student": self.foreign.pk})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(MealCollection.objects.exists())

    def test_bad_student_id_is_404_not_a_crash(self):
        self.assertEqual(self.client.post(self.url(), {"student": "abc"}).status_code, 404)
        self.assertEqual(self.client.post(self.url(), {}).status_code, 404)

    def test_recent_list_and_count(self):
        with now_is(at(8)):
            self.serve(self.alice)
            page = self.client.get(self.url())
        self.assertContains(page, "1 served today")
        self.assertContains(page, "Alice Anand")
        self.assertContains(page, "08:00")
