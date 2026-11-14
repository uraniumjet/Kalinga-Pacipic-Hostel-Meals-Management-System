from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from attendance.models import ExitPermit
from organizations.models import Category, DietType, Hostel, Organization, Room, StaffProfile
from residents.models import RoomAllocation, Student
from residents.services import allocate_room, mark_left, readmit

PW = "pw12345!Xy"


class LifecycleBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org A", slug="a", timezone="Asia/Kolkata")
        self.today = self.org.local_today()
        self.cat = Category.objects.create(organization=self.org, name="National")
        self.diet = DietType.objects.create(organization=self.org, name="Veg")
        self.boys1 = Hostel.objects.create(organization=self.org, name="Boys 1", gender="male")
        self.boys2 = Hostel.objects.create(organization=self.org, name="Boys 2", gender="male")
        self.girls = Hostel.objects.create(organization=self.org, name="Girls 1", gender="female")
        self.b1r1 = Room.objects.create(hostel=self.boys1, number="101", capacity=2)
        self.b1r2 = Room.objects.create(hostel=self.boys1, number="102", capacity=1)
        self.b2r1 = Room.objects.create(hostel=self.boys2, number="201", capacity=2)
        self.g1r1 = Room.objects.create(hostel=self.girls, number="301", capacity=2)
        self.admin = self.staff("admin1", "admin")
        self.warden = self.staff("warden1", "warden", [self.boys1])
        self.other = Organization.objects.create(name="Org B", slug="b")

    def staff(self, username, role, hostels=()):
        user = User.objects.create_user(username, password=PW)
        profile = StaffProfile.objects.create(user=user, organization=self.org, role=role)
        profile.hostels.set(hostels)
        return profile

    def login(self, name):
        self.client.login(username=name, password=PW)

    def student(self, roll, room=None, gender="male", since=None):
        s = Student.objects.create(organization=self.org, roll_number=roll, name=f"Student {roll}", gender=gender,
                                   category=self.cat, diet=self.diet)
        if room:
            allocate_room(s, room, since or self.today - timedelta(days=10))
        return s

    def permit(self, student, start, end, **extra):
        return ExitPermit.objects.create(organization=self.org, student=student, start_date=start, end_date=end, **extra)


class MoveServiceTests(LifecycleBase):
    def test_move_ends_the_old_stay_and_starts_a_new_one(self):
        s = self.student("S1", self.b1r1)
        allocate_room(s, self.b2r1, self.today)
        self.assertEqual(s.current_room, self.b2r1)
        old = RoomAllocation.objects.get(student=s, room=self.b1r1)
        self.assertEqual(old.end_date, self.today)
        self.assertEqual(s.allocations.count(), 2)

    def test_move_cannot_be_dated_before_the_current_stay_began(self):
        s = self.student("S1", self.b1r1, since=self.today - timedelta(days=2))
        with self.assertRaises(ValidationError):
            allocate_room(s, self.b2r1, self.today - timedelta(days=5))
        self.assertEqual(s.current_room, self.b1r1)


class MarkLeftServiceTests(LifecycleBase):
    def test_leaving_frees_the_bed_and_keeps_history(self):
        s = self.student("S1", self.b1r1)
        mark_left(s, self.today)
        s.refresh_from_db()
        self.assertEqual(s.status, "left")
        self.assertIsNone(s.current_room)
        self.assertEqual(self.b1r1.free_beds, 2)
        self.assertEqual(s.allocations.get().end_date, self.today)

    def test_student_without_a_room_can_leave(self):
        s = self.student("S1")
        mark_left(s, self.today)
        s.refresh_from_db()
        self.assertEqual(s.status, "left")

    def test_permits_that_have_not_started_are_cancelled(self):
        s = self.student("S1", self.b1r1)
        future = self.permit(s, self.today + timedelta(days=3), self.today + timedelta(days=5))
        old = self.permit(s, self.today - timedelta(days=9), self.today - timedelta(days=7), returned_on=self.today - timedelta(days=7))
        mark_left(s, self.today)
        future.refresh_from_db()
        old.refresh_from_db()
        self.assertTrue(future.cancelled)
        self.assertFalse(old.cancelled)

    def test_cannot_leave_while_on_leave_or_overdue(self):
        on_leave = self.student("S1", self.b1r1)
        self.permit(on_leave, self.today - timedelta(days=1), self.today + timedelta(days=2))
        overdue = self.student("S2", self.b1r1)
        self.permit(overdue, self.today - timedelta(days=6), self.today - timedelta(days=3))
        for s in (on_leave, overdue):
            with self.assertRaises(ValidationError):
                mark_left(s, self.today)
            s.refresh_from_db()
            self.assertEqual(s.status, "active")
            self.assertIsNotNone(s.current_room)

    def test_leaving_twice_and_backdating_before_move_in_are_refused(self):
        s = self.student("S1", self.b1r1, since=self.today - timedelta(days=3))
        with self.assertRaises(ValidationError):
            mark_left(s, self.today - timedelta(days=5))
        mark_left(s, self.today)
        with self.assertRaises(ValidationError):
            mark_left(s, self.today)


