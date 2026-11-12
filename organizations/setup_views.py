"""Admin-only setup screens: organisation settings, categories, diet types, hostels, rooms, staff."""
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from organizations.models import Category, DietType, Hostel, Room, StaffProfile

from .setup_forms import (
    BulkRoomForm,
    CategoryForm,
    DietForm,
    HostelForm,
    OrganizationForm,
    RoomForm,
    StaffForm,
)

LOOKUPS = {
    "category": (Category, CategoryForm, "Category", "Categories"),
    "diet": (DietType, DietForm, "Diet type", "Diet types"),
}


def _org(request):
    return request.staff.organization


@admin_required
def index(request):
    org = _org(request)
    form = OrganizationForm(request.POST or None, instance=org)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Organisation settings saved.")
        return redirect("setup:index")
    steps = [
        ("Categories", org.categories.count(), "setup:lookups", "Groups such as National and International."),
        ("Diet types", org.diet_types.count(), "setup:lookups", "Vegetarian, non-vegetarian and so on."),
        ("Hostels", org.hostels.count(), "setup:hostels", "Buildings or blocks, boys or girls."),
        ("Rooms", Room.objects.filter(hostel__organization=org).count(), "setup:hostels", "Rooms with the number of beds."),
        ("Meal types", org.meal_types.count(), "setup:meals", "Breakfast, lunch, dinner and their serving times."),
        ("Counters", org.counters.count(), "setup:counters", "Serving points where wardens scan students."),
        ("Wardens", org.staff.filter(role=StaffProfile.Role.WARDEN).count(), "setup:staff", "Accounts for the people who register students and serve meals."),
    ]
    return render(request, "organizations/setup/index.html", {"form": form, "org": org, "steps": steps})


@admin_required
def lookups(request):
    org = _org(request)
    forms = {
        "category": CategoryForm(prefix="category", organization=org),
        "diet": DietForm(prefix="diet", organization=org),
    }
    if request.method == "POST":
        kind = request.POST.get("kind")
        if kind not in LOOKUPS:
            return redirect("setup:lookups")
        form_class = LOOKUPS[kind][1]
        form = form_class(request.POST, prefix=kind, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f"{LOOKUPS[kind][2]} added.")
            return redirect("setup:lookups")
        forms[kind] = form
    sections = []
    for kind, (model, _form, singular, plural) in LOOKUPS.items():
        rows = model.objects.filter(organization=org).annotate(used=Count("students")).order_by("name")
        sections.append({"kind": kind, "title": plural, "singular": singular, "rows": rows, "form": forms[kind]})
    return render(request, "organizations/setup/lookups.html", {"sections": sections})


@admin_required
def lookup_edit(request, kind, pk):
    if kind not in LOOKUPS:
        return redirect("setup:lookups")
    model, form_class, singular, _plural = LOOKUPS[kind]
    obj = get_object_or_404(model, pk=pk, organization=_org(request))
    form = form_class(request.POST or None, instance=obj, organization=_org(request))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{singular} renamed.")
        return redirect("setup:lookups")
    return render(request, "organizations/setup/simple_form.html",
                  {"form": form, "title": f"Rename {singular.lower()}", "back_url": reverse("setup:lookups")})


@admin_required
@require_POST
def lookup_delete(request, kind, pk):
    if kind not in LOOKUPS:
        return redirect("setup:lookups")
    model, _form, singular, _plural = LOOKUPS[kind]
    obj = get_object_or_404(model, pk=pk, organization=_org(request))
    try:
        obj.delete()
        messages.success(request, f"{singular} deleted.")
    except ProtectedError:
        messages.error(request, f"{obj.name} is used by students, so it cannot be deleted.")
    return redirect("setup:lookups")


@admin_required
def hostels(request):
    org = _org(request)
    form = HostelForm(request.POST or None, organization=org)
    if request.method == "POST" and form.is_valid():
        hostel = form.save()
        messages.success(request, f"{hostel.name} added. Now add its rooms.")
        return redirect("setup:hostel", hostel.pk)
    rows = []
    for h in Hostel.objects.filter(organization=org).prefetch_related("rooms").order_by("name"):
        rooms = list(h.rooms.all())
        rows.append({"hostel": h, "rooms": len(rooms), "beds": sum(r.capacity for r in rooms),
                     "residents": sum(r.occupancy for r in rooms)})
    return render(request, "organizations/setup/hostels.html", {"rows": rows, "form": form})


