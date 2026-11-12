from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.access import can_manage_student, get_staff, hostels_for, students_for
from organizations.models import Category, DietType, Hostel, Organization, Room, StaffProfile
from residents.models import Student
from residents.services import allocate_room


class Fixture(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org A", slug="a")
        self.cat = Category.objects.create(organization=self.org, name="National")
        self.diet = DietType.objects.create(organization=self.org, name="Veg")
        self.h1 = Hostel.objects.create(organization=self.org, name="Block 1", gender="male")
        self.h2 = Hostel.objects.create(organization=self.org, name="Block 2", gender="male")
        self.r1 = Room.objects.create(hostel=self.h1, number="101", capacity=4)
        self.r2 = Room.objects.create(hostel=self.h2, number="201", capacity=4)

        self.s1 = self.student("S1", self.r1)
        self.s2 = self.student("S2", self.r2)
        self.s_new = self.student("S3", None)  # registered, no room yet

        self.admin = self.staff("admin1", StaffProfile.Role.ADMIN)
        self.warden = self.staff("warden1", StaffProfile.Role.WARDEN, hostels=[self.h1])

        # A second organisation that must stay invisible.
        self.other = Organization.objects.create(name="Org B", slug="b")
        oc = Category.objects.create(organization=self.other, name="National")
        od = DietType.objects.create(organization=self.other, name="Veg")
        self.foreign = Student.objects.create(
            organization=self.other, roll_number="X1", name="Foreign", gender="male", category=oc, diet=od
        )

    def student(self, roll, room):
        s = Student.objects.create(
            organization=self.org, roll_number=roll, name=roll, gender="male", category=self.cat, diet=self.diet
        )
        if room:
            allocate_room(s, room, date(2026, 11, 1))
        return s

    def staff(self, username, role, hostels=()):
        user = User.objects.create_user(username, password="pw12345!")
        profile = StaffProfile.objects.create(user=user, organization=self.org, role=role)
        profile.hostels.set(hostels)
        return profile


class AccessTests(Fixture):
    def test_user_without_profile_has_no_access(self):
        user = User.objects.create_user("nobody", password="x")
        self.assertIsNone(get_staff(user))

    def test_inactive_organization_blocks_access(self):
        self.org.is_active = False
        self.org.save()
        self.assertIsNone(get_staff(User.objects.get(username="warden1")))

    def test_admin_sees_all_org_hostels_and_students(self):
        self.assertEqual(set(hostels_for(self.admin)), {self.h1, self.h2})
        self.assertEqual(set(students_for(self.admin)), {self.s1, self.s2, self.s_new})

    def test_warden_sees_own_hostel_and_unallocated_only(self):
        self.assertEqual(set(hostels_for(self.warden)), {self.h1})
        self.assertEqual(set(students_for(self.warden)), {self.s1, self.s_new})
        self.assertFalse(can_manage_student(self.warden, self.s2))

    def test_nobody_sees_other_organization(self):
        for staff in (self.admin, self.warden):
            self.assertNotIn(self.foreign, students_for(staff))

    def test_moved_student_leaves_wardens_scope(self):
        allocate_room(self.s1, self.r2, date(2026, 11, 5))
        self.assertNotIn(self.s1, students_for(self.warden))

    def test_warden_with_no_hostels_sees_only_unallocated(self):
        bare = self.staff("bare", StaffProfile.Role.WARDEN)
        self.assertEqual(set(students_for(bare)), {self.s_new})


class ViewTests(Fixture):
    def test_anonymous_is_sent_to_login(self):
        r = self.client.get(reverse("accounts:home"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r["Location"])

    def test_user_without_profile_gets_403(self):
        User.objects.create_user("nobody", password="pw12345!")
        self.client.login(username="nobody", password="pw12345!")
        self.assertEqual(self.client.get(reverse("accounts:home")).status_code, 403)

    def test_login_then_home(self):
        r = self.client.post(reverse("accounts:login"), {"username": "warden1", "password": "pw12345!"})
        self.assertRedirects(r, reverse("accounts:home"))
        page = self.client.get(reverse("accounts:home"))
        self.assertContains(page, "Block 1")
        self.assertNotContains(page, "Block 2")

    def test_wrong_password_is_rejected(self):
        r = self.client.post(reverse("accounts:login"), {"username": "warden1", "password": "nope"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Wrong username or password")

    def test_logout_needs_post(self):
        self.client.login(username="admin1", password="pw12345!")
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))
        self.assertEqual(self.client.get(reverse("accounts:home")).status_code, 302)

    def test_admin_required_blocks_warden(self):
        from django.http import HttpResponse
        from django.test import RequestFactory
        from django.core.exceptions import PermissionDenied
        from accounts.decorators import admin_required

        @admin_required
        def secret(request):
            return HttpResponse("ok")

        rf = RequestFactory()
        req = rf.get("/x")
        req.user = self.warden.user
        with self.assertRaises(PermissionDenied):
            secret(req)
        req.user = self.admin.user
        self.assertEqual(secret(req).status_code, 200)


class UiTests(Fixture):
    def login(self, name):
        self.client.login(username=name, password="pw12345!")

    def test_pages_use_the_bootstrap_theme(self):
        self.login("admin1")
        page = self.client.get(reverse("accounts:home"))
        self.assertContains(page, "bootstrap@5.3.8")
        self.assertContains(page, "accounts/app.css")
        self.assertContains(page, 'id="theme-toggle"')

    def test_registration_warns_when_no_categories_exist(self):
        empty = Organization.objects.create(name="Empty Org", slug="empty")
        user = User.objects.create_user("warden_empty", password="pw12345!")
        StaffProfile.objects.create(user=user, organization=empty, role=StaffProfile.Role.WARDEN)
        self.login("warden_empty")
        page = self.client.get(reverse("residents:create"))
        self.assertContains(page, "Setup is not finished")
        self.assertContains(page, "no <strong>categories</strong>")
        self.assertContains(page, "Ask an admin to add them")

    def test_registration_has_no_warning_when_setup_is_done(self):
        self.login("warden1")
        page = self.client.get(reverse("residents:create"))
        self.assertNotContains(page, "Setup is not finished")
        self.assertContains(page, "National")

    def test_admin_home_shows_setup_checklist_but_warden_does_not(self):
        self.login("admin1")
        self.assertContains(self.client.get(reverse("accounts:home")), "Setup checklist")
        self.client.logout()
        self.login("warden1")
        self.assertNotContains(self.client.get(reverse("accounts:home")), "Setup checklist")

    def test_ui_filters(self):
        from accounts.templatetags.ui import initials, status_colour

        self.assertEqual(initials("Alice Anand"), "AA")
        self.assertEqual(initials("Bob"), "B")
        self.assertEqual(initials(""), "?")
        self.assertEqual(status_colour("overdue"), "danger")
