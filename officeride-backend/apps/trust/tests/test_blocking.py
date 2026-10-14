from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.bookings import services as booking_services
from apps.bookings.tests.helpers import car_ride, drop, future_monday, make_request, pickup
from apps.rides import matching
from apps.rides.tests.helpers import make_user, point_along

from .helpers import S, TripMixin


def suspend(user, days=7):
    user.suspended_until = timezone.now() + timedelta(days=days)
    user.save()


class BlockedUserTests(TripMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.searcher = make_user("searcher@acme.com")

    def search(self):
        return matching.find_rides(
            self.searcher, point_along(0.1)[:2], point_along(0.9)[:2], self.day, time(9, 0))

    def test_a_blocked_rider_cannot_request_a_seat(self):
        suspend(self.rider)
        with self.assertRaisesMessage(booking_services.BookingError, "suspended until"):
            booking_services.request_seat(self.rider, self.ride.pk, self.day, pickup(), drop())

    def test_a_rider_under_review_cannot_request_a_seat(self):
        self.rider.under_review = True
        self.rider.save()
        with self.assertRaisesMessage(booking_services.BookingError, "under review"):
            booking_services.request_seat(self.rider, self.ride.pk, self.day, pickup(), drop())

    def test_the_block_ends_by_itself(self):
        suspend(self.rider, days=-1)
        self.assertFalse(self.rider.is_blocked)
        self.assertEqual(booking_services.request_seat(self.rider, self.ride.pk, self.day, pickup(), drop()).status, S.PENDING)

    def test_a_blocked_driver_is_hidden_from_search_and_cannot_be_requested(self):
        self.assertEqual(len(self.search()), 1)
        suspend(self.driver)
        self.assertEqual(self.search(), [])
        with self.assertRaisesMessage(booking_services.BookingError, "not available"):
            booking_services.request_seat(self.rider, self.ride.pk, self.day, pickup(), drop())

    def test_a_driver_under_review_is_hidden_from_search(self):
        self.driver.under_review = True
        self.driver.save()
        self.assertEqual(self.search(), [])

    def test_a_blocked_driver_cannot_accept_a_request(self):
        req = make_request(self.ride, self.rider, self.day)
        suspend(self.driver)
        with self.assertRaisesMessage(booking_services.BookingError, "suspended until"):
            booking_services.accept(req.pk, self.driver)

    def test_a_blocked_driver_cannot_offer_a_ride_and_is_told_why(self):
        suspend(self.driver)
        self.client.force_login(self.driver)
        response = self.client.get(reverse("rides:offer"), follow=True)
        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertContains(response, "suspended until")

    def test_a_blocked_driver_cannot_switch_a_ride_back_on_or_offer_the_way_back(self):
        self.client.force_login(self.driver)
        self.client.post(reverse("rides:toggle", args=[self.ride.pk]))  # switch off while still allowed
        suspend(self.driver)
        self.client.post(reverse("rides:toggle", args=[self.ride.pk]))
        self.ride.refresh_from_db()
        self.assertFalse(self.ride.is_active)
        self.client.post(reverse("rides:offer_back", args=[self.ride.pk]), {"return_time": "18:00"})
        self.assertEqual(type(self.ride).objects.filter(driver=self.driver).count(), 1)

    def test_every_page_shows_a_banner_for_a_blocked_person(self):
        suspend(self.rider)
        self.client.force_login(self.rider)
        self.assertContains(self.client.get(reverse("bookings:trips")), "suspended until")

    def test_an_unblocked_person_sees_no_banner(self):
        self.client.force_login(self.rider)
        self.assertNotContains(self.client.get(reverse("bookings:trips")), "suspended until")