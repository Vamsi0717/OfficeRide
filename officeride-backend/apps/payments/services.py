from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.bookings.models import RideRequest

from . import gateway
from .models import Payment


class PaymentError(Exception):
    """Something the person should be told, in plain words."""


def can_pay(req, user):
    """Why this booking cannot be paid right now, or an empty string when it can."""
    if req.rider_id != user.id:
        return "Only the rider can pay for this booking."
    if req.status != RideRequest.Status.ACCEPTED:
        return "You can pay once the driver has accepted."
    if req.departure_at <= timezone.now():
        return "This ride has already left."
    if req.payments.filter(status=Payment.Status.PAID).exists():
        return "This booking is already paid."
    return ""


def start_payment(req, user):
    """Make (or reuse) the payment for a booking. The amount is the fare saved on the booking, never
    a number sent from the browser."""
    problem = can_pay(req, user)
    if problem:
        raise PaymentError(problem)
    fare_paise = req.fare * 100
    fee = settings.PLATFORM_FEE_PAISE
    total = fare_paise + fee
    waiting = req.payments.filter(status=Payment.Status.CREATED, amount_paise=total).first()
    if waiting:
        return waiting
    try:
        order_id = gateway.create_order(total, receipt=f"request-{req.pk}")
    except gateway.GatewayError as exc:
        raise PaymentError(str(exc)) from exc
    return Payment.objects.create(
        request=req, rider=user, razorpay_order_id=order_id,
        standard_fare_paise=req.standard_fare * 100, adjustment_paise=req.fare_adjustment * 100,
        platform_fee_paise=fee, amount_paise=total, driver_amount_paise=fare_paise,
    )


def mark_paid(order_id, payment_id):
    """Record a successful payment. Safe to call twice for the same payment (the browser and the webhook
    both do): the second call changes nothing. Returns True only when this call made it paid."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(razorpay_order_id=order_id).first()
        if payment is None or payment.status in (Payment.Status.PAID, Payment.Status.REFUNDED):
            return False
        payment.status = Payment.Status.PAID
        payment.razorpay_payment_id = payment_id
        payment.paid_at = timezone.now()
        try:
            with transaction.atomic():
                payment.save()
        except IntegrityError:
            return False  # the booking was already paid through another order
    return True


def mark_failed(order_id, payment_id=""):
    """Record a failed attempt. A payment that is already paid is never turned back into failed."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(razorpay_order_id=order_id).first()
        if payment is None or payment.status != Payment.Status.CREATED:
            return False
        payment.status = Payment.Status.FAILED
        payment.razorpay_payment_id = payment_id
        payment.failed_at = timezone.now()
        payment.save()
    return True


def confirm_checkout(user, order_id, payment_id, signature):
    """The rider's browser says the payment went through. Believe it only if the signature is right."""
    payment = Payment.objects.filter(razorpay_order_id=order_id, rider=user).first()
    if payment is None:
        raise PaymentError("We could not find that payment.")
    if not gateway.checkout_signature_ok(order_id, payment_id, signature):
        raise PaymentError("We could not confirm that payment. If money left your account it will be returned.")
    mark_paid(order_id, payment_id)
    return payment


def handle_webhook_event(event):
    """One event from Razorpay. Unknown events are ignored, repeated events are harmless."""
    kind = event.get("event")
    entity = (event.get("payload") or {}).get("payment", {}).get("entity", {})
    order_id, payment_id = entity.get("order_id", ""), entity.get("id", "")
    if not order_id:
        return
    if kind == "payment.captured":
        mark_paid(order_id, payment_id)
    elif kind == "payment.failed":
        mark_failed(order_id, payment_id)