@admin_required
def hostel_detail(request, pk):
    org = _org(request)
    hostel = get_object_or_404(Hostel, pk=pk, organization=org)
    edit_form = HostelForm(instance=hostel, organization=org, prefix="hostel")
    room_form = RoomForm(hostel=hostel, prefix="room")
    bulk_form = BulkRoomForm(prefix="bulk", initial={"capacity": 4})
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "hostel":
            edit_form = HostelForm(request.POST, instance=hostel, organization=org, prefix="hostel")
            if edit_form.is_valid():
                edit_form.save()
                messages.success(request, "Hostel saved.")
                return redirect("setup:hostel", hostel.pk)
        elif action == "room":
            room_form = RoomForm(request.POST, hostel=hostel, prefix="room")
            if room_form.is_valid():
                room_form.save()
                messages.success(request, "Room added.")
                return redirect("setup:hostel", hostel.pk)
        elif action == "bulk":
            bulk_form = BulkRoomForm(request.POST, prefix="bulk")
            if bulk_form.is_valid():
                existing = set(hostel.rooms.values_list("number", flat=True))
                new = [n for n in bulk_form.numbers() if n not in existing]
                Room.objects.bulk_create(
                    [Room(hostel=hostel, number=n, capacity=bulk_form.cleaned_data["capacity"]) for n in new]
                )
                skipped = len(bulk_form.numbers()) - len(new)
                messages.success(request, f"{len(new)} room(s) added." + (f" {skipped} already existed and were skipped." if skipped else ""))
                return redirect("setup:hostel", hostel.pk)
    rooms = list(hostel.rooms.order_by("number"))
    rooms.sort(key=lambda r: (len(r.number), r.number))
    return render(request, "organizations/setup/hostel_detail.html", {
        "hostel": hostel, "rooms": rooms, "edit_form": edit_form, "room_form": room_form, "bulk_form": bulk_form,
    })


@admin_required
@require_POST
def hostel_delete(request, pk):
    hostel = get_object_or_404(Hostel, pk=pk, organization=_org(request))
    try:
        hostel.delete()
        messages.success(request, "Hostel deleted.")
    except ProtectedError:
        messages.error(request, f"{hostel.name} has rooms with a stay history, so it cannot be deleted.")
        return redirect("setup:hostel", pk)
    return redirect("setup:hostels")


@admin_required
def room_edit(request, pk):
    room = get_object_or_404(Room, pk=pk, hostel__organization=_org(request))
    form = RoomForm(request.POST or None, instance=room, hostel=room.hostel)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Room saved.")
        return redirect("setup:hostel", room.hostel_id)
    return render(request, "organizations/setup/simple_form.html",
                  {"form": form, "title": f"Edit room {room.number}", "back_url": reverse("setup:hostel", args=[room.hostel_id])})


@admin_required
@require_POST
def room_delete(request, pk):
    room = get_object_or_404(Room, pk=pk, hostel__organization=_org(request))
    hostel_id = room.hostel_id
    try:
        room.delete()
        messages.success(request, "Room deleted.")
    except ProtectedError:
        messages.error(request, f"Room {room.number} has a stay history, so it cannot be deleted.")
    return redirect("setup:hostel", hostel_id)


@admin_required
def staff_list(request):
    rows = (
        StaffProfile.objects.filter(organization=_org(request))
        .select_related("user")
        .prefetch_related("hostels")
        .order_by("role", "user__username")
    )
    return render(request, "organizations/setup/staff_list.html", {"rows": rows})


def _guard_admin_rules(request, form, profile):
    """Stop an admin from locking the organisation out. Returns an error text or None."""
    data = form.cleaned_data
    if profile is None:
        return None
    still_admin = data["role"] == StaffProfile.Role.ADMIN and data["is_active"]
    if profile.pk == request.staff.pk and not still_admin:
        return "You cannot remove your own admin access or deactivate your own account."
    if not still_admin and profile.role == StaffProfile.Role.ADMIN:
        others = StaffProfile.objects.filter(
            organization=profile.organization, role=StaffProfile.Role.ADMIN, user__is_active=True
        ).exclude(pk=profile.pk)
        if not others.exists():
            return "The organisation needs at least one active admin."
    return None


@admin_required
def staff_edit(request, pk=None):
    org = _org(request)
    profile = get_object_or_404(StaffProfile, pk=pk, organization=org) if pk else None
    initial = None
    if profile:
        initial = {
            "username": profile.user.username,
            "full_name": profile.user.get_full_name(),
            "role": profile.role,
            "hostels": list(profile.hostels.values_list("pk", flat=True)),
            "is_active": profile.user.is_active,
        }
    form = StaffForm(request.POST or None, organization=org, profile=profile, initial=initial)
    if request.method == "POST" and form.is_valid():
        problem = _guard_admin_rules(request, form, profile)
        if problem:
            form.add_error(None, problem)
        else:
            with transaction.atomic():
                saved = form.save()
            messages.success(request, f"{saved.user.username} saved.")
            return redirect("setup:staff")
    return render(request, "organizations/setup/staff_form.html", {"form": form, "profile": profile})
