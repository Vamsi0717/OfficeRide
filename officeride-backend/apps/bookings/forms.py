from datetime import timedelta

from django import forms
from django.conf import settings
from django.utils import timezone

from apps.core.forms import BootstrapFormMixin
from apps.core.widgets import TimePickerWidget
from apps.rides.forms import PlaceFieldsMixin

from .models import PlanDay
from .planner import WORK_DAYS


class RequestSeatForm(PlaceFieldsMixin, forms.Form):
    """What the Request button on a search result sends: the date and the rider's own pickup and drop."""

    place_labels = {"pickup": "pickup place", "drop": "drop place"}

    pickup_name = PlaceFieldsMixin.place_fields()["name"]
    pickup_lat = PlaceFieldsMixin.place_fields()["lat"]
    pickup_lng = PlaceFieldsMixin.place_fields()["lng"]
    drop_name = PlaceFieldsMixin.place_fields()["name"]
    drop_lat = PlaceFieldsMixin.place_fields()["lat"]
    drop_lng = PlaceFieldsMixin.place_fields()["lng"]
    date = forms.DateField()

    def clean(self):
        cleaned = super().clean()
        self._check_places()
        return cleaned


class WeeklyPlanForm(BootstrapFormMixin, forms.Form):
    """One choice for each office day. Empty means no plan, so nothing is hidden or blocked that day."""

    def __init__(self, *args, can_drive=False, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "No plan"), (PlanDay.Mode.RIDING, "Riding with someone"), (PlanDay.Mode.NOT_GOING, "Not going")]
        if can_drive:
            choices.insert(1, (PlanDay.Mode.DRIVING, "Driving"))
        for number, label in WORK_DAYS:
            self.fields[f"day_{number}"] = forms.ChoiceField(label=label, required=False, choices=choices)

    def modes(self):
        return {number: self.cleaned_data.get(f"day_{number}", "") for number, _ in WORK_DAYS}


class OverrideForm(BootstrapFormMixin, forms.Form):
    """A one-off change for a single date."""

    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    mode = forms.ChoiceField(label="That day I am", choices=PlanDay.Mode.choices)

    def __init__(self, *args, can_drive=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not can_drive:
            self.fields["mode"].choices = [c for c in PlanDay.Mode.choices if c[0] != PlanDay.Mode.DRIVING]

    def clean_date(self):
        value = self.cleaned_data["date"]
        today = timezone.localdate()
        if value < today:
            raise forms.ValidationError("Choose today or a future date.")
        if value > today + timedelta(days=settings.BOOKING_DAYS_AHEAD):
            raise forms.ValidationError(f"Choose a date within the next {settings.BOOKING_DAYS_AHEAD} days.")
        return value


class BackSearchForm(BootstrapFormMixin, forms.Form):
    """The 'request ride back' page: when, and how flexible the time is."""

    WINDOWS = [("15", "Around that time (15 minutes either way)"), ("30", "30 minutes either way"), ("60", "1 hour either way")]

    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    time = forms.TimeField(label="Leaving around", widget=TimePickerWidget())
    window = forms.ChoiceField(label="How flexible", choices=WINDOWS, initial="15")

    def clean_date(self):
        value = self.cleaned_data["date"]
        today = timezone.localdate()
        if value < today:
            raise forms.ValidationError("Choose today or a future date.")
        if value > today + timedelta(days=settings.BOOKING_DAYS_AHEAD):
            raise forms.ValidationError(f"Choose a date within the next {settings.BOOKING_DAYS_AHEAD} days.")
        return value