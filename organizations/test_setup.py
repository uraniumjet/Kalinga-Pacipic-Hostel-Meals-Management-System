from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from organizations.models import Category, DietType, Hostel, Organization, Room, StaffProfile
from residents.models import Student
from residents.services import allocate_room

PW = "pw12345!Xy"


class SignupTests(TestCase):
    def data(self, **over):
        data = {
            "organization_name": "Sunrise Hostel",
            "timezone": "Asia/Kolkata",
            "username": "owner",
            "full_name": "Asha Rao",
            "password1": "Str0ng-pass-99",
            "password2": "Str0ng-pass-99",
            "starter_data": "on",
        }
        data.update(over)
        return data

    def test_login_page_offers_registration(self):
        self.assertContains(self.client.get(reverse("accounts:login")), reverse("accounts:signup"))

    @override_settings(ALLOW_ORG_SIGNUP=False)
    def test_signup_can_be_switched_off(self):
        self.assertEqual(self.client.get(reverse("accounts:signup")).status_code, 404)
        self.assertNotContains(self.client.get(reverse("accounts:login")), reverse("accounts:signup"))

    def test_signup_creates_organisation_admin_and_starter_data(self):
        response = self.client.post(reverse("accounts:signup"), self.data())
        self.assertRedirects(response, reverse("setup:index"))
        org = Organization.objects.get(name="Sunrise Hostel")
        self.assertEqual(org.timezone, "Asia/Kolkata")
        profile = StaffProfile.objects.get(user__username="owner")
        self.assertEqual(profile.organization, org)
        self.assertEqual(profile.role, StaffProfile.Role.ADMIN)
        self.assertEqual(profile.user.first_name, "Asha")
        self.assertEqual(profile.user.last_name, "Rao")
        self.assertEqual(set(org.categories.values_list("name", flat=True)), {"National", "International"})
        self.assertEqual(org.diet_types.count(), 2)
        # logged in straight away
        self.assertEqual(self.client.get(reverse("accounts:home")).status_code, 200)

    def test_starter_data_is_optional(self):
        data = self.data()
        del data["starter_data"]
        self.client.post(reverse("accounts:signup"), data)
        org = Organization.objects.get(name="Sunrise Hostel")
        self.assertEqual(org.categories.count(), 0)

    def test_same_name_gets_a_different_slug(self):
        self.client.post(reverse("accounts:signup"), self.data())
        self.client.logout()
        self.client.post(reverse("accounts:signup"), self.data(username="owner2"))
        slugs = set(Organization.objects.values_list("slug", flat=True))
        self.assertEqual(len(slugs), 2)

    def test_duplicate_username_and_bad_passwords_are_refused(self):
        User.objects.create_user("owner", password="x")
        page = self.client.post(reverse("accounts:signup"), self.data())
        self.assertContains(page, "already taken")
        self.assertFalse(Organization.objects.exists())
        page = self.client.post(reverse("accounts:signup"), self.data(password2="different"))
        self.assertContains(page, "do not match")
        page = self.client.post(reverse("accounts:signup"), self.data(username="o3", password1="12345678", password2="12345678"))
        self.assertEqual(page.status_code, 200)
        self.assertFalse(User.objects.filter(username="o3").exists())

    def test_invalid_timezone_is_refused(self):
        page = self.client.post(reverse("accounts:signup"), self.data(timezone="Mars/Base"))
        self.assertContains(page, "Select a valid choice")

    def test_signed_in_users_are_sent_home(self):
        self.client.post(reverse("accounts:signup"), self.data())
        self.assertRedirects(self.client.get(reverse("accounts:signup")), reverse("accounts:home"))


class SetupBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org A", slug="a", timezone="Asia/Kolkata")
        self.cat = Category.objects.create(organization=self.org, name="National")
        self.diet = DietType.objects.create(organization=self.org, name="Veg")
        self.h1 = Hostel.objects.create(organization=self.org, name="Block 1", gender="male")
        self.room = Room.objects.create(hostel=self.h1, number="101", capacity=2)
        self.admin = self.staff("admin1", StaffProfile.Role.ADMIN)
        self.warden = self.staff("warden1", StaffProfile.Role.WARDEN, [self.h1])

        self.other = Organization.objects.create(name="Org B", slug="b")
        self.other_cat = Category.objects.create(organization=self.other, name="Foreign")
        self.other_hostel = Hostel.objects.create(organization=self.other, name="Other block", gender="male")
        self.other_room = Room.objects.create(hostel=self.other_hostel, number="1", capacity=2)

    def staff(self, username, role, hostels=()):
        user = User.objects.create_user(username, password=PW)
        profile = StaffProfile.objects.create(user=user, organization=self.org, role=role)
        profile.hostels.set(hostels)
        return profile

    def login(self, name="admin1"):
        self.client.login(username=name, password=PW)

    def student(self, roll="S1", room=None):
        s = Student.objects.create(organization=self.org, roll_number=roll, name=roll, gender="male",
                                   category=self.cat, diet=self.diet)
        if room:
            allocate_room(s, room, date(2026, 11, 1))
        return s


