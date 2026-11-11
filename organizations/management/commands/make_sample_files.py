from django.core.management.base import BaseCommand

from organizations.demo import write_sample_files


class Command(BaseCommand):
    help = "Write fictional sample files for trying the student import (CSV, Excel, an error test file, photos zip)."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="sample_data", help="Folder to write into (default: sample_data)")
        parser.add_argument("--count", type=int, default=60, help="Number of students (default: 60)")
        parser.add_argument("--seed", type=int, default=2026, help="Random seed, so the same data comes out each time")

    def handle(self, *args, **options):
        paths = write_sample_files(options["out"], options["count"], options["seed"])
        for label, path in paths.items():
            self.stdout.write(f"{label:7} {path}")
