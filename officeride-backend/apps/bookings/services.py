"""Booking rules. Views call these functions and show the message when a BookingError is raised.

Seats are protected by locking the ride row (select_for_update) while a request is created or
accepted, so two riders can never take the last seat."""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.fares import services as fare_services
from apps.rides import matching
from apps.rides.models import CarUnavailableDate, Ride

from . import planner
from .models import RideRequest

S = RideRequest.Status

# The one place that says which status can follow which.
TRANSITIONS = {
    S.PENDING: {S.ACCEPTED, S.REJECTED, S.CANCELLED},
    S.ACCEPTED: {S.CANCELLED, S.COMPLETED, S.NO_SHOW},
}


class BookingError(Exception):
    """A rule was broken. str(error) is a message that is safe to show to the person."""


def can_transition(old, new):
    return new in TRANSITIONS.get(old, set())


def seats_left(ride, date):
    taken = RideRequest.objects.filter(ride=ride, date=date, status=S.ACCEPTED).count()
    return max(ride.seats - taken, 0)


def _lock_ride(ride_id):
    # of=("self",) locks only the ride row (the vehicle class can be empty, and PostgreSQL cannot lock that side of a join).
    return Ride.objects.select_for_update(of=("self",)).select_related("driver", "mileage_rate").get(pk=ride_id)


def request_seat(rider, ride_id, date, pickup, drop):
    """pickup and drop are dicts with name, lat and lng. Returns the new pending RideRequest."""
    today = timezone.localdate()
    if date < today:
        raise BookingError("Choose today or a future date.")
    if date > today + timedelta(days=settings.BOOKING_DAYS_AHEAD):
        raise BookingError(f"You can request a seat up to {settings.BOOKING_DAYS_AHEAD} days ahead.")

    with transaction.atomic():
        try:
            ride = _lock_ride(ride_id)
        except Ride.DoesNotExist:
            raise BookingError("That ride does not exist.") from None
        if not ride.is_active or not ride.driver.can_offer_rides:
            raise BookingError("This ride is not available.")
        if ride.driver_id == rider.id:
            raise BookingError("You cannot request a seat on your own ride.")
        if not ride.runs_on(date):
            raise BookingError("This ride does not run on that day.")
        if CarUnavailableDate.objects.filter(driver_id=ride.driver_id, date=date).exists():
            raise BookingError("The driver is not available on that day.")
        if ride.driver_id in planner.drivers_not_driving([ride.driver_id], date):
            raise BookingError("The driver is not driving on that day.")

        candidate = RideRequest(ride=ride, date=date)
        if candidate.departure_at <= timezone.now():
            raise BookingError("This ride has already left.")

        found = matching.route_match(ride, (pickup["lat"], pickup["lng"]), (drop["lat"], drop["lng"]))
        if found is None:
            raise BookingError("Your pickup and drop are not on this ride's route.")
        shared_m = round(found[2])

        if seats_left(ride, date) <= 0:
            raise BookingError("This ride is full on that day.")
        if RideRequest.objects.filter(ride=ride, rider=rider, date=date, status__in=RideRequest.ACTIVE).exists():
            raise BookingError("You already have a request for this ride on that day.")
        _refuse_clash(rider, ride, date)

        fare = fare_services.fare_for(ride, shared_m)
        if fare is None:
            raise BookingError("The fare is not available for this ride yet.")

        try:
            return RideRequest.objects.create(
                ride=ride, rider=rider, date=date,
                pickup_name=pickup["name"], pickup_lat=pickup["lat"], pickup_lng=pickup["lng"],
                drop_name=drop["name"], drop_lat=drop["lat"], drop_lng=drop["lng"],
                rider_distance_m=shared_m,
                standard_fare=fare.base_total, fare_adjustment=fare.adjustment, fare=fare.total,
            )
        except IntegrityError:  # two taps at once; the database rule caught the second
            raise BookingError("You already have a request for this ride on that day.") from None


def _refuse_clash(rider, ride, date):
    """A rider cannot be on two rides that leave close together on the same day."""
    gap = timedelta(minutes=settings.BOOKING_CLASH_MIN)
    mine = RideRequest(ride=ride, date=date).departure_at
    others = RideRequest.objects.filter(rider=rider, date=date, status__in=RideRequest.ACTIVE).select_related("ride")
    for other in others:
        if abs(other.departure_at - mine) < gap:
            raise BookingError("You already have a ride around that time.")


