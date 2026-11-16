from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from apps.bookings.models import RideRequest
from apps.payments import services
from apps.payments.models import Payment
from apps.rides.tests.helpers import make_user

from .helpers import Booked, checkout_signature, fake_orders, with_test_keys

S = RideRequest.Status


@with_test_keys
class StartPaymentTests(Booked, TestCase):
    def test_the_order_amount_comes_from_the_saved_fare_in_paise(self):
        with fake_orders() as orders:
            payment = services.start_payment(self.req, self.rider)
        orders.assert_called_once_with(5000, receipt=f"request-{self.req.pk}")
        self.assertEqual(payment.amount_paise, 5000)
        self.assertEqual(payment.driver_amount_paise, 5000)
        self.assertEqual(payment.status, "created")

    def test_the_fare_adjustment_is_kept_apart_from_the_standard_fare(self):
        RideRequest.objects.filter(pk=self.req.pk).update(standard_fare=50, fare_adjustment=-10, fare=40)
        self.req.refresh_from_db()
        with fake_orders():
            payment = services.start_payment(self.req, self.rider)
        self.assertEqual((payment.standard_fare_paise, payment.adjustment_paise, payment.amount_paise), (5000, -1000, 4000))

    @override_settings(PLATFORM_FEE_PAISE=500)
    def test_the_platform_fee_is_added_on_its_own_line_and_the_driver_does_not_get_it(self):
        with fake_orders() as orders:
            payment = services.start_payment(self.req, self.rider)
        orders.assert_called_once_with(5500, receipt=f"request-{self.req.pk}")
        self.assertEqual((payment.platform_fee_paise, payment.amount_paise, payment.driver_amount_paise), (500, 5500, 5000))

    def test_pressing_pay_twice_reuses_the_waiting_order(self):
        with fake_orders() as orders:
            first = services.start_payment(self.req, self.rider)
            second = services.start_payment(self.req, self.rider)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(orders.call_count, 1)

    def test_only_the_rider_can_pay(self):
        with self.assertRaises(services.PaymentError):
            services.start_payment(self.req, self.driver)

    def test_a_booking_the_driver_has_not_accepted_cannot_be_paid(self):
        for status in (S.PENDING, S.REJECTED, S.CANCELLED, S.COMPLETED, S.NO_SHOW):
            RideRequest.objects.filter(pk=self.req.pk).update(status=status)
            self.req.refresh_from_db()
            with self.subTest(status=status), self.assertRaises(services.PaymentError):
                services.start_payment(self.req, self.rider)

    def test_a_paid_booking_cannot_be_paid_again(self):
        with fake_orders():
            payment = services.start_payment(self.req, self.rider)
        services.mark_paid(payment.razorpay_order_id, "pay_1")
        with self.assertRaises(services.PaymentError):
            services.start_payment(self.req, self.rider)

    def test_a_ride_that_already_left_cannot_be_paid(self):
        from apps.bookings.tests.helpers import long_ago
        old = RideRequest.objects.get(pk=self.req.pk)
        old.date = long_ago()
        old.save()
        with self.assertRaises(services.PaymentError):
            services.start_payment(old, self.rider)

    def test_a_razorpay_problem_becomes_a_plain_message_and_saves_nothing(self):
        from apps.payments.gateway import GatewayError
        from unittest import mock
        with mock.patch("apps.payments.services.gateway.create_order", side_effect=GatewayError("down")):
            with self.assertRaises(services.PaymentError):
                services.start_payment(self.req, self.rider)
        self.assertEqual(Payment.objects.count(), 0)


@with_test_keys
class ConfirmAndWebhookTests(Booked, TestCase):
    def setUp(self):
        super().setUp()
        with fake_orders():
            self.payment = services.start_payment(self.req, self.rider)
        self.order = self.payment.razorpay_order_id

    def test_a_good_signature_marks_the_payment_paid(self):
        services.confirm_checkout(self.rider, self.order, "pay_9", checkout_signature(self.order, "pay_9"))
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.status, self.payment.razorpay_payment_id), ("paid", "pay_9"))
        self.assertIsNotNone(self.payment.paid_at)

    def test_a_bad_signature_is_refused_and_nothing_changes(self):
        for bad in ("", "abc", checkout_signature(self.order, "pay_other", "wrong-secret")):
            with self.subTest(signature=bad), self.assertRaises(services.PaymentError):
                services.confirm_checkout(self.rider, self.order, "pay_9", bad)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "created")

    def test_somebody_elses_order_is_not_found(self):
        with self.assertRaises(services.PaymentError):
            services.confirm_checkout(make_user("x@acme.com"), self.order, "pay_9", checkout_signature(self.order, "pay_9"))

    def test_marking_paid_twice_counts_once(self):
        self.assertTrue(services.mark_paid(self.order, "pay_9"))
        self.assertFalse(services.mark_paid(self.order, "pay_9"))
        self.assertEqual(Payment.objects.filter(status="paid").count(), 1)

    def test_a_failed_event_never_undoes_a_paid_payment(self):
        services.mark_paid(self.order, "pay_9")
        self.assertFalse(services.mark_failed(self.order, "pay_9"))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_a_failed_payment_can_be_tried_again_with_a_new_order(self):
        services.mark_failed(self.order, "pay_9")
        with fake_orders():
            again = services.start_payment(self.req, self.rider)
        self.assertNotEqual(again.pk, self.payment.pk)

    def test_the_database_allows_only_one_paid_payment_for_a_booking(self):
        services.mark_paid(self.order, "pay_9")
        other = Payment.objects.create(
            request=self.req, rider=self.rider, razorpay_order_id="order_other", standard_fare_paise=5000,
            amount_paise=5000, driver_amount_paise=5000,
        )
        other.status = "paid"
        with self.assertRaises(IntegrityError), transaction.atomic():
            other.save()