class ReadmitServiceTests(LifecycleBase):
    def test_readmit_with_and_without_a_room(self):
        s = self.student("S1", self.b1r1)
        mark_left(s, self.today)
        readmit(s, self.today, self.b2r1)
        s.refresh_from_db()
        self.assertEqual((s.status, s.current_room), ("active", self.b2r1))
        mark_left(s, self.today)
        readmit(s, self.today)
        s.refresh_from_db()
        self.assertEqual(s.status, "active")
        self.assertIsNone(s.current_room)

    def test_readmit_into_a_full_room_changes_nothing(self):
        s = self.student("S1", self.b1r1)
        mark_left(s, self.today)
        self.student("S2", self.b1r2)
        with self.assertRaises(ValidationError):
            readmit(s, self.today, self.b1r2)
        s.refresh_from_db()
        self.assertEqual(s.status, "left")

    def test_only_a_student_who_left_can_be_readmitted(self):
        with self.assertRaises(ValidationError):
            readmit(self.student("S1"), self.today)


class MoveViewTests(LifecycleBase):
    def test_room_choices_are_free_rooms_of_the_right_gender_in_scope(self):
        s = self.student("S1", self.b1r1)
        self.student("S2", self.b1r2)  # fills room 102
        self.login("warden1")
        page = self.client.get(reverse("residents:move", args=[s.pk]))
        self.assertEqual(page.status_code, 200)
        rooms = list(page.context["form"].fields["room"].queryset)
        self.assertEqual(rooms, [])  # 101 is where he lives, 102 is full, other hostels are not the warden's
        self.client.logout()
        self.login("admin1")
        rooms = list(self.client.get(reverse("residents:move", args=[s.pk])).context["form"].fields["room"].queryset)
        self.assertEqual(rooms, [self.b2r1])  # not the girls' hostel, not his own room, not the full room

    def test_warden_moves_a_student_within_scope(self):
        s = self.student("S1", self.b1r1)
        self.login("admin1")
        response = self.client.post(reverse("residents:move", args=[s.pk]), {"room": self.b2r1.pk, "date": self.today.isoformat()})
        self.assertRedirects(response, reverse("residents:detail", args=[s.pk]))
        self.assertEqual(s.current_room, self.b2r1)

    def test_future_and_too_early_dates_are_refused(self):
        s = self.student("S1", self.b1r1, since=self.today - timedelta(days=2))
        self.login("admin1")
        url = reverse("residents:move", args=[s.pk])
        page = self.client.post(url, {"room": self.b2r1.pk, "date": (self.today + timedelta(days=1)).isoformat()})
        self.assertContains(page, "cannot be in the future")
        page = self.client.post(url, {"room": self.b2r1.pk, "date": (self.today - timedelta(days=9)).isoformat()})
        self.assertContains(page, "before the student moved into")
        self.assertEqual(s.current_room, self.b1r1)

    def test_a_warden_cannot_touch_students_of_other_hostels(self):
        s = self.student("S1", self.b2r1)
        self.login("warden1")
        for name in ("residents:move", "residents:leave"):
            self.assertEqual(self.client.get(reverse(name, args=[s.pk])).status_code, 404, name)

    def test_buttons_follow_the_students_status(self):
        s = self.student("S1", self.b1r1)
        self.login("warden1")
        page = self.client.get(reverse("residents:detail", args=[s.pk]))
        self.assertContains(page, reverse("residents:move", args=[s.pk]))
        self.assertContains(page, reverse("residents:leave", args=[s.pk]))
        self.assertNotContains(page, reverse("residents:readmit", args=[s.pk]))


class LeaveViewTests(LifecycleBase):
    def test_confirm_page_then_leave(self):
        s = self.student("S1", self.b1r1)
        self.login("warden1")
        url = reverse("residents:leave", args=[s.pk])
        self.assertContains(self.client.get(url), "Mark as left")
        response = self.client.post(url, {"date": self.today.isoformat()}, follow=True)
        self.assertContains(response, "marked as left")
        s.refresh_from_db()
        self.assertEqual(s.status, "left")

    def test_the_reason_is_shown_when_the_student_is_away(self):
        s = self.student("S1", self.b1r1)
        self.permit(s, self.today - timedelta(days=1), self.today + timedelta(days=2))
        self.login("warden1")
        page = self.client.post(reverse("residents:leave", args=[s.pk]), {"date": self.today.isoformat()})
        self.assertContains(page, "Mark the student back from leave first")
        s.refresh_from_db()
        self.assertEqual(s.status, "active")

    def test_actions_on_a_student_who_already_left_redirect(self):
        s = self.student("S1", self.b1r1)
        mark_left(s, self.today)
        self.login("admin1")
        for name in ("residents:move", "residents:leave"):
            response = self.client.get(reverse(name, args=[s.pk]), follow=True)
            self.assertContains(response, "has left the hostel")


