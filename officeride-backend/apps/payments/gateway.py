"""The only file that talks to Razorpay. Everything else calls these small functions,
which is also what the tests replace, so no test ever makes a real payment call."""

import hashlib
import hmac
import logging
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    pass


def is_fake():
    """Practice mode: no Razorpay account, no real money. Orders are invented here and the checkout page has
    buttons that pretend to pay."""
    return settings.PAYMENTS_PROVIDER == "fake"


def create_order(amount_paise, receipt):
    """Ask Razorpay for an order and return its id. The amount comes from our own database."""
    if is_fake():
        return f"order_fake_{uuid.uuid4().hex[:14]}"
    import razorpay

    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise GatewayError("Payments are not set up yet.")
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    try:
        order = client.order.create({"amount": amount_paise, "currency": "INR", "receipt": receipt, "payment_capture": 1})
    except Exception as exc:  # the library raises several kinds of errors
        logger.warning("Razorpay refused the order: %r", exc)  # the real reason, for the terminal
        raise GatewayError("Razorpay did not accept the order.") from exc
    return order["id"]


def _matches(secret, message, signature):
    if not secret or not signature:
        return False  # with no secret set, nothing can be trusted
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def checkout_signature_ok(order_id, payment_id, signature):
    """The browser hands back a signature after paying. Only Razorpay and we know the secret that makes it."""
    return _matches(settings.RAZORPAY_KEY_SECRET, f"{order_id}|{payment_id}".encode(), signature)


def webhook_signature_ok(raw_body, signature):
    return _matches(settings.RAZORPAY_WEBHOOK_SECRET, raw_body, signature)