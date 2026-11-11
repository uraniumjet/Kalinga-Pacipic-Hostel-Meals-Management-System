from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from attendance.models import ExitPermit, RollCall, RollCallEntry
from attendance.services import (
    cancel_permit, grant_permit, hostel_sheet, leave_states, record_return, roll_call_is_open, take_roll_call,
)
from organizations.models import Category, DietType, Hostel, Organization, Room, StaffProfile
from residents.models import Student
from residents.services import allocate_room

IST = ZoneInfo("Asia/Kolkata")


def D(day):
    return date(2026, 11, day)


def at(h, m=0, day=12):
    return datetime(2026, 11, day, h, m, tzinfo=IST)


def now_is(moment):
    return patch("django.utils.timezone.now", return_value=moment)


class Fixture(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org A", slug="a", timezone="Asia/Kolkata")
        self.cat = Category.objects.create(organization=self.org, name="National")
        self.diet = DietType.objects.create(organization=self.org, name="Veg")
        self.h1 = Hostel.objects.create(organization=self.org, name="Boys 1", gender="male")
        self.h2 = Hostel.objects.create(organization=self.org, name="Boys 2", gender="male")
        self.room1 = Room.objects.create(hostel=self.h1, number="101", capacity=4)
        self.room2 = Room.objects.create(hostel=self.h2, number="201", capacity=4)
        self.alice = self.student("R1", "Alice", self.room1)
        self.bob = self.student("R2", "Bob", self.room1)
        self.cara = self.student("R3", "Cara", self.room1)
        self.dan = self.student("R4", "Dan", self.room2)

        warden = User.objects.create_user("warden", password="pw12345!")
        StaffProfile.objects.create(user=warden, organization=self.org, role="warden").hostels.set([self.h1])
        self.warden = warden
        admin = User.objects.create_user("admin", password="pw12345!")
        StaffProfile.objects.create(user=admin, organization=self.org, role="admin")

    def student(self, roll, name, room=None):
        s = Student.objects.create(
            organization=self.org, roll_number=roll, name=name, gender="male", category=self.cat, diet=self.diet
        )
        if room:
            allocate_room(s, room, date(2026, 11, 1))
        return s

    def permit(self, student, start, end, **kwargs):
        return ExitPermit.objects.create(
            organization=self.org, student=student, start_date=D(start), end_date=D(end), **kwargs
        )


class PermitDateTests(Fixture):
    def test_leave_covers_every_night_then_overdue(self):
        p = self.permit(self.alice, 10, 12)
        self.assertIsNone(p.state_on(D(9)))
        for day in (10, 11, 12):
            self.assertEqual(p.state_on(D(day)), ExitPermit.ON_LEAVE)
        self.assertEqual(p.state_on(D(13)), ExitPermit.OVERDUE)
        self.assertEqual(p.days_overdue_on(D(14)), 2)
        self.assertEqual(p.absent_from, D(13))
        self.assertEqual(p.days_until_absent(D(10)), 3)

    def test_early_return_counts_as_present_that_night(self):
        p = self.permit(self.alice, 10, 12, returned_on=D(11))
        self.assertEqual(p.state_on(D(10)), ExitPermit.ON_LEAVE)
        for day in (11, 12, 13):
            self.assertIsNone(p.state_on(D(day)))

    def test_late_return_is_overdue_until_the_return_night(self):
        p = self.permit(self.alice, 10, 12, returned_on=D(14))
        self.assertEqual(p.state_on(D(13)), ExitPermit.OVERDUE)
        self.assertIsNone(p.state_on(D(14)))

    def test_cancelled_permit_never_counts(self):
        p = self.permit(self.alice, 10, 12, cancelled=True)
        self.assertIsNone(p.state_on(D(11)))
        self.assertIsNone(p.state_on(D(14)))

    def test_describe(self):
        p = self.permit(self.alice, 10, 12)
        self.assertEqual(p.describe(D(11)), "On leave until 12 Nov; marked absent from 13 Nov (in 2 days)")
        self.assertIn("in 1 day)", p.describe(D(12)))
        self.assertIn("Overdue by 2 days", p.describe(D(14)))
        self.assertIn("Upcoming", p.describe(D(9)))
        p.returned_on = D(14)
        self.assertEqual(p.describe(D(15)), "Returned 14 Nov")

    def test_leave_states_one_query_and_priorities(self):
        self.permit(self.alice, 11, 14)  # on leave on the 12th
        self.permit(self.bob, 8, 10)  # overdue on the 12th
        with self.assertNumQueries(1):
            states = leave_states([self.alice.pk, self.bob.pk, self.cara.pk], D(12))
        self.assertEqual(states[self.alice.pk].state, ExitPermit.ON_LEAVE)
        self.assertEqual(states[self.bob.pk].state, ExitPermit.OVERDUE)
        self.assertEqual(states[self.bob.pk].days_overdue, 2)
        self.assertNotIn(self.cara.pk, states)


class PermitRuleTests(Fixture):
    def grant(self, student, start, end, **kwargs):
        return grant_permit(student, D(start), D(end), today=D(12), **kwargs)

    def test_grant_records_details(self):
        p = self.grant(self.alice, 12, 15, reason="Family", granted_by=self.warden, destination="Pune")
        self.assertEqual((p.reason, p.destination, p.granted_by), ("Family", "Pune", self.warden))
        self.assertEqual(p.organization, self.org)

    def test_end_before_start_is_refused(self):
        with self.assertRaises(ValidationError):
            self.grant(self.alice, 14, 13)

    def test_permit_ending_in_the_past_is_refused(self):
        with self.assertRaises(ValidationError):
            self.grant(self.alice, 8, 10)

    def test_inactive_student_is_refused(self):
        self.alice.status = "left"
        self.alice.save()
        with self.assertRaises(ValidationError):
            self.grant(self.alice, 12, 14)

    def test_overlapping_permit_is_refused_but_back_to_back_is_fine(self):
        self.grant(self.alice, 12, 15)
        with self.assertRaises(ValidationError):
            self.grant(self.alice, 14, 16)
        self.grant(self.alice, 16, 18)

    def test_overdue_permit_must_be_closed_first(self):
        old = self.permit(self.alice, 8, 10)
        with self.assertRaises(ValidationError) as ctx:
            self.grant(self.alice, 12, 14)
        self.assertIn("Record the return", str(ctx.exception))
        record_return(old, on_date=D(11), today=D(12))
        self.grant(self.alice, 12, 14)

    def test_record_return(self):
        p = self.permit(self.alice, 10, 15)
        record_return(p, today=D(12))
        self.assertEqual(p.returned_on, D(12))
        with self.assertRaises(ValidationError):
            record_return(p, today=D(12))  # twice

    def test_return_before_start_or_in_future_is_refused(self):
        p = self.permit(self.alice, 10, 15)
        with self.assertRaises(ValidationError):
            record_return(p, on_date=D(9), today=D(12))
        with self.assertRaises(ValidationError):
            record_return(p, on_date=D(13), today=D(12))

    def test_cancel_only_before_start(self):
        future = self.permit(self.alice, 15, 17)
        cancel_permit(future, today=D(12))
        self.assertTrue(future.cancelled)
        started = self.permit(self.bob, 12, 14)
        with self.assertRaises(ValidationError):
            cancel_permit(started, today=D(12))


class RollCallServiceTests(Fixture):
    def test_roll_call_is_night_only(self):
        self.assertFalse(roll_call_is_open(self.org, at(12)))
        self.assertTrue(roll_call_is_open(self.org, at(21)))
        with self.assertRaises(ValidationError) as ctx:
            take_roll_call(self.h1, set(), self.warden, now=at(12))
        self.assertIn("20:00", str(ctx.exception))
        self.assertFalse(RollCall.objects.exists())

    def test_sheet_lists_only_this_hostel(self):
        names = [row.student.name for row in hostel_sheet(self.h1, D(12))]
        self.assertEqual(names, ["Alice", "Bob", "Cara"])

    def test_ticked_students_are_absent_everyone_else_present(self):
        roll_call = take_roll_call(self.h1, {self.bob.pk}, self.warden, now=at(21))
        statuses = {e.student.name: e.status for e in roll_call.entries.all()}
        self.assertEqual(statuses, {"Alice": "present", "Bob": "absent", "Cara": "present"})
        self.assertEqual(roll_call.date, D(12))
        self.assertEqual(roll_call.taken_by, self.warden)

    def test_students_on_leave_and_overdue_are_recorded_by_the_permit(self):
        leave = self.permit(self.alice, 11, 13)
        overdue = self.permit(self.bob, 8, 10)
        roll_call = take_roll_call(self.h1, {self.cara.pk}, self.warden, now=at(21))
        entries = {e.student.name: e for e in roll_call.entries.select_related("permit")}
        self.assertEqual(entries["Alice"].status, "on_leave")
        self.assertEqual(entries["Alice"].permit, leave)
        self.assertEqual(entries["Bob"].status, "absent")
        self.assertEqual(entries["Bob"].permit, overdue)
        self.assertEqual(entries["Bob"].days_overdue, 2)
        self.assertEqual(entries["Cara"].status, "absent")
        self.assertIsNone(entries["Cara"].permit)
        self.assertEqual(entries["Cara"].days_overdue, 0)

    def test_ticking_a_student_on_leave_does_not_change_the_record(self):
        self.permit(self.alice, 11, 13)
        roll_call = take_roll_call(self.h1, {self.alice.pk}, self.warden, now=at(21))
        self.assertEqual(roll_call.entries.get(student=self.alice).status, "on_leave")

    def test_student_from_another_hostel_cannot_be_ticked(self):
        with self.assertRaises(ValidationError):
            take_roll_call(self.h1, {self.dan.pk}, self.warden, now=at(21))
        self.assertFalse(RollCall.objects.exists())

    def test_resubmitting_the_same_night_corrects_the_record(self):
        take_roll_call(self.h1, {self.bob.pk}, self.warden, now=at(21))
        take_roll_call(self.h1, set(), self.warden, now=at(22))
        self.assertEqual(RollCall.objects.count(), 1)
        self.assertEqual(RollCallEntry.objects.count(), 3)
        self.assertEqual(RollCallEntry.objects.get(student=self.bob).status, "present")

    def test_returned_student_is_present_that_night(self):
        p = self.permit(self.alice, 8, 10)
        record_return(p, on_date=D(12), today=D(12))
        roll_call = take_roll_call(self.h1, set(), self.warden, now=at(21))
        self.assertEqual(roll_call.entries.get(student=self.alice).status, "present")


class PermitViewTests(Fixture):
    def setUp(self):
        super().setUp()
        self.client.login(username="warden", password="pw12345!")

    def create(self, **overrides):
        data = {"roll_number": "R1", "start_date": "2026-11-12", "end_date": "2026-11-15",
                "destination": "Pune", "reason": "Family"}
        data.update(overrides)
        with now_is(at(10)):
            return self.client.post(reverse("attendance:permit_create"), data)

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        for name in ("attendance:permits", "attendance:permit_create", "attendance:rollcall_home"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("accounts:login"), response["Location"])

    def test_warden_gives_permit_alone(self):
        response = self.create()
        self.assertRedirects(response, reverse("attendance:permits"))
        permit = ExitPermit.objects.get()
        self.assertEqual((permit.student, permit.granted_by, permit.destination), (self.alice, self.warden, "Pune"))

    def test_student_of_another_hostel_is_not_found(self):
        response = self.create(roll_number="R4")
        self.assertContains(response, "No student with this roll number")
        self.assertFalse(ExitPermit.objects.exists())

    def test_rule_errors_are_shown_on_the_form(self):
        response = self.create(end_date="2026-11-10", start_date="2026-11-11")
        self.assertContains(response, "cannot be before")
        self.assertFalse(ExitPermit.objects.exists())

    def test_list_shows_countdown_to_absence(self):
        self.permit(self.alice, 12, 15)
        with now_is(at(10)):
            page = self.client.get(reverse("attendance:permits"))
        self.assertContains(page, "On leave until 15 Nov; marked absent from 16 Nov (in 4 days)")

    def test_return_and_cancel_actions(self):
        p = self.permit(self.alice, 10, 15)
        future = self.permit(self.bob, 20, 22)
        with now_is(at(10)):
            self.assertEqual(self.client.get(reverse("attendance:permit_return", args=[p.pk])).status_code, 405)
            self.client.post(reverse("attendance:permit_return", args=[p.pk]))
            self.client.post(reverse("attendance:permit_cancel", args=[future.pk]))
        p.refresh_from_db()
        future.refresh_from_db()
        self.assertEqual(p.returned_on, D(12))
        self.assertTrue(future.cancelled)

    def test_permit_of_a_student_outside_scope_is_404(self):
        hidden = self.permit(self.dan, 10, 15)
        self.assertEqual(self.client.post(reverse("attendance:permit_return", args=[hidden.pk])).status_code, 404)

    def test_student_page_and_list_show_the_leave(self):
        self.permit(self.alice, 12, 15)
        with now_is(at(10)):
            detail = self.client.get(reverse("residents:detail", args=[self.alice.pk]))
            listing = self.client.get(reverse("residents:list"))
        self.assertContains(detail, "On leave until 15 Nov; marked absent from 16 Nov (in 4 days)")
        self.assertContains(listing, "On leave until 15 Nov")

    def test_student_page_counts_absences_without_permission(self):
        take_roll_call(self.h1, {self.alice.pk}, self.warden, now=at(21, day=11))
        take_roll_call(self.h1, {self.alice.pk}, self.warden, now=at(21, day=12))
        with now_is(at(10, day=13)):
            detail = self.client.get(reverse("residents:detail", args=[self.alice.pk]))
        self.assertContains(detail, "Absent without permission: <strong>2</strong> nights")


class RollCallViewTests(Fixture):
    def setUp(self):
        super().setUp()
        self.client.login(username="warden", password="pw12345!")
        self.url = reverse("attendance:rollcall", args=[self.h1.pk])

    def test_sheet_shows_own_hostel_only(self):
        with now_is(at(21)):
            page = self.client.get(self.url)
        self.assertContains(page, "Alice")
        self.assertNotContains(page, "Dan")

    def test_other_hostel_is_404_for_warden_but_open_to_admin(self):
        other = reverse("attendance:rollcall", args=[self.h2.pk])
        self.assertEqual(self.client.get(other).status_code, 404)
        self.client.logout()
        self.client.login(username="admin", password="pw12345!")
        with now_is(at(21)):
            self.assertEqual(self.client.get(other).status_code, 200)

    def test_saving_at_night(self):
        with now_is(at(21)):
            response = self.client.post(self.url, {"absent": [self.bob.pk]}, follow=True)
        self.assertContains(response, "Roll call saved")
        self.assertEqual(RollCallEntry.objects.get(student=self.bob).status, "absent")
        self.assertEqual(RollCallEntry.objects.get(student=self.alice).status, "present")
        self.assertContains(response, "1 absent without permission")

    def test_saving_in_daytime_is_refused(self):
        with now_is(at(12)):
            response = self.client.post(self.url, {"absent": [self.bob.pk]}, follow=True)
        self.assertContains(response, "Roll call is open from")
        self.assertFalse(RollCall.objects.exists())

    def test_students_on_leave_have_no_checkbox(self):
        self.permit(self.alice, 12, 14)
        with now_is(at(21)):
            page = self.client.get(self.url)
        self.assertNotContains(page, f'name="absent" value="{self.alice.pk}"')
        self.assertContains(page, f'name="absent" value="{self.bob.pk}"')
        self.assertContains(page, "On leave until 14 Nov")
