"""Small helpers shared by the rides API tests."""

from apps.accounts.models import DriverDocument
from apps.fares.models import MileageRate
from apps.rides.tests.helpers import get_model, point_along

KR_PURAM = ("KR Puram", 13.0076, 77.6954)
BELLANDUR = ("Bellandur", 12.9260, 77.6760)


def offer_body(**overrides):
    """A good offer, as the app would send it. The model is sent as `vehicle_model`."""
    data = {
        "origin_name": KR_PURAM[0], "origin_lat": KR_PURAM[1], "origin_lng": KR_PURAM[2],
        "destination_name": BELLANDUR[0], "destination_lat": BELLANDUR[1], "destination_lng": BELLANDUR[2],
        "departure_time": "08:30", "office_days": [0, 1, 2, 3, 4], "seats": 3,
        "vehicle_model": get_model("car", "i20").pk,
    }
    data.update(overrides)
    return data


def bike_offer_body(**overrides):
    values = {"vehicle_model": get_model("bike").pk, "has_spare_helmet": True}
    values.update(overrides)
    return offer_body(**values)


def search_params(date, **overrides):
    pickup, drop = point_along(0.2, 300), point_along(0.8, -200)
    data = {
        "pickup_name": "Near start", "pickup_lat": pickup[0], "pickup_lng": pickup[1],
        "drop_name": "Near end", "drop_lat": drop[0], "drop_lng": drop[1],
        "date": date.isoformat(), "time": "09:05",
    }
    data.update(overrides)
    return data


def withdraw_approval(user):
    """The documents are rejected after the ride was made."""
    DriverDocument.objects.filter(user=user).update(status=DriverDocument.Status.REJECTED)
    return type(user).objects.get(pk=user.pk)


def names(rate_ids):
    return list(MileageRate.objects.filter(pk__in=rate_ids).values_list("name", flat=True))