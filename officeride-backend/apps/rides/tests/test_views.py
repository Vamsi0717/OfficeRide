from datetime import time, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.fares import services as fare_services
from apps.fares.models import MileageRate
from apps.rides import maps
from apps.rides.models import CarUnavailableDate, Ride

from .helpers import get_model, get_rate, make_driver, make_ride, make_user, next_weekday, point_along

KR_PURAM = ("KR Puram", 13.0076, 77.6954)
BELLANDUR = ("Bellandur", 12.9260, 77.6760)


def offer_payload(**overrides):
    data = {
        "origin_name": KR_PURAM[0], "origin_lat": KR_PURAM[1], "origin_lng": KR_PURAM[2],
        "destination_name": BELLANDUR[0], "destination_lat": BELLANDUR[1], "destination_lng": BELLANDUR[2],
        "departure_time": "08:30", "office_days": ["0", "1", "2", "3", "4"],
        "seats": "3", "mileage_rate": get_model("car", "i20").pk,
    }
    data.update(overrides)
    # The make follows the chosen model unless a test sets it on purpose.
    data.setdefault("make", MileageRate.objects.get(pk=data["mileage_rate"]).make)
    return data


class ModelTests(TestCase):
    def test_office_days_display_and_runs_on(self):
        ride = make_ride(make_driver(), days="0,2,4")
        self.assertEqual(ride.office_days_display, "Mon, Wed, Fri")
        self.assertTrue(ride.runs_on(next_weekday(2)))
        self.assertFalse(ride.runs_on(next_weekday(1)))

    def test_offered_vehicle_type_comes_from_the_documents(self):
        self.assertEqual(make_driver("c@acme.com").offered_vehicle_type, "car")
        self.assertEqual(make_driver("b@acme.com", vehicle_type="bike").offered_vehicle_type, "bike")
        self.assertIsNone(make_user("none@acme.com").offered_vehicle_type)

    def test_seats_constraint(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            make_ride(make_driver(), seats=9)
