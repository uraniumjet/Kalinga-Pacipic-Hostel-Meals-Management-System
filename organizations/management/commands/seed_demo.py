import secrets

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from organizations import demo
from organizations.demo_setup import build_setup
from organizations.models import Organization, StaffProfile


class Command(BaseCommand):
    help = "Create a fictional demo organisation (hostels, rooms, meals, counters, an admin and a warden)."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Password for the demo users (default: a random one is printed)")

    @transaction.atomic
    def handle(self, *args, **options):
        org, created = Organization.objects.get_or_create(slug=demo.ORG["slug"], defaults=demo.ORG)
        if not created:
            self.stdout.write(f"{org.name} already exists; adding anything that is missing.")
        categories, hostels = build_setup(org)

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
