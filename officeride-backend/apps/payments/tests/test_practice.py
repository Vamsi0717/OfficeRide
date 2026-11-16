from django.test import TestCase
from django.urls import reverse

from apps.bookings.models import RideRequest
from apps.payments.models import Payment
from apps.rides.tests.helpers import make_user

from .helpers import Booked, practice_mode, with_test_keys


@practice_mode
class PracticeModeTests(Booked, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.rider)

    def start(self):
        response = self.client.post(reverse("payments:pay", args=[self.req.pk]))
        self.payment = Payment.objects.get()
        return response

    def test_no_razorpay_account_is_needed_to_start_a_payment(self):
        self.assertRedirects(self.start(), reverse("payments:checkout", args=[self.payment.pk]))
        self.assertTrue(self.payment.razorpay_order_id.startswith("order_fake_"))
        self.assertEqual((self.payment.amount_paise, self.payment.status), (5000, "created"))

    def test_the_checkout_page_says_it_is_practice_and_has_no_razorpay_script(self):
        self.start()
        page = self.client.get(reverse("payments:checkout", args=[self.payment.pk]))
        self.assertContains(page, "Practice mode")
        self.assertContains(page, "Pretend to pay")
        self.assertNotContains(page, "checkout.razorpay.com")

    def test_pretending_to_pay_marks_it_paid_and_shows_the_receipt(self):
        self.start()
        response = self.client.post(reverse("payments:practice", args=[self.payment.pk]), {"result": "pay"})
        self.assertRedirects(response, reverse("payments:receipt", args=[self.payment.pk]))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")
        self.assertContains(self.client.get(response.url), "Payment received")

    def test_pretending_to_fail_marks_it_failed_and_the_rider_can_try_again(self):
        self.start()
        self.client.post(reverse("payments:practice", args=[self.payment.pk]), {"result": "fail"})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "failed")
        self.client.post(reverse("payments:pay", args=[self.req.pk]))
        self.assertEqual(Payment.objects.count(), 2)

    def test_somebody_else_cannot_use_the_buttons(self):
        self.start()
        self.client.force_login(make_user("x@acme.com"))
        self.assertEqual(self.client.post(reverse("payments:practice", args=[self.payment.pk]), {"result": "pay"}).status_code, 404)

    def test_the_buttons_need_a_post(self):
        self.start()
        self.assertEqual(self.client.get(reverse("payments:practice", args=[self.payment.pk])).status_code, 405)

    def test_a_paid_booking_cannot_be_paid_again_in_practice_mode(self):
        self.start()
        self.client.post(reverse("payments:practice", args=[self.payment.pk]), {"result": "pay"})
        response = self.client.post(reverse("payments:pay", args=[self.req.pk]), follow=True)
        self.assertContains(response, "already paid")

    def test_my_trips_shows_paid_after_pretending(self):
        self.start()
        self.client.post(reverse("payments:practice", args=[self.payment.pk]), {"result": "pay"})
        self.assertContains(self.client.get(reverse("bookings:trips")), "Receipt")


@with_test_keys
class PracticeButtonsAreOffInRealMode(Booked, TestCase):
    def test_the_practice_address_does_not_exist_when_razorpay_is_the_provider(self):
        from apps.payments import services
        from .helpers import fake_orders
        with fake_orders():
            payment = services.start_payment(self.req, self.rider)
        self.client.force_login(self.rider)
        response = self.client.post(reverse("payments:practice", args=[payment.pk]), {"result": "pay"})
        self.assertEqual(response.status_code, 404)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "created")