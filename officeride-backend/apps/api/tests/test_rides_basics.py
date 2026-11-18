from unittest import mock

from django.test import TestCase, override_settings

from apps.fares import services as fare_services
from apps.rides import maps
from apps.rides.tests.helpers import get_model, make_driver, make_ride, make_user

from .helpers import FreshCache, client_for
from .ride_helpers import offer_body

DRIVER_ONLY = [
    ("post", "/api/v1/rides/"),
    ("get", "/api/v1/unavailable-dates/"),
    ("post", "/api/v1/unavailable-dates/"),
]
VERIFIED_ONLY = [
    ("get", "/api/v1/places/?q=kor"),
    ("get", "/api/v1/vehicles/"),
    ("get", "/api/v1/fare-preview/"),
    ("get", "/api/v1/rides/search/"),
    ("get", "/api/v1/rides/mine/"),
]


class AccessTests(FreshCache, TestCase):
    def call(self, client, method, url):
        return getattr(client, method)(url, format="json")

    def test_nothing_works_without_a_login(self):
        for method, url in DRIVER_ONLY + VERIFIED_ONLY:
            self.assertEqual(self.call(client_for(), method, url).status_code, 401, url)

    def test_an_unverified_email_is_turned_away_everywhere(self):
        client = client_for(make_user(verified=False))
        for method, url in DRIVER_ONLY + VERIFIED_ONLY:
            response = self.call(client, method, url)
            self.assertEqual(response.status_code, 403, url)
            self.assertEqual(response.data["detail"], "Please verify your email first.")

    def test_a_rider_without_documents_cannot_offer_rides(self):
        client = client_for(make_user())
        for method, url in DRIVER_ONLY:
            response = self.call(client, method, url)
            self.assertEqual(response.status_code, 403, url)
            self.assertIn("driver documents", response.data["detail"])

    def test_a_driver_with_pending_documents_cannot_offer_rides(self):
        client = client_for(make_driver(approved=False))
        self.assertEqual(client.post("/api/v1/rides/", offer_body(), format="json").status_code, 403)

    def test_a_rider_can_use_search_and_my_rides(self):
        client = client_for(make_user())
        self.assertEqual(client.get("/api/v1/rides/mine/").status_code, 200)
        self.assertEqual(client.get("/api/v1/vehicles/").status_code, 200)


class PlaceSearchTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.client = client_for(make_user())

    def test_returns_places(self):
        response = self.client.get("/api/v1/places/", {"q": "kor"})
        self.assertEqual(response.status_code, 200)
        first = response.data["results"][0]
        self.assertEqual(set(first), {"name", "address", "lat", "lng"})
        self.assertIn("Koramangala", first["name"])

    def test_a_short_search_returns_nothing(self):
        self.assertEqual(self.client.get("/api/v1/places/", {"q": "ko"}).data, {"results": []})
        self.assertEqual(self.client.get("/api/v1/places/").data, {"results": []})

    @override_settings(PLACE_SEARCH_PER_MINUTE=2)
    def test_too_many_searches_in_a_minute(self):
        for _ in range(2):
            self.assertEqual(self.client.get("/api/v1/places/", {"q": "kor"}).status_code, 200)
        response = self.client.get("/api/v1/places/", {"q": "kor"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["code"], "too_many_requests")

    def test_a_maps_failure_is_a_clean_error(self):
        with mock.patch.object(maps, "search_places", side_effect=maps.MapsError("Maps are down.")):
            response = self.client.get("/api/v1/places/", {"q": "kor"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual((response.data["detail"], response.data["code"]), ("Maps are down.", "maps_unavailable"))

    def test_post_is_not_allowed(self):
        self.assertEqual(self.client.post("/api/v1/places/", {"q": "kor"}).status_code, 405)


class VehicleListTests(FreshCache, TestCase):
    def test_a_car_driver_sees_car_makes_and_models(self):
        response = client_for(make_driver()).get("/api/v1/vehicles/")
        self.assertEqual(response.data["vehicle_type"], "car")
        makes = {m["make"]: m["models"] for m in response.data["makes"]}
        self.assertIn("Maruti Suzuki", makes)
        self.assertIn("Swift", [m["name"] for m in makes["Maruti Suzuki"]])
        self.assertNotIn("Honda", [m for m in makes if "Activa" in str(makes[m])])

    def test_a_two_wheeler_driver_sees_two_wheelers(self):
        response = client_for(make_driver(vehicle_type="bike")).get("/api/v1/vehicles/")
        self.assertEqual(response.data["vehicle_type"], "bike")
        names = [m["name"] for make in response.data["makes"] for m in make["models"]]
        self.assertIn("Activa 6G", names)
        self.assertNotIn("Swift", names)

    def test_the_type_can_be_asked_for(self):
        response = client_for(make_user()).get("/api/v1/vehicles/", {"type": "bike"})
        self.assertEqual(response.data["vehicle_type"], "bike")

    def test_a_person_with_no_documents_gets_cars_by_default(self):
        self.assertEqual(client_for(make_user()).get("/api/v1/vehicles/").data["vehicle_type"], "car")

    def test_an_unknown_type_is_refused(self):
        self.assertEqual(client_for(make_user()).get("/api/v1/vehicles/", {"type": "boat"}).status_code, 400)

    def test_the_mileage_is_never_sent(self):
        text = client_for(make_driver()).get("/api/v1/vehicles/").content.decode().lower()
        for word in ("km_per_litre", "mileage", "fuel_type"):
            self.assertNotIn(word, text)


class FarePreviewTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.client = client_for(make_user())
        self.swift = get_model("car", "Swift")

    def preview(self, **extra):
        params = {"vehicle_model": self.swift.pk, "distance_km": 12, "seats": 3}
        params.update(extra)
        return self.client.get("/api/v1/fare-preview/", params)

    def test_the_fare_matches_what_a_real_ride_would_charge(self):
        ride = make_ride(make_driver(), seats=3, mileage_rate=self.swift, route_distance_m=12000)
        expected = fare_services.full_route_fare(ride)
        fare = self.preview().data["fare"]
        self.assertEqual((fare["total"], fare["base_total"]), (expected.total, expected.base_total))

    def test_toll_and_adjustment_move_the_fare(self):
        plain = self.preview().data["fare"]["total"]
        self.assertGreater(self.preview(toll_total=90).data["fare"]["total"], plain)
        self.assertEqual(self.preview(fare_adjustment=-5).data["fare"]["total"], plain - 5)

    def test_more_seats_share_the_cost(self):
        self.assertLess(self.preview(seats=3).data["fare"]["total"], self.preview(seats=1).data["fare"]["total"])

    def test_a_two_wheeler_always_has_one_seat(self):
        activa = get_model("bike")
        one = self.preview(vehicle_model=activa.pk, seats=1).data["fare"]["total"]
        self.assertEqual(self.preview(vehicle_model=activa.pk, seats=4).data["fare"]["total"], one)

    def test_mistakes_are_refused_with_the_field(self):
        for extra, field in (
            ({"distance_km": 0}, "distance_km"), ({"distance_km": 500}, "distance_km"),
            ({"vehicle_model": 99999}, "vehicle_model"), ({"seats": 9}, "seats"),
            ({"toll_total": 5000}, "toll_total"), ({"fare_adjustment": 21}, "fare_adjustment"),
        ):
            response = self.preview(**extra)
            self.assertEqual(response.status_code, 400, extra)
            self.assertIn(field, response.data["errors"], extra)

    def test_the_mileage_is_never_sent(self):
        text = self.preview().content.decode().lower()
        self.assertNotIn("mileage", text)
        self.assertNotIn("km_per_litre", text)