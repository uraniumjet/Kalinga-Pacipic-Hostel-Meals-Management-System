"""Organisation-level setup: who uses the system and how it is laid out.

Nothing here is specific to one institution. Categories, diet types, hostels
and rooms are rows that an administrator creates, not hard-coded choices.
"""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Organization(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    logo = models.ImageField(upload_to="org_logos/", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Category(models.Model):
    """Student category, e.g. International / National. Defined per organisation."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="uniq_category_per_org"),
        ]

    def __str__(self):
        return self.name


class DietType(models.Model):
    """Diet type, e.g. Vegetarian / Non-vegetarian. Defined per organisation."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="diet_types")
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="uniq_diet_per_org"),
        ]

    def __str__(self):
        return self.name


class Gender(models.TextChoices):
    MALE = "male", "Male"
    FEMALE = "female", "Female"


class Hostel(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="hostels")
    name = models.CharField(max_length=100)
    gender = models.CharField(max_length=10, choices=Gender.choices)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="uniq_hostel_per_org"),
        ]

    def __str__(self):
        return self.name


class Room(models.Model):
    hostel = models.ForeignKey(Hostel, on_delete=models.CASCADE, related_name="rooms")
    number = models.CharField(max_length=20)
    capacity = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ["hostel__name", "number"]
        constraints = [
            models.UniqueConstraint(fields=["hostel", "number"], name="uniq_room_per_hostel"),
        ]

    def __str__(self):
        return f"{self.hostel.name} / {self.number}"

    @property
    def occupancy(self):
        return self.allocations.filter(end_date__isnull=True).count()

    @property
    def free_beds(self):
        return self.capacity - self.occupancy


class StaffProfile(models.Model):
    """Links a login account to an organisation and a role."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        WARDEN = "warden", "Warden"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_profile")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="staff")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.WARDEN)
    hostels = models.ManyToManyField(Hostel, blank=True, related_name="staff")

    def __str__(self):
        return f"{self.user} ({self.role})"
