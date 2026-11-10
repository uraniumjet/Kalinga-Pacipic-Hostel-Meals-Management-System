"""Meal configuration and meal collection records.

Meal times, counters and special periods (Ramadan, Navratri, ...) are data that an
administrator edits. No institution-specific rule is written into the code.

Times are local to the organisation (Organization.timezone). A window must not
cross midnight.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from organizations.models import Category, Organization
from residents.models import Student


class MealType(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="meal_types")
    name = models.CharField(max_length=50)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="uniq_meal_per_org")]

    def __str__(self):
        return self.name


class Counter(models.Model):
    """A serving counter. An empty category list means it serves every student."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="counters")
    name = models.CharField(max_length=100)
    categories = models.ManyToManyField(Category, blank=True, related_name="counters")

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="uniq_counter_per_org")]

    def __str__(self):
        return self.name


class SpecialPeriod(models.Model):
    """A date range with different meal rules for some students (e.g. Ramadan).

    Which students: religion (case-insensitive text, blank = any) and categories
    (empty = any). Both must match. Meals listed in skipped_meals are not served
    during the period. A MealWindow linked to the period replaces the normal window
    of that meal.
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="special_periods")
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    religion = models.CharField(max_length=50, blank=True)
    categories = models.ManyToManyField(Category, blank=True, related_name="special_periods")
    skipped_meals = models.ManyToManyField(MealType, blank=True, related_name="skipped_in_periods")

    class Meta:
        ordering = ["start_date", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="period_end_not_before_start"),
        ]

    def __str__(self):
        return f"{self.name} ({self.start_date} to {self.end_date})"

    def applies_to(self, student):
        if self.religion and student.religion.strip().lower() != self.religion.strip().lower():
            return False
        if self.categories.exists() and not self.categories.filter(pk=student.category_id).exists():
            return False
        return True


class MealWindow(models.Model):
    """Serving time of a meal. special_period empty = the normal window."""

    meal_type = models.ForeignKey(MealType, on_delete=models.CASCADE, related_name="windows")
    special_period = models.ForeignKey(
        SpecialPeriod, on_delete=models.CASCADE, null=True, blank=True, related_name="windows"
    )
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["meal_type__sort_order", "start_time"]
        constraints = [
            models.CheckConstraint(condition=Q(start_time__lt=F("end_time")), name="window_start_before_end"),
            models.UniqueConstraint(
                fields=["meal_type", "special_period"],
                condition=Q(special_period__isnull=False),
                name="uniq_special_window_per_meal",
            ),
            models.UniqueConstraint(
                fields=["meal_type"],
                condition=Q(special_period__isnull=True),
                name="uniq_default_window_per_meal",
            ),
        ]

    def __str__(self):
        scope = self.special_period.name if self.special_period_id else "normal"
        return f"{self.meal_type} {self.start_time:%H:%M}-{self.end_time:%H:%M} ({scope})"

    def clean(self):
        if self.special_period_id and self.meal_type_id:
            if self.special_period.organization_id != self.meal_type.organization_id:
                raise ValidationError("The meal and the special period must belong to the same organisation.")


class WindowOverride(models.Model):
    """Change a window for one date only, e.g. the Iftar time that moves with sunset."""

    window = models.ForeignKey(MealWindow, on_delete=models.CASCADE, related_name="overrides")
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["window", "date"], name="uniq_override_per_window_date"),
            models.CheckConstraint(condition=Q(start_time__lt=F("end_time")), name="override_start_before_end"),
        ]

    def __str__(self):
        return f"{self.window.meal_type} on {self.date}: {self.start_time:%H:%M}-{self.end_time:%H:%M}"


class MealCollection(models.Model):
    """One row per meal served to a student. The database allows one per student, meal and day."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="collections")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="collections")
    meal_type = models.ForeignKey(MealType, on_delete=models.PROTECT, related_name="collections")
    date = models.DateField()
    counter = models.ForeignKey(Counter, on_delete=models.PROTECT, related_name="collections")
    # Set when a friend collected the meal for the student (proxy collection).
    collected_by = models.ForeignKey(
        Student, on_delete=models.PROTECT, null=True, blank=True, related_name="collected_for_others"
    )
    recorded_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["student", "meal_type", "date"], name="one_collection_per_meal_per_day"),
        ]

    def __str__(self):
        return f"{self.student} - {self.meal_type} - {self.date}"
