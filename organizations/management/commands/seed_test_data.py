import secrets

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from organizations import demo
from organizations.demo_history import seed_history, wipe_organization_data
from organizations.demo_setup import build_setup, ensure_user
from organizations.models import Organization, StaffProfile


class Command(BaseCommand):
    help = (
        "Fill an organisation with fictional test data: students with photos, leave in every state, two weeks of "
        "roll calls and meals, a running Ramadan period, and wardens for each hostel."
    )

    def add_arguments(self, parser):
        parser.add_argument("--org", default=demo.ORG["slug"], help="Organisation slug (default: demo, created if missing)")
        parser.add_argument("--students", type=int, default=60)
        parser.add_argument("--days", type=int, default=14, help="Days of history (default: 14)")
        parser.add_argument("--seed", type=int, default=2026, help="Same seed gives the same people")
        parser.add_argument("--password", help="Password for new test users (default: random, printed once)")
        parser.add_argument("--no-photos", action="store_true", help="Skip the generated photos")
        parser.add_argument("--reset", action="store_true", help="Demo organisation only: wipe its data first")

    def handle(self, *args, **options):
        slug = options["org"]
        if slug == demo.ORG["slug"]:
            org, _ = Organization.objects.get_or_create(slug=slug, defaults=demo.ORG)
        else:
            org = Organization.objects.filter(slug=slug).first()
            if org is None:
                raise CommandError(f"No organisation with slug '{slug}'. Register it first, or use the default demo organisation.")
        if options["reset"]:
            if slug != demo.ORG["slug"]:
                raise CommandError("--reset is only allowed for the demo organisation.")
            wipe_organization_data(org)
        if org.students.exists():
            raise CommandError(
                f"{org.name} already has students. Run with --reset to start over (demo organisation only)."
            )

        password = options["password"] or secrets.token_urlsafe(9)
        with transaction.atomic():
            categories, hostels = build_setup(org)
            prefix = slug.replace("-", "_")
            accounts = [
                (f"{prefix}_admin", "admin", None),
                (f"{prefix}_warden", "warden", hostels),
                (f"{prefix}_warden_a", "warden", hostels[:1]),
                (f"{prefix}_warden_b", "warden", hostels[1:2]),
            ]
            created = [name for name, role, hs in accounts if ensure_user(name, role, org, password, hs)]
            staff_user = StaffProfile.objects.get(user__username=f"{prefix}_warden").user
            summary = seed_history(
                org, hostels, staff_user, students=options["students"], days=options["days"],
                seed=options["seed"], photos=not options["no_photos"],
            )

        self.stdout.write(self.style.SUCCESS(f"Test data ready in {org.name}."))
        for key, value in summary.items():
            self.stdout.write(f"  {key}: {value}")
        if created:
            self.stdout.write(f"New users: {', '.join(created)}  password: {password}")
        else:
            self.stdout.write("The test users already existed; their passwords were not changed.")
