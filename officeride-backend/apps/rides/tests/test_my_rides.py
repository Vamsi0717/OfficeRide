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
    url = reverse("rides:mine")

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

    def test_live_and_switched_off_rides_are_in_separate_sections(self):
        off = car_ride(self.driver, days=ALL_DAYS, origin_name="Offroute")
        off.is_active = False
        off.save()
        page = self.client.get(self.url)
        self.assertContains(page, "Live")
        self.assertContains(page, "Switched off")
        self.assertEqual(len(page.context["live"]), 1)
        self.assertEqual(len(page.context["off"]), 1)

    def test_only_the_heading_for_a_section_that_has_rides_is_shown(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Live")
        self.assertNotContains(page, "Switched off")

    def test_today_tomorrow_and_next_booked_seats(self):
        self.booking(S.ACCEPTED, 0, "a@acme.com")
        self.booking(S.ACCEPTED, 0, "b@acme.com")
        self.booking(S.ACCEPTED, 1, "c@acme.com")
        self.booking(S.ACCEPTED, 4, "d@acme.com")
        self.booking(S.ACCEPTED, 4, "e@acme.com")
        self.booking(S.ACCEPTED, 9, "f@acme.com")
        ride = self.summary()
        self.assertEqual((ride.booked_today, ride.booked_tomorrow), (2, 1))
        self.assertEqual(ride.next_booked, (self.today + timedelta(days=4), 2))
        page = self.client.get(self.url)
        self.assertContains(page, "2 of 3")
        self.assertContains(page, "1 of 3")

    def test_pending_requests_are_counted_as_waiting_and_link_to_the_driving_tab(self):
        self.booking(S.PENDING, 2, "a@acme.com")
        self.booking(S.PENDING, 3, "b@acme.com")
        self.booking(S.ACCEPTED, 2, "c@acme.com")
        self.assertEqual(self.summary().waiting, 2)
        page = self.client.get(self.url)
        self.assertContains(page, "2 requests waiting for your reply")
        self.assertContains(page, reverse("bookings:trips") + "?view=driving")

    def test_cancelled_rejected_completed_and_past_bookings_do_not_count(self):
        self.booking(S.CANCELLED, 0, "a@acme.com")
        self.booking(S.REJECTED, 1, "b@acme.com")
        self.booking(S.COMPLETED, 0, "c@acme.com")
        self.booking(S.ACCEPTED, -3, "d@acme.com")
        ride = self.summary()
        self.assertEqual((ride.booked_today, ride.booked_tomorrow, ride.waiting, ride.next_booked), (0, 0, 0, None))

    def test_a_ride_that_does_not_run_today_says_so(self):
        tomorrow_only = (self.today + timedelta(days=1)).weekday()
        quiet = make_ride(make_driver("quiet@acme.com"), days=str(tomorrow_only))
        ride = services.attach_booking_summary([quiet])[0]
        self.assertFalse(ride.runs_today)
        self.assertTrue(ride.runs_tomorrow)
        self.client.force_login(quiet.driver)
        self.assertContains(self.client.get(self.url), "No ride")

    def test_a_deleted_ride_is_not_listed(self):
        self.ride.deleted_at = timezone.now()
        self.ride.save()
        page = self.client.get(self.url)
        self.assertContains(page, "You have not offered any rides yet")

    def test_the_empty_page_offers_the_next_step(self):
        self.client.force_login(make_driver("new@acme.com"))
        page = self.client.get(self.url)
        self.assertContains(page, "You have not offered any rides yet")
        self.assertContains(page, reverse("rides:offer"))

    def test_the_card_links_to_details_edit_and_switch(self):
        page = self.client.get(self.url)
        for name in ("rides:detail", "rides:edit", "rides:toggle", "rides:offer_back"):
            self.assertContains(page, reverse(name, args=[self.ride.pk]))

    def test_the_page_explains_the_difference_from_my_trips(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Rides I offer")
        self.assertContains(page, reverse("bookings:trips"))

    def test_the_query_count_does_not_grow_with_the_number_of_rides(self):
        self.booking(S.ACCEPTED, 0, "a@acme.com")
        with CaptureQueriesContext(connection) as few:
            self.client.get(self.url)
        for i in range(5):
            ride = car_ride(self.driver, days=ALL_DAYS, origin_name=f"R{i}")
            make_request(ride, make_user(f"x{i}@acme.com"), self.today, status=S.ACCEPTED)
            make_request(ride, make_user(f"y{i}@acme.com"), self.today + timedelta(days=2), status=S.PENDING)
        with CaptureQueriesContext(connection) as many:
            self.client.get(self.url)
        self.assertEqual(len(few), len(many))