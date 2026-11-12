from zoneinfo import available_timezones

from django.contrib.auth import password_validation
from django.contrib.auth.models import User
from django.db import transaction
from django.utils.text import slugify

from django import forms

from organizations.models import Category, DietType, Organization, StaffProfile

STARTER_CATEGORIES = ["National", "International"]
STARTER_DIETS = ["Vegetarian", "Non-vegetarian"]


def timezone_choices():
    return [(name, name) for name in sorted(available_timezones()) if "/" in name or name == "UTC"]


def unique_slug(name):
    base = slugify(name)[:40] or "organisation"
    slug, n = base, 2
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


class OrganizationSignupForm(forms.Form):
    """Creates an organisation and its first admin in one step."""

    organization_name = forms.CharField(label="Organisation name", max_length=200)
    timezone = forms.ChoiceField(
        label="Time zone",
        choices=timezone_choices,
        initial="Asia/Kolkata",
        help_text="Meal times and 'today' follow this zone.",
    )
    username = forms.CharField(label="Admin username", max_length=150)
    full_name = forms.CharField(label="Your full name", max_length=150, required=False)
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repeat password", widget=forms.PasswordInput)
    starter_data = forms.BooleanField(
        label="Add starter categories and diet types",
        required=False,
        initial=True,
        help_text="National, International, Vegetarian, Non-vegetarian. You can change them later.",
    )

    def clean_organization_name(self):
        return self.cleaned_data["organization_name"].strip()

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                try:
                    password_validation.validate_password(p1, User(username=cleaned.get("username", "")))
                except forms.ValidationError as error:
                    self.add_error("password1", error)
        return cleaned

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        org = Organization.objects.create(
            name=data["organization_name"], slug=unique_slug(data["organization_name"]), timezone=data["timezone"]
        )
        first, _, last = data["full_name"].strip().partition(" ")
        user = User.objects.create_user(
            data["username"], password=data["password1"], first_name=first, last_name=last
        )
        StaffProfile.objects.create(user=user, organization=org, role=StaffProfile.Role.ADMIN)
        if data["starter_data"]:
            for name in STARTER_CATEGORIES:
                Category.objects.create(organization=org, name=name)
            for name in STARTER_DIETS:
                DietType.objects.create(organization=org, name=name)
        return user
