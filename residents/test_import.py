import os
import tempfile
import time
import zipfile
from datetime import date
from io import BytesIO, StringIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import Workbook
from PIL import Image

from organizations.demo import write_sample_files
from organizations.models import Category, DietType, Hostel, Organization, Room, StaffProfile
from residents.import_files import COLUMNS, ImportFileError, ParsedFile, PhotoIndex, index_photos, read_table
from residents.importer import plan_import, run_import
from residents.models import Student
from residents.services import allocate_room

HEADER = "roll_number,name,gender,category,diet,hostel,room\n"


def jpeg(width=600, height=400):
    buffer = BytesIO()
    Image.new("RGB", (width, height), (30, 120, 200)).save(buffer, "JPEG")
    return buffer.getvalue()


def make_zip(files):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def csv_upload(body, header=HEADER, name="students.csv"):
    return SimpleUploadedFile(name, (header + body).encode("utf-8"), content_type="text/csv")


def parsed(*rows):
    blank = {column: "" for column in COLUMNS}
    return ParsedFile([(i + 2, {**blank, **row}) for i, row in enumerate(rows)])


def row(roll, name="Some Student", gender="male", category="National", diet="Vegetarian", hostel="", room="", **more):
    return {"roll_number": roll, "name": name, "gender": gender, "category": category, "diet": diet,
            "hostel": hostel, "room": room, **more}


class Fixture(TestCase):
    def setUp(self):
        self.staging = self.enterContext(tempfile.TemporaryDirectory())
        self.media = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(self.settings(IMPORT_STAGING_DIR=self.staging, MEDIA_ROOT=self.media))

        self.org = Organization.objects.create(name="Org A", slug="a", timezone="Asia/Kolkata")
        self.national = Category.objects.create(organization=self.org, name="National")
        self.intl = Category.objects.create(organization=self.org, name="International")
        self.veg = DietType.objects.create(organization=self.org, name="Vegetarian")
        DietType.objects.create(organization=self.org, name="Non-vegetarian")
        self.boys = Hostel.objects.create(organization=self.org, name="Boys A", gender="male")
        self.girls = Hostel.objects.create(organization=self.org, name="Girls B", gender="female")
        self.room101 = Room.objects.create(hostel=self.boys, number="101", capacity=2)
        self.room102 = Room.objects.create(hostel=self.boys, number="102", capacity=2)
        self.room201 = Room.objects.create(hostel=self.girls, number="201", capacity=2)

        admin = User.objects.create_user("admin", password="pw12345!")
        self.admin = StaffProfile.objects.create(user=admin, organization=self.org, role="admin")
        warden = User.objects.create_user("warden", password="pw12345!")
        self.warden = StaffProfile.objects.create(user=warden, organization=self.org, role="warden")
        self.warden.hostels.set([self.boys])

    def existing(self, roll, name="Existing", room=None):
        s = Student.objects.create(
            organization=self.org, roll_number=roll, name=name, gender="male", category=self.national, diet=self.veg
        )
        if room:
            allocate_room(s, room, date(2026, 11, 1))
        return s


