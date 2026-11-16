from django.test import TestCase
from django.urls import reverse

from apps.bookings.models import RideRequest
from apps.payments import services
from apps.payments.models import Payment
from apps.rides.tests.helpers import make_user

from .helpers import Booked, WEBHOOK_SECRET, checkout_signature, fake_orders, sign, webhook_body, with_test_keys


@with_test_keys
class CheckoutViewTests(Booked, TestCase):
    def test_pay_makes_an_order_and_shows_the_checkout_page(self):
        self.client.force_login(self.rider)
        with fake_orders():
            response = self.client.post(reverse("payments:pay", args=[self.req.pk]))
        payment = Payment.objects.get()
        self.assertRedirects(response, reverse("payments:checkout", args=[payment.pk]))
        page = self.client.get(response.url)
        self.assertContains(page, 'data-amount="5000"')
        self.assertContains(page, "order_")
        self.assertContains(page, "rzp_test_abc")
        self.assertContains(page, "Pay &#8377;50 with UPI")
        self.assertNotContains(page, "test-key-secret")

    def test_the_amount_in_the_form_is_ignored(self):
        self.client.force_login(self.rider)
        with fake_orders() as orders:
            self.client.post(reverse("payments:pay", args=[self.req.pk]), {"amount": "1", "amount_paise": "100"})
        self.assertEqual(orders.call_args.args[0], 5000)

    def test_pay_needs_a_post(self):
        self.client.force_login(self.rider)
        self.assertEqual(self.client.get(reverse("payments:pay", args=[self.req.pk])).status_code, 405)

    def test_somebody_else_cannot_pay_for_my_booking(self):
        self.client.force_login(make_user("x@acme.com"))
        self.assertEqual(self.client.post(reverse("payments:pay", args=[self.req.pk])).status_code, 404)

    def test_a_waiting_booking_shows_a_message_not_a_checkout(self):
        RideRequest.objects.filter(pk=self.req.pk).update(status="pending")
        self.client.force_login(self.rider)
        response = self.client.post(reverse("payments:pay", args=[self.req.pk]), follow=True)
        self.assertContains(response, "once the driver has accepted")

    def test_anonymous_goes_to_login(self):
        response = self.client.post(reverse("payments:pay", args=[self.req.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)


@with_test_keys
class ConfirmAndReceiptTests(Booked, TestCase):
    def setUp(self):
        super().setUp()
        with fake_orders():
            self.payment = services.start_payment(self.req, self.rider)
        self.client.force_login(self.rider)

    def confirm(self, signature):
        return self.client.post(reverse("payments:confirm"), {
            "razorpay_order_id": self.payment.razorpay_order_id, "razorpay_payment_id": "pay_7", "razorpay_signature": signature,
        })

    def test_a_good_signature_leads_to_the_receipt_with_the_breakdown(self):
        response = self.confirm(checkout_signature(self.payment.razorpay_order_id, "pay_7"))
        self.assertRedirects(response, reverse("payments:receipt", args=[self.payment.pk]))
        page = self.client.get(response.url)
        self.assertContains(page, "Payment received")
        self.assertContains(page, "Fare (fuel, wear and toll, shared)")
        self.assertContains(page, "OfficeRide fee")
        self.assertContains(page, "&#8377;50")

    def test_a_bad_signature_does_not_mark_it_paid(self):
        response = self.confirm("forged")
        self.assertRedirects(response, reverse("bookings:trips"))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "created")

    def test_the_checkout_page_of_a_paid_payment_goes_to_the_receipt(self):
        services.mark_paid(self.payment.razorpay_order_id, "pay_7")
        response = self.client.get(reverse("payments:checkout", args=[self.payment.pk]))
        self.assertRedirects(response, reverse("payments:receipt", args=[self.payment.pk]))

    def test_only_the_rider_can_see_the_receipt(self):
        self.client.force_login(self.driver)
        self.assertEqual(self.client.get(reverse("payments:receipt", args=[self.payment.pk])).status_code, 404)

    def test_the_trips_page_shows_pay_then_paid_with_a_receipt_link(self):
        trips = reverse("bookings:trips")
        self.assertContains(self.client.get(trips), "Pay &#8377;50")
        services.mark_paid(self.payment.razorpay_order_id, "pay_7")
        page = self.client.get(trips)
        self.assertContains(page, "Paid")
        self.assertContains(page, reverse("payments:receipt", args=[self.payment.pk]))
        self.assertNotContains(page, "Pay &#8377;50")

    def test_the_driver_does_not_see_a_pay_button(self):
        self.client.force_login(self.driver)
        self.assertNotContains(self.client.get(reverse("bookings:trips"), {"view": "driving"}), "Pay &#8377;")


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