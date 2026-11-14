from io import BytesIO

import qrcode
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.access import hostels_for, students_for
from accounts.decorators import admin_required, staff_required
from attendance.models import RollCallEntry
from attendance.services import leave_states

from . import idcards
from .forms import MarkLeftForm, MoveRoomForm, ReadmitForm, StudentForm
from .models import RoomAllocation, Student
from .services import allocate_room, mark_left, readmit

PAGE_SIZE = 25
PDF_LIMIT = 500


@staff_required
def student_list(request):
    q = request.GET.get("q", "").strip()
    show = request.GET.get("show", "active")
    students = students_for(request.staff).select_related("category")
    if show != "all":
        students = students.filter(status="active")
    if q:
        students = students.filter(Q(name__icontains=q) | Q(roll_number__icontains=q))
    current = RoomAllocation.objects.filter(end_date__isnull=True).select_related("room__hostel")
    students = students.prefetch_related(Prefetch("allocations", queryset=current, to_attr="current_allocs"))
    page = Paginator(students, PAGE_SIZE).get_page(request.GET.get("page"))
    page.object_list = list(page.object_list)
    states = leave_states([student.pk for student in page.object_list], request.staff.organization.local_today())
    for student in page.object_list:
        student.leave = states.get(student.pk)
    return render(request, "residents/student_list.html", {"page": page, "q": q, "show": show})


@staff_required
def student_detail(request, pk):
    student = get_object_or_404(students_for(request.staff).select_related("category", "diet"), pk=pk)
    history = student.allocations.select_related("room__hostel")
    today = request.staff.organization.local_today()
    absent = RollCallEntry.objects.filter(student=student, status=RollCallEntry.Status.ABSENT)
    context = {
        "student": student,
        "history": history,
        "permits": [{"permit": p, "text": p.describe(today), "status": p.status_on(today)} for p in student.permits.filter(cancelled=False)[:5]],
        "unauthorised_count": absent.count(),
        "unauthorised_dates": [e.roll_call.date for e in absent.select_related("roll_call").order_by("-roll_call__date")[:5]],
    }
    return render(request, "residents/student_detail.html", context)


def _save_form(request, instance, title):
    form = StudentForm(request.POST or None, request.FILES or None, instance=instance, staff=request.staff)
    if request.method == "POST" and form.is_valid():
        try:
            student = form.save()
        except ValidationError as error:
            form.add_error("room", error)  # e.g. the room filled up while the form was open
        else:
            messages.success(request, f"Saved {student.name}.")
            return redirect("residents:detail", pk=student.pk)
    return render(request, "residents/student_form.html", {"form": form, "title": title, "student": instance})


@staff_required
def student_create(request):
    return _save_form(request, None, "Register student")


@staff_required
def student_edit(request, pk):
    student = get_object_or_404(students_for(request.staff), pk=pk)
    return _save_form(request, student, f"Edit {student.name}")


@staff_required
def student_qr(request, pk):
    """PNG of the student's QR code. It encodes a random token, never the roll number."""
    student = get_object_or_404(students_for(request.staff), pk=pk)
    buffer = BytesIO()
    qrcode.make(str(student.qr_token), box_size=8, border=2).save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")


@staff_required
def student_photo(request, name):
    """Serve a student's photo to signed-in staff of the same organisation only.

    The file is found through the database (never by building a path from the URL), so nothing outside
    the student photos can be read, and photos of another organisation answer 404.
    """
    org = request.staff.organization
    student = Student.objects.filter(organization=org, photo=name).first()
    if student is not None and student.photo:
        stored = student.photo
    elif org.logo and org.logo.name == name:  # the organisation's own logo, shown in setup
        stored = org.logo
    else:
        raise Http404("No such photo")
    try:
        handle = stored.open("rb")
    except FileNotFoundError:
        raise Http404("No such photo") from None
    response = FileResponse(handle)
    response["Cache-Control"] = "private, max-age=3600"
    return response


def _active_student_or_redirect(request, pk):
    student = get_object_or_404(students_for(request.staff).select_related("category", "diet"), pk=pk)
    if student.status != Student.Status.ACTIVE:
        messages.error(request, f"{student.name} has left the hostel.")
        return student, redirect("residents:detail", pk=student.pk)
    return student, None


@staff_required
def student_move(request, pk):
    student, redirect_response = _active_student_or_redirect(request, pk)
    if redirect_response:
        return redirect_response
    today = request.staff.organization.local_today()
    form = MoveRoomForm(request.POST or None, staff=request.staff, student=student, today=today)
    if request.method == "POST" and form.is_valid():
        try:
            allocate_room(student, form.cleaned_data["room"], form.cleaned_data["date"])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f"{student.name} moved to {form.cleaned_data['room']}.")
            return redirect("residents:detail", pk=student.pk)
    return render(request, "residents/student_action.html", {
        "student": student, "form": form, "title": f"Change room: {student.name}", "button": "Move student",
        "intro": f"Now in {student.current_room or 'no room'}. The old room is freed on the date you choose.",
    })


