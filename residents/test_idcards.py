import shutil
import tempfile
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from organizations.models import Category, DietType, Hostel, Organization, Room, StaffProfile
from residents import idcards
from residents.models import Student
from residents.services import allocate_room

PW = "pw12345!Xy"
MEDIA = tempfile.mkdtemp()


def png(colour=(30, 64, 175, 255), size=(300, 200), name="logo.png"):
    buffer = BytesIO()
    Image.new("RGBA", size, colour).save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class DrawingTests(SimpleTestCase):
    def test_pdf_has_front_and_back_for_each_card_and_ten_per_sheet(self):
        org = idcards.OrgData(name="Org A")
        cards = [idcards.CardData(name=f"S{i}", roll_number=str(i), qr_token="t") for i in range(12)]
        self.assertEqual(idcards.build_pdf(cards[:3], org, "card").count(b"/Type /Page\n"), 6)
        self.assertEqual(idcards.build_pdf(cards, org, "sheet").count(b"/Type /Page\n"), 4)

    def test_card_is_credit_card_size(self):
        from reportlab.lib.units import mm

        self.assertAlmostEqual(idcards.CARD_W / mm, 85.6, places=2)
        self.assertAlmostEqual(idcards.CARD_H / mm, 53.98, places=2)

    def test_back_slots_mirror_the_front_for_double_sided_printing(self):
        self.assertEqual([idcards.mirrored_slot(i) for i in range(4)], [1, 0, 3, 2])

    def test_colour_comes_from_the_logo_with_a_fallback(self):
        self.assertEqual(idcards.dominant_colour(png().read()), "#1e40af")
        self.assertEqual(idcards.dominant_colour(b"not an image"), idcards.DEFAULT_COLOUR)
        self.assertEqual(idcards.dominant_colour(png((255, 255, 255, 255)).read()), idcards.DEFAULT_COLOUR)

    def test_text_the_pdf_fonts_cannot_print_does_not_crash(self):
        self.assertEqual(idcards.latin("José"), "José")
        self.assertEqual(idcards.latin("अमित"), "????")

    def test_long_text_is_shrunk_or_cut_to_fit(self):
        lines, size = idcards.fit_lines("A" * 200, "Helvetica-Bold", 10, 100, 1, 6)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith("..."))


@override_settings(MEDIA_ROOT=MEDIA)
class CardPdfViewTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.addClassCleanup(shutil.rmtree, MEDIA, True)

    def setUp(self):
        self.org = Organization.objects.create(name="Org A", slug="a")
        self.cat = Category.objects.create(organization=self.org, name="National")
        self.diet = DietType.objects.create(organization=self.org, name="Veg")
        self.hostel = Hostel.objects.create(organization=self.org, name="Boys 1", gender="male")
        self.room = Room.objects.create(hostel=self.hostel, number="101", capacity=2)
        for username, role in (("admin1", "admin"), ("warden1", "warden")):
            user = User.objects.create_user(username, password=PW)
            profile = StaffProfile.objects.create(user=user, organization=self.org, role=role)
            if role == "warden":
                profile.hostels.set([self.hostel])
        self.student = Student.objects.create(organization=self.org, roll_number="S1", name="Student S1", gender="male",
                                              category=self.cat, diet=self.diet)
        allocate_room(self.student, self.room, self.org.local_today())

    def test_pdf_downloads_in_both_modes(self):
        self.client.login(username="admin1", password=PW)
        for mode in ("card", "sheet"):
            response = self.client.get(reverse("residents:cards_pdf"), {"mode": mode})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertTrue(response.content.startswith(b"%PDF"))
            self.assertIn(mode, response["Content-Disposition"])

    def test_pdf_with_logo_and_photo(self):
        self.org.logo.save("logo.png", png(), save=True)
        self.student.photo.save("p.png", png((200, 50, 50, 255), (80, 100)), save=True)
        self.client.login(username="admin1", password=PW)
        response = self.client.get(reverse("residents:cards_pdf"))
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_pdf_respects_the_wardens_scope_and_filters(self):
        other = Hostel.objects.create(organization=self.org, name="Boys 2", gender="male")
        room2 = Room.objects.create(hostel=other, number="201", capacity=1)
        far = Student.objects.create(organization=self.org, roll_number="S2", name="Far Away", gender="male",
                                     category=self.cat, diet=self.diet)
        allocate_room(far, room2, self.org.local_today())
        self.client.login(username="warden1", password=PW)
        mine = self.client.get(reverse("residents:cards_pdf"), {"mode": "card"})
        everyone = self.client.get(reverse("residents:cards_pdf"), {"mode": "card", "ids": f"{self.student.pk},{far.pk}"})
        self.assertEqual(mine.content.count(b"/Type /Page\n"), 2)  # front + back of one student
        self.assertEqual(everyone.content.count(b"/Type /Page\n"), 2)  # the other hostel's student is not included

    def test_no_students_still_gives_a_valid_pdf(self):
        self.client.login(username="admin1", password=PW)
        response = self.client.get(reverse("residents:cards_pdf"), {"q": "nobody"})
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_anonymous_is_sent_to_login(self):
        self.assertEqual(self.client.get(reverse("residents:cards_pdf")).status_code, 302)

    def test_cards_page_offers_both_downloads_and_hints_when_no_logo(self):
        self.client.login(username="admin1", password=PW)
        page = self.client.get(reverse("residents:cards"))
        self.assertContains(page, "mode=card")
        self.assertContains(page, "mode=sheet")
        self.assertContains(page, "add one in Setup")


