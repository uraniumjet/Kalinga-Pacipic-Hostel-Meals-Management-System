"""Builds the report tables. Every report is scoped to what the staff member may see.

The system only records facts. "Absent without permission" means a night when the student
was not in the hostel and had no valid permit (never had one, or was still away after the
permit ended). Charging fines is for the central administration, not for this system.
"""
from datetime import timedelta

from django.db.models import Count, Max, Q

from accounts.access import hostels_for, students_for
from attendance.models import RollCallEntry, fmt
from mess.models import MealCollection
from residents.models import RoomAllocation, Student

from .tables import Table

NOTE_ABSENCE = (
    "Absent without permission means a night when the student was not in the hostel and had no valid "
    "exit permit: either no permit at all, or still away after the permit ended. This system records "
    "these nights only; it does not calculate or charge fines."
)


def _day_label(day):
    return f"{day.day} {day:%b %Y} ({day:%a})"


def _period_text(start, end):
    if start == end:
        return f"{start.day} {start:%b %Y}"
    return f"{start.day} {start:%b %Y} to {end.day} {end:%b %Y}"


def _subtitle(staff, start, end, hostel):
    where = hostel.name if hostel else ("all hostels" if staff.role == "admin" else "your hostels")
    return f"{staff.organization.name} - {where} - {_period_text(start, end)}"


def scoped_students(staff, hostel=None):
    """Students this staff member may report on, optionally only those living in one hostel."""
    students = students_for(staff)
    if hostel is not None:
        here = RoomAllocation.objects.filter(end_date__isnull=True, room__hostel=hostel).values("student_id")
        students = students.filter(pk__in=here)
    return students


def _rooms(student_ids):
    allocations = RoomAllocation.objects.filter(end_date__isnull=True, student_id__in=list(student_ids)).select_related(
        "room__hostel"
    )
    return {a.student_id: str(a.room) for a in allocations}


def _scoped_entries(staff, start, end, hostel):
    hostels = hostels_for(staff)
    if hostel is not None:
        hostels = hostels.filter(pk=hostel.pk)
    return RollCallEntry.objects.filter(roll_call__date__range=(start, end), roll_call__hostel__in=hostels)


def meals_daily(staff, start, end, hostel=None):
    org = staff.organization
    meal_types = list(org.meal_types.all())
    collections = MealCollection.objects.filter(
        organization=org, date__range=(start, end), student__in=scoped_students(staff, hostel)
    )
    counts = {
        (day, meal_id): n
        for day, meal_id, n in collections.values_list("date", "meal_type_id").annotate(n=Count("id")).order_by()
    }
    rows, totals = [], [0] * len(meal_types)
    day = start
    while day <= end:
        per_meal = [counts.get((day, meal.pk), 0) for meal in meal_types]
        rows.append([_day_label(day), *per_meal, sum(per_meal)])
        totals = [t + n for t, n in zip(totals, per_meal)]
        day += timedelta(days=1)
    rows.append(["Total", *totals, sum(totals)])
    return Table(
        "Meals served per day", _subtitle(staff, start, end, hostel),
        ["Date", *[m.name for m in meal_types], "Total"], rows,
    )


def meals_students(staff, start, end, hostel=None):
    org = staff.organization
    meal_types = list(org.meal_types.all())
    students = scoped_students(staff, hostel)
    collections = MealCollection.objects.filter(organization=org, date__range=(start, end), student__in=students)
    counts = {
        (student_id, meal_id): n
        for student_id, meal_id, n in collections.values_list("student_id", "meal_type_id")
        .annotate(n=Count("id")).order_by()
    }
    with_meals = {student_id for student_id, _ in counts}
    chosen = list(students.filter(Q(status=Student.Status.ACTIVE) | Q(pk__in=with_meals)).order_by("name"))
    rooms = _rooms(s.pk for s in chosen)
    rows, totals = [], [0] * len(meal_types)
    for s in chosen:
        per_meal = [counts.get((s.pk, meal.pk), 0) for meal in meal_types]
        rows.append([s.roll_number, s.name, rooms.get(s.pk, ""), *per_meal, sum(per_meal)])
        totals = [t + n for t, n in zip(totals, per_meal)]
    rows.append(["Total", "", "", *totals, sum(totals)])
    return Table(
        "Meals per student", _subtitle(staff, start, end, hostel),
        ["Roll no.", "Student", "Room", *[m.name for m in meal_types], "Total"], rows,
    )


def attendance_summary(staff, start, end, hostel=None):
    entries = _scoped_entries(staff, start, end, hostel)
    stats = (
        entries.values("student_id").order_by("student_id")
        .annotate(
            present=Count("id", filter=Q(status="present")),
            leave=Count("id", filter=Q(status="on_leave")),
            plain=Count("id", filter=Q(status="absent", permit__isnull=True)),
            overdue=Count("id", filter=Q(status="absent", permit__isnull=False)),
            longest=Max("days_overdue"),
        )
    )
    by_student = {row["student_id"]: row for row in stats}
    students = list(Student.objects.filter(pk__in=list(by_student)).order_by("name"))
    rooms = _rooms(list(by_student))
    ordered = sorted(students, key=lambda s: (-(by_student[s.pk]["plain"] + by_student[s.pk]["overdue"]), s.name))
    rows = []
    sums = [0, 0, 0, 0, 0]
    longest_overall = 0
    for s in ordered:
        r = by_student[s.pk]
        absent = r["plain"] + r["overdue"]
        longest = r["longest"] or 0
        rows.append([s.roll_number, s.name, rooms.get(s.pk, ""), r["present"], r["leave"], r["plain"], r["overdue"], absent, longest])
        for i, value in enumerate((r["present"], r["leave"], r["plain"], r["overdue"], absent)):
            sums[i] += value
        longest_overall = max(longest_overall, longest)
    rows.append(["Total", "", "", *sums, longest_overall])
    return Table(
        "Attendance summary per student", _subtitle(staff, start, end, hostel),
        ["Roll no.", "Student", "Room", "Nights present", "On permitted leave", "Absent (no permit)",
         "Absent after permit ended", "Total absent without permission", "Longest overdue (days)"],
        rows, [NOTE_ABSENCE],
    )


def absences(staff, start, end, hostel=None):
    entries = (
        _scoped_entries(staff, start, end, hostel).filter(status="absent")
        .select_related("roll_call__hostel", "student", "permit")
        .order_by("roll_call__date", "roll_call__hostel__name", "student__name")
    )
    rows = []
    for e in entries:
        if e.permit_id:
            days = "day" if e.days_overdue == 1 else "days"
            reason = f"Permit ended {fmt(e.permit.end_date)} ({e.days_overdue} {days} overdue)"
        else:
            reason = "No permit"
        rows.append([_day_label(e.roll_call.date), e.roll_call.hostel.name, e.student.roll_number, e.student.name,
                     reason, e.days_overdue])
    notes = [f"{len(rows)} night(s) of absence without permission by {len({e.student_id for e in entries})} student(s).",
             NOTE_ABSENCE]
    return Table(
        "Absent without permission", _subtitle(staff, start, end, hostel),
        ["Date", "Hostel", "Roll no.", "Student", "Reason", "Days overdue"], rows, notes,
    )


REPORTS = {
    "meals-daily": ("Meals served per day", "How many meals of each kind were served on each day.", meals_daily),
    "meals-students": ("Meals per student", "Meals each student collected in the period.", meals_students),
    "attendance-summary": (
        "Attendance summary per student", "Nights present, on leave and absent per student.", attendance_summary
    ),
    "absences": (
        "Absent without permission", "Every night a student was absent without a valid permit.", absences
    ),
}
