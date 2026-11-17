from datetime import date, timedelta

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from io import StringIO

from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import car_ride
from apps.payments import services
from apps.payments.models import Settlement
from apps.rides.tests.helpers import make_driver, make_user

from .helpers import Booked, paid_booking, with_test_keys

S = RideRequest.Status
MONDAY = date(2026, 11, 9)  # a Monday


@with_test_keys
class EarningsTests(Booked, TestCase):
    def test_a_week_runs_from_monday_to_sunday(self):
        self.assertEqual(services.week_of(date(2026, 11, 12)), (MONDAY, date(2026, 11, 15)))
        self.assertEqual(services.week_of(MONDAY), (MONDAY, date(2026, 11, 15)))
        self.assertEqual(services.week_of(date(2026, 11, 15)), (MONDAY, date(2026, 11, 15)))

    def test_only_completed_paid_rides_count_and_the_week_total_adds_up(self):
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED, fare=50)
        paid_booking(self.ride, self.rider, date=MONDAY + timedelta(days=2), status=S.COMPLETED, fare=40)
        paid_booking(self.ride, self.rider, date=MONDAY + timedelta(days=3), status=S.CANCELLED, fare=99)   # not a ride
        paid_booking(self.ride, self.rider, date=MONDAY + timedelta(days=4), status=S.NO_SHOW, fare=77)     # not completed
        paid_booking(self.ride, self.rider, date=MONDAY - timedelta(days=7), status=S.COMPLETED, fare=30)   # earlier week
        paid_booking(self.ride, self.rider, date=MONDAY + timedelta(days=7), status=S.COMPLETED, fare=20)   # later week
        summary = services.earnings_summary(self.driver, today=date(2026, 11, 12))
        self.assertEqual(len(summary["this_week"]), 2)
        self.assertEqual(summary["this_week_total"], 90)
        self.assertEqual(len(summary["earlier"]), 1)
        self.assertEqual(summary["waiting"], 90 + 30 + 20)

    def test_the_platform_fee_is_not_part_of_the_drivers_earnings(self):
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED, fare=50, fee=500)
        self.assertEqual(services.earnings_summary(self.driver, today=MONDAY)["this_week_total"], 50)

    def test_a_refunded_ride_is_not_an_earning(self):
        req, payment = paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED)
        type(payment).objects.filter(pk=payment.pk).update(status="refunded")
        self.assertEqual(services.earnings_summary(self.driver, today=MONDAY)["this_week_total"], 0)

    def test_another_drivers_rides_are_not_mine(self):
        other = car_ride(make_driver("d2@acme.com"))
        paid_booking(other, self.rider, date=MONDAY, status=S.COMPLETED)
        self.assertEqual(services.earnings_summary(self.driver, today=MONDAY)["this_week"], [])

    def test_the_earnings_page_shows_this_weeks_rides_and_total(self):
        paid_booking(self.ride, self.rider, date=timezone.localdate(), status=S.COMPLETED, fare=50)
        self.client.force_login(self.driver)
        page = self.client.get(reverse("payments:earnings"))
        self.assertContains(page, "My earnings")
        self.assertContains(page, "&#8377;50")
        self.assertContains(page, "Anita R.")
        self.assertContains(page, "Rides this week")

    def test_the_earnings_page_for_a_driver_with_no_rides_is_friendly(self):
        self.client.force_login(self.driver)
        self.assertContains(self.client.get(reverse("payments:earnings")), "No completed, paid rides this week yet.")

    def test_only_drivers_see_the_link_in_the_profile_menu(self):
        self.client.force_login(self.driver)
        self.assertContains(self.client.get(reverse("accounts:profile")), reverse("payments:earnings"))
        self.client.force_login(self.rider)
        self.assertNotContains(self.client.get(reverse("accounts:profile")), reverse("payments:earnings"))

    def test_anonymous_goes_to_login(self):
        self.assertEqual(self.client.get(reverse("payments:earnings")).status_code, 302)


