from datetime import datetime, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.bookings import trips
from apps.chat import services as chat
from apps.bookings.models import RideRequest
from apps.rides.tests.helpers import make_user

from .helpers import car_ride, make_request

S = RideRequest.Status


def at(date, hour, minute=0):
    return timezone.make_aware(datetime.combine(date, datetime.min.time().replace(hour=hour, minute=minute)))


class TripsSetup:
    """A 9:00 ride. 'now' is set to 7:00 on a chosen day so today's ride has not left yet."""

    def setUp(self):
        super().setUp()
        self.ride = car_ride()
        self.driver = self.ride.driver
        self.rider = make_user("rider@acme.com", first_name="Anita", last_name="Rao")
        self.today = timezone.localdate()
        self.now = at(self.today, 7)

    def booking(self, status, offset_days=0, rider=None):
        email = f"p{RideRequest.objects.count()}@acme.com"
        return make_request(self.ride, rider or make_user(email), self.today + timedelta(days=offset_days), status=status)


class BucketTests(TripsSetup, TestCase):
    def bucket(self, req, now=None):
        return trips.bucket_for(req, now or self.now)

    def test_a_pending_request_before_the_ride_leaves_is_waiting(self):
        self.assertEqual(self.bucket(self.booking(S.PENDING, 3)), "pending")

    def test_a_pending_request_nobody_answered_before_the_ride_left_is_closed(self):
        self.assertEqual(self.bucket(self.booking(S.PENDING, -1)), "closed")

    def test_accepted_rides_go_under_today_tomorrow_or_coming_up(self):
        self.assertEqual(self.bucket(self.booking(S.ACCEPTED, 0)), "today")
        self.assertEqual(self.bucket(self.booking(S.ACCEPTED, 1)), "tomorrow")
        self.assertEqual(self.bucket(self.booking(S.ACCEPTED, 2)), "later")
        self.assertEqual(self.bucket(self.booking(S.ACCEPTED, 30)), "later")

    def test_an_accepted_ride_that_has_left_needs_an_update(self):
        self.assertEqual(self.bucket(self.booking(S.ACCEPTED, -2)), "update")
        today_booking = self.booking(S.ACCEPTED, 0)
        self.assertEqual(self.bucket(today_booking, at(self.today, 10)), "update")

    def test_finished_and_closed_bookings(self):
        for status, expected in ((S.COMPLETED, "completed"), (S.NO_SHOW, "completed"), (S.CANCELLED, "closed"), (S.REJECTED, "closed")):
            self.assertEqual(self.bucket(self.booking(status, -1)), expected)
            self.assertEqual(self.bucket(self.booking(status, 5)), expected)


class GroupTests(TripsSetup, TestCase):
    def sections(self, reqs, as_driver=False):
        return trips.group(reqs, as_driver, self.now)

    def test_sections_come_in_the_order_update_waiting_today_tomorrow_coming_up_completed_closed(self):
        reqs = [self.booking(S.CANCELLED, -1), self.booking(S.COMPLETED, -1), self.booking(S.ACCEPTED, 5), self.booking(S.ACCEPTED, 1),
                self.booking(S.ACCEPTED, 0), self.booking(S.PENDING, 4), self.booking(S.ACCEPTED, -3)]
        self.assertEqual([s["key"] for s in self.sections(reqs)],
                         ["update", "pending", "today", "tomorrow", "later", "completed", "closed"])

    def test_empty_sections_are_left_out(self):
        self.assertEqual(self.sections([]), [])
        self.assertEqual([s["key"] for s in self.sections([self.booking(S.ACCEPTED, 0)])], ["today"])

    def test_the_waiting_section_is_worded_for_who_is_looking(self):
        req = self.booking(S.PENDING, 3)
        self.assertEqual(self.sections([req], as_driver=False)[0]["title"], "Waiting for the driver")
        self.assertEqual(self.sections([req], as_driver=True)[0]["title"], "Waiting for your reply")

    def test_upcoming_sections_are_soonest_first_and_finished_ones_newest_first(self):
        far, near = self.booking(S.ACCEPTED, 9), self.booking(S.ACCEPTED, 4)
        self.assertEqual(self.sections([far, near])[0]["items"], [near, far])
        old, recent = self.booking(S.COMPLETED, -9), self.booking(S.COMPLETED, -2)
        self.assertEqual(self.sections([old, recent])[0]["items"], [recent, old])

    def test_only_old_sections_are_folded_away(self):
        reqs = [self.booking(S.COMPLETED, -1), self.booking(S.CANCELLED, -1), self.booking(S.ACCEPTED, 0), self.booking(S.PENDING, 3)]
        collapsed = {s["key"]: s["collapsed"] for s in self.sections(reqs)}
        self.assertEqual(collapsed, {"pending": False, "today": False, "completed": True, "closed": True})

    def test_counts_for_the_tiles(self):
        reqs = [self.booking(S.ACCEPTED, 0), self.booking(S.ACCEPTED, 0), self.booking(S.ACCEPTED, 1), self.booking(S.PENDING, 3),
                self.booking(S.COMPLETED, -1)]
        counts = trips.counts(self.sections(reqs))
        self.assertEqual((counts["today"], counts["tomorrow"], counts["waiting"], counts["active"]), (2, 1, 1, 4))
