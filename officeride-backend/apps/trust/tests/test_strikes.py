from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.bookings import services as booking_services
from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import make_request
from apps.rides.tests.helpers import make_user
from apps.trust import services
from apps.trust.models import Strike

from .helpers import S, TripMixin, after_departure, before_departure


class StrikeRuleTests(TripMixin, TestCase):
    def strike(self, user=None, n=1):
        """Give someone n strikes, each on its own request."""
        user = user or self.rider
        for i in range(n):
            req = make_request(self.ride, make_user(f"other{Strike.objects.count()}@acme.com"), self.day, status=S.CANCELLED)
            services.record_strike(user, Strike.Reason.NO_SHOW, req)
        user.refresh_from_db()
        return user

    def test_one_and_two_strikes_are_only_a_warning(self):
        user = self.strike(n=2)
        self.assertFalse(user.is_blocked)
        self.assertEqual(services.strike_summary(user)["count"], 2)

    def test_the_third_strike_suspends_for_seven_days(self):
        user = self.strike(n=3)
        self.assertTrue(user.is_suspended)
        self.assertAlmostEqual((user.suspended_until - timezone.now()).total_seconds(), 7 * 86400, delta=60)
        self.assertIn("suspended until", user.block_message)

    def test_the_fifth_strike_sends_the_account_to_review(self):
        user = self.strike(n=5)
        self.assertTrue(user.under_review)
        self.assertTrue(user.is_blocked)
        self.assertIn("under review", user.block_message)

    def test_a_strike_older_than_ninety_days_does_not_count(self):
        user = self.strike(n=2)
        Strike.objects.filter(user=user).update(created_at=timezone.now() - timedelta(days=91))
        user = self.strike(user, n=1)
        self.assertEqual(services.active_strikes(user).count(), 1)
        self.assertFalse(user.is_blocked)

    def test_a_waived_strike_does_not_count_and_lifts_a_suspension(self):
        user = self.strike(n=3)
        admin = make_user("admin@acme.com", is_staff=True)
        services.waive(Strike.objects.filter(user=user).first(), admin)
        user.refresh_from_db()
        self.assertFalse(user.is_suspended)
        waived = Strike.objects.get(waived=True)
        self.assertEqual(waived.waived_by, admin)
        self.assertIsNotNone(waived.waived_at)
        self.assertEqual(services.active_strikes(user).count(), 2)

    def test_waiving_twice_does_nothing_the_second_time(self):
        self.strike(n=1)
        strike = Strike.objects.get()
        admin = make_user("admin@acme.com", is_staff=True)
        self.assertTrue(services.waive(strike, admin))
        self.assertFalse(services.waive(strike, admin))

    def test_the_same_event_cannot_give_two_strikes(self):
        req = self.booking(S.CANCELLED)
        self.assertIsNotNone(services.record_strike(self.rider, Strike.Reason.LATE_CANCEL, req))
        self.assertIsNone(services.record_strike(self.rider, Strike.Reason.LATE_CANCEL, req))
        self.assertEqual(Strike.objects.count(), 1)

    def test_a_person_can_add_a_note_to_their_own_strike_only(self):
        self.strike(n=1)
        strike = Strike.objects.get()
        services.add_explanation(strike, self.rider, "My bus broke down")
        strike.refresh_from_db()
        self.assertEqual(strike.explanation, "My bus broke down")
        with self.assertRaises(services.TrustError):
            services.add_explanation(strike, self.driver, "not mine")

    def test_the_summary_tells_the_person_where_they_stand(self):
        self.assertIn("No strikes", services.strike_summary(self.rider)["state"])
        user = self.strike(n=1)
        self.assertIn("2 more strikes", services.strike_summary(user)["state"])


class StrikesFromBookingEventsTests(TripMixin, TestCase):
    def test_a_late_cancel_by_the_rider_gives_the_rider_a_strike(self):
        req = self.booking(S.ACCEPTED)
        with before_departure(self.day, 30):
            booking_services.cancel(req.pk, self.rider)
        strike = Strike.objects.get()
        self.assertEqual((strike.user, strike.reason, strike.request), (self.rider, Strike.Reason.LATE_CANCEL, req))

    def test_a_late_cancel_by_the_driver_gives_the_driver_a_strike(self):
        req = self.booking(S.ACCEPTED)
        with before_departure(self.day, 30):
            booking_services.cancel(req.pk, self.driver)
        self.assertEqual(Strike.objects.get().user, self.driver)

    def test_an_early_cancel_gives_no_strike(self):
        req = self.booking(S.ACCEPTED)
        with before_departure(self.day, 120):
            booking_services.cancel(req.pk, self.rider)
        self.assertEqual(Strike.objects.count(), 0)

    def test_cancelling_a_pending_request_late_gives_no_strike(self):
        req = self.booking(S.PENDING)
        with before_departure(self.day, 10):
            booking_services.cancel(req.pk, self.rider)
        self.assertEqual(Strike.objects.count(), 0)

    def test_the_driver_reporting_a_no_show_strikes_the_rider(self):
        req = self.booking(S.ACCEPTED)
        with after_departure(self.day):
            booking_services.report_no_show(req.pk, self.driver)
        self.assertEqual(Strike.objects.get().user, self.rider)
        self.assertEqual(Strike.objects.get().reason, Strike.Reason.NO_SHOW)

    def test_the_rider_reporting_a_no_show_strikes_the_driver(self):
        req = self.booking(S.ACCEPTED)
        with after_departure(self.day):
            booking_services.report_no_show(req.pk, self.rider)
        self.assertEqual(Strike.objects.get().user, self.driver)

    def test_completing_a_ride_gives_no_strike(self):
        req = self.booking(S.ACCEPTED)
        with after_departure(self.day):
            booking_services.complete(req.pk, self.driver)
        self.assertEqual(Strike.objects.count(), 0)