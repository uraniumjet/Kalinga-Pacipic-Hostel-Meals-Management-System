from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase

from mess.models import Counter, MealType, MealWindow, SpecialPeriod, WindowOverride
from mess.services import CollectionDenied, current_meal, record_collection
from organizations.models import Category, DietType, Organization
from residents.models import Student

IST = ZoneInfo("Asia/Kolkata")


def at(h, m=0, day=10):
    """An aware datetime on 2026-11-<day> in local (Indian) time."""
    return datetime(2026, 11, day, h, m, tzinfo=IST)


class MealRuleTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test University", slug="test", timezone="Asia/Kolkata")
        self.intl = Category.objects.create(organization=self.org, name="International")
        self.natl = Category.objects.create(organization=self.org, name="National")
        self.diet = DietType.objects.create(organization=self.org, name="Veg")
        self.breakfast = MealType.objects.create(organization=self.org, name="Breakfast", sort_order=1)
        self.lunch = MealType.objects.create(organization=self.org, name="Lunch", sort_order=2)
        self.dinner = MealType.objects.create(organization=self.org, name="Dinner", sort_order=3)
        MealWindow.objects.create(meal_type=self.breakfast, start_time=time(7, 30), end_time=time(9, 0))
        MealWindow.objects.create(meal_type=self.lunch, start_time=time(12, 30), end_time=time(14, 0))
        self.dinner_window = MealWindow.objects.create(meal_type=self.dinner, start_time=time(19, 30), end_time=time(21, 0))
        self.intl_counter = Counter.objects.create(organization=self.org, name="International")
        self.intl_counter.categories.add(self.intl)
        self.natl_counter = Counter.objects.create(organization=self.org, name="National")
        self.natl_counter.categories.add(self.natl)
        self.warden = User.objects.create_user("warden", password="x")

    def student(self, roll, category=None, religion="", status="active"):
        return Student.objects.create(
            organization=self.org, roll_number=roll, name=f"Student {roll}", gender="male",
            category=category or self.intl, diet=self.diet, religion=religion, status=status,
        )

    def test_collection_inside_window(self):
        s = self.student("R1")
        c = record_collection(s, self.intl_counter, self.warden, now=at(8, 0))
        self.assertEqual(c.meal_type, self.breakfast)
        self.assertEqual(c.date, date(2026, 11, 10))
        self.assertIsNone(c.collected_by)

    def test_window_edges_are_inclusive(self):
        s = self.student("R1")
        record_collection(s, self.intl_counter, now=at(7, 30))
        s2 = self.student("R2")
        record_collection(s2, self.intl_counter, now=at(9, 0))

    def test_outside_any_window_is_denied(self):
        s = self.student("R1")
        with self.assertRaises(CollectionDenied) as ctx:
            record_collection(s, self.intl_counter, now=at(11, 0))
        self.assertEqual(ctx.exception.code, CollectionDenied.NO_MEAL_NOW)

    def test_second_collection_is_denied(self):
        s = self.student("R1")
        record_collection(s, self.intl_counter, now=at(8, 0))
        with self.assertRaises(CollectionDenied) as ctx:
            record_collection(s, self.intl_counter, now=at(8, 30))
        self.assertEqual(ctx.exception.code, CollectionDenied.ALREADY_COLLECTED)

    def test_next_day_is_a_new_collection(self):
        s = self.student("R1")
        record_collection(s, self.intl_counter, now=at(8, 0, day=10))
        record_collection(s, self.intl_counter, now=at(8, 0, day=11))

    def test_wrong_counter_is_denied(self):
        national = self.student("R1", category=self.natl)
        with self.assertRaises(CollectionDenied) as ctx:
            record_collection(national, self.intl_counter, now=at(8, 0))
        self.assertEqual(ctx.exception.code, CollectionDenied.WRONG_COUNTER)

    def test_counter_without_categories_serves_everyone(self):
        open_counter = Counter.objects.create(organization=self.org, name="Open")
        record_collection(self.student("R1", category=self.natl), open_counter, now=at(8, 0))

    def test_inactive_student_is_denied(self):
        gone = self.student("R1", status="left")
        with self.assertRaises(CollectionDenied) as ctx:
            record_collection(gone, self.intl_counter, now=at(8, 0))
        self.assertEqual(ctx.exception.code, CollectionDenied.NOT_ACTIVE)

    def test_proxy_collection_for_several_friends(self):
        friend = self.student("F1")
        a, b = self.student("A1"), self.student("A2")
        own = record_collection(friend, self.intl_counter, now=at(8, 0))
        for absent in (a, b):
            c = record_collection(absent, self.intl_counter, self.warden, collected_by=friend, now=at(8, 5))
            self.assertEqual(c.collected_by, friend)
        self.assertIsNone(own.collected_by)
        # A friend's own meal is unaffected, and a friend cannot collect twice for the same student.
        with self.assertRaises(CollectionDenied) as ctx:
            record_collection(a, self.intl_counter, collected_by=friend, now=at(8, 10))
        self.assertEqual(ctx.exception.code, CollectionDenied.ALREADY_COLLECTED)

    def test_proxy_blocks_later_self_collection(self):
        friend, absent = self.student("F1"), self.student("A1")
        record_collection(absent, self.intl_counter, collected_by=friend, now=at(8, 0))
        with self.assertRaises(CollectionDenied):
            record_collection(absent, self.intl_counter, now=at(8, 20))

    def test_proxy_with_inactive_collector_is_denied(self):
        gone, absent = self.student("F1", status="left"), self.student("A1")
        with self.assertRaises(CollectionDenied) as ctx:
            record_collection(absent, self.intl_counter, collected_by=gone, now=at(8, 0))
        self.assertEqual(ctx.exception.code, CollectionDenied.BAD_COLLECTOR)

    def test_other_organization_counter_is_denied(self):
        other = Organization.objects.create(name="Other", slug="other")
        foreign_counter = Counter.objects.create(organization=other, name="X")
        with self.assertRaises(CollectionDenied) as ctx:
            record_collection(self.student("R1"), foreign_counter, now=at(8, 0))
        self.assertEqual(ctx.exception.code, CollectionDenied.WRONG_ORGANIZATION)

    def test_organization_timezone_decides_the_local_time(self):
        # 02:30 UTC is 08:00 in Kolkata, inside breakfast.
        s = self.student("R1")
        utc_time = datetime(2026, 11, 10, 2, 30, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(current_meal(s, utc_time).meal_type, self.breakfast)


class SpecialPeriodTests(TestCase):
    """Ramadan-style rules: no breakfast, lunch moved to the afternoon, dinner at a daily Iftar time."""

    def setUp(self):
        self.org = Organization.objects.create(name="Test University", slug="test", timezone="Asia/Kolkata")
        self.cat = Category.objects.create(organization=self.org, name="National")
        self.diet = DietType.objects.create(organization=self.org, name="Veg")
        self.breakfast = MealType.objects.create(organization=self.org, name="Breakfast", sort_order=1)
        self.lunch = MealType.objects.create(organization=self.org, name="Lunch", sort_order=2)
        self.dinner = MealType.objects.create(organization=self.org, name="Dinner", sort_order=3)
        MealWindow.objects.create(meal_type=self.breakfast, start_time=time(7, 30), end_time=time(9, 0))
        MealWindow.objects.create(meal_type=self.lunch, start_time=time(12, 30), end_time=time(14, 0))
        MealWindow.objects.create(meal_type=self.dinner, start_time=time(19, 30), end_time=time(21, 0))
        self.counter = Counter.objects.create(organization=self.org, name="Main")
        self.period = SpecialPeriod.objects.create(
            organization=self.org, name="Ramadan", religion="muslim",
            start_date=date(2026, 11, 5), end_date=date(2026, 11, 20),
        )
        self.period.skipped_meals.add(self.breakfast)
        MealWindow.objects.create(
            meal_type=self.lunch, special_period=self.period, start_time=time(15, 30), end_time=time(17, 0)
        )
        self.iftar_window = MealWindow.objects.create(
            meal_type=self.dinner, special_period=self.period, start_time=time(18, 0), end_time=time(19, 30)
        )
        self.muslim = self.make("M1", "Muslim")
        self.other = self.make("O1", "Hindu")

    def make(self, roll, religion):
        return Student.objects.create(
            organization=self.org, roll_number=roll, name=f"Student {roll}", gender="male",
            category=self.cat, diet=self.diet, religion=religion,
        )

    def test_no_breakfast_for_fasting_students(self):
        with self.assertRaises(CollectionDenied) as ctx:
            record_collection(self.muslim, self.counter, now=at(8, 0))
        self.assertEqual(ctx.exception.code, CollectionDenied.NO_MEAL_NOW)

    def test_other_students_keep_normal_breakfast(self):
        self.assertEqual(current_meal(self.other, at(8, 0)).meal_type, self.breakfast)

    def test_lunch_moves_to_the_afternoon(self):
        self.assertIsNone(current_meal(self.muslim, at(13, 0)))
        self.assertEqual(current_meal(self.muslim, at(16, 0)).meal_type, self.lunch)
        self.assertEqual(current_meal(self.other, at(13, 0)).meal_type, self.lunch)
        self.assertIsNone(current_meal(self.other, at(16, 0)))

    def test_period_dates_are_inclusive_and_end(self):
        self.assertIsNone(current_meal(self.muslim, at(8, 0, day=5)))
        self.assertIsNone(current_meal(self.muslim, at(8, 0, day=20)))
        self.assertEqual(current_meal(self.muslim, at(8, 0, day=21)).meal_type, self.breakfast)
        self.assertEqual(current_meal(self.muslim, at(8, 0, day=4)).meal_type, self.breakfast)

    def test_iftar_time_can_be_set_for_a_single_day(self):
        WindowOverride.objects.create(
            window=self.iftar_window, date=date(2026, 11, 10), start_time=time(17, 23), end_time=time(18, 53)
        )
        self.assertEqual(current_meal(self.muslim, at(17, 30, day=10)).meal_type, self.dinner)
        self.assertIsNone(current_meal(self.muslim, at(17, 10, day=10)))
        # The next day still uses the period window.
        self.assertIsNone(current_meal(self.muslim, at(17, 30, day=11)))
        self.assertEqual(current_meal(self.muslim, at(18, 30, day=11)).meal_type, self.dinner)

    def test_religion_match_ignores_case_and_spaces(self):
        loud = self.make("M2", "  MUSLIM ")
        self.assertIsNone(current_meal(loud, at(8, 0)))
