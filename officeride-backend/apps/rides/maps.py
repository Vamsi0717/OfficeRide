"""The only file that talks to a maps service.

The rest of the app calls search_places() and get_route() and never knows which provider is used.
MAPS_PROVIDER=fake  -> sample Bangalore places and straight-line routes (offline, for development).
MAPS_PROVIDER=google -> Google Places API (New) and Routes API (needs GOOGLE_MAPS_API_KEY).
"""

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from . import geo

logger = logging.getLogger(__name__)

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


class MapsError(Exception):
    """The maps service could not answer. The message is safe to show to users."""


@dataclass
class PlaceResult:
    name: str
    address: str
    lat: float
    lng: float


@dataclass
class RouteResult:
    points: list  # [(lat, lng), ...] from start to end
    distance_m: int
    duration_s: int


# ---------------------------------------------------------------- fake provider (development)

SAMPLE_PLACES = [
    ("KR Puram", 13.0076, 77.6954),
    ("Bellandur", 12.9260, 77.6760),
    ("Embassy Tech Village, Devarabisanahalli", 12.9366, 77.6931),
    ("Whitefield (ITPL)", 12.9850, 77.7360),
    ("Manyata Tech Park, Nagavara", 13.0475, 77.6208),
    ("Electronic City", 12.8452, 77.6602),
    ("Koramangala", 12.9352, 77.6245),
    ("Indiranagar", 12.9784, 77.6408),
    ("HSR Layout", 12.9116, 77.6474),
    ("Marathahalli", 12.9569, 77.7011),
    ("Hebbal", 13.0358, 77.5970),
    ("Yelahanka", 13.1007, 77.5963),
    ("Jayanagar", 12.9250, 77.5938),
    ("Majestic (Kempegowda Bus Station)", 12.9767, 77.5713),
    ("Banashankari", 12.9255, 77.5468),
    ("Sarjapur Road", 12.9100, 77.6870),
    ("Silk Board Junction", 12.9177, 77.6233),
    ("Domlur", 12.9609, 77.6387),
    ("MG Road", 12.9757, 77.6068),
    ("Kadubeesanahalli", 12.9380, 77.6970),
]


class FakeMaps:
    """Offline stand-in. Routes are straight lines, so use it for development only."""

    def search_places(self, query, limit=5):
        needle = query.strip().lower()
        found = [
            PlaceResult(name, f"{name}, Bengaluru (sample place)", lat, lng)
            for name, lat, lng in SAMPLE_PLACES
            if needle in name.lower()
        ]
        return found[:limit]

    def get_route(self, origin_lat, origin_lng, dest_lat, dest_lng):
        steps = 40
        points = [
            (origin_lat + (dest_lat - origin_lat) * i / steps, origin_lng + (dest_lng - origin_lng) * i / steps)
            for i in range(steps + 1)
        ]
        road_factor = 1.25  # roads are longer than a straight line
        distance = geo.haversine_m(origin_lat, origin_lng, dest_lat, dest_lng) * road_factor
        return RouteResult(points=points, distance_m=round(distance), duration_s=round(distance / 6.0))


# ---------------------------------------------------------------- Google provider


def _http_post_json(url, headers, body, timeout):
    """POST JSON and return the decoded JSON reply. Every failure becomes a MapsError."""
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.error("Maps service error %s: %s", exc.code, exc.read()[:500])
        raise MapsError("The maps service refused the request. Please try again later.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.error("Maps service unreachable: %s", exc)
        raise MapsError("We could not reach the maps service. Please try again.") from exc
    except ValueError as exc:
        logger.error("Maps service sent unreadable data: %s", exc)
        raise MapsError("The maps service sent an unexpected answer.") from exc


class GoogleMaps:
    def __init__(self, api_key):
        self.api_key = api_key

    def _headers(self, field_mask):
        return {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": field_mask}

    def search_places(self, query, limit=5):
        lat, lng = settings.BANGALORE_CENTER
        body = {
            "textQuery": query,
            "pageSize": limit,
            "regionCode": "IN",
            "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 30000.0}},
        }
        data = _http_post_json(
            PLACES_URL,
            self._headers("places.displayName,places.formattedAddress,places.location"),
            body,
            settings.MAPS_TIMEOUT_SECONDS,
        )
        results = []
        for place in data.get("places", []):
            location = place.get("location") or {}
            if "latitude" not in location or "longitude" not in location:
                continue
            if not geo.in_bangalore(location["latitude"], location["longitude"]):
                continue
            results.append(
                PlaceResult(
                    name=(place.get("displayName") or {}).get("text", ""),
                    address=place.get("formattedAddress", ""),
                    lat=location["latitude"],
                    lng=location["longitude"],
                )
            )
        return results

    def get_route(self, origin_lat, origin_lng, dest_lat, dest_lng):
        body = {
            "origin": {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lng}}},
            "destination": {"location": {"latLng": {"latitude": dest_lat, "longitude": dest_lng}}},
            "travelMode": "DRIVE",
        }
        data = _http_post_json(
            ROUTES_URL,
            self._headers("routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"),
            body,
            settings.MAPS_TIMEOUT_SECONDS,
        )
        routes = data.get("routes") or []
        if not routes:
            raise MapsError("No driving route was found between those two places.")
        route = routes[0]
        try:
            points = geo.decode_polyline(route["polyline"]["encodedPolyline"])
            distance = int(route["distanceMeters"])
            duration = int(float(str(route["duration"]).rstrip("s")))
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            raise MapsError("The maps service sent an unexpected answer.") from exc
        if len(points) < 2:
            raise MapsError("No driving route was found between those two places.")
        return RouteResult(points=points, distance_m=distance, duration_s=duration)


# ---------------------------------------------------------------- public functions


def get_provider():
    name = settings.MAPS_PROVIDER
    if name == "fake":
        return FakeMaps()
    if name == "google":
        if not settings.GOOGLE_MAPS_API_KEY:
            raise ImproperlyConfigured("MAPS_PROVIDER=google needs GOOGLE_MAPS_API_KEY in .env.")
        return GoogleMaps(settings.GOOGLE_MAPS_API_KEY)
    raise ImproperlyConfigured(f"Unknown MAPS_PROVIDER {name!r}. Use 'fake' or 'google'.")


def search_places(query, limit=5):
    return get_provider().search_places(query, limit)


def get_route(origin_lat, origin_lng, dest_lat, dest_lng):
    return get_provider().get_route(origin_lat, origin_lng, dest_lat, dest_lng)