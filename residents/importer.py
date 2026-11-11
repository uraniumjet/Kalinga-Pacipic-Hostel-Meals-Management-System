"""Planning and running a student import. The plan is built without writing anything."""
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.core.files.base import ContentFile

from accounts.access import hostels_for
from organizations.models import Hostel, Room

from .images import normalize_photo
from .import_files import normalise_gender, read_photo
from .models import Student
from .services import allocate_room

FIELD_LIMITS = {
    "roll_number": 50, "name": 200, "religion": 50, "course": 150, "department": 150, "country": 100,
    "state": 100, "guardian_name": 200, "guardian_phone": 30,
}
TEXT_FIELDS = ["religion", "course", "department", "country", "state", "guardian_name", "guardian_phone"]


@dataclass
class RowResult:
    number: int
    data: dict
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    category: object = None
    diet: object = None
    room: object = None
    photo_member: str = ""

    @property
    def ok(self):
        return not self.errors


@dataclass
class ImportPlan:
    rows: list
    ignored_columns: list
    unmatched_photos: list = field(default_factory=list)
    photo_problems: list = field(default_factory=list)

    @property
    def ok_rows(self):
        return [r for r in self.rows if r.ok]

    @property
    def bad_rows(self):
        return [r for r in self.rows if not r.ok]

    @property
    def photos_matched(self):
        return sum(1 for r in self.ok_rows if r.photo_member)


@dataclass
class ImportSummary:
    created: int = 0
    failed: list = field(default_factory=list)  # [(row number, message)]
    photos_attached: int = 0
    photo_problems: list = field(default_factory=list)


def _names(objects):
    return ", ".join(sorted(o.name for o in objects)) or "none set up yet"


def plan_import(staff, parsed, photo_index=None):
    org = staff.organization
    categories = {c.name.lower(): c for c in org.categories.all()}
    diets = {d.name.lower(): d for d in org.diet_types.all()}
    my_hostels = {h.name.lower(): h for h in hostels_for(staff)}
    org_hostel_names = {n.lower() for n in Hostel.objects.filter(organization=org).values_list("name", flat=True)}
    rooms = {
        (r.hostel_id, r.number.lower()): r
        for r in Room.objects.filter(hostel__in=my_hostels.values()).select_related("hostel").annotate(
            occ=Count("allocations", filter=Q(allocations__end_date__isnull=True))
        )
    }
    existing = {r.lower() for r in Student.objects.filter(organization=org).values_list("roll_number", flat=True)}
    seen, reserved = {}, {}
    results = []

    for number, data in parsed.rows:
        row = RowResult(number, dict(data))
        roll = data["roll_number"]

        if len(roll) > FIELD_LIMITS["roll_number"]:
            row.errors.append("The roll number is too long.")
        elif roll.lower() in existing:
            row.errors.append(f"Roll number {roll} is already registered.")
        elif roll.lower() in seen:
            row.errors.append(f"Roll number {roll} appears twice in the file (first on row {seen[roll.lower()]}).")
        seen.setdefault(roll.lower(), number)

        if not data["name"]:
            row.errors.append("The name is missing.")
        elif len(data["name"]) > FIELD_LIMITS["name"]:
            row.errors.append("The name is too long.")

        gender = normalise_gender(data["gender"])
        if gender is None:
            row.errors.append(f"Gender must be male or female (found \"{data['gender']}\").")
        row.data["gender"] = gender or ""

        row.category = categories.get(data["category"].lower())
        if row.category is None:
            row.errors.append(f"Unknown category \"{data['category']}\". Use one of: {_names(categories.values())}.")
        row.diet = diets.get(data["diet"].lower())
        if row.diet is None:
            row.errors.append(f"Unknown diet \"{data['diet']}\". Use one of: {_names(diets.values())}.")

        for name in TEXT_FIELDS:
            if len(data.get(name, "")) > FIELD_LIMITS[name]:
                row.errors.append(f"{name.replace('_', ' ').capitalize()} is too long.")

        hostel_name, room_number = data.get("hostel", ""), data.get("room", "")
        if hostel_name or room_number:
            if not (hostel_name and room_number):
                row.errors.append("Give both the hostel and the room, or leave both empty.")
            elif hostel_name.lower() not in my_hostels:
                if hostel_name.lower() in org_hostel_names:
                    row.errors.append(f"Hostel \"{hostel_name}\" is not one of your hostels.")
                else:
                    row.errors.append(f"Unknown hostel \"{hostel_name}\". Use one of: {_names(my_hostels.values())}.")
            else:
                hostel = my_hostels[hostel_name.lower()]
                room = rooms.get((hostel.pk, room_number.lower()))
                if room is None:
                    row.errors.append(f"Hostel {hostel.name} has no room {room_number}.")
                elif gender and hostel.gender != gender:
                    row.errors.append(f"{hostel.name} is a {hostel.get_gender_display().lower()} hostel.")
                elif room.occ + reserved.get(room.pk, 0) >= room.capacity:
                    row.errors.append(f"Room {room.number} in {hostel.name} is full ({room.capacity} beds).")
                else:
                    row.room = room

        if photo_index is not None:
            row.photo_member = photo_index.find(roll, data.get("photo", "")) or ""
            if data.get("photo") and not row.photo_member:
                row.warnings.append(f"Photo file \"{data['photo']}\" was not found in the zip.")

        if row.ok and row.room is not None:
            reserved[row.room.pk] = reserved.get(row.room.pk, 0) + 1
        results.append(row)

    plan = ImportPlan(results, list(parsed.ignored_columns))
    if photo_index is not None:
        used = {r.photo_member for r in results if r.photo_member}
        plan.unmatched_photos = sorted(m for m in photo_index.by_name.values() if m not in used)
        plan.photo_problems = list(photo_index.problems)
    return plan


def run_import(staff, plan, photo_zip=None):
    """Create the students of every valid row. A row that fails at the last moment is reported, not fatal."""
    org = staff.organization
    today = org.local_today()
    summary = ImportSummary()
    created = []
    for row in plan.ok_rows:
        d = row.data
        try:
            with transaction.atomic():
                student = Student.objects.create(
                    organization=org, roll_number=d["roll_number"], name=d["name"], gender=d["gender"],
                    category=row.category, diet=row.diet,
                    **{name: d.get(name, "") for name in TEXT_FIELDS},
                )
                if row.room is not None:
                    allocate_room(student, row.room, today)
        except ValidationError as error:
            summary.failed.append((row.number, " ".join(error.messages)))
        except IntegrityError:
            summary.failed.append((row.number, f"Roll number {d['roll_number']} was registered in the meantime."))
        else:
            summary.created += 1
            created.append((student, row))

    if photo_zip is not None:
        for student, row in created:
            if not row.photo_member:
                continue
            try:
                picture = normalize_photo(ContentFile(read_photo(photo_zip, row.photo_member)))
                student.photo.save(picture.name, picture, save=True)
            except Exception:  # a broken picture must not undo the students already created
                summary.photo_problems.append(f"{row.photo_member}: could not be read as a picture.")
            else:
                summary.photos_attached += 1
    return summary
