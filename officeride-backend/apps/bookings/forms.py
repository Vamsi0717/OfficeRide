from django import forms

from apps.rides.forms import PlaceFieldsMixin


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