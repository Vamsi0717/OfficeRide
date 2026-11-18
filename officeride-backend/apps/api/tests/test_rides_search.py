from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import bike_ride, car_ride, make_request
from apps.rides.models import CarUnavailableDate
from apps.rides.tests.helpers import make_driver, make_user, next_weekday

from .helpers import FreshCache, client_for
from .ride_helpers import search_params

URL = "/api/v1/rides/search/"


class SearchTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.driver = make_driver()
        self.ride = car_ride(self.driver)
        self.rider = make_user("rider@acme.com")
        self.client = client_for(self.rider)
        self.monday = next_weekday(0)

    def search(self, **overrides):
        params = search_params(self.monday)
        params.update(overrides)
        return self.client.get(URL, params)

    def test_finds_the_ride(self):
        response = self.search()
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.data["count"], response.data["window_min"]), (1, 15))
        result = response.data["results"][0]
        self.assertEqual(result["ride"]["id"], self.ride.pk)
        self.assertEqual(result["ride"]["departure_time"], "09:00")
        self.assertEqual(result["time_diff_min"], 5)
        self.assertGreater(result["rider_km"], 5)
        self.assertEqual(set(result), {"ride", "rider_km", "pickup_offset_km", "drop_offset_km", "time_diff_min"})

    def test_the_fare_is_for_the_riders_own_trip_not_the_whole_route(self):
        result = self.search().data["results"][0]
        self.assertLess(result["ride"]["fare"]["total"], 60)
        self.assertLess(float(result["ride"]["fare"]["rider_km"]), self.ride.distance_km)

    def test_the_driver_is_shown_without_contact_details(self):
        result = self.search().data["results"][0]
        driver = result["ride"]["driver"]
        self.assertEqual((driver["first_name"], driver["last_name"]), ("Ravi", "Kumar"))
        self.assertEqual(driver["stats"], {"average": None, "count": 0, "rides": 0})
        text = self.search().content.decode()
        for private in ("driver@acme.com", "phone", "email"):
            self.assertNotIn(private, text)

    def test_the_mileage_is_never_sent(self):
        text = self.search().content.decode().lower()
        self.assertNotIn("mileage", text)
        self.assertNotIn("km_per_litre", text)

    def test_nothing_found_is_an_empty_list_not_an_error(self):
        response = self.search(time="14:00")
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.data["count"], response.data["results"]), (0, []))

    def test_every_mistake_is_reported_at_once(self):
        response = self.client.get(URL, {"date": "2020-01-01"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invalid")
        self.assertEqual(set(response.data["errors"]), {"date", "time", "pickup_name", "drop_name"})

    def test_a_place_must_be_picked(self):
        response = self.search(pickup_name="", pickup_lat="", pickup_lng="")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Pick the pickup place", response.data["errors"]["pickup_name"][0])

    def test_a_place_outside_bangalore_is_refused(self):
        response = self.search(drop_lat=28.61, drop_lng=77.20)
        self.assertEqual(response.data["errors"]["drop_name"], ["OfficeRide works inside Bangalore only."])

    def test_a_past_date_is_refused(self):
        response = self.search(date=(timezone.localdate() - timedelta(days=1)).isoformat())
        self.assertEqual(response.data["errors"]["date"], ["Choose today or a future date."])

    def test_a_date_too_far_ahead_is_refused(self):
        response = self.search(date=(timezone.localdate() + timedelta(days=90)).isoformat())
        self.assertEqual(response.data["errors"]["date"], ["Choose a date within the next 60 days."])

    def test_own_ride_is_not_shown_to_its_driver(self):
        self.assertEqual(client_for(self.driver).get(URL, search_params(self.monday)).data["count"], 0)

    def test_the_vehicle_filter(self):
        bike = bike_ride()
        both = self.search()
        self.assertEqual(both.data["count"], 2)
        bikes = self.search(vehicle="bike")
        self.assertEqual([r["ride"]["id"] for r in bikes.data["results"]], [bike.pk])
        self.assertTrue(bikes.data["results"][0]["ride"]["has_spare_helmet"])
        cars = self.search(vehicle="car")
        self.assertEqual([r["ride"]["id"] for r in cars.data["results"]], [self.ride.pk])

    def test_a_day_the_car_is_off_hides_the_ride(self):
        CarUnavailableDate.objects.create(driver=self.driver, date=self.monday)
        self.assertEqual(self.search().data["count"], 0)

    def test_a_switched_off_ride_is_not_shown(self):
        self.ride.is_active = False
        self.ride.save()
        self.assertEqual(self.search().data["count"], 0)

    def test_a_full_ride_is_not_shown(self):
        for n in range(3):
            make_request(self.ride, make_user(f"p{n}@acme.com"), self.monday, status=RideRequest.Status.ACCEPTED)
        self.assertEqual(self.search().data["count"], 0)

    def test_a_driver_with_pending_documents_is_not_shown(self):
        car_ride(make_driver("new@acme.com", approved=False), origin_name="Other")
        self.assertEqual(self.search().data["count"], 1)

    def test_a_rating_shows_on_the_result(self):
        from apps.trust.models import Rating

        req = make_request(self.ride, self.rider, status=RideRequest.Status.COMPLETED)
        Rating.objects.create(request=req, rater=self.rider, rated=self.driver, stars=5)
        stats = self.search().data["results"][0]["ride"]["driver"]["stats"]
        self.assertEqual((stats["average"], stats["count"]), (5.0, 1))