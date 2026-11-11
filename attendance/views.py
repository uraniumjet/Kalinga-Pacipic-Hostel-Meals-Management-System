from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.access import hostels_for, students_for
from accounts.decorators import staff_required

from .forms import PermitForm
from .models import ExitPermit, RollCall, RollCallEntry
from .services import (
    cancel_permit, grant_permit, hostel_sheet, local_now, record_return, roll_call_is_open, take_roll_call,
)


def _scoped_permit(request, pk):
    return get_object_or_404(ExitPermit.objects.filter(student__in=students_for(request.staff)), pk=pk)


@staff_required
def permit_list(request):
    today = request.staff.organization.local_today()
    show = request.GET.get("show", "current")
    permits = ExitPermit.objects.filter(student__in=students_for(request.staff)).select_related("student")
    if show == "all":
        permits = permits[:300]
    else:
        permits = permits.filter(cancelled=False, returned_on__isnull=True).order_by("end_date", "id")
    rows = [{"permit": p, "status": p.status_on(today), "text": p.describe(today)} for p in permits]
    return render(request, "attendance/permit_list.html", {"rows": rows, "show": show})


@staff_required
def permit_create(request):
    staff = request.staff
    initial = {"start_date": staff.organization.local_today(), "roll_number": request.GET.get("roll", "")}
    form = PermitForm(request.POST or None, staff=staff, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            permit = grant_permit(
                form.student, data["start_date"], data["end_date"], data["reason"], request.user,
                destination=data["destination"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f"Permit recorded for {permit.student.name}: {permit.describe(permit.start_date)}.")
            return redirect("attendance:permits")
    return render(request, "attendance/permit_form.html", {"form": form})


@staff_required
@require_POST
def permit_return(request, pk):
    permit = _scoped_permit(request, pk)
    try:
        record_return(permit)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, f"{permit.student.name} is recorded as back.")
    return redirect("attendance:permits")


@staff_required
@require_POST
def permit_cancel(request, pk):
    permit = _scoped_permit(request, pk)
    try:
        cancel_permit(permit)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, f"Permit for {permit.student.name} cancelled.")
    return redirect("attendance:permits")


@staff_required
def rollcall_home(request):
    org = request.staff.organization
    today = local_now(org).date()
    done = set(RollCall.objects.filter(organization=org, date=today).values_list("hostel_id", flat=True))
    rows = [{"hostel": h, "done": h.pk in done} for h in hostels_for(request.staff).order_by("name")]
    return render(request, "attendance/rollcall_home.html", {"rows": rows, "open": roll_call_is_open(org), "org": org})


@staff_required
def rollcall(request, hostel_pk):
    org = request.staff.organization
    hostel = get_object_or_404(hostels_for(request.staff), pk=hostel_pk)
    ticked = None
    if request.method == "POST":
        ticked = {int(v) for v in request.POST.getlist("absent") if v.isdigit()}
        try:
            take_roll_call(hostel, ticked, request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"Roll call saved for {hostel.name}.")
            return redirect("attendance:rollcall", hostel_pk=hostel.pk)

    day = local_now(org).date()
    rows = []
    for r in hostel_sheet(hostel, day):
        checked = (r.student.pk in ticked) if ticked is not None else r.existing == RollCallEntry.Status.ABSENT
        rows.append({"student": r.student, "room": r.room, "leave": r.leave, "checked": checked})

    entries = RollCallEntry.objects.filter(roll_call__hostel=hostel, roll_call__date=day)
    counts = {status: entries.filter(status=status).count() for status in RollCallEntry.Status.values}
    saved = None
    if entries.exists():
        saved = {
            "present": counts["present"], "on_leave": counts["on_leave"], "absent": counts["absent"],
            "absent_names": [e.student.name for e in entries.filter(status="absent").select_related("student")],
        }
    context = {"hostel": hostel, "rows": rows, "day": day, "open": roll_call_is_open(org), "org": org, "saved": saved}
    return render(request, "attendance/rollcall.html", context)
