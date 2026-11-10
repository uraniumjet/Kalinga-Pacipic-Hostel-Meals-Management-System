from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from organizations.models import Category, DietType, Hostel, Organization, Room
from residents.models import RoomAllocation, Student
from residents.services import allocate_room, vacate_room


class AllocationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test University", slug="test")
        self.intl = Category.objects.create(organization=self.org, name="International")
        self.veg = DietType.objects.create(organization=self.org, name="Vegetarian")
        self.boys = Hostel.objects.create(organization=self.org, name="Boys A", gender="male")
        self.girls = Hostel.objects.create(organization=self.org, name="Girls A", gender="female")
        self.room2 = Room.objects.create(hostel=self.boys, number="101", capacity=2)
        self.room4 = Room.objects.create(hostel=self.boys, number="102", capacity=4)
        self.girls_room = Room.objects.create(hostel=self.girls, number="201", capacity=2)

    def student(self, roll, gender="male"):
        return Student.objects.create(
            organization=self.org, roll_number=roll, name=f"Student {roll}",
            gender=gender, category=self.intl, diet=self.veg,
        )

    def test_roll_number_unique_per_organization(self):
        self.student("R1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.student("R1")

    def test_allocation_sets_current_room(self):
        s = self.student("R1")
        allocate_room(s, self.room2, date(2026, 8, 1))
        self.assertEqual(s.current_room, self.room2)
        self.assertEqual(self.room2.free_beds, 1)

    def test_room_capacity_is_enforced(self):
        a, b, c = self.student("R1"), self.student("R2"), self.student("R3")
        allocate_room(a, self.room2, date(2026, 8, 1))
        allocate_room(b, self.room2, date(2026, 8, 1))
        with self.assertRaises(ValidationError):
            allocate_room(c, self.room2, date(2026, 8, 1))
        self.assertEqual(self.room2.free_beds, 0)

    def test_gender_must_match_hostel(self):
        girl = self.student("R9", gender="female")
        with self.assertRaises(ValidationError):
            allocate_room(girl, self.room2, date(2026, 8, 1))
        allocate_room(girl, self.girls_room, date(2026, 8, 1))

    def test_transfer_keeps_history(self):
        s = self.student("R1")
        allocate_room(s, self.room2, date(2026, 8, 1))
        allocate_room(s, self.room4, date(2026, 10, 1))
        self.assertEqual(s.current_room, self.room4)
        self.assertEqual(RoomAllocation.objects.filter(student=s).count(), 2)
        old = RoomAllocation.objects.get(student=s, room=self.room2)
        self.assertEqual(old.end_date, date(2026, 10, 1))
        self.assertEqual(self.room2.free_beds, 2)

    def test_cannot_move_into_same_room(self):
        s = self.student("R1")
        allocate_room(s, self.room2, date(2026, 8, 1))
        with self.assertRaises(ValidationError):
            allocate_room(s, self.room2, date(2026, 9, 1))

    def test_database_blocks_two_current_rooms(self):
        s = self.student("R1")
        RoomAllocation.objects.create(student=s, room=self.room2, start_date=date(2026, 8, 1))
        with self.assertRaises(IntegrityError), transaction.atomic():
            RoomAllocation.objects.create(student=s, room=self.room4, start_date=date(2026, 8, 2))

    def test_vacate(self):
        s = self.student("R1")
        allocate_room(s, self.room2, date(2026, 8, 1))
        vacate_room(s, date(2026, 12, 1))
        self.assertIsNone(s.current_room)
        with self.assertRaises(ValidationError):
            vacate_room(s, date(2026, 12, 2))

    def test_category_must_match_organization(self):
        other = Organization.objects.create(name="Other", slug="other")
        foreign = Category.objects.create(organization=other, name="International")
        s = Student(organization=self.org, roll_number="X", name="X", gender="male", category=foreign, diet=self.veg)
        with self.assertRaises(ValidationError):
            s.full_clean()
