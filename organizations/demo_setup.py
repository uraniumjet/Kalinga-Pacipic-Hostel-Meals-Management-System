"""Shared set-up used by the demo commands: categories, hostels, rooms, meals, counters and staff."""
from datetime import time

from django.contrib.auth.models import User

from mess.models import Counter, MealType, MealWindow
from organizations import demo
from organizations.models import Category, DietType, Hostel, Room, StaffProfile


def build_setup(org):
    """Create whatever is missing. Returns (categories by name, hostels in a fixed order)."""
    categories = {n: Category.objects.get_or_create(organization=org, name=n)[0] for n in demo.CATEGORIES}
    for n in demo.DIETS:
        DietType.objects.get_or_create(organization=org, name=n)
    hostels = []
    for name, (gender, rooms) in demo.HOSTELS.items():
        hostel, _ = Hostel.objects.get_or_create(organization=org, name=name, defaults={"gender": gender})
        hostels.append(hostel)
        for number, capacity in rooms:
            Room.objects.get_or_create(hostel=hostel, number=number, defaults={"capacity": capacity})
    for name, order, start, end in demo.MEALS:
        meal, _ = MealType.objects.get_or_create(organization=org, name=name, defaults={"sort_order": order})
        if not meal.windows.filter(special_period__isnull=True).exists():
            MealWindow.objects.create(meal_type=meal, start_time=time.fromisoformat(start), end_time=time.fromisoformat(end))
    for name, served in demo.COUNTERS:
        counter, _ = Counter.objects.get_or_create(organization=org, name=name)
        counter.categories.set([categories[c] for c in served])
    return categories, hostels


def ensure_user(username, role, org, password, hostels=None):
    """Create a staff user if missing. Returns True when a new user was created."""
    user, created = User.objects.get_or_create(username=username)
    if created:
        user.set_password(password)
        user.save()
    profile, _ = StaffProfile.objects.get_or_create(user=user, defaults={"organization": org, "role": role})
    if hostels is not None:
        profile.hostels.set(hostels)
    return created
