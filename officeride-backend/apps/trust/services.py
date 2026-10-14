"""Trust rules: strikes and what they lead to, ratings, and complaints. Views and the booking rules call these."""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import RideRequest

from .models import Complaint, Rating, Strike


class TrustError(Exception):
    """A rule was broken. str(error) is safe to show."""


# ---- strikes -------------------------------------------------------------------------------------

def active_strikes(user):
    cutoff = timezone.now() - timedelta(days=settings.STRIKE_WINDOW_DAYS)
    return Strike.objects.filter(user=user, waived=False, created_at__gte=cutoff)


def record_strike(user, reason, request):
    """Add a strike (once per person, request and reason) and apply what the new total leads to."""
    try:
        with transaction.atomic():
            strike, created = Strike.objects.get_or_create(user=user, request=request, reason=reason)
    except IntegrityError:
        return None
    if created:
        apply_consequences(user)
    return strike if created else None


def apply_consequences(user):
    """1 to 2 active strikes: a warning only. 3 and 4: a 7-day suspension. 5 or more: the account goes to an admin."""
    count = active_strikes(user).count()
    fields = []
    if count >= settings.STRIKE_REVIEW_AT:
        user.under_review = True
        fields.append("under_review")
    elif count >= settings.STRIKE_SUSPEND_AT:
        user.suspended_until = timezone.now() + timedelta(days=settings.SUSPENSION_DAYS)
        fields.append("suspended_until")
    if fields:
        user.save(update_fields=fields)
    return count


def strike_summary(user):
    """What the profile shows: the count, the limit, and a plain sentence about where the person stands."""
    count = active_strikes(user).count()
    limit = settings.STRIKE_REVIEW_AT
    if user.is_blocked:
        state = user.block_message
    elif count:
        left = settings.STRIKE_SUSPEND_AT - count
        state = f"A warning. {left} more strike{'s' if left != 1 else ''} will suspend your account for {settings.SUSPENSION_DAYS} days." if left > 0 else ""
    else:
        state = "No strikes. Thank you for keeping your plans."
    return {"count": count, "limit": limit, "state": state, "percent": min(count, limit) * 100 // limit}


def add_explanation(strike, user, text):
    if strike.user_id != user.id:
        raise TrustError("This strike is not yours.")
    strike.explanation = text.strip()[:300]
    strike.save(update_fields=["explanation"])


def waive(strike, admin_user):
    """Cancel a strike. If the person now has fewer than 3 active strikes, a suspension caused by strikes is lifted."""
    if strike.waived:
        return False
    strike.waived = True
    strike.waived_by = admin_user
    strike.waived_at = timezone.now()
    strike.save(update_fields=["waived", "waived_by", "waived_at"])
    user = User.objects.get(pk=strike.user_id)
    if active_strikes(user).count() < settings.STRIKE_SUSPEND_AT and user.suspended_until:
        user.suspended_until = None
        user.save(update_fields=["suspended_until"])
    return True


def suspend(user, days=None):
    user.suspended_until = timezone.now() + timedelta(days=days or settings.SUSPENSION_DAYS)
    user.save(update_fields=["suspended_until"])


def clear_suspension(user):
    user.suspended_until = None
    user.save(update_fields=["suspended_until"])


def send_to_review(user):
    user.under_review = True
    user.save(update_fields=["under_review"])


def clear_review(user):
    user.under_review = False
    user.save(update_fields=["under_review"])


# ---- ratings -------------------------------------------------------------------------------------

def other_person(req, user):
    """The other person on a request, or None when user is not on it."""
    if user.id == req.rider_id:
        return req.ride.driver
    if user.id == req.ride.driver_id:
        return req.rider
    return None


def rate(req, rater, stars, tags=(), comment=""):
    """Rate the other person on a completed request. Once each; outsiders are refused."""
    if req.status != RideRequest.Status.COMPLETED:
        raise TrustError("You can rate a ride after it is completed.")
    rated = other_person(req, rater)
    if rated is None:
        raise TrustError("This ride is not yours.")
    if not 1 <= int(stars) <= 5:
        raise TrustError("Choose 1 to 5 stars.")
    allowed = {key for key, _ in Rating.TAGS}
    tags = [t for t in tags if t in allowed]
    try:
        with transaction.atomic():
            return Rating.objects.create(
                request=req, rater=rater, rated=rated, stars=int(stars), tags=tags, comment=comment.strip()[:300]
            )
    except IntegrityError:
        raise TrustError("You have already rated this ride.") from None


def rating_stats(user_ids):
    """{user id: {'average': 4.5 or None, 'count': n, 'rides': n}} for these people, using two queries."""
    ids = list(user_ids)
    stats = {i: {"average": None, "count": 0, "rides": 0} for i in ids}
    for row in Rating.objects.filter(rated_id__in=ids).values("rated_id").annotate(avg=Avg("stars"), n=Count("id")):
        stats[row["rated_id"]].update(average=round(row["avg"], 1), count=row["n"])
    done = RideRequest.objects.filter(status=RideRequest.Status.COMPLETED).filter(
        Q(rider_id__in=ids) | Q(ride__driver_id__in=ids)
    ).values_list("rider_id", "ride__driver_id")
    for rider_id, driver_id in done:
        for person in (rider_id, driver_id):
            if person in stats:
                stats[person]["rides"] += 1
    return stats


def attach_driver_stats(matches):
    """Sets match.driver_stats on each search result."""
    stats = rating_stats({m.ride.driver_id for m in matches})
    for m in matches:
        m.driver_stats = stats[m.ride.driver_id]
    return matches


# ---- complaints ----------------------------------------------------------------------------------

def file_complaint(req, reporter, kind, text):
    reported = other_person(req, reporter)
    if reported is None:
        raise TrustError("This ride is not yours.")
    if req.status not in (RideRequest.Status.COMPLETED, RideRequest.Status.CANCELLED, RideRequest.Status.NO_SHOW):
        raise TrustError("You can report a problem after the ride is completed, cancelled or marked as a no-show.")
    if kind == Complaint.Kind.HELMET and not req.ride.is_bike:
        raise TrustError("The helmet complaint is only for two-wheeler rides.")
    if Complaint.objects.filter(reporter=reporter, request=req, status=Complaint.Status.OPEN).exists():
        raise TrustError("You have already reported this trip. We are looking into it.")
    return Complaint.objects.create(reporter=reporter, reported=reported, request=req, kind=kind, text=text.strip())