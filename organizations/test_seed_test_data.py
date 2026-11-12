import tempfile
from datetime import timedelta
from io import StringIO
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.access import can_manage_student, get_staff, hostels_for, students_for
from attendance.models import ExitPermit, RollCall, RollCallEntry
from attendance.services import leave_states
from mess.models import MealCollection, SpecialPeriod
from mess.services import period_for, window_times
from organizations.models import Organization, StaffProfile
from residents.models import RoomAllocation, Student

PASSWORD = "seed-pass-12345"


def seed(**options):
    options.setdefault("students", 40)
    options.setdefault("days", 7)
    options.setdefault("no_photos", True)
    options.setdefault("password", PASSWORD)
    call_command("seed_test_data", stdout=StringIO(), **options)


class SeedContentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed()
        cls.org = Organization.objects.get(slug="demo")
        cls.today = cls.org.local_today()

    def test_students_and_their_rooms(self):
        students = Student.objects.filter(organization=self.org)
        self.assertEqual(students.count(), 40)
        left = students.filter(status="left")
        self.assertEqual(left.count(), 2)
        for student in left:
            self.assertIsNone(student.current_room)
        waiting = [s for s in students.filter(status="active") if s.current_room is None]
        self.assertGreaterEqual(len(waiting), 1)  # registered but not yet placed
        self.assertTrue(any(s.allocations.count() > 1 for s in students))  # someone has a room history
        self.assertTrue(students.filter(religion="Muslim").exists())

    def test_leave_exists_in_every_state(self):
        states = {p.status_on(self.today) for p in ExitPermit.objects.filter(organization=self.org)}
        self.assertEqual(states, {"upcoming", "on_leave", "overdue", "returned", "cancelled"})

    def test_meal_history_covers_every_past_day_but_not_today(self):
        dates = set(MealCollection.objects.filter(organization=self.org).values_list("date", flat=True))
        self.assertEqual(dates, {self.today - timedelta(days=n) for n in range(1, 8)})

    def test_every_meal_was_served_inside_its_window_and_at_the_right_counter(self):
        tz = ZoneInfo(self.org.timezone)
        checked = 0
        for row in MealCollection.objects.filter(organization=self.org).select_related("student", "meal_type", "counter"):
            period = period_for(row.student, row.date)
            start, end = window_times(row.meal_type, period, row.date)
            served_at = timezone.localtime(row.created_at, tz)
            self.assertEqual(served_at.date(), row.date)
            self.assertTrue(start <= served_at.time() <= end, (row, served_at.time(), start, end))
            categories = {c.pk for c in row.counter.categories.all()}
            self.assertTrue(not categories or row.student.category_id in categories)
            checked += 1
        self.assertGreater(checked, 300)

    def test_nobody_is_served_while_away(self):
        for offset in range(1, 8):
            day = self.today - timedelta(days=offset)
            away = leave_states(Student.objects.filter(organization=self.org).values_list("pk", flat=True), day)
            served = MealCollection.objects.filter(organization=self.org, date=day, student_id__in=list(away))
            self.assertFalse(served.exists(), day)

    def test_ramadan_changes_what_fasting_students_are_served(self):
        period = SpecialPeriod.objects.get(organization=self.org, name="Ramadan (demo)")
        self.assertTrue(period.start_date <= self.today <= period.end_date)
        muslim = MealCollection.objects.filter(organization=self.org, student__religion="Muslim")
        others = MealCollection.objects.filter(organization=self.org).exclude(student__religion="Muslim")
        in_period = muslim.filter(date__gte=period.start_date)
        self.assertTrue(in_period.filter(meal_type__name="Iftaar").exists())
        self.assertFalse(in_period.filter(meal_type__name__in=["Breakfast", "Lunch"]).exists())
        self.assertFalse(others.filter(meal_type__name__in=["Iftaar", "Suhoor"]).exists())
        self.assertTrue(others.filter(meal_type__name="Breakfast").exists())

    def test_iftaar_time_moves_from_day_to_day(self):
        period = SpecialPeriod.objects.get(organization=self.org, name="Ramadan (demo)")
        iftaar = period.windows.get(meal_type__name="Iftaar")
        starts = {o.start_time for o in iftaar.overrides.all()}
        self.assertGreater(len(starts), 10)

    def test_roll_calls_for_both_hostels_every_day(self):
        self.assertEqual(RollCall.objects.filter(organization=self.org).count(), 2 * 7)
        entries = RollCallEntry.objects.filter(roll_call__organization=self.org)
        self.assertTrue(entries.filter(status="present").exists())
        self.assertTrue(entries.filter(status="on_leave", permit__isnull=False).exists())
        overdue = entries.filter(status="absent", days_overdue__gt=0)
        self.assertTrue(overdue.exists())
        self.assertFalse(entries.filter(status="on_leave", days_overdue__gt=0).exists())

    def test_wardens_see_only_their_own_hostel(self):
        a = StaffProfile.objects.get(user__username="demo_warden_a")
        b = StaffProfile.objects.get(user__username="demo_warden_b")
        both = StaffProfile.objects.get(user__username="demo_warden")
        self.assertEqual([h.name for h in hostels_for(a)], ["Boys Hostel A"])
        self.assertEqual([h.name for h in hostels_for(b)], ["Girls Hostel B"])
        self.assertEqual(hostels_for(both).count(), 2)
        girl = RoomAllocation.objects.filter(end_date__isnull=True, room__hostel__name="Girls Hostel B").first().student
        self.assertFalse(can_manage_student(a, girl))
        self.assertTrue(can_manage_student(b, girl))
        self.assertNotIn(girl, students_for(a))

    def test_all_three_levels_can_open_the_main_pages(self):
        pages = ["accounts:home", "residents:list", "mess:counters", "attendance:rollcall_home",
                 "attendance:permits", "reports:index"]
        for username in ("demo_admin", "demo_warden", "demo_warden_a"):
            self.client.logout()
            self.assertTrue(self.client.login(username=username, password=PASSWORD), username)
            for name in pages:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200, (username, name))
        self.client.logout()
        self.client.login(username="demo_admin", password=PASSWORD)
        for name in ("setup:index", "setup:hostels", "setup:meals", "setup:counters", "setup:periods", "setup:staff"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_a_student_page_shows_leave_and_room_history(self):
        permit = ExitPermit.objects.filter(organization=self.org, cancelled=False, returned_on__isnull=True).first()
        self.client.login(username="demo_admin", password=PASSWORD)
        page = self.client.get(reverse("residents:detail", args=[permit.student.pk]))
        self.assertContains(page, permit.student.name)
        self.assertContains(page, "Leave and attendance")


class SeedCommandTests(TestCase):
    def test_second_run_is_refused_until_reset(self):
        seed()
        with self.assertRaises(CommandError):
            seed()
        users_before = set(User.objects.values_list("username", flat=True))
        seed(reset=True)
        self.assertEqual(Student.objects.filter(organization__slug="demo").count(), 40)
        self.assertEqual(set(User.objects.values_list("username", flat=True)), users_before)
        self.assertEqual(MealCollection.objects.exclude(organization__slug="demo").count(), 0)

    def test_same_seed_gives_the_same_people(self):
        seed()
        first = list(Student.objects.order_by("roll_number").values_list("roll_number", "name"))
        seed(reset=True)
        self.assertEqual(first, list(Student.objects.order_by("roll_number").values_list("roll_number", "name")))

    def test_a_real_organisation_can_be_filled_but_never_reset(self):
        real = Organization.objects.create(name="Kalinga University", slug="kalinga", timezone="Asia/Kolkata")
        seed(org="kalinga")
        self.assertEqual(real.students.count(), 40)
        self.assertTrue(StaffProfile.objects.filter(user__username="kalinga_admin", organization=real).exists())
        self.assertFalse(Student.objects.filter(organization__slug="demo").exists())
        with self.assertRaises(CommandError):
            seed(org="kalinga", reset=True)
        self.assertEqual(real.students.count(), 40)  # nothing was wiped

    def test_unknown_organisation_is_refused(self):
        with self.assertRaises(CommandError):
            seed(org="nowhere")

    def test_photos_are_generated_when_asked(self):
        media = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(self.settings(MEDIA_ROOT=media))
        seed(students=5, days=2, no_photos=False)
        students = Student.objects.filter(organization__slug="demo")
        self.assertEqual(students.count(), 5)
        self.assertTrue(all(s.photo and s.photo.name.startswith("student_photos/") for s in students))

    def test_existing_demo_command_still_works_alongside(self):
        call_command("seed_demo", password=PASSWORD, stdout=StringIO())
        seed()
        self.assertTrue(get_staff(User.objects.get(username="demo_admin")))
