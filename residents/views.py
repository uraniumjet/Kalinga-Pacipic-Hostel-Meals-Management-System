from io import BytesIO

import qrcode
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.access import students_for
from accounts.decorators import staff_required
from attendance.models import RollCallEntry
from attendance.services import leave_states

from .forms import StudentForm
from .models import RoomAllocation, Student

PAGE_SIZE = 25


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
    student = Student.objects.filter(organization=request.staff.organization, photo=name).first()
    if student is None or not student.photo:
        raise Http404("No such photo")
    try:
        handle = student.photo.open("rb")
    except FileNotFoundError:
        raise Http404("No such photo") from None
    response = FileResponse(handle)
    response["Cache-Control"] = "private, max-age=3600"
    return response
