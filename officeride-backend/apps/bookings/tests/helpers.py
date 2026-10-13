from datetime import time, timedelta

from django.utils import timezone

from apps.bookings.models import RideRequest
from apps.rides.tests.helpers import get_rate, make_driver, make_ride, make_user, next_weekday, point_along


def future_monday():
    """A Monday at least a week away, so the 9:00 ride has certainly not left yet."""
    return next_weekday(0) + timedelta(days=7)


def pickup(fraction=0.1):
    lat, lng = point_along(fraction)
    return {"name": "Pickup spot", "lat": lat, "lng": lng}


def drop(fraction=0.9):
    lat, lng = point_along(fraction)
    return {"name": "Drop spot", "lat": lat, "lng": lng}


def car_ride(driver=None, seats=3, **extra):
    driver = driver or make_driver()
    extra.setdefault("mileage_rate", get_rate("car", "Sedan"))
    return make_ride(driver, seats=seats, **extra)


def bike_ride(email="biker@acme.com", **extra):
    driver = make_driver(email, vehicle_type="bike")
    return make_ride(driver, seats=1, vehicle_type="bike", has_spare_helmet=True,
                     mileage_rate=get_rate("bike"), **extra)


def make_request(ride, rider, date=None, status=RideRequest.Status.PENDING, **extra):
    """A request made directly in the database, for tests that need a date in the past or a given status."""
    values = dict(
        ride=ride, rider=rider, date=date or future_monday(),
        pickup_name="Pickup spot", pickup_lat=point_along(0.1)[0], pickup_lng=point_along(0.1)[1],
        drop_name="Drop spot", drop_lat=point_along(0.9)[0], drop_lng=point_along(0.9)[1],
        rider_distance_m=8000, standard_fare=50, fare_adjustment=0, fare=50, status=status,
    )
    values.update(extra)
    return RideRequest.objects.create(**values)


def long_ago():
    return timezone.localdate() - timedelta(days=3)