@override_settings(MEDIA_ROOT=MEDIA)
class LogoSetupTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.addClassCleanup(shutil.rmtree, MEDIA, True)

    def setUp(self):
        self.org = Organization.objects.create(name="Org A", slug="a", timezone="Asia/Kolkata")
        self.other = Organization.objects.create(name="Org B", slug="b")
        for org, username, role in ((self.org, "admin1", "admin"), (self.other, "admin2", "admin"), (self.org, "warden1", "warden")):
            StaffProfile.objects.create(user=User.objects.create_user(username, password=PW), organization=org, role=role)

    def data(self, **extra):
        base = {"name": "Org A", "timezone": "Asia/Kolkata", "roll_call_start": "18:00", "roll_call_end": "20:00"}
        base.update(extra)
        return base

    def test_admin_can_upload_a_logo_which_is_stored_as_a_small_png(self):
        self.client.login(username="admin1", password=PW)
        big = png(size=(1500, 900))
        response = self.client.post(reverse("setup:index"), self.data(logo=big))
        self.assertEqual(response.status_code, 302)
        self.org.refresh_from_db()
        self.assertTrue(self.org.logo.name.endswith(".png"))
        image = Image.open(self.org.logo.path)
        self.assertLessEqual(max(image.size), 600)

    def test_a_non_image_is_refused(self):
        self.client.login(username="admin1", password=PW)
        bad = SimpleUploadedFile("x.png", b"definitely not an image", content_type="image/png")
        response = self.client.post(reverse("setup:index"), self.data(logo=bad))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "valid image")
        self.org.refresh_from_db()
        self.assertFalse(self.org.logo)

    def test_saving_without_a_file_keeps_the_logo_and_remove_clears_it(self):
        self.org.logo.save("logo.png", png(), save=True)
        self.client.login(username="admin1", password=PW)
        self.client.post(reverse("setup:index"), self.data())
        self.org.refresh_from_db()
        self.assertTrue(self.org.logo)
        self.client.post(reverse("setup:index"), self.data(remove_logo="on"))
        self.org.refresh_from_db()
        self.assertFalse(self.org.logo)

    def test_logo_is_served_to_own_staff_only(self):
        self.org.logo.save("logo.png", png(), save=True)
        url = self.org.logo.url
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.login(username="warden1", password=PW)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.logout()
        self.client.login(username="admin2", password=PW)
        self.assertEqual(self.client.get(url).status_code, 404)
