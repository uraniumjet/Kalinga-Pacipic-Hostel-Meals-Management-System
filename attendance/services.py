"""Permit and roll-call rules. Views must call these rather than writing rows directly."""
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from residents.models import RoomAllocation, Student

from .models import ExitPermit, RollCall, RollCallEntry


# ---------- permits ----------

@dataclass(frozen=True)
class LeaveState:
    state: str  # ExitPermit.ON_LEAVE or ExitPermit.OVERDUE
    permit: ExitPermit
    day: object

    @property
    def days_overdue(self):
        return self.permit.days_overdue_on(self.day)

    @property
    def text(self):
        return self.permit.describe(self.day)


def leave_states(student_ids, day):
    """{student_id: LeaveState} for students who are on leave or overdue on `day`. One query."""
    permits = (
        ExitPermit.objects.filter(student_id__in=list(student_ids), cancelled=False)
        .filter(Q(end_date__gte=day) | Q(returned_on__isnull=True) | Q(returned_on__gt=day))
        .order_by("start_date", "id")
    )
    result = {}
    for permit in permits:
        state = permit.state_on(day)
        if state is None:
            continue
        new = LeaveState(state, permit, day)
        current = result.get(permit.student_id)
        if current is None:
            result[permit.student_id] = new
        elif state == ExitPermit.ON_LEAVE:
            result[permit.student_id] = new  # a valid permit beats an old overdue one
        elif current.state == ExitPermit.OVERDUE and permit.end_date < current.permit.end_date:
            result[permit.student_id] = new  # between overdue permits, the most overdue is shown
    return result


def leave_state(student, day):
    return leave_states([student.pk], day).get(student.pk)


def grant_permit(student, start_date, end_date, reason="", granted_by=None, today=None, destination=""):
    org = student.organization
    today = today or org.local_today()
    if student.status != Student.Status.ACTIVE:
        raise ValidationError("Only active students can be given a permit.")
    if end_date < start_date:
        raise ValidationError("The end date cannot be before the start date.")
    if end_date < today:
        raise ValidationError("A permit cannot end in the past.")
    with transaction.atomic():
        for other in ExitPermit.objects.select_for_update().filter(student=student, cancelled=False):
            if other.returned_on is None and other.end_date < today:
                raise ValidationError(
                    f"Record the return of the earlier permit ({other.start_date} to {other.end_date}) first."
                )
            if other.start_date <= end_date and other.last_day_covered() >= start_date:
                raise ValidationError(
                    f"This overlaps another permit ({other.start_date} to {other.end_date})."
                )
        return ExitPermit.objects.create(
            organization=org, student=student, start_date=start_date, end_date=end_date,
            reason=reason, destination=destination, granted_by=granted_by,
        )


def record_return(permit, on_date=None, today=None):
    today = today or permit.organization.local_today()
    on_date = on_date or today
    if permit.cancelled:
        raise ValidationError("This permit was cancelled.")
    if permit.returned_on is not None:
        raise ValidationError("The return was already recorded.")
    if on_date < permit.start_date:
        raise ValidationError("The student cannot return before the permit starts.")
    if on_date > today:
        raise ValidationError("The return date cannot be in the future.")
    permit.returned_on = on_date
    permit.save(update_fields=["returned_on"])
    return permit


def cancel_permit(permit, today=None):
    today = today or permit.organization.local_today()
    if permit.start_date <= today:
        raise ValidationError("A permit that has started cannot be cancelled. Record the return instead.")
    permit.cancelled = True
    permit.save(update_fields=["cancelled"])
    return permit


# ---------- roll call ----------

def local_now(organization, now=None):
    return organization.local_now(now)


def roll_call_is_open(organization, now=None):
    t = local_now(organization, now).time()
    return organization.roll_call_start <= t <= organization.roll_call_end


@dataclass(frozen=True)
class SheetRow:
    student: Student
    room: object
    leave: object  # LeaveState or None
    existing: str  # status already saved for this night, or ""


def hostel_sheet(hostel, day):
    """Students currently living in the hostel, ordered by room, with their leave state for `day`."""
    allocations = list(
        RoomAllocation.objects.filter(
            end_date__isnull=True, room__hostel=hostel, student__status=Student.Status.ACTIVE
        )
        .select_related("student", "room")
        .order_by("room__number", "student__name")
    )
    states = leave_states([a.student_id for a in allocations], day)
    saved = dict(
        RollCallEntry.objects.filter(roll_call__hostel=hostel, roll_call__date=day).values_list("student_id", "status")
    )
    return [
        SheetRow(a.student, a.room, states.get(a.student_id), saved.get(a.student_id, ""))
        for a in allocations
    ]


def take_roll_call(hostel, absent_ids, taken_by=None, now=None):
    """Save tonight's roll call for a hostel.

    absent_ids: ids of the students the warden found missing. Everyone else in the hostel is
    present, except that students on permitted leave are recorded as ON_LEAVE and students past
    their permit as ABSENT with the days overdue (ticks for them are ignored). It can be
    submitted again the same night to correct mistakes.
    """
    org = hostel.organization
    if not roll_call_is_open(org, now):
        raise ValidationError(
            f"Roll call is open from {org.roll_call_start:%H:%M} to {org.roll_call_end:%H:%M}."
        )
    day = local_now(org, now).date()
    rows = hostel_sheet(hostel, day)
    absent_ids = set(absent_ids)
    unknown = absent_ids - {row.student.pk for row in rows}
    if unknown:
        raise ValidationError("Some ticked students do not live in this hostel.")

    plan = []
    for row in rows:
        if row.leave and row.leave.state == ExitPermit.ON_LEAVE:
            plan.append((row.student, RollCallEntry.Status.ON_LEAVE, row.leave.permit, 0))
        elif row.leave:
            plan.append((row.student, RollCallEntry.Status.ABSENT, row.leave.permit, row.leave.days_overdue))
        elif row.student.pk in absent_ids:
            plan.append((row.student, RollCallEntry.Status.ABSENT, None, 0))
        else:
            plan.append((row.student, RollCallEntry.Status.PRESENT, None, 0))

    with transaction.atomic():
        roll_call, created = RollCall.objects.get_or_create(
            organization=org, hostel=hostel, date=day, defaults={"taken_by": taken_by}
        )
        if not created:
            roll_call.taken_by = taken_by
            roll_call.save(update_fields=["taken_by", "updated_at"])
        for student, status, permit, overdue in plan:
            RollCallEntry.objects.update_or_create(
                roll_call=roll_call, student=student,
                defaults={"status": status, "permit": permit, "days_overdue": overdue},
            )
    return roll_call
