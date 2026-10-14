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


class TripsPageTests(TripsSetup, TestCase):
    url = reverse("bookings:trips")

    def test_the_default_tab_is_riding_for_a_rider(self):
        self.booking(S.PENDING, 3, rider=self.rider)
        self.client.force_login(self.rider)
        response = self.client.get(self.url)
        self.assertEqual(response.context["tab"], "riding")
        self.assertContains(response, "Waiting for the driver")

    def test_the_default_tab_is_driving_when_someone_waits_for_my_reply(self):
        self.booking(S.PENDING, 3, rider=self.rider)
        self.client.force_login(self.driver)
        response = self.client.get(self.url)
        self.assertEqual(response.context["tab"], "driving")
        self.assertContains(response, "Waiting for your reply")
        self.assertContains(response, "1 to answer")

    def test_a_person_who_both_rides_and_drives_stays_on_riding_unless_someone_waits(self):
        other_ride = car_ride(driver=self.rider)
        make_request(other_ride, self.driver, self.today + timedelta(days=3), status=S.ACCEPTED)
        self.client.force_login(self.driver)
        self.assertEqual(self.client.get(self.url).context["tab"], "riding")

    def test_the_view_parameter_picks_the_tab_and_a_bad_value_falls_back(self):
        self.booking(S.ACCEPTED, 3, rider=self.rider)
        self.client.force_login(self.driver)
        self.assertEqual(self.client.get(self.url, {"view": "riding"}).context["tab"], "riding")
        self.assertEqual(self.client.get(self.url, {"view": "driving"}).context["tab"], "driving")
        self.assertEqual(self.client.get(self.url, {"view": "banana"}).context["tab"], "driving")

    def test_the_two_tabs_never_mix_the_bookings(self):
        mine = self.booking(S.ACCEPTED, 3, rider=self.rider)
        self.client.force_login(self.rider)
        riding = self.client.get(self.url, {"view": "riding"})
        driving = self.client.get(self.url, {"view": "driving"})
        self.assertContains(riding, reverse("chat:thread", args=[mine.pk]))
        self.assertNotContains(driving, reverse("chat:thread", args=[mine.pk]))
        self.assertContains(driving, "No one has asked for a seat on your rides yet")

    def test_empty_riding_tab_offers_find_a_ride(self):
        self.client.force_login(self.rider)
        response = self.client.get(self.url, {"view": "riding"})
        self.assertContains(response, "You have not asked for a ride yet")
        self.assertContains(response, reverse("rides:find"))

    def test_sections_and_tiles_show_on_the_page(self):
        self.booking(S.ACCEPTED, 3, rider=self.rider)
        self.booking(S.COMPLETED, -2, rider=self.rider)
        self.booking(S.CANCELLED, -2, rider=self.rider)
        self.client.force_login(self.rider)
        response = self.client.get(self.url)
        self.assertContains(response, "Coming up")
        self.assertContains(response, "Completed")
        self.assertContains(response, "Cancelled or declined")
        self.assertContains(response, "<details")  # the old ones are folded away
        self.assertEqual(response.context["counts"]["active"], 1)

    def test_the_card_has_a_big_time_the_date_the_person_and_the_fare(self):
        self.booking(S.ACCEPTED, 3, rider=self.rider)
        self.client.force_login(self.rider)
        response = self.client.get(self.url)
        self.assertContains(response, "9:00 AM")
        self.assertContains(response, "Driver: Ravi K.")
        self.assertContains(response, "&#8377;50")

    def test_a_driver_sees_the_rider_as_the_other_person(self):
        self.booking(S.PENDING, 3, rider=self.rider)
        self.client.force_login(self.driver)
        self.assertContains(self.client.get(self.url), "Rider: Anita R.")

    def test_navigation_uses_clear_names(self):
        self.client.force_login(self.rider)
        page = self.client.get(self.url)
        self.assertContains(page, "Rides I offer")
        self.assertContains(page, "My trips")

    def test_the_query_count_does_not_grow_with_the_number_of_bookings(self):
        self.booking(S.ACCEPTED, 3, rider=self.rider)
        self.client.force_login(self.rider)
        with CaptureQueriesContext(connection) as few:
            self.client.get(self.url)
        for i in range(8):
            self.booking(S.ACCEPTED, 4 + i, rider=make_user(f"extra{i}@acme.com"))
            make_request(self.ride, self.rider, self.today + timedelta(days=20 + i), status=S.ACCEPTED)
        with CaptureQueriesContext(connection) as many:
            self.client.get(self.url)
        self.assertEqual(len(few), len(many))


class CallIconTests(TripsSetup, TestCase):
    url = reverse("bookings:trips")

    def setUp(self):
        super().setUp()
        self.driver.phone = "9876543210"
        self.driver.save()

    def test_an_accepted_ride_today_shows_a_call_icon_without_the_number(self):
        req = self.booking(S.ACCEPTED, 0, rider=self.rider)
        self.client.force_login(self.rider)
        page = self.client.get(self.url)
        self.assertContains(page, reverse("chat:call", args=[req.pk]))
        self.assertContains(page, "bi-telephone-fill")
        self.assertNotContains(page, "9876543210")

    def test_no_call_icon_for_pending_or_far_away_rides(self):
        pending = self.booking(S.PENDING, 0, rider=self.rider)
        far = self.booking(S.ACCEPTED, 5, rider=make_user("far@acme.com"))
        self.client.force_login(self.rider)
        page = self.client.get(self.url)
        self.assertNotContains(page, reverse("chat:call", args=[pending.pk]))
        self.assertNotContains(page, reverse("chat:call", args=[far.pk]))

    def test_a_disabled_icon_when_the_other_person_has_no_phone(self):
        self.driver.phone = ""
        self.driver.save()
        req = self.booking(S.ACCEPTED, 0, rider=self.rider)
        self.client.force_login(self.rider)
        page = self.client.get(self.url)
        self.assertContains(page, "bi-telephone-x")
        self.assertNotContains(page, reverse("chat:call", args=[req.pk]))

    def test_the_chat_icon_has_an_unread_badge_and_a_label(self):
        req = self.booking(S.ACCEPTED, 3, rider=self.rider)
        chat.send(req, self.rider, "Hello")
        self.client.force_login(self.driver)
        page = self.client.get(self.url, {"view": "driving"})
        self.assertContains(page, 'aria-label="Chat"')
        self.assertContains(page, "bi-chat-dots-fill")