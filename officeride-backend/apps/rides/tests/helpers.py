from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import DriverDocument
from apps.rides import geo
from apps.rides.models import Ride

User = get_user_model()

# A straight west-to-east road about 10.8 km long, near Bellandur. Handy for matching tests.
START = (12.9500, 77.6000)
END = (12.9500, 77.7000)


def line(start=START, end=END, steps=50):
    return [
        (start[0] + (end[0] - start[0]) * i / steps, start[1] + (end[1] - start[1]) * i / steps)
        for i in range(steps + 1)
    ]


def point_along(fraction, north_m=0.0, start=START, end=END):
    """A point a fraction of the way along the road, optionally pushed north by some metres."""
    lat = start[0] + (end[0] - start[0]) * fraction + north_m / geo.METRES_PER_DEG_LAT
    lng = start[1] + (end[1] - start[1]) * fraction
    return lat, lng


def make_user(email="user@acme.com", verified=True, **extra):
    values = {"first_name": "Test", "last_name": "User", "email_verified": verified}
    values.update(extra)
    return User.objects.create_user(email, "S3cure-pass!", **values)


def make_driver(email="driver@acme.com", approved=True, insurance_days=200, vehicle_type="car"):
    user = make_user(email, first_name="Ravi", last_name="Kumar")
    DriverDocument.objects.create(
        user=user,
        licence_number="KA01 20110012345", licence_file="driver_docs/x/l.pdf",
        rc_number="KA01AB1234", rc_file="driver_docs/x/r.pdf",
        insurance_expiry=timezone.localdate() + timedelta(days=insurance_days), insurance_file="driver_docs/x/i.pdf",
        status=DriverDocument.Status.APPROVED if approved else DriverDocument.Status.PENDING,
        vehicle_type=vehicle_type,
    )
    return User.objects.get(pk=user.pk)  # fresh copy, no cached relations


def make_ride(driver, points=None, departure=time(9, 0), days="0,1,2,3,4", seats=3, **extra):
    points = points or line()
    lat_min, lat_max, lng_min, lng_max = geo.bounding_box(points)
    values = dict(
        driver=driver, origin_name="Start", origin_lat=points[0][0], origin_lng=points[0][1],
        destination_name="End", destination_lat=points[-1][0], destination_lng=points[-1][1],
        departure_time=departure, office_days=days, seats=seats, car_model="Maruti Swift",
        route_points=[[a, b] for a, b in points],
        route_distance_m=round(geo.cumulative_distances_m(points)[-1]), route_duration_s=1500,
        min_lat=lat_min, max_lat=lat_max, min_lng=lng_min, max_lng=lng_max,
    )
    values.update(extra)
    return Ride.objects.create(**values)


def next_weekday(weekday=0):
    """The next date (today or later) that falls on the given weekday, Monday = 0."""
    today = timezone.localdate()
    return today + timedelta(days=(weekday - today.weekday()) % 7)