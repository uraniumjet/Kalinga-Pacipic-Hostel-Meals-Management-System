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
        if current and start_date < current.start_date:
            raise ValidationError(f"The move date is before the student moved into room {current.room}.")
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


OPEN_LEAVE = ("on_leave", "overdue")


def mark_left(student: Student, left_on) -> None:
    """The student leaves the hostel: free the bed, cancel leave that has not started, set the status to left.

    Refused while the student is away on leave or overdue, because the leave has to be closed first
    (mark the student back) so that the attendance record stays truthful.
    """
    if student.status != Student.Status.ACTIVE:
        raise ValidationError("This student has already left.")
    with transaction.atomic():
        open_permits = student.permits.filter(cancelled=False, returned_on__isnull=True)
        for permit in open_permits:
            if permit.status_on(left_on) in OPEN_LEAVE:
                raise ValidationError(
                    f"{student.name} is on leave or overdue. Mark the student back from leave first, then mark as left."
                )
        current = RoomAllocation.objects.select_for_update().filter(student=student, end_date__isnull=True).first()
        if current:
            if left_on < current.start_date:
                raise ValidationError(f"The leaving date is before the student moved into room {current.room}.")
            current.end_date = left_on
            current.save(update_fields=["end_date"])
        open_permits.filter(start_date__gt=left_on).update(cancelled=True)
        student.status = Student.Status.LEFT
        student.save(update_fields=["status"])


def readmit(student: Student, on_date, room=None) -> None:
    """A student who left comes back. They get a room straight away only if one is given."""
    if student.status != Student.Status.LEFT:
        raise ValidationError("This student has not left.")
    with transaction.atomic():
        student.status = Student.Status.ACTIVE
        student.save(update_fields=["status"])
        if room is not None:
            allocate_room(student, room, on_date)
