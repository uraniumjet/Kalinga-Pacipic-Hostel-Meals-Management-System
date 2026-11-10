"""Room allocation rules. Views and admin actions should call these, not create rows directly."""
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import RoomAllocation, Student


def allocate_room(student: Student, room, start_date) -> RoomAllocation:
    """Move a student into a room, ending any current stay. Raises ValidationError on a broken rule."""
    hostel = room.hostel
    if hostel.organization_id != student.organization_id:
        raise ValidationError("The room belongs to a different organisation.")
    if hostel.gender != student.gender:
        raise ValidationError("A student can only be placed in a hostel of the same gender.")
    if student.status != Student.Status.ACTIVE:
        raise ValidationError("Only active students can be allocated a room.")

    with transaction.atomic():
        current = (
            RoomAllocation.objects.select_for_update()
            .filter(student=student, end_date__isnull=True)
            .first()
        )
        if current and current.room_id == room.id:
            raise ValidationError("The student is already in this room.")
        occupied = RoomAllocation.objects.filter(room=room, end_date__isnull=True).count()
        if occupied >= room.capacity:
            raise ValidationError(f"Room {room} is full ({room.capacity} of {room.capacity}).")
        if current:
            current.end_date = start_date
            current.save(update_fields=["end_date"])
        return RoomAllocation.objects.create(student=student, room=room, start_date=start_date)


def vacate_room(student: Student, end_date) -> None:
    """End the student's current stay without placing them elsewhere."""
    updated = RoomAllocation.objects.filter(student=student, end_date__isnull=True).update(end_date=end_date)
    if not updated:
        raise ValidationError("The student has no current room.")
