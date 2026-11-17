import hashlib
import hmac
import itertools
import json
from datetime import timedelta
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
_weeks = itertools.count(1)


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


def paid_booking(ride, rider, date=None, status=RideRequest.Status.ACCEPTED, fare=50, fee=0, **extra):
    """A booking that was paid for (through the real service, with a fake order) and then put in the given
    status and date, so a test can have a completed ride in the past."""
    from django.test import override_settings as _override

    from apps.payments import services
    from apps.bookings.tests.helpers import future_monday

    # A different week each time, so one rider can have several bookings on the same ride in a test.
    day = future_monday() + timedelta(weeks=next(_weeks))
    req = make_request(ride, rider, day, status=RideRequest.Status.ACCEPTED, standard_fare=fare, fare=fare)
    with _override(PLATFORM_FEE_PAISE=fee), fake_orders():
        payment = services.start_payment(req, rider)
    services.mark_paid(payment.razorpay_order_id, f"pay_{payment.pk}")
    values = {"status": status, **extra}
    if date is not None:
        values["date"] = date
    RideRequest.objects.filter(pk=req.pk).update(**values)
    req.refresh_from_db()
    payment.refresh_from_db()
    return req, payment


def fake_refunds():
    return mock.patch("apps.payments.services.gateway.refund", side_effect=lambda payment_id, amount: f"rfnd_{payment_id}")