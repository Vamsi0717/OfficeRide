"""Business rules for rides. Views call these functions."""

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import VehicleType

from . import geo, maps
from .models import Ride


def _apply_route(ride, route):
    ride.route_points = [[lat, lng] for lat, lng in route.points]
    ride.route_distance_m = route.distance_m
    ride.route_duration_s = route.duration_s
    ride.min_lat, ride.max_lat, ride.min_lng, ride.max_lng = geo.bounding_box(route.points)


@transaction.atomic
def create_ride(driver, data):
    """Create a ride from cleaned form data, plus the return ride when asked.

    Raises maps.MapsError when the route cannot be calculated; nothing is saved in that case.
    """
    route = maps.get_route(data["origin_lat"], data["origin_lng"], data["destination_lat"], data["destination_lng"])
    days = ",".join(sorted(data["office_days"]))
    vehicle_type = driver.driver_document.vehicle_type  # comes from the approved documents, never from the form
    is_bike = vehicle_type == VehicleType.BIKE
    common = {
        "driver": driver, "office_days": days, "car_model": data["car_model"], "vehicle_type": vehicle_type,
        "seats": 1 if is_bike else data["seats"],  # a two-wheeler carries one rider
        "has_spare_helmet": bool(data.get("has_spare_helmet")) if is_bike else False,
        "mileage_rate": data["mileage_rate"], "toll_total": data.get("toll_total") or 0,
        "fare_adjustment": data.get("fare_adjustment") or 0,
    }

    outbound = Ride(
        origin_name=data["origin_name"], origin_lat=data["origin_lat"], origin_lng=data["origin_lng"],
        destination_name=data["destination_name"], destination_lat=data["destination_lat"],
        destination_lng=data["destination_lng"], departure_time=data["departure_time"], **common,
    )
    _apply_route(outbound, route)
    outbound.save()
    rides = [outbound]

    if data.get("offer_return"):
        back = Ride(
            origin_name=data["destination_name"], origin_lat=data["destination_lat"],
            origin_lng=data["destination_lng"], destination_name=data["origin_name"],
            destination_lat=data["origin_lat"], destination_lng=data["origin_lng"],
            departure_time=data["return_time"], **common,
        )
        # The way back is the same road in reverse. One map call is enough.
        _apply_route(back, maps.RouteResult(list(reversed(route.points)), route.distance_m, route.duration_s))
        back.save()
        rides.append(back)
    return rides


class ReturnRideError(Exception):
    """The way-back ride could not be made. str(error) is safe to show."""


@transaction.atomic
def create_return_ride(ride, return_time):
    """Copy a ride with the start and end swapped and the road reversed, leaving at return_time.

    The way back is its own Ride with its own bookings."""
    if Ride.objects.filter(
        driver=ride.driver, origin_name=ride.destination_name, destination_name=ride.origin_name,
        departure_time=return_time, is_active=True,
    ).exists():
        raise ReturnRideError("You already offer the way back at that time.")
    back = Ride(
        driver=ride.driver, office_days=ride.office_days, seats=ride.seats, vehicle_type=ride.vehicle_type,
        car_model=ride.car_model, has_spare_helmet=ride.has_spare_helmet, mileage_rate=ride.mileage_rate,
        toll_total=ride.toll_total, fare_adjustment=ride.fare_adjustment,
        origin_name=ride.destination_name, origin_lat=ride.destination_lat, origin_lng=ride.destination_lng,
        destination_name=ride.origin_name, destination_lat=ride.origin_lat, destination_lng=ride.origin_lng,
        departure_time=return_time,
    )
    _apply_route(back, maps.RouteResult([tuple(p) for p in reversed(ride.route_points)], ride.route_distance_m, ride.route_duration_s))
    back.save()
    return back


class RideChangeError(Exception):
    """A change to a ride was refused. str(error) is safe to show."""


def live_future_requests(ride):
    """Pending or accepted requests on this ride for today or later."""
    from apps.bookings.models import RideRequest

    return RideRequest.objects.filter(
        ride=ride, status__in=RideRequest.ACTIVE, date__gte=timezone.localdate()
    ).select_related("rider")


@transaction.atomic
def update_ride(ride, data):
    """Save the editable parts of a ride, refusing changes that would break a booking.

    Fare, toll, vehicle details and the helmet can change at any time: riders who already booked keep the
    fare they were shown. The time, the days and the number of seats are protected while riders depend on them."""
    from django.db.models import Count

    from apps.bookings.models import RideRequest

    ride = Ride.objects.select_for_update().get(pk=ride.pk)
    if ride.is_deleted:
        raise RideChangeError("This ride has been deleted.")
    live = live_future_requests(ride)

    days = ",".join(sorted(data["office_days"]))
    if (data["departure_time"] != ride.departure_time or days != ride.office_days) and live.exists():
        raise RideChangeError(
            f"{live.count()} rider(s) have a pending or accepted booking on this ride. "
            "Cancel those bookings first, or leave the time and days as they are."
        )

    seats = 1 if ride.is_bike else data["seats"]
    most_accepted = (
        RideRequest.objects.filter(ride=ride, status=RideRequest.Status.ACCEPTED, date__gte=timezone.localdate())
        .values("date").annotate(n=Count("id")).order_by("-n").values_list("n", flat=True).first() or 0
    )
    if seats < most_accepted:
        raise RideChangeError(
            f"You have already accepted {most_accepted} riders on one day. Keep at least {most_accepted} seats, or cancel a booking first."
        )

    ride.departure_time = data["departure_time"]
    ride.office_days = days
    ride.seats = seats
    ride.car_model = data["car_model"]
    ride.mileage_rate = data["mileage_rate"]
    ride.toll_total = data.get("toll_total") or 0
    ride.fare_adjustment = data.get("fare_adjustment") or 0
    if ride.is_bike:
        ride.has_spare_helmet = bool(data.get("has_spare_helmet"))
    ride.save()
    return ride


@transaction.atomic
def set_fare_adjustment(ride, amount):
    ride = Ride.objects.select_for_update().get(pk=ride.pk)
    if ride.is_deleted:
        raise RideChangeError("This ride has been deleted.")
    ride.fare_adjustment = amount
    ride.save(update_fields=["fare_adjustment"])
    return ride


@transaction.atomic
def delete_ride(ride):
    """Delete a ride. Pending and accepted bookings for today or later are cancelled first.

    The ride row is kept (marked deleted) so past bookings and, later, payments and ratings keep their history.
    Returns the number of bookings that were cancelled."""
    from apps.bookings import services as booking_services

    ride = Ride.objects.select_for_update().get(pk=ride.pk)
    if ride.is_deleted:
        return 0
    cancelled = 0
    for request in list(live_future_requests(ride)):
        try:
            booking_services.cancel(request.pk, ride.driver)
            cancelled += 1
        except booking_services.BookingError:
            pass  # the ride has already left today; there is nothing to cancel
    ride.is_active = False
    ride.deleted_at = timezone.now()
    ride.save(update_fields=["is_active", "deleted_at"])
    return cancelled