class AccessTests(SetupBase):
    URLS = ["setup:index", "setup:lookups", "setup:hostels", "setup:staff", "setup:staff_new"]

    def test_anonymous_users_are_sent_to_login(self):
        for name in self.URLS:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)

    def test_wardens_cannot_open_setup(self):
        self.login("warden1")
        for name in self.URLS:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_admins_can_open_setup_and_see_the_menu_link(self):
        self.login()
        for name in self.URLS:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertContains(self.client.get(reverse("accounts:home")), reverse("setup:index"))

    def test_wardens_do_not_see_the_setup_link(self):
        self.login("warden1")
        self.assertNotContains(self.client.get(reverse("accounts:home")), reverse("setup:index"))


class OrganisationSettingsTests(SetupBase):
    def test_admin_changes_name_timezone_and_roll_call(self):
        self.login()
        response = self.client.post(reverse("setup:index"), {
            "name": "Renamed", "timezone": "Asia/Dubai", "roll_call_start": "21:00", "roll_call_end": "23:30",
        })
        self.assertRedirects(response, reverse("setup:index"))
        self.org.refresh_from_db()
        self.assertEqual((self.org.name, self.org.timezone), ("Renamed", "Asia/Dubai"))
        self.assertEqual(self.org.roll_call_start.strftime("%H:%M"), "21:00")

    def test_roll_call_must_end_after_it_starts(self):
        self.login()
        page = self.client.post(reverse("setup:index"), {
            "name": "Org A", "timezone": "Asia/Kolkata", "roll_call_start": "23:00", "roll_call_end": "21:00",
        })
        self.assertContains(page, "must end after it starts")
        self.org.refresh_from_db()
        self.assertEqual(self.org.roll_call_start.strftime("%H:%M"), "20:00")

    def test_bad_timezone_is_refused(self):
        self.login()
        page = self.client.post(reverse("setup:index"), {
            "name": "Org A", "timezone": "Nowhere/Land", "roll_call_start": "20:00", "roll_call_end": "23:00",
        })
        self.assertContains(page, "Select a valid choice")


class LookupTests(SetupBase):
    def test_add_category_and_diet(self):
        self.login()
        self.client.post(reverse("setup:lookups"), {"kind": "category", "category-name": "International"})
        self.client.post(reverse("setup:lookups"), {"kind": "diet", "diet-name": "Non-vegetarian"})
        self.assertTrue(Category.objects.filter(organization=self.org, name="International").exists())
        self.assertTrue(DietType.objects.filter(organization=self.org, name="Non-vegetarian").exists())

    def test_names_are_unique_ignoring_case(self):
        self.login()
        page = self.client.post(reverse("setup:lookups"), {"kind": "category", "category-name": "national"})
        self.assertContains(page, "already exists")
        self.assertEqual(Category.objects.filter(organization=self.org).count(), 1)

    def test_same_name_is_fine_in_another_organisation(self):
        self.login()
        self.client.post(reverse("setup:lookups"), {"kind": "category", "category-name": "Foreign"})
        self.assertEqual(Category.objects.filter(name="Foreign").count(), 2)

    def test_rename(self):
        self.login()
        self.client.post(reverse("setup:lookup_edit", args=["category", self.cat.pk]), {"name": "Local"})
        self.cat.refresh_from_db()
        self.assertEqual(self.cat.name, "Local")

    def test_unused_item_can_be_deleted(self):
        self.login()
        spare = Category.objects.create(organization=self.org, name="Spare")
        self.client.post(reverse("setup:lookup_delete", args=["category", spare.pk]))
        self.assertFalse(Category.objects.filter(pk=spare.pk).exists())

    def test_item_in_use_cannot_be_deleted(self):
        self.login()
        self.student()
        response = self.client.post(reverse("setup:lookup_delete", args=["category", self.cat.pk]), follow=True)
        self.assertTrue(Category.objects.filter(pk=self.cat.pk).exists())
        self.assertContains(response, "used by students")

    def test_other_organisations_items_are_out_of_reach(self):
        self.login()
        self.assertEqual(self.client.get(reverse("setup:lookup_edit", args=["category", self.other_cat.pk])).status_code, 404)
        self.client.post(reverse("setup:lookup_delete", args=["category", self.other_cat.pk]))
        self.assertTrue(Category.objects.filter(pk=self.other_cat.pk).exists())

    def test_delete_needs_post(self):
        self.login()
        self.assertEqual(self.client.get(reverse("setup:lookup_delete", args=["category", self.cat.pk])).status_code, 405)

    def test_registration_form_now_offers_the_new_category(self):
        self.login("warden1")
        self.assertContains(self.client.get(reverse("residents:create")), "National")


