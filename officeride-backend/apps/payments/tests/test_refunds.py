from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.bookings import services as booking_services
from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import car_ride, long_ago, make_request
from apps.payments import gateway, services
from apps.payments.models import Payment
from apps.rides.tests.helpers import make_driver, make_user

from .helpers import Booked, fake_refunds, paid_booking, practice_mode, with_test_keys

S = RideRequest.Status


@with_test_keys
class RefundRuleTests(Booked, TestCase):
    def test_the_rider_cancelling_a_paid_booking_gets_the_full_amount_back(self):
        req, payment = paid_booking(self.ride, self.rider)
        with fake_refunds() as refund:
            booking_services.cancel(req.pk, self.rider)
        refund.assert_called_once_with(payment.razorpay_payment_id, 5000)
        payment.refresh_from_db()
        self.assertEqual((payment.status, payment.razorpay_refund_id), ("refunded", f"rfnd_{payment.razorpay_payment_id}"))
        self.assertIsNotNone(payment.refunded_at)

    def test_the_driver_cancelling_a_paid_booking_also_refunds_the_rider(self):
        req, payment = paid_booking(self.ride, self.rider)
        with fake_refunds():
            booking_services.cancel(req.pk, self.driver)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "refunded")

    def test_the_platform_fee_is_refunded_too(self):
        req, payment = paid_booking(self.ride, self.rider, fee=500)
        with fake_refunds() as refund:
            booking_services.cancel(req.pk, self.rider)
        refund.assert_called_once_with(payment.razorpay_payment_id, 5500)

    def test_cancelling_an_unpaid_booking_asks_for_no_refund(self):
        with fake_refunds() as refund:
            booking_services.cancel(self.req.pk, self.rider)
        refund.assert_not_called()

    def test_a_rider_who_reports_that_the_driver_did_not_come_is_refunded(self):
        req, payment = paid_booking(self.ride, self.rider, date=long_ago())
        with fake_refunds():
            booking_services.report_no_show(req.pk, self.rider)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "refunded")

    def test_a_driver_who_reports_that_the_rider_did_not_come_keeps_the_money(self):
        req, payment = paid_booking(self.ride, self.rider, date=long_ago())
        with fake_refunds() as refund:
            booking_services.report_no_show(req.pk, self.driver)
        refund.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(payment.status, "paid")

    def test_a_completed_ride_is_never_refunded(self):
        req, payment = paid_booking(self.ride, self.rider, status=S.COMPLETED)
        with fake_refunds() as refund:
            self.assertIsNone(services.refund_for_request(req))
        refund.assert_not_called()

    def test_the_rule_in_one_table(self):
        req = self.req  # only the status and the reporter are changed in memory
        cases = [(S.PENDING, None, False), (S.ACCEPTED, None, False), (S.REJECTED, None, False), (S.COMPLETED, None, False),
                 (S.CANCELLED, None, True), (S.NO_SHOW, self.rider.id, True), (S.NO_SHOW, self.driver.id, False)]
        for status, reporter, expected in cases:
            req.status, req.reported_by_id = status, reporter
            with self.subTest(status=status, reporter=reporter):
                self.assertEqual(services.refund_due(req), expected)

    def test_refunding_twice_asks_razorpay_once(self):
        req, payment = paid_booking(self.ride, self.rider)
        with fake_refunds() as refund:
            services.refund_payment(payment.pk)
            services.refund_payment(payment.pk)
        self.assertEqual(refund.call_count, 1)


@with_test_keys
class RefundTroubleTests(Booked, TestCase):
    def test_a_refund_razorpay_refuses_does_not_stop_the_cancel_and_can_be_retried(self):
        req, payment = paid_booking(self.ride, self.rider)
        with mock.patch("apps.payments.services.gateway.refund", side_effect=gateway.GatewayError("down")):
            booking_services.cancel(req.pk, self.rider)
        req.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(req.status, "cancelled")
        self.assertEqual(payment.status, "paid")
        self.assertIn("Refund failed", payment.refund_note)
        with fake_refunds():
            services.refund_payment(payment.pk)
        payment.refresh_from_db()
        self.assertEqual((payment.status, payment.refund_note), ("refunded", ""))

    def test_the_admin_action_retries_only_payments_that_are_due(self):
        from apps.payments.admin import PaymentAdmin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        due_req, due = paid_booking(self.ride, self.rider, status=S.CANCELLED)
        other = make_user("b@acme.com")
        done_req, not_due = paid_booking(car_ride(make_driver("d2@acme.com")), other, status=S.COMPLETED)
        admin = PaymentAdmin(Payment, AdminSite())
        request = RequestFactory().post("/")
        request._messages = mock.MagicMock()
        with fake_refunds():
            admin.retry_refunds(request, Payment.objects.all())
        due.refresh_from_db()
        not_due.refresh_from_db()
        self.assertEqual((due.status, not_due.status), ("refunded", "paid"))


@with_test_keys
class RefundScreenTests(Booked, TestCase):
    def test_the_trips_page_shows_refunded_after_a_cancel(self):
        req, payment = paid_booking(self.ride, self.rider)
        self.client.force_login(self.rider)
        with fake_refunds():
            self.client.post(reverse("bookings:act", args=[req.pk, "cancel"]))
        page = self.client.get(reverse("bookings:trips"), {"view": "riding"})
        self.assertContains(page, "Refunded")
        self.assertContains(page, reverse("payments:receipt", args=[payment.pk]))

    def test_the_receipt_of_a_refunded_payment_says_so(self):
        req, payment = paid_booking(self.ride, self.rider)
        with fake_refunds():
            services.refund_payment(payment.pk)
        self.client.force_login(self.rider)
        self.assertContains(self.client.get(reverse("payments:receipt", args=[payment.pk])), "Payment refunded")


@practice_mode
class PracticeRefundTests(Booked, TestCase):
    def test_practice_mode_refunds_without_razorpay(self):
        req, payment = paid_booking(self.ride, self.rider)
        booking_services.cancel(req.pk, self.rider)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "refunded")
        self.assertTrue(payment.razorpay_refund_id.startswith("rfnd_fake_"))