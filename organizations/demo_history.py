"""Fictional test data for a whole organisation: students, photos, leave, roll calls, meals and Ramadan.

Everything is generated relative to "today" in the organisation's time zone, and the meal history is
produced with the real rule engine in mess.services, so the data follows the same rules as the live app.
"""
import random
from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.files.base import ContentFile

from attendance.models import ExitPermit, RollCall, RollCallEntry
from attendance.services import leave_states
from mess.models import Counter, MealCollection, MealType, MealWindow, SpecialPeriod, WindowOverride
from mess.services import period_for, window_times
from organizations import demo
from organizations.models import Category, DietType, Hostel, Room
from residents.models import RoomAllocation, Student
from residents.services import allocate_room, vacate_room

DESTINATIONS = ["Home town", "Bhubaneswar", "Cuttack", "Kolkata", "Patna", "Relative's house", "Hospital visit", "Delhi"]
REASONS = ["Family function", "Medical", "Festival", "Personal work", "Passport office", "Exam centre"]
EAT_CHANCE = {"breakfast": 0.85, "lunch": 0.9, "dinner": 0.92, "suhoor": 0.8, "iftaar": 0.95}


def wipe_organization_data(org):
    """Remove students, history and set-up rows of one organisation, in a safe order. Users and the organisation stay."""
    MealCollection.objects.filter(organization=org).delete()
    RollCall.objects.filter(organization=org).delete()
    ExitPermit.objects.filter(organization=org).delete()
    RoomAllocation.objects.filter(student__organization=org).delete()
    Student.objects.filter(organization=org).delete()
    WindowOverride.objects.filter(window__meal_type__organization=org).delete()
    MealWindow.objects.filter(meal_type__organization=org).delete()
    SpecialPeriod.objects.filter(organization=org).delete()
    Counter.objects.filter(organization=org).delete()
    MealType.objects.filter(organization=org).delete()
    Room.objects.filter(hostel__organization=org).delete()
    Hostel.objects.filter(organization=org).delete()
    Category.objects.filter(organization=org).delete()
    DietType.objects.filter(organization=org).delete()


def _make_students(org, rng, count, seed, with_photos, today, days):
    categories = {c.name: c for c in Category.objects.filter(organization=org)}
    diets = {d.name: d for d in DietType.objects.filter(organization=org)}
    rooms = {(r.hostel.name, r.number): r for r in Room.objects.filter(hostel__organization=org).select_related("hostel")}
    moved_in = today - timedelta(days=days + 2)
    students = []
    for index, row in enumerate(demo.generate_students(count, seed)):
        student = Student.objects.create(
            organization=org, roll_number=row["roll_number"], name=row["name"], gender=row["gender"],
            course=row["course"], department=row["department"], country=row["country"], state=row["state"],
            guardian_name=row["guardian_name"], guardian_phone=row["guardian_phone"], religion=row["religion"],
            category=categories[row["category"]], diet=diets[row["diet"]],
        )
        if with_photos:
            data = demo._avatar(row["name"], demo._COLOURS[index % len(demo._COLOURS)])
            student.photo.save(f"{row['roll_number']}.jpg", ContentFile(data), save=True)
        if row["hostel"]:
            allocate_room(student, rooms[(row["hostel"], row["room"])], moved_in)
        students.append(student)
    return students


def _move_one_student(org, students, today):
    """Give one student a room history by moving them to another room of the same hostel."""
    for student in students:
        current = student.current_room
        if current is None:
            continue
        for room in Room.objects.filter(hostel=current.hostel).exclude(pk=current.pk):
            if room.free_beds > 0:
                allocate_room(student, room, today - timedelta(days=3))
                return student
    return None


def _ramadan(org, today):
    """A period that is running now: iftaar and suhoor instead of breakfast and lunch, with iftaar moving daily."""
    meals = {m.name: m for m in MealType.objects.filter(organization=org)}
    suhoor, _ = MealType.objects.get_or_create(organization=org, name="Suhoor", defaults={"sort_order": 0})
    iftaar, _ = MealType.objects.get_or_create(organization=org, name="Iftaar", defaults={"sort_order": 4})
    period = SpecialPeriod.objects.create(
        organization=org, name="Ramadan (demo)", start_date=today - timedelta(days=5),
        end_date=today + timedelta(days=10), religion="Muslim",
    )
    skipped = [meals[n] for n in ("Breakfast", "Lunch") if n in meals]
    period.skipped_meals.set(skipped)
    MealWindow.objects.create(meal_type=suhoor, special_period=period, start_time=time(4, 0), end_time=time(5, 15))
    iftaar_window = MealWindow.objects.create(meal_type=iftaar, special_period=period, start_time=time(17, 50), end_time=time(18, 40))
    if "Dinner" in meals:
        MealWindow.objects.create(meal_type=meals["Dinner"], special_period=period, start_time=time(20, 30), end_time=time(22, 0))
    # sunset moves a little every day, so iftaar opens a minute later each day
    for offset in range((period.end_date - period.start_date).days + 1):
        start = datetime(2000, 1, 1, 17, 48) + timedelta(minutes=offset)
        WindowOverride.objects.create(
            window=iftaar_window, date=period.start_date + timedelta(days=offset),
            start_time=start.time(), end_time=(start + timedelta(minutes=50)).time(),
        )
    return period


