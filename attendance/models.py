"""Exit permits and the night roll call.

The system only records facts. It never charges fines: the roll-call records say who was
present, on permitted leave, or absent (and how many days overdue), and the central
administration decides what to charge from the reports.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from organizations.models import Hostel, Organization
from residents.models import Student


def fmt(day):
    return f"{day.day} {day:%b}"


def days(n):
    return f"{n} day{'' if n == 1 else 's'}"


class ExitPermit(models.Model):
    """Permission for a student to be away from start_date to end_date (both nights included).

    The student is marked absent from the night after end_date unless the return is recorded.
    """

    ON_LEAVE = "on_leave"
    OVERDUE = "overdue"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="permits")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="permits")
    start_date = models.DateField()
    end_date = models.DateField()
    destination = models.CharField(max_length=200, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    granted_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    # The day the student came back. They count as present for that night's roll call.
    returned_on = models.DateField(null=True, blank=True)
    cancelled = models.BooleanField(default=False)

    class Meta:
        ordering = ["-start_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="permit_end_not_before_start"),
            models.CheckConstraint(
                condition=Q(returned_on__isnull=True) | Q(returned_on__gte=F("start_date")),
                name="permit_return_not_before_start",
            ),
        ]

    def __str__(self):
        return f"{self.student} {self.start_date} to {self.end_date}"

    def clean(self):
        if self.student_id and self.student.organization_id != self.organization_id:
            raise ValidationError("The student belongs to a different organisation.")

    @property
    def absent_from(self):
        """First night the student is marked absent if they have not returned."""
        return self.end_date + timedelta(days=1)

    def days_until_absent(self, today):
        return (self.absent_from - today).days

    def last_day_covered(self):
        if self.returned_on is None:
            return self.end_date
        return min(self.end_date, self.returned_on - timedelta(days=1))

    def state_on(self, day):
        """How this permit counts for the roll call of `day`: ON_LEAVE, OVERDUE, or None."""
        if self.cancelled:
            return None
        if self.start_date <= day <= self.last_day_covered():
            return self.ON_LEAVE
        if day > self.end_date and (self.returned_on is None or day < self.returned_on):
            return self.OVERDUE
        return None

    def days_overdue_on(self, day):
        return (day - self.end_date).days if self.state_on(day) == self.OVERDUE else 0

    def status_on(self, day):
        """Plain status of the permit as of `day`: cancelled, returned, upcoming, on_leave, overdue."""
        if self.cancelled:
            return "cancelled"
        if self.returned_on is not None and day >= self.returned_on:
            return "returned"
        if day < self.start_date:
            return "upcoming"
        if day <= self.end_date:
            return "on_leave"
        return "overdue"

    def describe(self, today):
        status = self.status_on(today)
        if status == "cancelled":
            return "Cancelled"
        if status == "returned":
            return f"Returned {fmt(self.returned_on)}"
        if status == "upcoming":
            return f"Upcoming: {fmt(self.start_date)} to {fmt(self.end_date)}"
        if status == "on_leave":
            return (
                f"On leave until {fmt(self.end_date)}; marked absent from {fmt(self.absent_from)} "
                f"(in {days(self.days_until_absent(today))})"
            )
        return f"Overdue by {days((today - self.end_date).days)} - was due back {fmt(self.end_date)}"


class RollCall(models.Model):
    """The night roll call of one hostel on one date."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="roll_calls")
    hostel = models.ForeignKey(Hostel, on_delete=models.PROTECT, related_name="roll_calls")
    date = models.DateField()
    taken_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "hostel__name"]
        constraints = [
            models.UniqueConstraint(fields=["hostel", "date"], name="one_roll_call_per_hostel_per_day"),
        ]

    def __str__(self):
        return f"{self.hostel} {self.date}"


class RollCallEntry(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        ON_LEAVE = "on_leave", "On permitted leave"

    roll_call = models.ForeignKey(RollCall, on_delete=models.CASCADE, related_name="entries")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="roll_call_entries")
    status = models.CharField(max_length=10, choices=Status.choices)
    # The permit that explains an ON_LEAVE entry, or the expired permit behind an overdue ABSENT entry.
    permit = models.ForeignKey(ExitPermit, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # Days past the end of the permit (0 for ordinary absences).
    days_overdue = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["roll_call", "student"], name="one_entry_per_student_per_roll_call"),
        ]

    def __str__(self):
        return f"{self.student} {self.status}"
