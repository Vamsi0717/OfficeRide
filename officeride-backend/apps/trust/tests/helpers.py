from datetime import datetime, timedelta
from unittest import mock

from django.utils import timezone

from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import car_ride, future_monday, make_request
from apps.rides.tests.helpers import make_user

S = RideRequest.Status


def at(date, hour, minute=0):
    return timezone.make_aware(datetime.combine(date, datetime.min.time().replace(hour=hour, minute=minute)))


def after_departure(day, minutes=60):
    """Pretend it is some time after the 9:00 ride on this day has left."""
    return mock.patch("django.utils.timezone.now", return_value=at(day, 9) + timedelta(minutes=minutes))


def before_departure(day, minutes=30):
    return mock.patch("django.utils.timezone.now", return_value=at(day, 9) - timedelta(minutes=minutes))


class TripMixin:
    """A driver with a 9:00 car ride, a rider, and a day in the future."""

    def setUp(self):
        super().setUp()
        self.ride = car_ride()
        self.driver = self.ride.driver
        self.rider = make_user("rider@acme.com", first_name="Anita", last_name="Rao")
        self.day = future_monday()

    def booking(self, status=S.ACCEPTED, rider=None, **extra):
        return make_request(self.ride, rider or self.rider, self.day, status=status, **extra)