def _permits(org, rng, students, staff_user, today):
    """Leave in every state: upcoming, on leave, overdue, returned (some late) and cancelled."""
    housed = [s for s in students if s.current_room is not None]
    rng.shuffle(housed)
    taken = {"upcoming": 4, "on_leave": 5, "overdue": 3, "returned": 6, "cancelled": 1}
    plan = {}
    for kind, count in taken.items():
        plan[kind] = [housed.pop() for _ in range(min(count, len(housed)))]

    def make(student, start, end, **extra):
        return ExitPermit.objects.create(
            organization=org, student=student, start_date=start, end_date=end,
            destination=rng.choice(DESTINATIONS), reason=rng.choice(REASONS), granted_by=staff_user, **extra,
        )

    for student in plan["upcoming"]:
        start = today + timedelta(days=rng.randint(2, 6))
        make(student, start, start + timedelta(days=rng.randint(1, 4)))
    for student in plan["on_leave"]:
        make(student, today - timedelta(days=rng.randint(1, 4)), today + timedelta(days=rng.randint(0, 4)))
    for student, late in zip(plan["overdue"], (1, 2, 4)):
        end = today - timedelta(days=late)
        make(student, end - timedelta(days=3), end)
    for number, student in enumerate(plan["returned"]):
        start = today - timedelta(days=rng.randint(8, 12))
        end = start + timedelta(days=rng.randint(1, 3))
        make(student, start, end, returned_on=end + timedelta(days=1 if number == 0 else 0))
    for student in plan["cancelled"]:
        start = today + timedelta(days=8)
        make(student, start, start + timedelta(days=1), cancelled=True)
    return {kind: len(items) for kind, items in plan.items()}


def _roll_calls(org, rng, hostels, staff_user, today, days):
    entries = []
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        for hostel in hostels:
            housed = list(
                RoomAllocation.objects.filter(end_date__isnull=True, room__hostel=hostel).values_list("student_id", flat=True)
            )
            if not housed:
                continue
            states = leave_states(housed, day)
            call = RollCall.objects.create(organization=org, hostel=hostel, date=day, taken_by=staff_user)
            for student_id in housed:
                state = states.get(student_id)
                if state and state.state == ExitPermit.ON_LEAVE:
                    entries.append(RollCallEntry(roll_call=call, student_id=student_id, status="on_leave", permit=state.permit))
                elif state:
                    entries.append(RollCallEntry(roll_call=call, student_id=student_id, status="absent",
                                                 permit=state.permit, days_overdue=state.days_overdue))
                elif rng.random() < 0.03:
                    entries.append(RollCallEntry(roll_call=call, student_id=student_id, status="absent"))
                else:
                    entries.append(RollCallEntry(roll_call=call, student_id=student_id, status="present"))
    RollCallEntry.objects.bulk_create(entries, batch_size=500)
    return len(entries)


def _meal_history(org, rng, students, staff_user, today, days):
    tz = ZoneInfo(org.timezone)
    meals = list(MealType.objects.filter(organization=org))
    counters = list(Counter.objects.filter(organization=org).prefetch_related("categories"))

    def counter_for(student):
        for counter in counters:
            ids = {c.pk for c in counter.categories.all()}
            if not ids or student.category_id in ids:
                return counter
        return None

    stamps, rows = {}, []
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        away = leave_states([s.pk for s in students], day)
        for student in students:
            counter = counter_for(student)
            if counter is None or student.pk in away:
                continue
            period = period_for(student, day)
            skipped = set(period.skipped_meals.values_list("pk", flat=True)) if period else set()
            for meal in meals:
                if meal.pk in skipped:
                    continue
                times = window_times(meal, period, day)
                if times is None or rng.random() > EAT_CHANCE.get(meal.name.lower(), 0.8):
                    continue
                start = datetime.combine(day, times[0], tzinfo=tz)
                length = int((datetime.combine(day, times[1]) - datetime.combine(day, times[0])).total_seconds())
                stamps[(student.pk, meal.pk, day)] = start + timedelta(seconds=rng.randint(0, max(length, 1)))
                rows.append(MealCollection(organization=org, student=student, meal_type=meal, date=day,
                                           counter=counter, recorded_by=staff_user))
    MealCollection.objects.bulk_create(rows, batch_size=500)
    # created_at is filled automatically on insert, so set the real serving times afterwards
    saved = list(MealCollection.objects.filter(organization=org, date__lt=today))
    for row in saved:
        row.created_at = stamps[(row.student_id, row.meal_type_id, row.date)]
    MealCollection.objects.bulk_update(saved, ["created_at"], batch_size=500)
    return len(saved)


def seed_history(org, hostels, staff_user, students=60, days=14, seed=2026, photos=True):
    """Fill an organisation that has no students yet. Returns a dict of counts."""
    rng = random.Random(seed)
    today = org.local_today()
    people = _make_students(org, rng, students, seed, photos, today, days)
    moved = _move_one_student(org, people, today)
    permits = _permits(org, rng, people, staff_user, today)
    period = _ramadan(org, today)
    roll_entries = _roll_calls(org, rng, hostels, staff_user, today, days)
    collections = _meal_history(org, rng, people, staff_user, today, days)

    # two students have left the hostel (their history stays)
    leavers = [s for s in people if s.current_room is not None and s.pk != getattr(moved, "pk", None)
               and not s.permits.exists()][:2]
    for student in leavers:
        vacate_room(student, today - timedelta(days=1))
        student.status = Student.Status.LEFT
        student.save(update_fields=["status"])
    return {
        "students": len(people), "left": len(leavers), "permits": permits, "period": period.name,
        "roll_call_entries": roll_entries, "meals_served": collections, "moved": getattr(moved, "name", None),
    }