def _load(request_id, user, *, driver_only=False, participant_only=True):
    """Lock the ride row, then the request, and check that this person is allowed to touch it."""
    try:
        first = RideRequest.objects.select_related("ride").get(pk=request_id)
    except RideRequest.DoesNotExist:
        raise BookingError("That request does not exist.") from None
    _lock_ride(first.ride_id)
    req = RideRequest.objects.select_for_update(of=("self",)).select_related("ride", "rider").get(pk=request_id)
    is_driver = req.ride.driver_id == user.id
    is_rider = req.rider_id == user.id
    if driver_only and not is_driver:
        raise BookingError("Only the driver of this ride can do that.")
    if participant_only and not (is_driver or is_rider):
        raise BookingError("This request is not yours.")
    return req


def _move(req, new_status):
    if not can_transition(req.status, new_status):
        raise BookingError(f"A request that is {req.get_status_display().lower()} cannot be changed to {new_status.label.lower()}.")
    req.status = new_status


def accept(request_id, user):
    with transaction.atomic():
        req = _load(request_id, user, driver_only=True)
        _move(req, S.ACCEPTED)
        if req.departure_at <= timezone.now():
            raise BookingError("This ride has already left.")
        if seats_left(req.ride, req.date) <= 0:  # accepted requests are counted while the ride row is locked
            raise BookingError("No seat is left on that day.")
        req.decided_at = timezone.now()
        req.save(update_fields=["status", "decided_at", "updated_at"])
        return req


def reject(request_id, user):
    with transaction.atomic():
        req = _load(request_id, user, driver_only=True)
        _move(req, S.REJECTED)
        req.decided_at = timezone.now()
        req.save(update_fields=["status", "decided_at", "updated_at"])
        return req


def cancel(request_id, user):
    """The rider or the driver cancels a pending or accepted request. Late cancelling is recorded for Phase 6."""
    with transaction.atomic():
        req = _load(request_id, user)
        was_accepted = req.status == S.ACCEPTED
        _move(req, S.CANCELLED)
        now = timezone.now()
        if req.departure_at <= now:
            raise BookingError("This ride has already left. Report a no-show instead.")
        req.cancelled_by = user
        req.late_cancel = was_accepted and (req.departure_at - now) < timedelta(minutes=settings.LATE_CANCEL_MIN)
        req.decided_at = now
        req.save(update_fields=["status", "cancelled_by", "late_cancel", "decided_at", "updated_at"])
        return req


def complete(request_id, user):
    with transaction.atomic():
        req = _load(request_id, user, driver_only=True)
        _move(req, S.COMPLETED)
        if req.departure_at > timezone.now():
            raise BookingError("You can mark a ride completed only after it has left.")
        req.save(update_fields=["status", "updated_at"])
        return req


def report_no_show(request_id, user):
    with transaction.atomic():
        req = _load(request_id, user)
        _move(req, S.NO_SHOW)
        if req.departure_at > timezone.now():
            raise BookingError("You can report a no-show only after the ride has left.")
        req.reported_by = user
        req.save(update_fields=["status", "reported_by", "updated_at"])
        return req


ACTIONS = {
    "accept": accept,
    "reject": reject,
    "cancel": cancel,
    "complete": complete,
    "no-show": report_no_show,
}


def allowed_actions(req, user):
    """The buttons to show for this person: a list of action names, using the same rules as the functions."""
    is_driver = req.ride.driver_id == user.id
    is_rider = req.rider_id == user.id
    now = timezone.now()
    left = req.departure_at > now
    actions = []
    if req.status == S.PENDING:
        if is_driver:
            actions += ["accept", "reject"]
        if is_driver or is_rider:
            actions.append("cancel")
    elif req.status == S.ACCEPTED:
        if left and (is_driver or is_rider):
            actions.append("cancel")
        if not left:
            if is_driver:
                actions.append("complete")
            if is_driver or is_rider:
                actions.append("no-show")
    return actions