@with_test_keys
class SettlementTests(Booked, TestCase):
    def setUp(self):
        super().setUp()
        self.driver2 = make_driver("d2@acme.com")
        self.ride2 = car_ride(self.driver2)

    def test_each_driver_gets_one_settlement_whose_totals_add_up(self):
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED, fare=50, fee=500)
        paid_booking(self.ride, self.rider, date=MONDAY + timedelta(days=1), status=S.COMPLETED, fare=40, fee=500)
        paid_booking(self.ride2, self.rider, date=MONDAY + timedelta(days=1), status=S.COMPLETED, fare=60)
        made = services.build_settlements(MONDAY)
        self.assertEqual(len(made), 2)
        first = Settlement.objects.get(driver=self.driver)
        self.assertEqual((first.rides, first.total_paise, first.platform_fee_paise), (2, 9000, 1000))
        second = Settlement.objects.get(driver=self.driver2)
        self.assertEqual((second.rides, second.total_paise, second.platform_fee_paise), (1, 6000, 0))
        self.assertEqual((first.week_start, first.week_end), (MONDAY, date(2026, 11, 15)))

    def test_refunded_cancelled_unpaid_and_no_show_rides_are_left_out(self):
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED, fare=50)
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.CANCELLED, fare=11)
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.NO_SHOW, fare=12)
        _, refunded = paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED, fare=13)
        type(refunded).objects.filter(pk=refunded.pk).update(status="refunded")
        services.build_settlements(MONDAY)
        settlement = Settlement.objects.get()
        self.assertEqual((settlement.rides, settlement.total_paise), (1, 5000))

    def test_running_it_again_never_counts_a_payment_twice(self):
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED, fare=50)
        services.build_settlements(MONDAY)
        self.assertEqual(services.build_settlements(MONDAY), [])
        self.assertEqual(Settlement.objects.get().total_paise, 5000)

    def test_a_late_ride_is_added_to_the_waiting_settlement(self):
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED, fare=50)
        services.build_settlements(MONDAY)
        paid_booking(self.ride, self.rider, date=MONDAY + timedelta(days=2), status=S.COMPLETED, fare=25)
        services.build_settlements(MONDAY)
        settlement = Settlement.objects.get()
        self.assertEqual((settlement.rides, settlement.total_paise), (2, 7500))

    def test_rides_after_the_week_wait_for_the_next_one_and_earlier_stragglers_come_along(self):
        paid_booking(self.ride, self.rider, date=MONDAY - timedelta(days=3), status=S.COMPLETED, fare=30)
        paid_booking(self.ride, self.rider, date=MONDAY + timedelta(days=8), status=S.COMPLETED, fare=20)
        services.build_settlements(MONDAY)
        self.assertEqual(Settlement.objects.get().total_paise, 3000)
        services.build_settlements(MONDAY + timedelta(days=7))
        self.assertEqual(sorted(Settlement.objects.values_list("total_paise", flat=True)), [2000, 3000])

    def test_a_paid_out_settlement_is_never_changed_and_new_rides_wait_for_the_next_week(self):
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED, fare=50)
        services.build_settlements(MONDAY)
        services.mark_settlement_paid(Settlement.objects.get(), "UTR123")
        paid_booking(self.ride, self.rider, date=MONDAY + timedelta(days=1), status=S.COMPLETED, fare=25)
        services.build_settlements(MONDAY)
        self.assertEqual(Settlement.objects.get().total_paise, 5000)
        services.build_settlements(MONDAY + timedelta(days=7))
        self.assertEqual(Settlement.objects.count(), 2)

    def test_marking_paid_needs_a_reference_and_records_when(self):
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED)
        services.build_settlements(MONDAY)
        settlement = Settlement.objects.get()
        for empty in ("", "   ", None):
            with self.subTest(reference=empty), self.assertRaises(services.PaymentError):
                services.mark_settlement_paid(settlement, empty)
        services.mark_settlement_paid(settlement, " UTR98765 ")
        settlement.refresh_from_db()
        self.assertEqual((settlement.status, settlement.payout_reference), ("paid", "UTR98765"))
        self.assertIsNotNone(settlement.paid_at)

    def test_the_command_makes_settlements_and_says_what_it_did(self):
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED, fare=50)
        out = StringIO()
        call_command("make_settlements", "--week-start", "2026-11-09", stdout=out)
        self.assertIn("1 settlement(s) made or updated", out.getvalue())
        self.assertIn("driver@acme.com", out.getvalue())
        self.assertEqual(Settlement.objects.count(), 1)

    def test_the_command_refuses_a_date_that_is_not_a_monday(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("make_settlements", "--week-start", "2026-11-10")

    def test_the_earnings_page_lists_the_settlements(self):
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED, fare=50)
        services.build_settlements(MONDAY)
        self.client.force_login(self.driver)
        page = self.client.get(reverse("payments:earnings"))
        self.assertContains(page, "To be paid")
        services.mark_settlement_paid(Settlement.objects.get(), "UTR1")
        self.assertContains(self.client.get(reverse("payments:earnings")), "Paid out")


@with_test_keys
class SettlementAdminTests(Booked, TestCase):
    def setUp(self):
        super().setUp()
        paid_booking(self.ride, self.rider, date=MONDAY, status=S.COMPLETED, fare=50, fee=500)
        services.build_settlements(MONDAY)
        self.settlement = Settlement.objects.get()
        self.client.force_login(make_user("boss@acme.com", is_staff=True, is_superuser=True))

    def test_the_list_and_the_detail_show_the_totals_and_the_rides(self):
        page = self.client.get(reverse("admin:payments_settlement_changelist"))
        self.assertContains(page, "driver@acme.com")
        detail = self.client.get(reverse("admin:payments_settlement_change", args=[self.settlement.pk]))
        self.assertContains(detail, "pay_")

    def test_the_action_marks_paid_only_when_a_reference_was_typed(self):
        url = reverse("admin:payments_settlement_changelist")
        data = {"action": "mark_paid", "_selected_action": [self.settlement.pk]}
        self.client.post(url, data)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, "pending")
        Settlement.objects.filter(pk=self.settlement.pk).update(payout_reference="UTR555")
        self.client.post(url, data)
        self.settlement.refresh_from_db()
        self.assertEqual(self.settlement.status, "paid")

    def test_nobody_can_add_or_delete_a_settlement_in_the_admin(self):
        self.assertEqual(self.client.get(reverse("admin:payments_settlement_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:payments_settlement_delete", args=[self.settlement.pk])).status_code, 403)