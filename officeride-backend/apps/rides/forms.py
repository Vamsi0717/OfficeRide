from datetime import timedelta

from django import forms
from django.conf import settings
from django.utils import timezone

from apps.core.forms import BootstrapFormMixin

from . import geo
from .models import WEEKDAYS


class PlaceFieldsMixin:
    """Each place is three hidden fields (name, lat, lng) filled in by the place picker on the page."""

    place_labels = {}  # prefix -> label used in messages, e.g. {"origin": "start"}

    @staticmethod
    def place_fields():
        return {
            "name": forms.CharField(max_length=200, required=False, widget=forms.HiddenInput),
            "lat": forms.FloatField(required=False, widget=forms.HiddenInput),
            "lng": forms.FloatField(required=False, widget=forms.HiddenInput),
        }

    def _check_places(self):
        """Adds an error to <prefix>_name when a place was not picked or is outside Bangalore."""
        for prefix, label in self.place_labels.items():
            name = (self.cleaned_data.get(f"{prefix}_name") or "").strip()
            lat = self.cleaned_data.get(f"{prefix}_lat")
            lng = self.cleaned_data.get(f"{prefix}_lng")
            if not name or lat is None or lng is None:
                self.add_error(f"{prefix}_name", f"Pick the {label} from the suggestions.")
            elif not geo.in_bangalore(lat, lng):
                self.add_error(f"{prefix}_name", "OfficeRide works inside Bangalore only.")


def _time_widget():
    return forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class OfferRideForm(PlaceFieldsMixin, BootstrapFormMixin, forms.Form):
    place_labels = {"origin": "start place", "destination": "end place"}

    origin_name = PlaceFieldsMixin.place_fields()["name"]
    origin_lat = PlaceFieldsMixin.place_fields()["lat"]
    origin_lng = PlaceFieldsMixin.place_fields()["lng"]
    destination_name = PlaceFieldsMixin.place_fields()["name"]
    destination_lat = PlaceFieldsMixin.place_fields()["lat"]
    destination_lng = PlaceFieldsMixin.place_fields()["lng"]

    departure_time = forms.TimeField(label="Leaving at", widget=_time_widget())
    office_days = forms.MultipleChoiceField(
        label="Office days",
        choices=[(str(n), label) for n, label in WEEKDAYS],
        widget=forms.CheckboxSelectMultiple,
        initial=["0", "1", "2", "3", "4"],
        error_messages={"required": "Choose at least one day."},
    )
    seats = forms.IntegerField(label="Seats you can offer", min_value=1, max_value=settings.MAX_SEATS, initial=3)
    car_model = forms.CharField(label="Car (make and model)", max_length=60)
    offer_return = forms.BooleanField(label="Also offer the way back", required=False)
    return_time = forms.TimeField(label="Leaving for the way back at", required=False, widget=_time_widget())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["office_days"].widget.attrs["class"] = "form-check-input"

    def clean(self):
        cleaned = super().clean()
        self._check_places()
        if not self.errors:
            distance = geo.haversine_m(
                cleaned["origin_lat"], cleaned["origin_lng"], cleaned["destination_lat"], cleaned["destination_lng"]
            )
            if distance < settings.RIDE_MIN_DISTANCE_M:
                self.add_error("destination_name", "The start and end are too close to share a ride.")
        if cleaned.get("offer_return") and not cleaned.get("return_time"):
            self.add_error("return_time", "Enter the time for the way back.")
        return cleaned


class SearchForm(PlaceFieldsMixin, BootstrapFormMixin, forms.Form):
    place_labels = {"pickup": "pickup place", "drop": "drop place"}

    pickup_name = PlaceFieldsMixin.place_fields()["name"]
    pickup_lat = PlaceFieldsMixin.place_fields()["lat"]
    pickup_lng = PlaceFieldsMixin.place_fields()["lng"]
    drop_name = PlaceFieldsMixin.place_fields()["name"]
    drop_lat = PlaceFieldsMixin.place_fields()["lat"]
    drop_lng = PlaceFieldsMixin.place_fields()["lng"]

    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    time = forms.TimeField(label="Around", widget=_time_widget())

    def clean_date(self):
        value = self.cleaned_data["date"]
        today = timezone.localdate()
        if value < today:
            raise forms.ValidationError("Choose today or a future date.")
        if value > today + timedelta(days=60):
            raise forms.ValidationError("Choose a date within the next 60 days.")
        return value

    def clean(self):
        cleaned = super().clean()
        self._check_places()
        return cleaned


class UnavailableDateForm(BootstrapFormMixin, forms.Form):
    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    reason = forms.CharField(label="Reason (optional)", max_length=100, required=False)

    def clean_date(self):
        value = self.cleaned_data["date"]
        if value < timezone.localdate():
            raise forms.ValidationError("Choose today or a future date.")
        return value