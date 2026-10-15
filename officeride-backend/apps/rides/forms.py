from datetime import timedelta

from django import forms
from django.conf import settings
from django.utils import timezone

from apps.core.forms import BootstrapFormMixin
from apps.core.widgets import TimePickerWidget

from . import geo
from apps.fares.engine import MAX_ADJUSTMENT_RS
from apps.fares.models import MileageRate

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
    return TimePickerWidget()


class VehicleModelSelect(forms.Select):
    """The model dropdown. Every option carries its make, so the page can show only the chosen make's models."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        rate = getattr(value, "instance", None)
        if rate is not None:
            option["attrs"]["data-make"] = rate.make  # the only thing the page needs; mileage is never sent to it
        return option


class VehicleModelChoiceField(forms.ModelChoiceField):
    """Shows only the model name in the dropdown. The mileage must never reach a driver's screen."""

    def label_from_instance(self, obj):
        return obj.name


class VehiclePickerMixin:
    """A make dropdown and a model dropdown. The model decides the mileage behind the fare, in the background."""

    def setup_vehicle_fields(self, vehicle_type):
        rates = MileageRate.objects.filter(vehicle_type=vehicle_type).exclude(make="")
        # Makes in catalog order (the most common in Bangalore first), each once.
        makes = list(dict.fromkeys(rates.order_by("id").values_list("make", flat=True)))
        self.fields["make"].choices = [("", "Choose make")] + [(m, m) for m in makes]
        self.fields["mileage_rate"].queryset = rates

    def clean_vehicle(self, cleaned):
        """Checks the model belongs to the make and fills in car_model (the text shown to riders)."""
        rate, make = cleaned.get("mileage_rate"), cleaned.get("make")
        if rate and make and rate.make != make:
            self.add_error("mileage_rate", f"That model is not a {make}. Pick one from the list.")
        elif rate:
            cleaned["car_model"] = rate.full_name


class OfferRideForm(VehiclePickerMixin, PlaceFieldsMixin, BootstrapFormMixin, forms.Form):
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
    make = forms.ChoiceField(label="Make", choices=[("", "Choose make")])
    mileage_rate = VehicleModelChoiceField(
        label="Model", queryset=MileageRate.objects.none(), empty_label="Choose model", widget=VehicleModelSelect,
    )
    toll_total = forms.IntegerField(
        label="Toll for the whole trip in ₹ (if any)", min_value=0, max_value=settings.FARE_MAX_TOLL_RS,
        required=False, initial=0, help_text="Split between the seats.",
    )
    fare_adjustment = forms.IntegerField(
        label="Change the fare by ₹ (optional)", min_value=-MAX_ADJUSTMENT_RS, max_value=MAX_ADJUSTMENT_RS,
        required=False, initial=0,
        help_text=f"Each rider pays this much more (plus) or less (minus) than the standard fare. Between -{MAX_ADJUSTMENT_RS} and {MAX_ADJUSTMENT_RS}.",
    )
    has_spare_helmet = forms.BooleanField(label="I will carry a spare helmet for the rider", required=False)
    offer_return = forms.BooleanField(label="Also offer the way back", required=False)
    return_time = forms.TimeField(label="Leaving for the way back at", required=False, widget=_time_widget())

    def __init__(self, *args, vehicle_type="car", **kwargs):
        super().__init__(*args, **kwargs)
        self.vehicle_type = vehicle_type
        self.fields["office_days"].widget.attrs["class"] = "form-check-input"
        # Only makes and models of this driver's vehicle type: a car driver is never offered scooter mileage.
        self.setup_vehicle_fields(vehicle_type)
        if vehicle_type == "bike":
            # A two-wheeler carries one rider, and the rider must wear a helmet.
            self.fields["seats"].initial = 1
            self.fields["seats"].disabled = True
            self.fields["has_spare_helmet"].required = True
            self.fields["has_spare_helmet"].error_messages["required"] = (
                "Riders must wear a helmet. Confirm that you carry a spare one."
            )
        else:
            del self.fields["has_spare_helmet"]

    def clean_toll_total(self):
        return self.cleaned_data.get("toll_total") or 0

    def clean_fare_adjustment(self):
        return self.cleaned_data.get("fare_adjustment") or 0

    def clean(self):
        cleaned = super().clean()
        self._check_places()
        self.clean_vehicle(cleaned)
        if not self.errors:
            distance = geo.haversine_m(
                cleaned["origin_lat"], cleaned["origin_lng"], cleaned["destination_lat"], cleaned["destination_lng"]
            )
            if distance < settings.RIDE_MIN_DISTANCE_M:
                self.add_error("destination_name", "The start and end are too close to share a ride.")
        if cleaned.get("offer_return") and not cleaned.get("return_time"):
            self.add_error("return_time", "Enter the time for the way back.")
        return cleaned


