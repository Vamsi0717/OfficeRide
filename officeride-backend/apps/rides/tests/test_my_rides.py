from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import car_ride, make_request
from apps.rides import services
from apps.rides.tests.helpers import make_driver, make_ride, make_user

S = RideRequest.Status
ALL_DAYS = "0,1,2,3,4,5,6"


class OfferedRidesPageTests(TestCase):

    def setUp(self):
        self.driver = make_driver()
        self.ride = car_ride(self.driver, days=ALL_DAYS)
        self.today = timezone.localdate()
        self.client.force_login(self.driver)

    def booking(self, status, offset, email):
        return make_request(self.ride, make_user(email), self.today + timedelta(days=offset), status=status)

    def summary(self):
        ride = services.attach_booking_summary([self.ride])[0]
        return ride


    def test_cancelled_rejected_completed_and_past_bookings_do_not_count(self):
        self.booking(S.CANCELLED, 0, "a@acme.com")
        self.booking(S.REJECTED, 1, "b@acme.com")
        self.booking(S.COMPLETED, 0, "c@acme.com")
        self.booking(S.ACCEPTED, -3, "d@acme.com")
        ride = self.summary()
        self.assertEqual((ride.booked_today, ride.booked_tomorrow, ride.waiting, ride.next_booked), (0, 0, 0, None))