class PlanTests(Fixture):
    def plan(self, *rows, staff=None, photos=None):
        return plan_import(staff or self.admin, parsed(*rows), photos)

    def test_valid_rows_are_normalised(self):
        plan = self.plan(row("R1", gender="M", category="national", diet="VEGETARIAN", hostel="boys a", room="101"))
        r = plan.rows[0]
        self.assertTrue(r.ok, r.errors)
        self.assertEqual((r.data["gender"], r.category, r.diet, r.room), ("male", self.national, self.veg, self.room101))

    def test_unknown_values_list_the_allowed_ones(self):
        plan = self.plan(row("R1", category="Foreigner"), row("R2", diet="Vegan"), row("R3", gender="X"), row("R4", name=""))
        messages = [r.errors[0] for r in plan.rows]
        self.assertIn("Use one of: International, National", messages[0])
        self.assertIn("Use one of: Non-vegetarian, Vegetarian", messages[1])
        self.assertIn("Gender must be male or female", messages[2])
        self.assertIn("name is missing", messages[3])
        self.assertEqual(len(plan.bad_rows), 4)

    def test_duplicates_in_file_and_in_database(self):
        self.existing("R9")
        plan = self.plan(row("R1"), row("r1"), row("r9"))
        self.assertTrue(plan.rows[0].ok)
        self.assertIn("appears twice in the file (first on row 2)", plan.rows[1].errors[0])
        self.assertIn("already registered", plan.rows[2].errors[0])

    def test_room_rules(self):
        plan = self.plan(
            row("R1", hostel="Boys A"),
            row("R2", room="101"),
            row("R3", hostel="Nowhere", room="1"),
            row("R4", hostel="Boys A", room="999"),
            row("R5", gender="female", hostel="Boys A", room="101"),
        )
        text = [r.errors[0] for r in plan.rows]
        self.assertIn("both the hostel and the room", text[0])
        self.assertIn("both the hostel and the room", text[1])
        self.assertIn('Unknown hostel "Nowhere"', text[2])
        self.assertIn("has no room 999", text[3])
        self.assertIn("is a male hostel", text[4])

    def test_warden_can_only_use_own_hostels(self):
        girl = row("R1", gender="female", hostel="Girls B", room="201")
        self.assertIn("not one of your hostels", self.plan(girl, staff=self.warden).rows[0].errors[0])
        self.assertTrue(self.plan(girl, staff=self.admin).rows[0].ok)

    def test_room_capacity_counts_current_occupants_and_earlier_rows(self):
        self.existing("E1", room=self.room101)  # one of two beds taken
        plan = self.plan(row("R1", hostel="Boys A", room="101"), row("R2", hostel="Boys A", room="101"))
        self.assertTrue(plan.rows[0].ok)
        self.assertIn("is full (2 beds)", plan.rows[1].errors[0])

    def test_a_rejected_row_does_not_take_a_bed(self):
        plan = self.plan(
            row("R1", gender="X", hostel="Boys A", room="102"),
            row("R2", hostel="Boys A", room="102"),
            row("R3", hostel="Boys A", room="102"),
            row("R4", hostel="Boys A", room="102"),
        )
        self.assertEqual([r.ok for r in plan.rows], [False, True, True, False])

    def test_photo_matching_by_roll_number_and_by_column(self):
        index = PhotoIndex(
            by_stem={"r1": "R1.jpg", "other": "other.png", "stray": "stray.jpg"},
            by_name={"r1.jpg": "R1.jpg", "other.png": "other.png", "stray.jpg": "stray.jpg"},
        )
        plan = self.plan(row("R1"), row("R2", photo="other.png"), row("R3", photo="missing.png"), photos=index)
        self.assertEqual([r.photo_member for r in plan.rows], ["R1.jpg", "other.png", ""])
        self.assertIn("missing.png", plan.rows[2].warnings[0])
        self.assertEqual(plan.unmatched_photos, ["stray.jpg"])
        self.assertEqual(plan.photos_matched, 2)


class RunTests(Fixture):
    def test_run_creates_students_rooms_and_tokens(self):
        plan = plan_import(self.admin, parsed(row("R1", hostel="Boys A", room="101"), row("R2"), row("R3", gender="X")))
        summary = run_import(self.admin, plan)
        self.assertEqual((summary.created, summary.failed), (2, []))
        r1 = Student.objects.get(roll_number="R1")
        self.assertEqual((r1.organization, r1.current_room, r1.status), (self.org, self.room101, "active"))
        self.assertIsNone(Student.objects.get(roll_number="R2").current_room)
        self.assertFalse(Student.objects.filter(roll_number="R3").exists())
        self.assertNotEqual(r1.qr_token, Student.objects.get(roll_number="R2").qr_token)

    def test_a_row_that_fails_late_does_not_stop_the_others(self):
        plan = plan_import(self.admin, parsed(row("R1"), row("R2")))
        self.existing("R1")  # registered after the preview
        summary = run_import(self.admin, plan)
        self.assertEqual(summary.created, 1)
        self.assertEqual(summary.failed[0][0], 2)
        self.assertIn("registered in the meantime", summary.failed[0][1])
        self.assertTrue(Student.objects.filter(roll_number="R2").exists())

    def test_photos_are_attached_resized_and_bad_ones_reported(self):
        path = os.path.join(self.staging, "p.zip")
        with open(path, "wb") as handle:
            handle.write(make_zip({"R1.jpg": jpeg(1600, 900), "R2.jpg": b"this is not a picture"}))
        plan = plan_import(self.admin, parsed(row("R1"), row("R2")), index_photos(path))
        summary = run_import(self.admin, plan, path)
        self.assertEqual((summary.created, summary.photos_attached), (2, 1))
        self.assertIn("R2.jpg", summary.photo_problems[0])
        with Image.open(Student.objects.get(roll_number="R1").photo) as stored:
            self.assertLessEqual(max(stored.size), 400)
        self.assertFalse(Student.objects.get(roll_number="R2").photo)


