from django.test import TestCase
from django.urls import reverse

from apps.bookings.models import RideRequest
from apps.payments import services
from apps.payments.models import Payment
from apps.rides.tests.helpers import make_user

from .helpers import Booked, WEBHOOK_SECRET, checkout_signature, fake_orders, sign, webhook_body, with_test_keys


@with_test_keys
class WebhookTests(Booked, TestCase):
    def setUp(self):
        super().setUp()
        with fake_orders():
            self.payment = services.start_payment(self.req, self.rider)
        self.order = self.payment.razorpay_order_id
        self.url = reverse("payments:webhook")

    def send(self, event, secret=WEBHOOK_SECRET, signature=None):
        body = webhook_body(event, self.order)
        return self.client.post(
            self.url, body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=signature or sign(body, secret),
        )

    def test_a_signed_captured_event_marks_the_payment_paid(self):
        self.assertEqual(self.send("payment.captured").status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.status, self.payment.razorpay_payment_id), ("paid", "pay_1"))

    def test_the_same_event_twice_counts_once(self):
        self.send("payment.captured")
        paid_at = Payment.objects.get().paid_at
        self.assertEqual(self.send("payment.captured").status_code, 200)
        self.assertEqual(Payment.objects.filter(status="paid").count(), 1)
        self.assertEqual(Payment.objects.get().paid_at, paid_at)

    def test_a_failed_event_marks_the_attempt_failed(self):
        self.send("payment.failed")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "failed")

    def test_a_late_failed_event_does_not_undo_a_paid_payment(self):
        self.send("payment.captured")
        self.send("payment.failed")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_a_wrong_or_missing_signature_is_rejected_and_changes_nothing(self):
        self.assertEqual(self.send("payment.captured", secret="wrong").status_code, 400)
        body = webhook_body("payment.captured", self.order)
        self.assertEqual(self.client.post(self.url, body, content_type="application/json").status_code, 400)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "created")

    def test_an_unknown_event_or_order_is_accepted_and_ignored(self):
        self.assertEqual(self.send("refund.created").status_code, 200)
        body = webhook_body("payment.captured", "order_nobody")
        response = self.client.post(self.url, body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sign(body, WEBHOOK_SECRET))
        self.assertEqual(response.status_code, 200)

    def test_with_no_webhook_secret_set_everything_is_rejected(self):
        from django.test import override_settings
        body = webhook_body("payment.captured", self.order)
        with override_settings(RAZORPAY_WEBHOOK_SECRET=""):
            response = self.client.post(self.url, body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sign(body, ""))
        self.assertEqual(response.status_code, 400)

    def test_the_webhook_needs_no_login_and_no_csrf_token(self):
        from django.test import Client
        body = webhook_body("payment.captured", self.order)
        response = Client(enforce_csrf_checks=True).post(
            self.url, body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sign(body, WEBHOOK_SECRET),
        )
        self.assertEqual(response.status_code, 200)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


class AdminTests(Booked, TestCase):
    def test_the_admin_shows_a_payment_with_its_breakdown_and_cannot_add_or_delete(self):
        with_test_keys.enable()
        self.addCleanup(with_test_keys.disable)
        with fake_orders():
            payment = services.start_payment(self.req, self.rider)
        boss = make_user("boss@acme.com", is_staff=True, is_superuser=True)
        self.client.force_login(boss)
        page = self.client.get(reverse("admin:payments_payment_changelist"))
        self.assertContains(page, payment.razorpay_order_id)
        self.assertEqual(self.client.get(reverse("admin:payments_payment_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:payments_payment_delete", args=[payment.pk])).status_code, 403)
