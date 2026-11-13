from django import forms

from accounts.access import hostels_for

from .periods import resolve_period


def _date_input():
    return forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})


class ReportFilterForm(forms.Form):
    PERIODS = [("day", "Daily"), ("week", "Weekly (Monday to Sunday)"), ("month", "Monthly"), ("custom", "Custom range")]

    period = forms.ChoiceField(choices=PERIODS)
    date = forms.DateField(required=False, widget=_date_input(), label="Date (for daily, weekly, monthly)")
    start = forms.DateField(required=False, widget=_date_input(), label="From (custom range)")
    end = forms.DateField(required=False, widget=_date_input(), label="To (custom range)")
    hostel = forms.ModelChoiceField(queryset=None, required=False, empty_label="All hostels")

    def __init__(self, *args, staff, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hostel"].queryset = hostels_for(staff).order_by("name")
        self.today = staff.organization.local_today()
        self.range = None

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        try:
            self.range = resolve_period(
                cleaned["period"], cleaned.get("date") or self.today, cleaned.get("start"), cleaned.get("end")
            )
        except ValueError as error:
            raise forms.ValidationError(str(error)) from None
        return cleaned
