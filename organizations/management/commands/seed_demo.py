import secrets
from datetime import time

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from mess.models import Counter, MealType, MealWindow
from organizations import demo
from organizations.models import Category, DietType, Hostel, Organization, Room, StaffProfile


class Command(BaseCommand):
    help = "Create a fictional demo organisation (hostels, rooms, meals, counters, an admin and a warden)."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Password for the demo users (default: a random one is printed)")

    @transaction.atomic
    def handle(self, *args, **options):
        org, created = Organization.objects.get_or_create(slug=demo.ORG["slug"], defaults=demo.ORG)
        if not created:
            self.stdout.write(f"{org.name} already exists; adding anything that is missing.")
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
                MealWindow.objects.create(
                    meal_type=meal, start_time=time.fromisoformat(start), end_time=time.fromisoformat(end)
                )
        for name, served in demo.COUNTERS:
            counter, _ = Counter.objects.get_or_create(organization=org, name=name)
            counter.categories.set([categories[c] for c in served])

        password = options["password"] or secrets.token_urlsafe(9)
        shown = []
        for username, role in (("demo_admin", "admin"), ("demo_warden", "warden")):
            user, new_user = User.objects.get_or_create(username=username)
            if new_user:
                user.set_password(password)
                user.save()
                shown.append(username)
            profile, _ = StaffProfile.objects.get_or_create(user=user, defaults={"organization": org, "role": role})
            if role == "warden":
                profile.hostels.set(hostels)
        self.stdout.write(self.style.SUCCESS("Demo organisation is ready."))
        if shown:
            self.stdout.write(f"New users: {', '.join(shown)}  password: {password}")
        else:
            self.stdout.write("Demo users already existed; their passwords were not changed.")
