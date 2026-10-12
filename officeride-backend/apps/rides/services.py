"""Business rules for rides. Views call these functions."""

from django.db import transaction

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