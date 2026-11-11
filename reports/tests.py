from datetime import date

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from attendance.models import ExitPermit, RollCall, RollCallEntry
from mess.models import Counter, MealCollection, MealType
from organizations.models import Category, DietType, Hostel, Organization, Room, StaffProfile
from reports import builders
from reports.exporters import to_csv, to_pdf
from reports.periods import resolve_period
from reports.tables import Table
from residents.models import Student
from residents.services import allocate_room


def D(day):
    return date(2026, 11, day)


class PeriodTests(SimpleTestCase):
    def test_day(self):
        self.assertEqual(resolve_period("day", D(11), None, None), (D(11), D(11)))

    def test_week_runs_monday_to_sunday(self):
        self.assertEqual(resolve_period("week", D(11), None, None), (D(9), D(15)))
        self.assertEqual(resolve_period("week", D(9), None, None), (D(9), D(15)))
        self.assertEqual(resolve_period("week", D(15), None, None), (D(9), D(15)))

    def test_month(self):
        self.assertEqual(resolve_period("month", D(11), None, None), (D(1), D(30)))
        self.assertEqual(resolve_period("month", date(2028, 2, 15), None, None), (date(2028, 2, 1), date(2028, 2, 29)))

    def test_custom_rules(self):
        self.assertEqual(resolve_period("custom", D(1), D(3), D(5)), (D(3), D(5)))
        for start, end in ((None, D(5)), (D(5), None), (D(6), D(5)), (date(2026, 1, 1), date(2027, 6, 1))):
            with self.assertRaises(ValueError):
                resolve_period("custom", D(1), start, end)


class ExporterTests(SimpleTestCase):
    table = Table("T", "sub", ["Name", "Count"], [["=cmd|calc", 3], ["Ann", 4]], ["a note"])

    def test_csv_has_bom_header_and_neutralised_formulas(self):
        data = to_csv(self.table)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        lines = data.decode("utf-8-sig").splitlines()
        self.assertEqual(lines[0], "Name,Count")
        self.assertEqual(lines[1], "'=cmd|calc,3")

    def test_pdf_is_a_pdf(self):
        self.assertTrue(to_pdf(self.table, heading="Generated now").startswith(b"%PDF"))
        self.assertTrue(to_pdf(Table("Empty", "sub", ["A"], [])).startswith(b"%PDF"))


