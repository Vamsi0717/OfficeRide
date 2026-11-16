import hashlib
import hmac
import itertools
import json
from unittest import mock

from django.test import override_settings

from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import car_ride, make_request
from apps.rides.tests.helpers import make_driver, make_user

KEY_SECRET = "test-key-secret"
WEBHOOK_SECRET = "test-webhook-secret"


def sign(message, secret):
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def checkout_signature(order_id, payment_id, secret=KEY_SECRET):
    return sign(f"{order_id}|{payment_id}".encode(), secret)


def webhook_body(event, order_id, payment_id="pay_1"):
    return json.dumps({"event": event, "payload": {"payment": {"entity": {"id": payment_id, "order_id": order_id}}}}).encode()


_order_numbers = itertools.count(1)


def fake_orders():
    """Replaces the Razorpay call. Every order gets a new id, and the calls are kept so a test can look at them."""
    return mock.patch(
        "apps.payments.services.gateway.create_order", side_effect=lambda amount, receipt: f"order_{next(_order_numbers)}",
    )


class Booked:
    """An accepted booking with a fare of 50 rupees."""

    def setUp(self):
        self.driver = make_driver()
        self.ride = car_ride(self.driver)
        self.rider = make_user("anita@acme.com", first_name="Anita", last_name="Rao")
        self.req = make_request(self.ride, self.rider, status=RideRequest.Status.ACCEPTED)


# The other tests check the Razorpay path, so they say so. The practice-mode tests turn "fake" on themselves.
with_test_keys = override_settings(
    PAYMENTS_PROVIDER="razorpay", RAZORPAY_KEY_ID="rzp_test_abc", RAZORPAY_KEY_SECRET=KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET, PLATFORM_FEE_PAISE=0,
)
practice_mode = override_settings(PAYMENTS_PROVIDER="fake", RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="", PLATFORM_FEE_PAISE=0)