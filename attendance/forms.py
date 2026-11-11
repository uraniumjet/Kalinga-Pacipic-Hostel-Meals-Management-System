from django import forms

from accounts.access import students_for


def _date_input():
    return forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})


class PermitForm(forms.Form):
    roll_number = forms.CharField(max_length=50)
    start_date = forms.DateField(widget=_date_input())
    end_date = forms.DateField(label="Last night away", widget=_date_input())
    destination = forms.CharField(max_length=200, required=False)
    reason = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, staff, **kwargs):
        super().__init__(*args, **kwargs)
        self.staff = staff
        self.student = None

    def clean_roll_number(self):
        roll = self.cleaned_data["roll_number"].strip()
        self.student = students_for(self.staff).filter(roll_number__iexact=roll).first()
        if self.student is None:
            raise forms.ValidationError("No student with this roll number in your hostels.")
        return roll
