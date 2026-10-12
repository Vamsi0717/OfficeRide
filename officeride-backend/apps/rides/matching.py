"""Finding rides for a rider. Works for any two places in Bangalore.

A ride matches when:
  1. it runs on the rider's weekday, the car is available that day and the driver is approved;
  2. it leaves within MATCH_TIME_WINDOW_MIN minutes of the rider's time;
  3. the rider's pickup and drop are both within MATCH_RADIUS_M of the driver's route;
  4. the pickup comes before the drop along the driver's direction of travel;
  5. optionally, the vehicle is the type the rider asked for (car or two-wheeler).
"""

from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from . import geo
from .models import Ride


@dataclass
class RideMatch:
    ride: Ride
    pickup_offset_m: int     # how far the pickup is from the route
    drop_offset_m: int       # how far the drop is from the route
    rider_distance_m: int    # distance along the route between pickup and drop (used for the fare in Phase 4)
    time_diff_min: int

    @property
    def rider_km(self):
        return round(self.rider_distance_m / 1000, 1)

    @property
    def pickup_offset_km(self):
        return round(self.pickup_offset_m / 1000, 1)

    @property
    def drop_offset_km(self):
        return round(self.drop_offset_m / 1000, 1)


def _minutes(t):
    return t.hour * 60 + t.minute


def time_difference_min(a, b):
    """Gap between two clock times in minutes, going the short way round midnight."""
    gap = abs(_minutes(a) - _minutes(b))
    return min(gap, 1440 - gap)


def find_rides(rider, pickup, drop, on_date, at_time, vehicle_type=None):
    """pickup and drop are (lat, lng). vehicle_type is 'car', 'bike' or None for both.

    Returns a list of RideMatch, best first."""
    radius = settings.MATCH_RADIUS_M
    window = settings.MATCH_TIME_WINDOW_MIN
    (p_lat, p_lng), (d_lat, d_lng) = pickup, drop
    m_lat, m_lng = geo.box_margin_degrees(radius, p_lat)

    candidates = (
        Ride.objects.filter(
            is_active=True,
            office_days__contains=str(on_date.weekday()),
            driver__driver_document__status="approved",
            driver__driver_document__insurance_expiry__gte=max(on_date, timezone.localdate()),
            min_lat__lte=min(p_lat, d_lat) + m_lat,
            max_lat__gte=max(p_lat, d_lat) - m_lat,
            min_lng__lte=min(p_lng, d_lng) + m_lng,
            max_lng__gte=max(p_lng, d_lng) - m_lng,
        )
        .exclude(driver=rider)
        .exclude(driver__unavailable_dates__date=on_date)
        .select_related("driver")
    )
    if vehicle_type:
        candidates = candidates.filter(vehicle_type=vehicle_type)

    matches = []
    for ride in candidates:
        gap = time_difference_min(ride.departure_time, at_time)
        if gap > window:
            continue
        points = ride.route_points
        cumulative = geo.cumulative_distances_m(points)
        pickup_off, pickup_along = geo.project_onto_route(points, cumulative, p_lat, p_lng)
        drop_off, drop_along = geo.project_onto_route(points, cumulative, d_lat, d_lng)
        if pickup_off > radius or drop_off > radius:
            continue
        shared = drop_along - pickup_along
        if shared < settings.MATCH_MIN_TRIP_M:  # also rejects the wrong direction (negative)
            continue
        matches.append(
            RideMatch(
                ride=ride,
                pickup_offset_m=round(pickup_off),
                drop_offset_m=round(drop_off),
                rider_distance_m=round(shared),
                time_diff_min=gap,
            )
        )
    matches.sort(key=lambda m: (m.time_diff_min, m.pickup_offset_m + m.drop_offset_m))
    return matches