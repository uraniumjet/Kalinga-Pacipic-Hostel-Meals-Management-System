from zoneinfo import ZoneInfo

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import staff_required
from residents.models import Student

from .lookup import find_students
from .models import Counter, MealCollection
from .services import CollectionDenied, check_collection, record_collection


@staff_required
def counter_list(request):
    counters = Counter.objects.filter(organization=request.staff.organization)
    return render(request, "mess/counter_list.html", {"counters": counters})


@staff_required
def counter_screen(request, pk):
    org = request.staff.organization
    counter = get_object_or_404(Counter, pk=pk, organization=org)

    if request.method == "POST":
        try:
            student_id = int(request.POST.get("student", ""))
        except ValueError:
            raise Http404("Unknown student")
        student = get_object_or_404(Student, pk=student_id, organization=org)
        try:
            collection = record_collection(student, counter, recorded_by=request.user)
        except CollectionDenied as denied:
            messages.error(request, denied.message)
        else:
            messages.success(request, f"{collection.meal_type.name} served to {student.name} ({student.roll_number}).")
        return redirect("mess:counter", pk=counter.pk)

    q = request.GET.get("q", "").strip()
    results = []
    for student in find_students(org, q):
        try:
            slot, _ = check_collection(student, counter)
            results.append({"student": student, "meal": slot.meal_type.name, "problem": ""})
        except CollectionDenied as denied:
            results.append({"student": student, "meal": "", "problem": denied.message})

    zone = ZoneInfo(org.timezone)
    todays = MealCollection.objects.filter(counter=counter, date=org.local_today()).select_related("student", "meal_type")
    recent = [
        {"collection": c, "time": timezone.localtime(c.created_at, zone).strftime("%H:%M")}
        for c in todays[:10]
    ]
    context = {"counter": counter, "q": q, "results": results, "recent": recent, "served_today": todays.count()}
    return render(request, "mess/counter.html", context)
