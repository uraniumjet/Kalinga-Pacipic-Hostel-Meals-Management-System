from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.urls import reverse

from mess.models import Counter, MealCollection, MealType, MealWindow, SpecialPeriod, WindowOverride
from mess.services import current_meal
from organizations.test_setup import SetupBase
from residents.models import Student

IST = ZoneInfo("Asia/Kolkata")


class MealSetupBase(SetupBase):
    def setUp(self):
        super().setUp()
        self.breakfast = MealType.objects.create(organization=self.org, name="Breakfast", sort_order=1)
        MealWindow.objects.create(meal_type=self.breakfast, start_time="07:30", end_time="09:00")
        self.counter = Counter.objects.create(organization=self.org, name="Main")
        self.other_meal = MealType.objects.create(organization=self.other, name="Foreign meal")
        self.other_counter = Counter.objects.create(organization=self.other, name="Foreign counter")

    def collection(self, meal=None, counter=None):
        student = self.student("C1")
        return MealCollection.objects.create(
            organization=self.org, student=student, meal_type=meal or self.breakfast,
            date=date(2026, 11, 10), counter=counter or self.counter,
        )


class AccessTests(MealSetupBase):
    def test_wardens_are_kept_out_and_admins_get_in(self):
        names = ["setup:meals", "setup:counters", "setup:periods"]
        self.login("warden1")
        for name in names:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        self.client.logout()
        self.login()
        for name in names:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)


class MealTests(MealSetupBase):
    def test_add_meal_with_a_normal_time(self):
        self.login()
        self.client.post(reverse("setup:meals"), {"name": "Lunch", "sort_order": "2", "start_time": "12:30", "end_time": "14:00"})
        meal = MealType.objects.get(organization=self.org, name="Lunch")
        window = meal.windows.get()
        self.assertEqual((window.start_time.strftime("%H:%M"), window.end_time.strftime("%H:%M")), ("12:30", "14:00"))
        self.assertIsNone(window.special_period)

    def test_meal_without_times_has_no_normal_window(self):
        self.login()
        self.client.post(reverse("setup:meals"), {"name": "Iftaar", "sort_order": "5", "start_time": "", "end_time": ""})
        self.assertFalse(MealType.objects.get(name="Iftaar", organization=self.org).windows.exists())

    def test_times_must_come_as_a_pair_and_in_order(self):
        self.login()
        page = self.client.post(reverse("setup:meals"), {"name": "X", "sort_order": "1", "start_time": "12:00", "end_time": ""})
        self.assertContains(page, "both times")
        page = self.client.post(reverse("setup:meals"), {"name": "X", "sort_order": "1", "start_time": "14:00", "end_time": "12:00"})
        self.assertContains(page, "must be after the start")
        self.assertFalse(MealType.objects.filter(name="X").exists())

    def test_meal_names_are_unique_ignoring_case(self):
        self.login()
        page = self.client.post(reverse("setup:meals"), {"name": "breakfast", "sort_order": "1", "start_time": "", "end_time": ""})
        self.assertContains(page, "already exists")

    def test_edit_changes_name_and_time(self):
        self.login()
        self.client.post(reverse("setup:meal_edit", args=[self.breakfast.pk]),
                         {"name": "Morning meal", "sort_order": "1", "start_time": "08:00", "end_time": "09:30"})
        self.breakfast.refresh_from_db()
        self.assertEqual(self.breakfast.name, "Morning meal")
        self.assertEqual(self.breakfast.windows.get().start_time.strftime("%H:%M"), "08:00")

    def test_clearing_the_times_removes_the_normal_window(self):
        self.login()
        self.client.post(reverse("setup:meal_edit", args=[self.breakfast.pk]),
                         {"name": "Breakfast", "sort_order": "1", "start_time": "", "end_time": ""})
        self.assertFalse(self.breakfast.windows.exists())

    def test_edit_form_shows_current_time(self):
        self.login()
        self.assertContains(self.client.get(reverse("setup:meal_edit", args=[self.breakfast.pk])), "07:30")

    def test_delete_unused_meal_but_not_one_with_records(self):
        self.login()
        spare = MealType.objects.create(organization=self.org, name="Snack")
        self.client.post(reverse("setup:meal_delete", args=[spare.pk]))
        self.assertFalse(MealType.objects.filter(pk=spare.pk).exists())
        self.collection()
        response = self.client.post(reverse("setup:meal_delete", args=[self.breakfast.pk]), follow=True)
        self.assertTrue(MealType.objects.filter(pk=self.breakfast.pk).exists())
        self.assertContains(response, "served-meal records")

    def test_other_organisations_meals_are_out_of_reach(self):
        self.login()
        self.assertEqual(self.client.get(reverse("setup:meal_edit", args=[self.other_meal.pk])).status_code, 404)
        self.client.post(reverse("setup:meal_delete", args=[self.other_meal.pk]))
        self.assertTrue(MealType.objects.filter(pk=self.other_meal.pk).exists())


