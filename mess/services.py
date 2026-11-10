"""Meal rules. Views must call record_collection and must not create collections directly."""
from dataclasses import dataclass
from datetime import date, time
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import MealCollection, MealType


class CollectionDenied(Exception):
    """A collection that is refused. `code` is stable and meant for the UI."""

    NOT_ACTIVE = "not_active"
    WRONG_ORGANIZATION = "wrong_organization"
    WRONG_COUNTER = "wrong_counter"
    NO_MEAL_NOW = "no_meal_now"
    ALREADY_COLLECTED = "already_collected"
    BAD_COLLECTOR = "bad_collector"

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MealSlot:
    meal_type: MealType
    day: date
    start: time
    end: time


def local_now(organization, now=None):
    now = now or timezone.now()
    return timezone.localtime(now, ZoneInfo(organization.timezone))


def period_for(student, day):
    """The special period that applies to this student on this date, if any (earliest start wins)."""
    candidates = student.organization.special_periods.filter(start_date__lte=day, end_date__gte=day)
    for period in candidates.order_by("start_date", "id"):
        if period.applies_to(student):
            return period
    return None


def window_times(meal, period, day):
    """(start, end) for a meal on a day: date override, else period window, else normal window."""
    window = None
    if period is not None:
        window = meal.windows.filter(special_period=period).first()
    if window is None:
        window = meal.windows.filter(special_period__isnull=True).first()
    if window is None:
        return None
    override = window.overrides.filter(date=day).first()
    if override:
        return override.start_time, override.end_time
    return window.start_time, window.end_time


def current_meal(student, now=None):
    """The meal this student may collect right now, or None."""
    local = local_now(student.organization, now)
    day, t = local.date(), local.time()
    period = period_for(student, day)
    skipped = set(period.skipped_meals.values_list("pk", flat=True)) if period else set()
    matches = []
    for meal in student.organization.meal_types.all():
        if meal.pk in skipped:
            continue
        times = window_times(meal, period, day)
        if times and times[0] <= t <= times[1]:
            matches.append(MealSlot(meal, day, times[0], times[1]))
    if not matches:
        return None
    return min(matches, key=lambda slot: slot.start)


def check_collection(student, counter, collected_by=None, now=None):
    """Check the rules without writing anything.

    Returns (slot, collector) when the collection is allowed, otherwise raises CollectionDenied.
    """
    if student.status != student.Status.ACTIVE:
        raise CollectionDenied(CollectionDenied.NOT_ACTIVE, "This student is not active.")
    if counter.organization_id != student.organization_id:
        raise CollectionDenied(CollectionDenied.WRONG_ORGANIZATION, "The counter belongs to another organisation.")

    collector = None
    if collected_by is not None and collected_by.pk != student.pk:
        if collected_by.organization_id != student.organization_id or collected_by.status != collected_by.Status.ACTIVE:
            raise CollectionDenied(CollectionDenied.BAD_COLLECTOR, "The collecting student is not valid.")
        collector = collected_by

    if counter.categories.exists() and not counter.categories.filter(pk=student.category_id).exists():
        raise CollectionDenied(
            CollectionDenied.WRONG_COUNTER, f"{student.name} is not served at the {counter.name} counter."
        )

    slot = current_meal(student, now)
    if slot is None:
        raise CollectionDenied(CollectionDenied.NO_MEAL_NOW, f"No meal is being served to {student.name} now.")

    existing = MealCollection.objects.filter(student=student, meal_type=slot.meal_type, date=slot.day).first()
    if existing:
        at = timezone.localtime(existing.created_at, ZoneInfo(student.organization.timezone))
        raise CollectionDenied(
            CollectionDenied.ALREADY_COLLECTED,
            f"{slot.meal_type.name} was already collected by {student.name} at {at:%H:%M}.",
        )
    return slot, collector


def record_collection(student, counter, recorded_by=None, collected_by=None, now=None):
    """Record that a student's meal was served. Raises CollectionDenied if a rule is broken.

    collected_by: optional audit field for a friend who collected the meal (the counter screen
    leaves it empty: a proxy collection is recorded as if the student came in person).
    """
    slot, collector = check_collection(student, counter, collected_by, now)
    try:
        with transaction.atomic():
            return MealCollection.objects.create(
                organization=student.organization,
                student=student,
                meal_type=slot.meal_type,
                date=slot.day,
                counter=counter,
                collected_by=collector,
                recorded_by=recorded_by,
            )
    except IntegrityError:
        raise CollectionDenied(
            CollectionDenied.ALREADY_COLLECTED, f"{slot.meal_type.name} was already collected by {student.name}."
        )
