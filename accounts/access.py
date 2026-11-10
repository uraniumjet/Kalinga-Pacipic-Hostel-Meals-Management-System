"""Who may see what. Every screen and API must scope its data through these helpers.

Rules
- Only users with a StaffProfile in an active organisation may use the system.
- An admin sees everything in their own organisation.
- A warden sees the hostels assigned to them, the students currently living in those
  hostels, and active students who have no room yet (so they can be registered and
  allocated).
- Meal counters are organisation-wide: any staff member can serve any active student of
  their organisation, whichever hostel the student lives in.
"""
from organizations.models import Hostel, StaffProfile
from residents.models import Student


def get_staff(user):
    """The user's StaffProfile, or None if they may not use the system."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return None
    try:
        staff = user.staff_profile
    except StaffProfile.DoesNotExist:
        return None
    if not staff.organization.is_active:
        return None
    return staff


def is_admin(staff):
    return staff.role == StaffProfile.Role.ADMIN


def hostels_for(staff):
    if is_admin(staff):
        return Hostel.objects.filter(organization=staff.organization)
    return staff.hostels.filter(organization=staff.organization)


def students_for(staff):
    students = Student.objects.filter(organization=staff.organization)
    if is_admin(staff):
        return students
    in_my_hostels = students.filter(
        allocations__end_date__isnull=True, allocations__room__hostel__in=hostels_for(staff)
    )
    unallocated = students.filter(status=Student.Status.ACTIVE).exclude(allocations__end_date__isnull=True)
    return (in_my_hostels | unallocated).distinct()


def can_manage_student(staff, student):
    return students_for(staff).filter(pk=student.pk).exists()