class CounterTests(MealSetupBase):
    def test_add_counter_for_some_categories(self):
        self.login()
        self.client.post(reverse("setup:counters"), {"name": "National counter", "categories": [self.cat.pk]})
        counter = Counter.objects.get(organization=self.org, name="National counter")
        self.assertEqual(list(counter.categories.all()), [self.cat])

    def test_counter_without_categories_serves_everyone(self):
        self.login()
        self.client.post(reverse("setup:counters"), {"name": "Open"})
        self.assertFalse(Counter.objects.get(organization=self.org, name="Open").categories.exists())

    def test_duplicate_counter_name_is_refused(self):
        self.login()
        page = self.client.post(reverse("setup:counters"), {"name": "main"})
        self.assertContains(page, "already exists")

    def test_category_of_another_organisation_is_refused(self):
        self.login()
        page = self.client.post(reverse("setup:counters"), {"name": "Sneaky", "categories": [self.other_cat.pk]})
        self.assertContains(page, "Select a valid choice")
        self.assertFalse(Counter.objects.filter(name="Sneaky").exists())

    def test_edit_counter(self):
        self.login()
        self.client.post(reverse("setup:counter_edit", args=[self.counter.pk]), {"name": "Main hall", "categories": [self.cat.pk]})
        self.counter.refresh_from_db()
        self.assertEqual(self.counter.name, "Main hall")
        self.assertEqual(list(self.counter.categories.all()), [self.cat])

    def test_delete_counter_with_and_without_records(self):
        self.login()
        spare = Counter.objects.create(organization=self.org, name="Spare")
        self.client.post(reverse("setup:counter_delete", args=[spare.pk]))
        self.assertFalse(Counter.objects.filter(pk=spare.pk).exists())
        self.collection()
        response = self.client.post(reverse("setup:counter_delete", args=[self.counter.pk]), follow=True)
        self.assertTrue(Counter.objects.filter(pk=self.counter.pk).exists())
        self.assertContains(response, "served-meal records")

    def test_other_organisations_counters_are_out_of_reach(self):
        self.login()
        self.assertEqual(self.client.get(reverse("setup:counter_edit", args=[self.other_counter.pk])).status_code, 404)
        self.client.post(reverse("setup:counter_delete", args=[self.other_counter.pk]))
        self.assertTrue(Counter.objects.filter(pk=self.other_counter.pk).exists())


