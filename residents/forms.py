from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Count, F, Q

from accounts.access import hostels_for
from organizations.models import Category, DietType, Room

from .images import normalize_photo
from .models import Student
from .services import allocate_room, vacate_room


class RoomChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, room):
        free = room.capacity - room.occ
        return f"{room.hostel.name} / {room.number} - {free} free of {room.capacity}"


class StudentForm(forms.ModelForm):
    """Register or edit a student. Everything offered is limited to the staff member's scope."""

    room = RoomChoiceField(queryset=Room.objects.none(), required=False, empty_label="No room yet")

    class Meta:
        model = Student
        fields = [
            "roll_number", "name", "gender", "category", "diet", "religion",
            "course", "department", "country", "state",
            "guardian_name", "guardian_phone", "photo", "status",
        ]

    def __init__(self, *args, staff, **kwargs):
        super().__init__(*args, **kwargs)
        self.staff = staff
        org = staff.organization
        self.instance.organization = org  # needed so Student.clean() can compare organisations
        self.fields["category"].queryset = Category.objects.filter(organization=org)
        self.fields["diet"].queryset = DietType.objects.filter(organization=org)

        current = self.instance.current_room if self.instance.pk else None
        rooms = (
            Room.objects.filter(hostel__in=hostels_for(staff))
            .select_related("hostel")
            .annotate(occ=Count("allocations", filter=Q(allocations__end_date__isnull=True)))
        )
        has_space = Q(occ__lt=F("capacity"))
        if current:
            has_space |= Q(pk=current.pk)
        self.fields["room"].queryset = rooms.filter(has_space)
        self.fields["room"].initial = current

        if not self.instance.pk:
            del self.fields["status"]  # new students are always active

    def clean_roll_number(self):
        roll = self.cleaned_data["roll_number"].strip()
        clash = Student.objects.filter(organization=self.staff.organization, roll_number=roll)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("A student with this roll number already exists.")
        return roll

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if isinstance(photo, UploadedFile):
            return normalize_photo(photo)
        return photo

    def clean(self):
        cleaned = super().clean()
        room, gender = cleaned.get("room"), cleaned.get("gender")
        if room and gender and room.hostel.gender != gender:
            self.add_error("room", f"{room.hostel.name} is a {room.hostel.get_gender_display().lower()} hostel.")
        return cleaned

    def save(self, commit=True):
        """Save the student and move them into the chosen room. May raise ValidationError (e.g. room just filled)."""
        student = super().save(commit=False)
        student.organization = self.staff.organization
        room = self.cleaned_data.get("room")
        with transaction.atomic():
            student.save()
            current = student.current_room
            if student.status == Student.Status.LEFT:
                if current:
                    vacate_room(student, student.organization.local_today())
            elif room and (current is None or current.pk != room.pk):
                allocate_room(student, room, student.organization.local_today())
        return student


DATE_INPUT = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})


class _DatedForm(forms.Form):
    """A form with an effective date that cannot be in the future."""

    def __init__(self, *args, today, **kwargs):
        super().__init__(*args, **kwargs)
        self.today = today
        self.fields["date"].initial = today
        self.fields["date"].widget.attrs["max"] = today.isoformat()

    def clean_date(self):
        day = self.cleaned_data["date"]
        if day > self.today:
            raise forms.ValidationError("The date cannot be in the future.")
        return day


def _rooms_with_space(staff, student, keep=None):
    rooms = (
        Room.objects.filter(hostel__in=hostels_for(staff), hostel__gender=student.gender)
        .select_related("hostel")
        .annotate(occ=Count("allocations", filter=Q(allocations__end_date__isnull=True)))
        .filter(occ__lt=F("capacity"))
    )
    if keep is not None:
        rooms = rooms.exclude(pk=keep.pk)
    return rooms.order_by("hostel__name", "number")


class MoveRoomForm(_DatedForm):
    room = RoomChoiceField(queryset=Room.objects.none(), label="New room")
    date = forms.DateField(widget=DATE_INPUT, label="Moves on")

    def __init__(self, *args, staff, student, today, **kwargs):
        super().__init__(*args, today=today, **kwargs)
        self.fields["room"].queryset = _rooms_with_space(staff, student, keep=student.current_room)


class MarkLeftForm(_DatedForm):
    date = forms.DateField(widget=DATE_INPUT, label="Left on")


class ReadmitForm(_DatedForm):
    room = RoomChoiceField(queryset=Room.objects.none(), required=False, empty_label="No room yet", label="Room")
    date = forms.DateField(widget=DATE_INPUT, label="Back on")

    def __init__(self, *args, staff, student, today, **kwargs):
        super().__init__(*args, today=today, **kwargs)
        self.fields["room"].queryset = _rooms_with_space(staff, student)