class Fixture(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org A", slug="a", timezone="Asia/Kolkata")
        self.cat = Category.objects.create(organization=self.org, name="National")
        self.diet = DietType.objects.create(organization=self.org, name="Veg")
        self.h1 = Hostel.objects.create(organization=self.org, name="Boys 1", gender="male")
        self.h2 = Hostel.objects.create(organization=self.org, name="Boys 2", gender="male")
        self.room1 = Room.objects.create(hostel=self.h1, number="101", capacity=4)
        self.room2 = Room.objects.create(hostel=self.h2, number="201", capacity=4)
        self.breakfast = MealType.objects.create(organization=self.org, name="Breakfast", sort_order=1)
        self.lunch = MealType.objects.create(organization=self.org, name="Lunch", sort_order=2)
        self.counter = Counter.objects.create(organization=self.org, name="Main")
        self.alice = self.student("R1", "Alice", self.room1)
        self.bob = self.student("R2", "Bob", self.room1)
        self.cara = self.student("R3", "Cara", self.room1)
        self.dan = self.student("R4", "Dan", self.room2)

        warden = User.objects.create_user("warden", password="pw12345!")
        self.warden = StaffProfile.objects.create(user=warden, organization=self.org, role="warden")
        self.warden.hostels.set([self.h1])
        admin = User.objects.create_user("admin", password="pw12345!")
        self.admin = StaffProfile.objects.create(user=admin, organization=self.org, role="admin")

    def student(self, roll, name, room=None, status="active"):
        s = Student.objects.create(
            organization=self.org, roll_number=roll, name=name, gender="male", category=self.cat, diet=self.diet,
            status=status,
        )
        if room:
            allocate_room(s, room, date(2026, 11, 1))
        return s

    def serve(self, student, meal, day):
        return MealCollection.objects.create(
            organization=self.org, student=student, meal_type=meal, date=D(day), counter=self.counter
        )

    def entry(self, hostel, student, day, status, permit=None, overdue=0):
        roll_call, _ = RollCall.objects.get_or_create(organization=self.org, hostel=hostel, date=D(day))
        return RollCallEntry.objects.create(
            roll_call=roll_call, student=student, status=status, permit=permit, days_overdue=overdue
        )

    def seed_meals(self):
        self.serve(self.alice, self.breakfast, 10)
        self.serve(self.alice, self.lunch, 10)
        self.serve(self.bob, self.breakfast, 10)
        self.serve(self.dan, self.breakfast, 11)

    def seed_attendance(self):
        leave = ExitPermit.objects.create(organization=self.org, student=self.cara, start_date=D(9), end_date=D(11))
        ended = ExitPermit.objects.create(organization=self.org, student=self.bob, start_date=D(7), end_date=D(9))
        self.entry(self.h1, self.alice, 10, "present")
        self.entry(self.h1, self.bob, 10, "absent")
        self.entry(self.h1, self.cara, 10, "on_leave", permit=leave)
        self.entry(self.h1, self.alice, 11, "present")
        self.entry(self.h1, self.bob, 11, "absent", permit=ended, overdue=2)
        self.entry(self.h1, self.cara, 11, "present")
        self.entry(self.h2, self.dan, 10, "absent")


class MealReportTests(Fixture):
    def test_meals_per_day_for_admin(self):
        self.seed_meals()
        table = builders.meals_daily(self.admin, D(10), D(12))
        self.assertEqual(table.headers, ["Date", "Breakfast", "Lunch", "Total"])
        self.assertEqual(table.rows, [
            ["10 Nov 2026 (Tue)", 2, 1, 3],
            ["11 Nov 2026 (Wed)", 1, 0, 1],
            ["12 Nov 2026 (Thu)", 0, 0, 0],
            ["Total", 3, 1, 4],
        ])

    def test_warden_only_counts_students_in_own_hostels(self):
        self.seed_meals()
        table = builders.meals_daily(self.warden, D(10), D(11))
        self.assertEqual(table.rows[-1], ["Total", 2, 1, 3])
        self.assertEqual(table.rows[1], ["11 Nov 2026 (Wed)", 0, 0, 0])

    def test_hostel_filter(self):
        self.seed_meals()
        table = builders.meals_daily(self.admin, D(10), D(11), hostel=self.h2)
        self.assertEqual(table.rows[-1], ["Total", 1, 0, 1])

    def test_other_organizations_are_never_counted(self):
        self.seed_meals()
        other = Organization.objects.create(name="Org B", slug="b")
        oc = Category.objects.create(organization=other, name="National")
        od = DietType.objects.create(organization=other, name="Veg")
        stranger = Student.objects.create(organization=other, roll_number="X1", name="Stranger", gender="male", category=oc, diet=od)
        meal = MealType.objects.create(organization=other, name="Breakfast")
        counter = Counter.objects.create(organization=other, name="C")
        MealCollection.objects.create(organization=other, student=stranger, meal_type=meal, date=D(10), counter=counter)
        self.assertEqual(builders.meals_daily(self.admin, D(10), D(10)).rows[0], ["10 Nov 2026 (Tue)", 2, 1, 3])

    def test_meals_per_student_lists_active_students_with_zero(self):
        self.seed_meals()
        self.student("R8", "Lena", status="left")  # left, no meals: not listed
        table = builders.meals_students(self.admin, D(10), D(12))
        self.assertEqual([r[1] for r in table.rows[:-1]], ["Alice", "Bob", "Cara", "Dan"])
        self.assertEqual(table.rows[0], ["R1", "Alice", "Boys 1 / 101", 1, 1, 2])
        self.assertEqual(table.rows[2], ["R3", "Cara", "Boys 1 / 101", 0, 0, 0])
        self.assertEqual(table.rows[-1], ["Total", "", "", 3, 1, 4])

    def test_left_student_with_meals_in_the_period_is_listed(self):
        zed = self.student("R9", "Zed", status="left")
        self.serve(zed, self.breakfast, 10)
        names = [r[1] for r in builders.meals_students(self.admin, D(10), D(10)).rows[:-1]]
        self.assertIn("Zed", names)


class AttendanceReportTests(Fixture):
    def test_summary_for_admin(self):
        self.seed_attendance()
        table = builders.attendance_summary(self.admin, D(10), D(11))
        self.assertEqual(table.headers[7], "Total absent without permission")
        self.assertEqual(table.rows, [
            ["R2", "Bob", "Boys 1 / 101", 0, 0, 1, 1, 2, 2],
            ["R4", "Dan", "Boys 2 / 201", 0, 0, 1, 0, 1, 0],
            ["R1", "Alice", "Boys 1 / 101", 2, 0, 0, 0, 0, 0],
            ["R3", "Cara", "Boys 1 / 101", 1, 1, 0, 0, 0, 0],
            ["Total", "", "", 3, 1, 2, 1, 3, 2],
        ])
        self.assertIn("does not calculate or charge fines", table.notes[0])

    def test_summary_for_warden_leaves_out_other_hostels(self):
        self.seed_attendance()
        table = builders.attendance_summary(self.warden, D(10), D(11))
        self.assertEqual([r[1] for r in table.rows[:-1]], ["Bob", "Alice", "Cara"])
        self.assertEqual(table.rows[-1], ["Total", "", "", 3, 1, 1, 1, 2, 2])

    def test_period_limits_the_nights_counted(self):
        self.seed_attendance()
        table = builders.attendance_summary(self.admin, D(11), D(11))
        self.assertEqual(table.rows[-1], ["Total", "", "", 2, 0, 0, 1, 1, 2])

    def test_absence_list(self):
        self.seed_attendance()
        table = builders.absences(self.admin, D(10), D(11))
        self.assertEqual(len(table.rows), 3)
        self.assertEqual([r[3] for r in table.rows], ["Bob", "Dan", "Bob"])
        self.assertEqual(table.rows[0][4:], ["No permit", 0])
        self.assertEqual(table.rows[2][4:], ["Permit ended 9 Nov (2 days overdue)", 2])
        self.assertEqual(table.notes[0], "3 night(s) of absence without permission by 2 student(s).")

    def test_absence_list_for_warden_and_hostel_filter(self):
        self.seed_attendance()
        self.assertEqual([r[3] for r in builders.absences(self.warden, D(10), D(11)).rows], ["Bob", "Bob"])
        self.assertEqual([r[3] for r in builders.absences(self.admin, D(10), D(11), hostel=self.h2).rows], ["Dan"])

    def test_empty_period_gives_header_only_report(self):
        table = builders.absences(self.admin, D(10), D(11))
        self.assertEqual(table.rows, [])


class ReportViewTests(Fixture):
    def setUp(self):
        super().setUp()
        self.seed_meals()
        self.seed_attendance()
        self.client.login(username="admin", password="pw12345!")
        self.url = reverse("reports:report", args=["absences"])
        self.params = {"period": "custom", "start": "2026-11-10", "end": "2026-11-11"}

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        for url in (reverse("reports:index"), self.url):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("accounts:login"), response["Location"])

    def test_index_offers_every_report_in_every_format(self):
        page = self.client.get(reverse("reports:index"))
        self.assertEqual(page.status_code, 200)
        for text in ("Meals served per day", "Attendance summary per student", "Absent without permission",
                     "format=csv", "format=pdf", "Download CSV", "Download PDF"):
            self.assertContains(page, text)

    def test_html_report(self):
        page = self.client.get(self.url, self.params)
        self.assertContains(page, "Bob")
        self.assertContains(page, "Permit ended 9 Nov (2 days overdue)")
        self.assertContains(page, "Download CSV")

    def test_csv_download(self):
        response = self.client.get(self.url, {**self.params, "format": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("absences_2026-11-10_2026-11-11.csv", response["Content-Disposition"])
        text = response.content.decode("utf-8-sig")
        self.assertEqual(text.splitlines()[0], "Date,Hostel,Roll no.,Student,Reason,Days overdue")
        self.assertIn("Bob", text)

    def test_csv_neutralises_formulas_in_student_names(self):
        self.bob.name = "=cmd|calc"
        self.bob.save()
        text = self.client.get(self.url, {**self.params, "format": "csv"}).content.decode("utf-8-sig")
        self.assertIn("'=cmd|calc", text)

    def test_pdf_download(self):
        response = self.client.get(self.url, {**self.params, "format": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn(".pdf", response["Content-Disposition"])

    def test_weekly_and_monthly_presets(self):
        for period in ("week", "month"):
            response = self.client.get(self.url, {"period": period, "date": "2026-11-11", "format": "csv"})
            self.assertEqual(response.status_code, 200)
        self.assertIn("2026-11-09_2026-11-15", self.client.get(
            self.url, {"period": "week", "date": "2026-11-11", "format": "csv"})["Content-Disposition"])

    def test_bad_custom_range_shows_a_message(self):
        response = self.client.get(self.url, {"period": "custom", "format": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose both dates")

    def test_format_alone_gives_todays_report(self):
        response = self.client.get(self.url, {"format": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))

    def test_unknown_report_is_404(self):
        self.assertEqual(self.client.get(reverse("reports:report", args=["nope"])).status_code, 404)

    def test_warden_cannot_report_on_another_hostel(self):
        self.client.logout()
        self.client.login(username="warden", password="pw12345!")
        response = self.client.get(self.url, {**self.params, "hostel": self.h2.pk, "format": "csv"})
        self.assertFalse(response["Content-Type"].startswith("text/csv"))
        self.assertContains(response, "Select a valid choice")

    def test_warden_report_leaves_out_other_hostels(self):
        self.client.logout()
        self.client.login(username="warden", password="pw12345!")
        page = self.client.get(self.url, self.params)
        self.assertContains(page, "Bob")
        self.assertNotContains(page, "Dan")