class PeriodTests(MealSetupBase):
    def make_period(self, **over):
        data = {
            "organization": self.org, "name": "Ramadan", "start_date": date(2026, 11, 1),
            "end_date": date(2026, 11, 30), "religion": "Muslim",
        }
        data.update(over)
        return SpecialPeriod.objects.create(**data)

    def test_add_period_then_land_on_its_page(self):
        self.login()
        response = self.client.post(reverse("setup:periods"), {
            "name": "Ramadan", "start_date": "2026-11-01", "end_date": "2026-11-30", "religion": "Muslim",
            "skipped_meals": [self.breakfast.pk],
        })
        period = SpecialPeriod.objects.get(name="Ramadan")
        self.assertRedirects(response, reverse("setup:period", args=[period.pk]))
        self.assertEqual(list(period.skipped_meals.all()), [self.breakfast])

    def test_end_date_cannot_be_before_start(self):
        self.login()
        page = self.client.post(reverse("setup:periods"), {"name": "Bad", "start_date": "2026-11-10", "end_date": "2026-11-01"})
        self.assertContains(page, "cannot be before the start date")
        self.assertFalse(SpecialPeriod.objects.filter(name="Bad").exists())

    def test_meals_of_another_organisation_cannot_be_skipped(self):
        self.login()
        page = self.client.post(reverse("setup:periods"), {
            "name": "Bad", "start_date": "2026-11-01", "end_date": "2026-11-02", "skipped_meals": [self.other_meal.pk],
        })
        self.assertContains(page, "Select a valid choice")

    def test_set_and_clear_a_period_time(self):
        self.login()
        period = self.make_period()
        url = reverse("setup:period", args=[period.pk])
        self.client.post(url, {"action": "window", "window-meal": self.breakfast.pk, "window-start_time": "04:00", "window-end_time": "05:00"})
        window = MealWindow.objects.get(meal_type=self.breakfast, special_period=period)
        self.assertEqual(window.start_time.strftime("%H:%M"), "04:00")
        self.client.post(url, {"action": "window", "window-meal": self.breakfast.pk, "window-start_time": "04:30", "window-end_time": "05:30"})
        self.assertEqual(MealWindow.objects.filter(meal_type=self.breakfast, special_period=period).count(), 1)
        self.client.post(reverse("setup:period_window_clear", args=[period.pk, self.breakfast.pk]))
        self.assertFalse(MealWindow.objects.filter(meal_type=self.breakfast, special_period=period).exists())
        self.assertTrue(MealWindow.objects.filter(meal_type=self.breakfast, special_period__isnull=True).exists())

    def test_period_time_must_end_after_it_starts(self):
        self.login()
        period = self.make_period()
        page = self.client.post(reverse("setup:period", args=[period.pk]),
                                {"action": "window", "window-meal": self.breakfast.pk, "window-start_time": "06:00", "window-end_time": "05:00"})
        self.assertContains(page, "must be after the start")

    def test_day_time_uses_the_period_window_when_there_is_one(self):
        self.login()
        period = self.make_period()
        own = MealWindow.objects.create(meal_type=self.breakfast, special_period=period, start_time="04:00", end_time="05:00")
        self.client.post(reverse("setup:period", args=[period.pk]),
                         {"action": "override", "day-meal": self.breakfast.pk, "day-date": "2026-11-10", "day-start_time": "04:10", "day-end_time": "05:10"})
        self.assertEqual(WindowOverride.objects.get().window, own)

    def test_day_time_falls_back_to_the_normal_window_and_is_replaced_on_repeat(self):
        self.login()
        period = self.make_period()
        normal = self.breakfast.windows.get()
        url = reverse("setup:period", args=[period.pk])
        for end in ("09:30", "10:00"):
            self.client.post(url, {"action": "override", "day-meal": self.breakfast.pk, "day-date": "2026-11-10",
                                   "day-start_time": "08:00", "day-end_time": end})
        override = WindowOverride.objects.get()
        self.assertEqual(override.window, normal)
        self.assertEqual(override.end_time.strftime("%H:%M"), "10:00")

    def test_day_time_must_be_inside_the_period_and_the_meal_needs_a_time(self):
        self.login()
        period = self.make_period()
        url = reverse("setup:period", args=[period.pk])
        page = self.client.post(url, {"action": "override", "day-meal": self.breakfast.pk, "day-date": "2026-12-05",
                                      "day-start_time": "08:00", "day-end_time": "09:00"})
        self.assertContains(page, "must be inside the period")
        iftaar = MealType.objects.create(organization=self.org, name="Iftaar")
        page = self.client.post(url, {"action": "override", "day-meal": iftaar.pk, "day-date": "2026-11-10",
                                      "day-start_time": "18:00", "day-end_time": "19:00"})
        self.assertContains(page, "no serving time in the period yet")
        self.assertFalse(WindowOverride.objects.exists())

    def test_skipped_meals_cannot_get_a_day_time(self):
        self.login()
        period = self.make_period()
        period.skipped_meals.add(self.breakfast)
        page = self.client.post(reverse("setup:period", args=[period.pk]),
                                {"action": "override", "day-meal": self.breakfast.pk, "day-date": "2026-11-10",
                                 "day-start_time": "08:00", "day-end_time": "09:00"})
        self.assertContains(page, "Select a valid choice")

    def test_delete_a_day_time_and_a_period(self):
        self.login()
        period = self.make_period()
        override = WindowOverride.objects.create(window=self.breakfast.windows.get(), date=date(2026, 11, 10),
                                                 start_time="08:00", end_time="09:00")
        self.client.post(reverse("setup:override_delete", args=[period.pk, override.pk]))
        self.assertFalse(WindowOverride.objects.exists())
        self.client.post(reverse("setup:period_delete", args=[period.pk]))
        self.assertFalse(SpecialPeriod.objects.filter(pk=period.pk).exists())

    def test_other_organisations_periods_are_out_of_reach(self):
        self.login()
        foreign = SpecialPeriod.objects.create(organization=self.other, name="F", start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
        self.assertEqual(self.client.get(reverse("setup:period", args=[foreign.pk])).status_code, 404)
        self.client.post(reverse("setup:period_delete", args=[foreign.pk]))
        self.assertTrue(SpecialPeriod.objects.filter(pk=foreign.pk).exists())

    def test_period_page_lists_each_meal_with_its_time(self):
        self.login()
        period = self.make_period()
        page = self.client.get(reverse("setup:period", args=[period.pk]))
        self.assertContains(page, "07:30")
        self.assertContains(page, "normal time")


class RamadanFromTheScreensTests(MealSetupBase):
    """Set Ramadan up only through the screens, then check what the counter would allow."""

    def test_ramadan_end_to_end(self):
        self.login()
        self.client.post(reverse("setup:meals"), {"name": "Iftaar", "sort_order": "4", "start_time": "", "end_time": ""})
        iftaar = MealType.objects.get(organization=self.org, name="Iftaar")
        self.client.post(reverse("setup:periods"), {
            "name": "Ramadan", "start_date": "2026-11-01", "end_date": "2026-11-30", "religion": "Muslim",
            "skipped_meals": [self.breakfast.pk],
        })
        period = SpecialPeriod.objects.get(name="Ramadan")
        url = reverse("setup:period", args=[period.pk])
        self.client.post(url, {"action": "window", "window-meal": iftaar.pk, "window-start_time": "17:50", "window-end_time": "18:30"})

        fasting = Student.objects.create(organization=self.org, roll_number="M1", name="Musa", gender="male",
                                         category=self.cat, diet=self.diet, religion="Muslim")
        other = Student.objects.create(organization=self.org, roll_number="H1", name="Hari", gender="male",
                                       category=self.cat, diet=self.diet, religion="Hindu")

        def at(h, m, day=10):
            return datetime(2026, 11, day, h, m, tzinfo=IST)

        self.assertEqual(current_meal(fasting, at(18, 0)).meal_type, iftaar)
        self.assertIsNone(current_meal(fasting, at(8, 0)))  # breakfast skipped for the fasting student
        self.assertEqual(current_meal(other, at(8, 0)).meal_type, self.breakfast)
        self.assertIsNone(current_meal(other, at(18, 0)))  # iftaar exists only inside the period

        # sunset moves later on the 11th
        self.client.post(url, {"action": "override", "day-meal": iftaar.pk, "day-date": "2026-11-11",
                               "day-start_time": "18:10", "day-end_time": "18:50"})
        self.assertIsNone(current_meal(fasting, at(18, 0, day=11)))
        self.assertEqual(current_meal(fasting, at(18, 40, day=11)).meal_type, iftaar)
        self.assertEqual(current_meal(fasting, at(18, 0, day=10)).meal_type, iftaar)  # other days unchanged


class HomeAndProgressTests(MealSetupBase):
    def test_home_checklist_and_progress_link_to_meal_setup(self):
        self.login()
        home = self.client.get(reverse("accounts:home"))
        self.assertContains(home, reverse("setup:meals"))
        self.assertContains(home, reverse("setup:counters"))
        self.assertContains(self.client.get(reverse("setup:index")), reverse("setup:meals"))


class RenderingTests(MealSetupBase):
    def test_tick_boxes_do_not_get_text_box_styling(self):
        self.login()
        page = self.client.get(reverse("setup:counter_edit", args=[self.counter.pk]))
        self.assertContains(page, "form-check-input")
        self.assertNotContains(page, "form-check-input form-control")