class HostelTests(SetupBase):
    def test_add_hostel_then_land_on_its_page(self):
        self.login()
        response = self.client.post(reverse("setup:hostels"), {"name": "Girls A", "gender": "female"})
        hostel = Hostel.objects.get(organization=self.org, name="Girls A")
        self.assertRedirects(response, reverse("setup:hostel", args=[hostel.pk]))

    def test_hostel_name_is_unique_ignoring_case(self):
        self.login()
        page = self.client.post(reverse("setup:hostels"), {"name": "block 1", "gender": "male"})
        self.assertContains(page, "already exists")

    def test_add_single_room(self):
        self.login()
        self.client.post(reverse("setup:hostel", args=[self.h1.pk]), {"action": "room", "room-number": "102", "room-capacity": "3"})
        self.assertEqual(Room.objects.get(hostel=self.h1, number="102").capacity, 3)

    def test_duplicate_room_is_refused(self):
        self.login()
        page = self.client.post(reverse("setup:hostel", args=[self.h1.pk]), {"action": "room", "room-number": "101", "room-capacity": "3"})
        self.assertContains(page, "already exists")

    def test_bulk_rooms_skip_existing_numbers(self):
        self.login()
        url = reverse("setup:hostel", args=[self.h1.pk])
        self.client.post(url, {"action": "bulk", "bulk-prefix": "", "bulk-first": "101", "bulk-last": "104", "bulk-capacity": "4"})
        self.assertEqual(self.h1.rooms.count(), 4)
        self.assertEqual(Room.objects.get(hostel=self.h1, number="101").capacity, 2)  # untouched
        self.assertEqual(Room.objects.get(hostel=self.h1, number="104").capacity, 4)

    def test_bulk_rooms_with_prefix(self):
        self.login()
        self.client.post(reverse("setup:hostel", args=[self.h1.pk]),
                         {"action": "bulk", "bulk-prefix": "A-", "bulk-first": "1", "bulk-last": "2", "bulk-capacity": "2"})
        self.assertTrue(Room.objects.filter(hostel=self.h1, number="A-2").exists())

    def test_bulk_rooms_reject_backwards_range(self):
        self.login()
        page = self.client.post(reverse("setup:hostel", args=[self.h1.pk]),
                                {"action": "bulk", "bulk-first": "10", "bulk-last": "5", "bulk-capacity": "2"})
        self.assertContains(page, "must not be smaller")

    def test_room_cannot_shrink_below_its_residents(self):
        self.login()
        s1, s2 = self.student("S1"), self.student("S2")
        allocate_room(s1, self.room, date(2026, 11, 1))
        allocate_room(s2, self.room, date(2026, 11, 1))
        page = self.client.post(reverse("setup:room_edit", args=[self.room.pk]), {"number": "101", "capacity": "1"})
        self.assertContains(page, "at least that many beds")
        self.room.refresh_from_db()
        self.assertEqual(self.room.capacity, 2)

    def test_hostel_gender_cannot_change_while_students_live_there(self):
        self.login()
        self.student("S1", self.room)
        page = self.client.post(reverse("setup:hostel", args=[self.h1.pk]), {"action": "hostel", "hostel-name": "Block 1", "hostel-gender": "female"})
        self.assertContains(page, "cannot be changed")
        self.h1.refresh_from_db()
        self.assertEqual(self.h1.gender, "male")

    def test_empty_room_and_hostel_can_be_deleted(self):
        self.login()
        spare = Room.objects.create(hostel=self.h1, number="999", capacity=1)
        self.client.post(reverse("setup:room_delete", args=[spare.pk]))
        self.assertFalse(Room.objects.filter(pk=spare.pk).exists())
        empty = Hostel.objects.create(organization=self.org, name="Empty", gender="female")
        self.client.post(reverse("setup:hostel_delete", args=[empty.pk]))
        self.assertFalse(Hostel.objects.filter(pk=empty.pk).exists())

    def test_room_with_stay_history_cannot_be_deleted(self):
        self.login()
        self.student("S1", self.room)
        response = self.client.post(reverse("setup:room_delete", args=[self.room.pk]), follow=True)
        self.assertTrue(Room.objects.filter(pk=self.room.pk).exists())
        self.assertContains(response, "stay history")

    def test_other_organisations_hostels_and_rooms_are_out_of_reach(self):
        self.login()
        self.assertEqual(self.client.get(reverse("setup:hostel", args=[self.other_hostel.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("setup:room_edit", args=[self.other_room.pk])).status_code, 404)
        self.client.post(reverse("setup:hostel_delete", args=[self.other_hostel.pk]))
        self.assertTrue(Hostel.objects.filter(pk=self.other_hostel.pk).exists())


class StaffTests(SetupBase):
    def test_admin_creates_a_warden_who_can_sign_in(self):
        self.login()
        response = self.client.post(reverse("setup:staff_new"), {
            "username": "newwarden", "full_name": "Nina Nair", "role": "warden",
            "hostels": [self.h1.pk], "is_active": "on", "password": "Another-Pass-77",
        })
        self.assertRedirects(response, reverse("setup:staff"))
        profile = StaffProfile.objects.get(user__username="newwarden")
        self.assertEqual(profile.organization, self.org)
        self.assertEqual(list(profile.hostels.all()), [self.h1])
        self.client.logout()
        self.assertTrue(self.client.login(username="newwarden", password="Another-Pass-77"))

    def test_username_must_be_free_and_password_strong(self):
        self.login()
        page = self.client.post(reverse("setup:staff_new"), {"username": "warden1", "role": "warden", "is_active": "on", "password": "Another-Pass-77"})
        self.assertContains(page, "already taken")
        page = self.client.post(reverse("setup:staff_new"), {"username": "weak", "role": "warden", "is_active": "on", "password": "12345678"})
        self.assertFalse(User.objects.filter(username="weak").exists())
        self.assertEqual(page.status_code, 200)

    def test_cannot_assign_a_hostel_of_another_organisation(self):
        self.login()
        page = self.client.post(reverse("setup:staff_new"), {
            "username": "sneaky", "role": "warden", "hostels": [self.other_hostel.pk], "is_active": "on", "password": "Another-Pass-77",
        })
        self.assertContains(page, "Select a valid choice")
        self.assertFalse(User.objects.filter(username="sneaky").exists())

    def test_edit_changes_hostels_role_and_password(self):
        self.login()
        h2 = Hostel.objects.create(organization=self.org, name="Block 2", gender="male")
        self.client.post(reverse("setup:staff_edit", args=[self.warden.pk]), {
            "username": "warden1", "full_name": "W One", "role": "warden", "hostels": [h2.pk],
            "is_active": "on", "password": "Fresh-Pass-4242",
        })
        self.warden.refresh_from_db()
        self.assertEqual(list(self.warden.hostels.all()), [h2])
        self.client.logout()
        self.assertTrue(self.client.login(username="warden1", password="Fresh-Pass-4242"))

    def test_blank_password_keeps_the_old_one(self):
        self.login()
        self.client.post(reverse("setup:staff_edit", args=[self.warden.pk]), {
            "username": "warden1", "role": "warden", "hostels": [self.h1.pk], "is_active": "on", "password": "",
        })
        self.client.logout()
        self.assertTrue(self.client.login(username="warden1", password=PW))

    def test_deactivated_warden_cannot_sign_in(self):
        self.login()
        self.client.post(reverse("setup:staff_edit", args=[self.warden.pk]), {
            "username": "warden1", "role": "warden", "hostels": [self.h1.pk], "password": "",
        })
        self.client.logout()
        self.assertFalse(self.client.login(username="warden1", password=PW))

    def test_admin_cannot_lock_themselves_out(self):
        self.login()
        page = self.client.post(reverse("setup:staff_edit", args=[self.admin.pk]), {
            "username": "admin1", "role": "warden", "is_active": "on", "password": "",
        })
        self.assertContains(page, "cannot remove your own admin access")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, "admin")
        page = self.client.post(reverse("setup:staff_edit", args=[self.admin.pk]), {
            "username": "admin1", "role": "admin", "password": "",
        })
        self.assertContains(page, "cannot remove your own admin access")

    def test_other_organisations_staff_are_out_of_reach(self):
        self.login()
        user = User.objects.create_user("foreigner", password=PW)
        foreign = StaffProfile.objects.create(user=user, organization=self.other, role="admin")
        self.assertEqual(self.client.get(reverse("setup:staff_edit", args=[foreign.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("setup:staff")), "foreigner")
