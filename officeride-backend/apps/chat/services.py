"""Chat rules. A thread belongs to one booking. Only its two people can read or write, and it can be
written to only while the booking is pending or accepted; afterwards it stays readable."""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.utils import timezone

from apps.bookings.models import RideRequest

from .models import ChatRead, Message

QUICK_REPLIES = {
    "at-pickup": "I'm at the pickup point",
    "running-late": "Running 5 minutes late",
    "midpoint": "Can we meet at the midpoint?",
}


class ChatError(Exception):
    """A rule was broken. str(error) is safe to show."""


def is_participant(req, user):
    return user.id == req.rider_id or user.id == req.ride.driver_id


def can_write(req):
    return req.status in RideRequest.ACTIVE


def other_person(req, user):
    return req.ride.driver if user.id == req.rider_id else req.rider


def _check_write(req, user):
    if not is_participant(req, user):
        raise ChatError("This chat is not yours.")
    if not can_write(req):
        raise ChatError("This chat is closed because the ride is no longer active.")


def send(req, user, text):
    _check_write(req, user)
    text = (text or "").strip()
    if not text:
        raise ChatError("Write a message first.")
    if len(text) > settings.CHAT_MAX_CHARS:
        raise ChatError(f"Messages can be up to {settings.CHAT_MAX_CHARS} characters. Yours has {len(text)}.")
    if Message.objects.filter(request=req).count() >= settings.CHAT_MAX_MESSAGES:
        raise ChatError("This chat has reached its message limit.")
    return Message.objects.create(request=req, sender=user, text=text)


def send_quick(req, user, key):
    if key not in QUICK_REPLIES:
        raise ChatError("That quick reply does not exist.")
    return send(req, user, QUICK_REPLIES[key])


def confirm_pickup(req, user, spot):
    """Save the agreed meeting spot on the booking and tell the other person in the thread."""
    _check_write(req, user)
    spot = (spot or "").strip()
    if not spot:
        raise ChatError("Write the pickup point you agreed on.")
    if len(spot) > 120:
        raise ChatError("Keep the pickup point under 120 characters.")
    req.agreed_pickup = spot
    req.agreed_pickup_by = user
    req.agreed_pickup_at = timezone.now()
    req.save(update_fields=["agreed_pickup", "agreed_pickup_by", "agreed_pickup_at", "updated_at"])
    return send(req, user, f"Pickup point confirmed: {spot}")


def call_window_open(req):
    """The call button works for an accepted booking whose ride day is today, or at most CALL_WINDOW_DAYS ahead."""
    today = timezone.localdate()
    return req.status == RideRequest.Status.ACCEPTED and today <= req.date <= today + timedelta(days=settings.CALL_WINDOW_DAYS)


def call_number(req, user):
    """The other person's 10 digit phone number, only for the two people on an accepted booking around the ride day.

    The number is never put on a page. The Call button goes through a view that checks these rules at the moment of the tap."""
    if not is_participant(req, user):
        raise ChatError("This booking is not yours.")
    other = other_person(req, user)
    if not call_window_open(req):
        raise ChatError("Calling opens for an accepted ride from the day it runs.")
    number = (other.phone or "").strip()
    if len(number) != 10 or not number.isdigit():
        raise ChatError(f"{other.first_name} has not added a phone number yet. Use chat instead.")
    return number


def mark_read(req, user):
    ChatRead.objects.update_or_create(request=req, user=user, defaults={"last_read_at": timezone.now()})


def summary(user, request_ids):
    """{request id: {'total': n, 'unread': n}} for these bookings, using one query."""
    last_read = ChatRead.objects.filter(request=OuterRef("request"), user=user).values("last_read_at")[:1]
    unread = ~Q(sender=user) & (Q(last__isnull=True) | Q(created_at__gt=F("last")))
    rows = (
        Message.objects.filter(request_id__in=list(request_ids))
        .annotate(last=Subquery(last_read))
        .values("request_id")
        .annotate(total=Count("id"), unread=Count("id", filter=unread))
    )
    return {row["request_id"]: {"total": row["total"], "unread": row["unread"]} for row in rows}