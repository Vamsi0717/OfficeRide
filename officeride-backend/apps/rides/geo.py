"""Small map-maths helpers. No database and no network, so they are easy to test."""

import math

from django.conf import settings

EARTH_RADIUS_M = 6_371_000.0
METRES_PER_DEG_LAT = 110_540.0
METRES_PER_DEG_LNG_AT_EQUATOR = 111_320.0


def haversine_m(lat1, lng1, lat2, lng2):
    """Straight-line distance in metres between two points on the Earth."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def in_bangalore(lat, lng):
    box = settings.BANGALORE_BOUNDS
    return box["south"] <= lat <= box["north"] and box["west"] <= lng <= box["east"]


def decode_polyline(encoded):
    """Turn Google's encoded polyline text into a list of (lat, lng) points."""
    points = []
    index = lat = lng = 0
    while index < len(encoded):
        for axis in (0, 1):
            shift = result = 0
            while True:
                chunk = ord(encoded[index]) - 63
                index += 1
                result |= (chunk & 0x1F) << shift
                shift += 5
                if chunk < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lng += delta
        points.append((lat / 1e5, lng / 1e5))
    return points


def cumulative_distances_m(points):
    """Distance along the route, in metres, at each point. The first value is 0."""
    total = 0.0
    out = [0.0]
    for (lat1, lng1), (lat2, lng2) in zip(points, points[1:]):
        total += haversine_m(lat1, lng1, lat2, lng2)
        out.append(total)
    return out


def bounding_box(points):
    """(min_lat, max_lat, min_lng, max_lng) of a list of points."""
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return min(lats), max(lats), min(lngs), max(lngs)


def box_margin_degrees(metres, lat):
    """Degrees of latitude and longitude that equal a distance, used to widen a bounding box."""
    d_lat = metres / METRES_PER_DEG_LAT
    d_lng = metres / (METRES_PER_DEG_LNG_AT_EQUATOR * math.cos(math.radians(lat)))
    return d_lat, d_lng


def project_onto_route(points, cumulative, lat, lng):
    """Find where a point is closest to the route.

    Returns (distance_to_route_m, distance_along_route_m). City-sized distances are small
    enough that a flat-map approximation around the point is accurate to a few metres.
    """
    cos_lat = math.cos(math.radians(lat))
    k_lng = METRES_PER_DEG_LNG_AT_EQUATOR * cos_lat

    def flat(p_lat, p_lng):
        return (p_lng - lng) * k_lng, (p_lat - lat) * METRES_PER_DEG_LAT

    best_distance = math.inf
    best_along = 0.0
    prev = flat(*points[0])
    if len(points) == 1:
        return math.hypot(*prev), 0.0
    for i in range(1, len(points)):
        cur = flat(*points[i])
        ax, ay = prev
        bx, by = cur
        dx, dy = bx - ax, by - ay
        seg_sq = dx * dx + dy * dy
        t = 0.0 if seg_sq == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg_sq))
        cx, cy = ax + t * dx, ay + t * dy
        distance = math.hypot(cx, cy)
        if distance < best_distance:
            best_distance = distance
            best_along = cumulative[i - 1] + t * (cumulative[i] - cumulative[i - 1])
        prev = cur
    return best_distance, best_along