class EditRideForm(VehiclePickerMixin, BootstrapFormMixin, forms.Form):
    """Change a ride you already offer. The start and end are not editable: to change the route, delete the ride and offer a new one."""

    departure_time = forms.TimeField(label="Leaving at", widget=_time_widget())
    office_days = forms.MultipleChoiceField(
        label="Office days",
        choices=[(str(n), label) for n, label in WEEKDAYS],
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Choose at least one day."},
    )
    seats = forms.IntegerField(label="Seats you can offer", min_value=1, max_value=settings.MAX_SEATS)
    make = forms.ChoiceField(label="Make", choices=[("", "Choose make")])
    mileage_rate = VehicleModelChoiceField(
        label="Model", queryset=MileageRate.objects.none(), empty_label="Choose model", widget=VehicleModelSelect,
    )
    toll_total = forms.IntegerField(
        label="Toll for the whole trip in ₹ (if any)", min_value=0, max_value=settings.FARE_MAX_TOLL_RS,
        required=False, help_text="Split between the seats.",
    )
    fare_adjustment = forms.IntegerField(
        label="Change the fare by ₹", min_value=-MAX_ADJUSTMENT_RS, max_value=MAX_ADJUSTMENT_RS, required=False,
        help_text=f"Each new rider pays this much more (plus) or less (minus) than the standard fare. Between -{MAX_ADJUSTMENT_RS} and {MAX_ADJUSTMENT_RS}.",
    )
    has_spare_helmet = forms.BooleanField(label="I will carry a spare helmet for the rider", required=False)

    def __init__(self, *args, ride, **kwargs):
        initial = {
            "departure_time": ride.departure_time, "office_days": ride.office_days_list and [str(d) for d in ride.office_days_list],
            "seats": ride.seats, "make": ride.mileage_rate.make if ride.mileage_rate else "",
            "mileage_rate": ride.mileage_rate_id,
            "toll_total": ride.toll_total, "fare_adjustment": ride.fare_adjustment, "has_spare_helmet": ride.has_spare_helmet,
        }
        super().__init__(*args, initial=initial, **kwargs)
        self.ride = ride
        self.fields["office_days"].widget.attrs["class"] = "form-check-input"
        self.setup_vehicle_fields(ride.vehicle_type)
        if ride.is_bike:
            self.fields["seats"].disabled = True  # a two-wheeler carries one rider
            self.fields["has_spare_helmet"].required = True
            self.fields["has_spare_helmet"].error_messages["required"] = "Riders must wear a helmet. Confirm that you carry a spare one."
        else:
            del self.fields["has_spare_helmet"]

    def clean_toll_total(self):
        return self.cleaned_data.get("toll_total") or 0

    def clean_fare_adjustment(self):
        return self.cleaned_data.get("fare_adjustment") or 0

    def clean(self):
        cleaned = super().clean()
        self.clean_vehicle(cleaned)
        return cleaned


class FareAdjustmentForm(forms.Form):
    """The quick box on the ride page for moving the fare up or down."""

    fare_adjustment = forms.IntegerField(min_value=-MAX_ADJUSTMENT_RS, max_value=MAX_ADJUSTMENT_RS)


class SearchForm(PlaceFieldsMixin, BootstrapFormMixin, forms.Form):
    place_labels = {"pickup": "pickup place", "drop": "drop place"}

    pickup_name = PlaceFieldsMixin.place_fields()["name"]
    pickup_lat = PlaceFieldsMixin.place_fields()["lat"]
    pickup_lng = PlaceFieldsMixin.place_fields()["lng"]
    drop_name = PlaceFieldsMixin.place_fields()["name"]
    drop_lat = PlaceFieldsMixin.place_fields()["lat"]
    drop_lng = PlaceFieldsMixin.place_fields()["lng"]

    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    time = forms.TimeField(label="Around what time?", widget=_time_widget())
    vehicle = forms.ChoiceField(
        label="Vehicle",
        required=False,
        choices=[("", "Car or two-wheeler"), ("car", "Car only"), ("bike", "Two-wheeler only")],
    )

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


class ReturnTimeForm(forms.Form):
    return_time = forms.TimeField()


class UnavailableDateForm(BootstrapFormMixin, forms.Form):
    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    reason = forms.CharField(label="Reason (optional)", max_length=100, required=False)

    def clean_date(self):
        value = self.cleaned_data["date"]
        if value < timezone.localdate():
            raise forms.ValidationError("Choose today or a future date.")
        return value