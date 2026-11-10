from django.shortcuts import render

from .access import hostels_for, is_admin, students_for
from .decorators import staff_required


@staff_required
def home(request):
    staff = request.staff
    context = {
        "staff": staff,
        "organization": staff.organization,
        "is_admin": is_admin(staff),
        "hostels": hostels_for(staff).order_by("name"),
        "student_count": students_for(staff).count(),
    }
    return render(request, "accounts/home.html", context)