class ReadmitViewTests(LifecycleBase):
    def test_admin_readmits_into_a_room(self):
        s = self.student("S1", self.b1r1)
        mark_left(s, self.today)
        self.login("admin1")
        page = self.client.get(reverse("residents:detail", args=[s.pk]))
        self.assertContains(page, reverse("residents:readmit", args=[s.pk]))
        response = self.client.post(reverse("residents:readmit", args=[s.pk]),
                                    {"room": self.b2r1.pk, "date": self.today.isoformat()})
        self.assertRedirects(response, reverse("residents:detail", args=[s.pk]))
        s.refresh_from_db()
        self.assertEqual((s.status, s.current_room), ("active", self.b2r1))

    def test_wardens_cannot_readmit(self):
        s = self.student("S1", self.b1r1)
        mark_left(s, self.today)
        self.login("warden1")
        self.assertEqual(self.client.get(reverse("residents:readmit", args=[s.pk])).status_code, 403)

    def test_readmit_of_another_organisations_student_is_404(self):
        cat = Category.objects.create(organization=self.other, name="C")
        diet = DietType.objects.create(organization=self.other, name="D")
        foreign = Student.objects.create(organization=self.other, roll_number="X", name="X", gender="male",
                                         category=cat, diet=diet, status="left")
        self.login("admin1")
        self.assertEqual(self.client.get(reverse("residents:readmit", args=[foreign.pk])).status_code, 404)


class CardTests(LifecycleBase):
    def test_cards_show_name_roll_room_and_qr_for_students_in_scope(self):
        mine = self.student("S1", self.b1r1)
        theirs = self.student("S2", self.b2r1)
        self.login("warden1")
        page = self.client.get(reverse("residents:cards"))
        self.assertContains(page, mine.name)
        self.assertContains(page, "Roll no. S1")
        self.assertContains(page, reverse("residents:qr", args=[mine.pk]))
        self.assertContains(page, "Org A")
        self.assertNotContains(page, theirs.name)

    def test_filters_by_hostel_search_and_ids(self):
        a = self.student("S1", self.b1r1)
        b = self.student("S2", self.b2r1)
        self.login("admin1")
        only_b2 = self.client.get(reverse("residents:cards"), {"hostel": self.boys2.pk})
        self.assertContains(only_b2, b.name)
        self.assertNotContains(only_b2, a.name)
        by_id = self.client.get(reverse("residents:cards"), {"ids": str(a.pk)})
        self.assertContains(by_id, a.name)
        self.assertNotContains(by_id, b.name)
        by_search = self.client.get(reverse("residents:cards"), {"q": "S2"})
        self.assertContains(by_search, b.name)
        self.assertNotContains(by_search, a.name)

    def test_a_hostel_the_warden_does_not_have_is_ignored(self):
        self.student("S2", self.b2r1)
        self.login("warden1")
        page = self.client.get(reverse("residents:cards"), {"hostel": self.boys2.pk})
        self.assertNotContains(page, "Student S2")

    def test_students_who_left_and_other_organisations_are_not_printed(self):
        gone = self.student("S1", self.b1r1)
        mark_left(gone, self.today)
        cat = Category.objects.create(organization=self.other, name="C")
        diet = DietType.objects.create(organization=self.other, name="D")
        Student.objects.create(organization=self.other, roll_number="X", name="Foreign Kid", gender="male", category=cat, diet=diet)
        self.login("admin1")
        page = self.client.get(reverse("residents:cards"))
        self.assertNotContains(page, gone.name)
        self.assertNotContains(page, "Foreign Kid")
        self.assertContains(page, "No students to print")

    def test_anonymous_visitors_are_sent_to_login(self):
        self.assertEqual(self.client.get(reverse("residents:cards")).status_code, 302)

    def test_the_student_page_and_list_link_to_the_cards(self):
        s = self.student("S1", self.b1r1)
        self.login("admin1")
        self.assertContains(self.client.get(reverse("residents:detail", args=[s.pk])), f"{reverse('residents:cards')}?ids={s.pk}")
        self.assertContains(self.client.get(reverse("residents:list")), reverse("residents:cards"))


class DateHelperSanityTests(TestCase):
    def test_dates_are_plain_dates(self):
        self.assertIsInstance(date.today(), date)
