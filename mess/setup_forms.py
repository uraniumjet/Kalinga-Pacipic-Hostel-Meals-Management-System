"""Forms for the meal setup screens. Every form is bound to one organisation."""
from django import forms

from organizations.models import Category

from .models import Counter, MealType, MealWindow, SpecialPeriod, WindowOverride

TIME = forms.TimeInput(format="%H:%M", attrs={"type": "time"})
DATE = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})
CHECKS = {"class": "form-check-input"}


def effective_window(meal, period):
    """The window that decides a meal's time during a period: the period's own, else the normal one."""
    return (
        meal.windows.filter(special_period=period).first()
        or meal.windows.filter(special_period__isnull=True).first()
    )


def _check_times(form, start, end, end_field="end_time"):
    if start is not None and end is not None and start >= end:
        form.add_error(end_field, "The end time must be after the start time.")


class MealForm(forms.Form):
    """A meal and its normal serving time. Leave the times empty for a meal that only exists in a special period."""

    name = forms.CharField(max_length=50)
    sort_order = forms.IntegerField(min_value=0, max_value=999, initial=0, label="Order",
                                    help_text="Meals are shown in this order (1 for breakfast, 2 for lunch and so on).")
    start_time = forms.TimeField(widget=TIME, required=False, label="Normal serving starts")
    end_time = forms.TimeField(widget=TIME, required=False, label="Normal serving ends")

    def __init__(self, *args, organization, meal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.meal = meal
        if meal is not None and not self.is_bound:
            window = meal.windows.filter(special_period__isnull=True).first()
            self.initial.update({
                "name": meal.name,
                "sort_order": meal.sort_order,
                "start_time": window.start_time if window else None,
                "end_time": window.end_time if window else None,
            })

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = MealType.objects.filter(organization=self.organization, name__iexact=name)
        if self.meal:
            clash = clash.exclude(pk=self.meal.pk)
        if clash.exists():
            raise forms.ValidationError("A meal with this name already exists.")
        return name

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_time"), cleaned.get("end_time")
        if (start is None) != (end is None):
            self.add_error("end_time", "Give both times, or leave both empty.")
        else:
            _check_times(self, start, end)
        return cleaned

    def save(self):
        data = self.cleaned_data
        meal = self.meal or MealType(organization=self.organization)
        meal.name, meal.sort_order = data["name"], data["sort_order"]
        meal.save()
        window = meal.windows.filter(special_period__isnull=True).first()
        if data["start_time"] is None:
            if window:
                window.delete()
        elif window:
            window.start_time, window.end_time = data["start_time"], data["end_time"]
            window.save()
        else:
            MealWindow.objects.create(meal_type=meal, start_time=data["start_time"], end_time=data["end_time"])
        return meal


class CounterForm(forms.ModelForm):
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs=CHECKS),
        help_text="Tick the categories this counter serves. Leave all unticked to serve every student.",
    )

    class Meta:
        model = Counter
        fields = ["name", "categories"]

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.instance.organization = organization
        self.fields["categories"].queryset = Category.objects.filter(organization=organization)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = Counter.objects.filter(organization=self.organization, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("A counter with this name already exists.")
        return name


class PeriodForm(forms.ModelForm):
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.none(), required=False, widget=forms.CheckboxSelectMultiple(attrs=CHECKS),
        help_text="Leave all unticked to include every category.",
    )
    skipped_meals = forms.ModelMultipleChoiceField(
        queryset=MealType.objects.none(), required=False, widget=forms.CheckboxSelectMultiple(attrs=CHECKS),
        label="Meals not served in this period",
    )

    class Meta:
        model = SpecialPeriod
        fields = ["name", "start_date", "end_date", "religion", "categories", "skipped_meals"]
        widgets = {"start_date": DATE, "end_date": DATE}
        help_texts = {"religion": "Leave empty to include students of every religion."}

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.organization = organization
        self.fields["categories"].queryset = Category.objects.filter(organization=organization)
        self.fields["skipped_meals"].queryset = MealType.objects.filter(organization=organization)

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "The end date cannot be before the start date.")
        return cleaned


class WindowForm(forms.Form):
    """The serving time of one meal during a special period."""

    meal = forms.ModelChoiceField(queryset=MealType.objects.none())
    start_time = forms.TimeField(widget=TIME, label="Starts")
    end_time = forms.TimeField(widget=TIME, label="Ends")

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["meal"].queryset = MealType.objects.filter(organization=organization)

    def clean(self):
        cleaned = super().clean()
        _check_times(self, cleaned.get("start_time"), cleaned.get("end_time"))
        return cleaned


class OverrideForm(forms.Form):
    """A different time for one meal on one date inside a period (e.g. the iftaar time that moves with sunset)."""

    meal = forms.ModelChoiceField(queryset=MealType.objects.none())
    date = forms.DateField(widget=DATE)
    start_time = forms.TimeField(widget=TIME, label="Starts")
    end_time = forms.TimeField(widget=TIME, label="Ends")

    def __init__(self, *args, organization, period, **kwargs):
        super().__init__(*args, **kwargs)
        self.period = period
        self.fields["meal"].queryset = MealType.objects.filter(organization=organization).exclude(
            pk__in=period.skipped_meals.values("pk")
        )

    def clean(self):
        cleaned = super().clean()
        _check_times(self, cleaned.get("start_time"), cleaned.get("end_time"))
        day, meal = cleaned.get("date"), cleaned.get("meal")
        if day and not (self.period.start_date <= day <= self.period.end_date):
            self.add_error("date", "The date must be inside the period.")
        if meal and effective_window(meal, self.period) is None:
            self.add_error("meal", "This meal has no serving time in the period yet. Set its time first.")
        return cleaned

    def save(self):
        data = self.cleaned_data
        window = effective_window(data["meal"], self.period)
        override, _ = WindowOverride.objects.update_or_create(
            window=window, date=data["date"],
            defaults={"start_time": data["start_time"], "end_time": data["end_time"]},
        )
        return override