class ViewTests(Fixture):
    def setUp(self):
        super().setUp()
        self.client.login(username="admin", password="pw12345!")
        self.url = reverse("residents:import")

    def upload(self, body="", header=HEADER, name="students.csv", photos=None, file=None):
        data = {"file": file or csv_upload(body, header, name)}
        if photos is not None:
            data["photos"] = SimpleUploadedFile("photos.zip", photos, content_type="application/zip")
        return self.client.post(self.url, data)

    def staged(self):
        return os.listdir(self.staging)

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        for name in ("residents:import", "residents:import_template"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    def test_upload_page_lists_what_is_allowed(self):
        page = self.client.get(self.url)
        for text in ("International, National", "Boys A, Girls B", "Download a template file"):
            self.assertContains(page, text)

    def test_preview_saves_nothing(self):
        page = self.upload("R1,Ann,female,National,Vegetarian,,\nR2,Bob,male,Nobody,Vegetarian,,\nR3,Cy,male,National,Vegetarian,Boys A,101\n")
        self.assertContains(page, "<strong>2</strong> of 3 rows are ready to import")
        self.assertContains(page, "Unknown category")
        self.assertContains(page, "Skip the 1 problem row and import 2")
        self.assertFalse(Student.objects.exists())
        self.assertEqual(len(self.staged()), 1)

    def test_confirm_imports_and_clears_the_upload(self):
        self.upload("R1,Ann,female,National,Vegetarian,,\nR2,Bob,male,Nobody,Vegetarian,,\nR3,Cy,male,National,Vegetarian,Boys A,101\n")
        page = self.client.post(reverse("residents:import_confirm"))
        self.assertContains(page, "<strong>2</strong> students imported")
        self.assertEqual(sorted(Student.objects.values_list("roll_number", flat=True)), ["R1", "R3"])
        self.assertEqual(Student.objects.get(roll_number="R3").current_room, self.room101)
        self.assertEqual(self.staged(), [])
        again = self.client.post(reverse("residents:import_confirm"), follow=True)
        self.assertContains(again, "There is no import waiting")
        self.assertEqual(Student.objects.count(), 2)

    def test_cancel_discards_everything(self):
        self.upload("R1,Ann,female,National,Vegetarian,,\n")
        self.client.post(reverse("residents:import_cancel"))
        self.assertEqual(self.staged(), [])
        self.assertFalse(Student.objects.exists())

    def test_confirm_needs_post(self):
        self.assertEqual(self.client.get(reverse("residents:import_confirm")).status_code, 405)

    def test_forged_token_is_ignored(self):
        session = self.client.session
        session["import_token"] = "../../etc"
        session.save()
        page = self.client.post(reverse("residents:import_confirm"), follow=True)
        self.assertContains(page, "There is no import waiting")

    def test_unusable_files_give_a_message(self):
        page = self.upload("R1,Ann\n", header="roll_number,name\n")
        self.assertContains(page, "Missing column(s): gender, category, diet")
        bad_type = SimpleUploadedFile("students.txt", b"x", content_type="text/plain")
        self.assertContains(self.upload(file=bad_type), "Use a .csv or .xlsx file")
        self.assertEqual(self.staged(), [])

    def test_excel_upload(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Roll No", "Student Name", "Sex", "Category", "Diet"])
        sheet.append([1234.0, "Ann Example", "F", "National", "Vegetarian"])
        buffer = BytesIO()
        workbook.save(buffer)
        upload = SimpleUploadedFile("list.xlsx", buffer.getvalue())
        self.assertContains(self.upload(file=upload), "<strong>1</strong> of 1 rows are ready to import")
        self.client.post(reverse("residents:import_confirm"))
        self.assertEqual(Student.objects.get().roll_number, "1234")

    def test_photo_zip_is_matched_and_attached(self):
        archive = make_zip({"R1.jpg": jpeg(), "nobody.jpg": jpeg()})
        page = self.upload("R1,Ann,female,National,Vegetarian,,\n", photos=archive)
        self.assertContains(page, "Photos: 1 matched to students")
        self.assertContains(page, "1 picture(s) belong to nobody")
        self.client.post(reverse("residents:import_confirm"))
        self.assertTrue(Student.objects.get(roll_number="R1").photo)

    def test_invalid_zip_is_rejected(self):
        page = self.upload("R1,Ann,female,National,Vegetarian,,\n", photos=b"not a zip")
        self.assertContains(page, "not a valid zip")
        self.assertEqual(self.staged(), [])

    def test_old_uploads_are_purged(self):
        old = os.path.join(self.staging, "a" * 32)
        os.makedirs(old)
        two_days_ago = time.time() - 2 * 24 * 3600
        os.utime(old, (two_days_ago, two_days_ago))
        self.upload("R1,Ann,female,National,Vegetarian,,\n")
        self.assertNotIn("a" * 32, self.staged())

    def test_template_download(self):
        response = self.client.get(reverse("residents:import_template"))
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        lines = response.content.decode("utf-8-sig").splitlines()
        self.assertEqual(lines[0], ",".join(COLUMNS))
        self.assertIn("EXAMPLE001", lines[1])

    def test_warden_cannot_import_into_another_hostel(self):
        self.client.logout()
        self.client.login(username="warden", password="pw12345!")
        page = self.upload("R1,Ann,female,National,Vegetarian,Girls B,201\n")
        self.assertContains(page, "not one of your hostels")
        self.client.post(reverse("residents:import_confirm"))
        self.assertFalse(Student.objects.exists())


class FileReadingTests(SimpleTestCase):
    def setUp(self):
        self.dir = self.enterContext(tempfile.TemporaryDirectory())

    def write(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_windows_encoding_semicolons_and_alias_headers(self):
        text = "Roll No;Student Name;Sex;Student Category;Food;Extra\nR1;José Pérez;M;National;Veg;x\n"
        result = read_table(self.write("a.csv", text.encode("cp1252")))
        self.assertEqual(result.rows[0][1]["name"], "José Pérez")
        self.assertEqual(result.ignored_columns, ["Extra"])

    def test_blank_rows_are_skipped_but_row_numbers_stay(self):
        result = read_table(self.write("a.csv", (HEADER + "\nR1,A,m,National,Veg,,\n,,,,,,\nR2,B,m,National,Veg,,\n").encode()))
        self.assertEqual([n for n, _ in result.rows], [3, 5])

    def test_file_without_students_is_refused(self):
        with self.assertRaises(ImportFileError):
            read_table(self.write("a.csv", HEADER.encode()))

    def test_picture_names_are_taken_from_the_file_name_only(self):
        path = self.write("p.zip", make_zip({"folder/../KU1.JPG": jpeg(50, 50), "notes.txt": b"x", "__MACOSX/._KU1.jpg": b"x"}))
        index = index_photos(path)
        self.assertEqual(index.find("ku1"), "folder/../KU1.JPG")
        self.assertEqual(len(index.by_stem), 1)
        self.assertEqual(len(index.problems), 1)


class DemoDataTests(TestCase):
    def setUp(self):
        self.staging = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(self.settings(IMPORT_STAGING_DIR=self.staging))
        call_command("seed_demo", password="demo-pass-123", stdout=StringIO())
        self.admin = StaffProfile.objects.get(user__username="demo_admin")
        self.files = write_sample_files(self.enterContext(tempfile.TemporaryDirectory()))

    def test_seed_is_repeatable(self):
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(Organization.objects.filter(slug="demo").count(), 1)
        self.assertEqual(Room.objects.filter(hostel__organization__slug="demo").count(), 22)
        self.assertTrue(User.objects.get(username="demo_warden").check_password("demo-pass-123"))

    def test_sample_csv_and_excel_import_cleanly_with_photos(self):
        for key in ("csv", "xlsx"):
            plan = plan_import(self.admin, read_table(self.files[key]), index_photos(self.files["photos"]))
            self.assertEqual((len(plan.rows), len(plan.bad_rows)), (60, 0), [r.errors for r in plan.bad_rows])
            self.assertEqual(plan.photos_matched, 60)
        summary = run_import(self.admin, plan, self.files["photos"])
        self.assertEqual((summary.created, summary.failed, summary.photo_problems), (60, [], []))

    def test_error_file_has_exactly_the_six_planted_problems(self):
        plan = plan_import(self.admin, read_table(self.files["errors"]))
        self.assertEqual(len(plan.bad_rows), 6, [(r.number, r.errors) for r in plan.bad_rows])