@staff_required
def student_leave(request, pk):
    student, redirect_response = _active_student_or_redirect(request, pk)
    if redirect_response:
        return redirect_response
    today = request.staff.organization.local_today()
    form = MarkLeftForm(request.POST or None, today=today)
    if request.method == "POST" and form.is_valid():
        try:
            mark_left(student, form.cleaned_data["date"])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f"{student.name} is marked as left. The bed is free again.")
            return redirect("residents:list")  # a warden can no longer open a student who has no room in their hostels
    return render(request, "residents/student_action.html", {
        "student": student, "form": form, "title": f"Mark as left: {student.name}", "button": "Mark as left",
        "danger": True,
        "intro": "The student's room is freed and exit permits that have not started are cancelled. "
                 "Meals, roll calls and reports for earlier dates are kept.",
    })


@admin_required
def student_readmit(request, pk):
    student = get_object_or_404(Student, pk=pk, organization=request.staff.organization)
    if student.status != Student.Status.LEFT:
        messages.error(request, f"{student.name} has not left.")
        return redirect("residents:detail", pk=student.pk)
    today = request.staff.organization.local_today()
    form = ReadmitForm(request.POST or None, staff=request.staff, student=student, today=today)
    if request.method == "POST" and form.is_valid():
        try:
            readmit(student, form.cleaned_data["date"], form.cleaned_data["room"])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f"{student.name} is back in the hostel.")
            return redirect("residents:detail", pk=student.pk)
    return render(request, "residents/student_action.html", {
        "student": student, "form": form, "title": f"Re-admit {student.name}", "button": "Re-admit",
        "intro": "The student becomes active again. Choose a room now, or place them later.",
    })


CARD_LIMIT = 120


def _card_students(request):
    """Active students in the staff member's scope, narrowed by the hostel, ids and q query parameters."""
    students = students_for(request.staff).filter(status=Student.Status.ACTIVE).select_related("category")
    hostels = list(hostels_for(request.staff))
    chosen = None
    hostel_id = request.GET.get("hostel", "")
    if hostel_id.isdigit():
        chosen = next((h for h in hostels if h.pk == int(hostel_id)), None)
        if chosen is not None:
            students = students.filter(allocations__end_date__isnull=True, allocations__room__hostel=chosen)
    ids = [int(i) for i in request.GET.get("ids", "").split(",") if i.strip().isdigit()]
    if ids:
        students = students.filter(pk__in=ids)
    q = request.GET.get("q", "").strip()
    if q:
        students = students.filter(Q(name__icontains=q) | Q(roll_number__icontains=q))
    current = RoomAllocation.objects.filter(end_date__isnull=True).select_related("room__hostel")
    students = students.prefetch_related(Prefetch("allocations", queryset=current, to_attr="current_allocs"))
    return students.order_by("name"), hostels, chosen, q


@staff_required
def student_cards(request):
    """Choose which students get an ID card, preview them, and download the PDF."""
    students, hostels, chosen, q = _card_students(request)
    total = students.count()
    return render(request, "residents/cards.html", {
        "students": list(students[:CARD_LIMIT]), "total": total, "limit": CARD_LIMIT,
        "hostels": hostels, "chosen": chosen, "q": q, "organization": request.staff.organization,
        "query": request.GET.urlencode(), "pdf_limit": PDF_LIMIT,
    })


@staff_required
def student_cards_pdf(request):
    """The ID cards as a PDF: mode=card (one per page, front then back) or mode=sheet (ten per A4 page)."""
    students, _, _, _ = _card_students(request)
    org = request.staff.organization
    rows = list(students[:PDF_LIMIT])
    cards = []
    for s in rows:
        alloc = s.current_allocs[0] if s.current_allocs else None
        photo = None
        if s.photo:
            try:
                with s.photo.open("rb") as handle:
                    photo = handle.read()
            except FileNotFoundError:
                photo = None
        cards.append(idcards.CardData(
            name=s.name, roll_number=s.roll_number, qr_token=str(s.qr_token), category=s.category.name,
            course=s.course or "", room=str(alloc.room) if alloc else "", photo=photo,
        ))
    logo = None
    if org.logo:
        try:
            with org.logo.open("rb") as handle:
                logo = handle.read()
        except FileNotFoundError:
            logo = None
    mode = "sheet" if request.GET.get("mode") == "sheet" else "card"
    pdf = idcards.build_pdf(cards, idcards.OrgData(name=org.name, logo=logo), mode=mode, issued=org.local_today())
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="id-cards-{mode}.pdf"'
    response["Cache-Control"] = "private, no-store"
    return response
