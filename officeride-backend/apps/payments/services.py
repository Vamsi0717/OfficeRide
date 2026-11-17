from datetime import date, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.bookings.models import RideRequest

from . import gateway
from .models import Payment, Settlement


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


# ---------------------------------------------------------------- refunds

def refund_due(req):
    """The refund rule, in one place (also written in docs/decisions.md).

    Full refund when the booking is cancelled by either side before the ride leaves, and when the rider
    reports that the driver did not turn up. No refund for a completed ride, and none when the driver
    reports that the rider did not turn up."""
    if req.status == RideRequest.Status.CANCELLED:
        return True
    if req.status == RideRequest.Status.NO_SHOW:
        return req.reported_by_id == req.rider_id
    return False


def refund_for_request(req):
    """Called when a booking is cancelled or reported as a no-show. Does nothing if nothing was paid or
    the rule says no refund. Returns the payment when a refund was made or tried."""
    if not refund_due(req):
        return None
    payment = req.payments.filter(status__in=[Payment.Status.PAID]).first()
    if payment is None:
        return None
    return refund_payment(payment.pk)


def refund_payment(payment_pk):
    """Refund one paid payment in full. Safe to call again: a refunded payment is left alone, and a refund
    that Razorpay refused leaves the payment paid with a note, so it can be retried from the admin."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_pk)
        if payment.status != Payment.Status.PAID:
            return payment
        try:
            refund_id = gateway.refund(payment.razorpay_payment_id, payment.amount_paise)
        except gateway.GatewayError as exc:
            payment.refund_note = f"Refund failed: {exc}"
            payment.save(update_fields=["refund_note"])
            return payment
        payment.status = Payment.Status.REFUNDED
        payment.razorpay_refund_id = refund_id
        payment.refunded_at = timezone.now()
        payment.refund_note = ""
        payment.save(update_fields=["status", "razorpay_refund_id", "refunded_at", "refund_note"])
        return payment


# ---------------------------------------------------------------- driver earnings and settlements

def week_of(day):
    """The Monday and the Sunday of the week that holds this date."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def earned_payments(driver):
    """Paid payments for rides this driver completed. Refunded and unpaid ones are not earnings."""
    return Payment.objects.filter(
        request__ride__driver=driver, status=Payment.Status.PAID, request__status=RideRequest.Status.COMPLETED,
    ).select_related("request", "request__rider")


def earnings_summary(driver, today=None):
    today = today or timezone.localdate()
    monday, sunday = week_of(today)
    rows = list(earned_payments(driver).order_by("-request__date", "-pk")[:100])
    this_week = [p for p in rows if monday <= p.request.date <= sunday]
    return {
        "week_start": monday, "week_end": sunday,
        "this_week": this_week, "this_week_total": sum(p.driver_amount_paise for p in this_week) / 100,
        "earlier": [p for p in rows if p.request.date < monday],
        "waiting": sum(p.driver_amount_paise for p in rows if p.settlement_id is None) / 100,
    }


def build_settlements(week_start):
    """Gather every earned payment up to the end of that week that is not yet in a settlement, and put it
    in the settlement of its driver for that week. Safe to run again: a payment is never counted twice,
    and a settlement that is already paid out is not touched. Returns the settlements that were changed."""
    week_end = week_start + timedelta(days=6)
    changed = []
    drivers = (
        Payment.objects.filter(
            status=Payment.Status.PAID, request__status=RideRequest.Status.COMPLETED,
            settlement__isnull=True, request__date__lte=week_end,
        ).order_by().values_list("request__ride__driver", flat=True).distinct()  # order_by() so DISTINCT is not widened by the default ordering
    )
    for driver_id in drivers:
        with transaction.atomic():
            settlement, _ = Settlement.objects.select_for_update().get_or_create(
                driver_id=driver_id, week_start=week_start, defaults={"week_end": week_end},
            )
            if settlement.status == Settlement.Status.PAID:
                continue
            todo = Payment.objects.select_for_update().filter(
                request__ride__driver_id=driver_id, status=Payment.Status.PAID, request__status=RideRequest.Status.COMPLETED,
                settlement__isnull=True, request__date__lte=week_end,
            )
            todo.update(settlement=settlement)
            mine = settlement.payments.all()
            settlement.rides = mine.count()
            settlement.total_paise = sum(p.driver_amount_paise for p in mine)
            settlement.platform_fee_paise = sum(p.platform_fee_paise for p in mine)
            settlement.save(update_fields=["rides", "total_paise", "platform_fee_paise"])
            changed.append(settlement)
    return changed


def mark_settlement_paid(settlement, reference):
    reference = (reference or "").strip()
    if not reference:
        raise PaymentError("Type the bank or UPI reference of the transfer first.")
    if settlement.status == Settlement.Status.PAID:
        return settlement
    settlement.status = Settlement.Status.PAID
    settlement.paid_at = timezone.now()
    settlement.payout_reference = reference
    settlement.save(update_fields=["status", "paid_at", "payout_reference"])
    return settlement