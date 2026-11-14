"""Forms for the in-app setup screens. Every form is bound to one organisation."""

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile

from accounts.forms import timezone_choices
from organizations.images import normalize_logo
from organizations.models import Category, DietType, Hostel, Organization, Room, StaffProfile

TIME_WIDGET = forms.TimeInput(format="%H:%M", attrs={"type": "time"})


class OrganizationForm(forms.ModelForm):
    remove_logo = forms.BooleanField(required=False, label="Remove the current logo")
    timezone = forms.ChoiceField(choices=timezone_choices, help_text="Meal times and 'today' follow this zone.")
    roll_call_start = forms.TimeField(widget=TIME_WIDGET, label="Roll call opens")
    roll_call_end = forms.TimeField(widget=TIME_WIDGET, label="Roll call closes")

    class Meta:
        model = Organization
        fields = ["name", "logo", "timezone", "roll_call_start", "roll_call_end"]
        widgets = {"logo": forms.FileInput(attrs={"accept": "image/*"})}
        help_texts = {"logo": "Printed on student ID cards. A square or wide PNG with a transparent background works best (max 2 MB)."}

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if isinstance(logo, UploadedFile):
            return normalize_logo(logo)
        return logo

    def save(self, commit=True):
        org = super().save(commit=False)
        if self.cleaned_data.get("remove_logo") and "logo" not in self.files:
            org.logo = ""
        if commit:
            org.save()
        return org


class NameForm(forms.ModelForm):
    """Add or rename a category or diet type; names are unique per organisation, ignoring case."""

    class Meta:
        fields = ["name"]

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.instance.organization = organization

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = self._meta.model.objects.filter(organization=self.organization, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("This name already exists.")
        return name


class CategoryForm(NameForm):
    class Meta(NameForm.Meta):
        model = Category


class DietForm(NameForm):
    class Meta(NameForm.Meta):
        model = DietType


class HostelForm(forms.ModelForm):
    class Meta:
        model = Hostel
        fields = ["name", "gender"]

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.instance.organization = organization

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = Hostel.objects.filter(organization=self.organization, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("A hostel with this name already exists.")
        return name

    def clean_gender(self):
        gender = self.cleaned_data["gender"]
        if self.instance.pk and gender != self.instance.gender:
            from residents.models import RoomAllocation

            if RoomAllocation.objects.filter(room__hostel=self.instance, end_date__isnull=True).exists():
                raise forms.ValidationError("Students are living here now, so the gender cannot be changed.")
        return gender


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["number", "capacity"]

    def __init__(self, *args, hostel, **kwargs):
        super().__init__(*args, **kwargs)
        self.hostel = hostel
        self.instance.hostel = hostel

    def clean_number(self):
        number = self.cleaned_data["number"].strip()
        clash = Room.objects.filter(hostel=self.hostel, number__iexact=number)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("This room already exists in this hostel.")
        return number

    def clean_capacity(self):
        capacity = self.cleaned_data["capacity"]
        if self.instance.pk and capacity < self.instance.occupancy:
            raise forms.ValidationError(f"{self.instance.occupancy} students live here now, so it needs at least that many beds.")
        return capacity


class BulkRoomForm(forms.Form):
    """Create a run of rooms at once, e.g. 101 to 120 with 4 beds each."""

    prefix = forms.CharField(required=False, max_length=10, label="Prefix (optional)", help_text="For example A- gives A-101.")
    first = forms.IntegerField(min_value=0, max_value=99999, label="First number")
    last = forms.IntegerField(min_value=0, max_value=99999, label="Last number")
    capacity = forms.IntegerField(min_value=1, max_value=50, label="Beds per room", initial=4)

    def clean(self):
        cleaned = super().clean()
        first, last = cleaned.get("first"), cleaned.get("last")
        if first is not None and last is not None:
            if last < first:
                self.add_error("last", "The last number must not be smaller than the first.")
            elif last - first + 1 > 300:
                self.add_error("last", "Add at most 300 rooms at a time.")
        return cleaned

    def numbers(self):
        prefix = self.cleaned_data["prefix"].strip()
        return [f"{prefix}{n}" for n in range(self.cleaned_data["first"], self.cleaned_data["last"] + 1)]


class StaffForm(forms.Form):
    """Create or edit a warden/admin account inside one organisation."""

    username = forms.CharField(max_length=150)
    full_name = forms.CharField(max_length=150, required=False)
    role = forms.ChoiceField(choices=StaffProfile.Role.choices, initial=StaffProfile.Role.WARDEN)
    hostels = forms.ModelMultipleChoiceField(queryset=Hostel.objects.none(), required=False, widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
                                             help_text="Wardens see only these hostels. Admins see all.")
    is_active = forms.BooleanField(required=False, initial=True, label="Account is active")
    password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))

    def __init__(self, *args, organization, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.profile = profile
        self.fields["hostels"].queryset = Hostel.objects.filter(organization=organization)
        if profile is None:
            self.fields["password"].required = True
            self.fields["password"].label = "Password"
        else:
            self.fields["password"].label = "New password (leave empty to keep the current one)"
            self.fields["username"].disabled = True

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if self.profile is None and User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_password(self):
        password = self.cleaned_data["password"]
        if password:
            user = self.profile.user if self.profile else User(username=self.data.get("username", ""))
            password_validation.validate_password(password, user)
        return password

    def save(self):
        data = self.cleaned_data
        first, _, last = data["full_name"].strip().partition(" ")
        if self.profile is None:
            user = User.objects.create_user(data["username"], password=data["password"], first_name=first, last_name=last)
            self.profile = StaffProfile.objects.create(user=user, organization=self.organization, role=data["role"])
        else:
            user = self.profile.user
            user.first_name, user.last_name = first, last
            if data["password"]:
                user.set_password(data["password"])
            self.profile.role = data["role"]
            self.profile.save()
        user.is_active = data["is_active"]
        user.save()
        self.profile.hostels.set(data["hostels"])
        return self.profile
