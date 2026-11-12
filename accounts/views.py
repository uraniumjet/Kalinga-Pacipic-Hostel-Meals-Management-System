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
    if context["is_admin"]:
        org = staff.organization
        context["setup"] = [
            ("Categories", org.categories.count(), "admin:organizations_category_changelist", "Students are grouped by category (for example National, International)."),
            ("Diet types", org.diet_types.count(), "admin:organizations_diettype_changelist", "Veg, non-veg and so on."),
            ("Hostels", org.hostels.count(), "admin:organizations_hostel_changelist", "Buildings or blocks that students live in."),
            ("Meal types", org.meal_types.count(), "admin:mess_mealtype_changelist", "Breakfast, lunch, dinner, with their serving times."),
            ("Counters", org.counters.count(), "admin:mess_counter_changelist", "Serving points where wardens scan students."),
        ]
        context["setup_missing"] = any(count == 0 for _, count, _, _ in context["setup"])
    return render(request, "accounts/home.html", context)
