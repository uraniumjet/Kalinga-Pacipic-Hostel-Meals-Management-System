import uuid

from django.core.exceptions import ValidationError
from django.db import models

from organizations.models import Category, DietType, Gender, Organization, Room


class Student(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        LEFT = "left", "Left"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="students")
    roll_number = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    gender = models.CharField(max_length=10, choices=Gender.choices)
    course = models.CharField(max_length=150, blank=True)
    department = models.CharField(max_length=150, blank=True)
    country = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    photo = models.ImageField(upload_to="student_photos/", blank=True)
    guardian_name = models.CharField(max_length=200, blank=True)
    guardian_phone = models.CharField(max_length=30, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="students")
    diet = models.ForeignKey(DietType, on_delete=models.PROTECT, related_name="students")
    religion = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    # Value encoded in the printed QR card. Random, so it cannot be guessed from a roll number.
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "roll_number"], name="uniq_roll_per_org"),
        ]

    def __str__(self):
        return f"{self.name} ({self.roll_number})"

    def clean(self):
        for field in ("category", "diet"):
            related = getattr(self, field, None)
            if related is not None and related.organization_id != self.organization_id:
                raise ValidationError({field: "Must belong to the same organisation as the student."})

    @property
    def current_allocation(self):
        return self.allocations.filter(end_date__isnull=True).select_related("room__hostel").first()

    @property
    def current_room(self):
        allocation = self.current_allocation
        return allocation.room if allocation else None


class RoomAllocation(models.Model):
    """One row per stay in a room. The current room is the row with no end date."""

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="allocations")
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="allocations")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["student"],
                condition=models.Q(end_date__isnull=True),
                name="one_current_room_per_student",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True) | models.Q(end_date__gte=models.F("start_date")),
                name="allocation_end_not_before_start",
            ),
        ]

    def __str__(self):
        return f"{self.student} -> {self.room}"
