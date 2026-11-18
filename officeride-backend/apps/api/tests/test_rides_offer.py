from unittest import mock

from django.test import TestCase, override_settings

from apps.rides import maps
from apps.rides.models import Ride
from apps.rides.tests.helpers import get_model, make_driver

from .helpers import FreshCache, client_for
from .ride_helpers import bike_offer_body, offer_body, withdraw_approval

URL = "/api/v1/rides/"


class OfferRideTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.driver = make_driver()
        self.client = client_for(self.driver)

    def offer(self, **overrides):
        return self.client.post(URL, offer_body(**overrides), format="json")

    def test_a_good_offer_saves_a_ride_with_its_route(self):
        response = self.offer()
        self.assertEqual(response.status_code, 201)
        ride = Ride.objects.get()
        self.assertEqual((ride.driver, ride.origin_name, ride.destination_name), (self.driver, "KR Puram", "Bellandur"))
        self.assertEqual((ride.seats, ride.office_days, ride.vehicle_type), (3, "0,1,2,3,4", "car"))
        self.assertEqual(ride.car_model, "Hyundai i20")
        self.assertGreater(len(ride.route_points), 2)
        self.assertGreater(ride.route_distance_m, 5000)
        self.assertEqual(ride.mileage_rate, get_model("car", "i20"))

    def test_the_answer_has_the_ride_and_what_a_rider_pays(self):
        rides = self.offer().data["rides"]
        self.assertEqual(len(rides), 1)
        ride = rides[0]
        self.assertEqual((ride["departure_time"], ride["office_days"], ride["is_active"]), ("08:30", [0, 1, 2, 3, 4], True))
        self.assertEqual(ride["vehicle_model"], "Hyundai i20")
        self.assertGreater(ride["fare"]["total"], 0)
        self.assertNotIn("mileage", str(ride).lower())

    def test_the_way_back_makes_a_second_ride_in_reverse(self):
        response = self.offer(offer_return=True, return_time="18:00")
        self.assertEqual(len(response.data["rides"]), 2)
        out, back = Ride.objects.order_by("departure_time")
        self.assertEqual((back.origin_name, back.destination_name, str(back.departure_time)), ("Bellandur", "KR Puram", "18:00:00"))
        self.assertEqual(out.route_distance_m, back.route_distance_m)

    def test_the_way_back_needs_a_time(self):
        response = self.offer(offer_return=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("return_time", response.data["errors"])
        self.assertFalse(Ride.objects.exists())

    def test_a_place_must_be_picked(self):
        response = self.offer(origin_name="", origin_lat=None, origin_lng=None)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Pick the start place", response.data["errors"]["origin_name"][0])

    def test_a_place_outside_bangalore_is_refused(self):
        response = self.offer(destination_lat=28.61, destination_lng=77.20)
        self.assertEqual(response.data["errors"]["destination_name"], ["OfficeRide works inside Bangalore only."])
        self.assertFalse(Ride.objects.exists())

    def test_start_and_end_too_close(self):
        response = self.offer(destination_lat=13.0080, destination_lng=77.6960, destination_name="Next door")
        self.assertEqual(response.data["errors"]["destination_name"], ["The start and end are too close to share a ride."])

    def test_at_least_one_day_is_required(self):
        for days in ([], None):
            response = self.offer(office_days=days)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["errors"]["office_days"], ["Choose at least one day."])

    def test_days_can_be_sent_as_numbers_or_text(self):
        self.offer(office_days=["0", "2"])
        self.assertEqual(Ride.objects.get().office_days, "0,2")

    def test_seats_must_be_between_1_and_6(self):
        for seats in (0, 7):
            self.assertEqual(self.offer(seats=seats).status_code, 400)
        self.assertEqual(self.offer(seats=6).status_code, 201)

    def test_every_mistake_is_reported_at_once(self):
        response = self.client.post(URL, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invalid")
        self.assertTrue({"origin_name", "destination_name", "departure_time", "office_days", "seats", "vehicle_model"}
                        <= set(response.data["errors"]))

    def test_the_vehicle_model_is_required_and_must_match_the_vehicle_type(self):
        self.assertIn("vehicle_model", self.client.post(URL, offer_body(vehicle_model=None), format="json").data["errors"])
        response = self.offer(vehicle_model=get_model("bike").pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("vehicle_model", response.data["errors"])
        self.assertFalse(Ride.objects.exists())

    def test_toll_is_optional_and_limited(self):
        self.assertEqual(self.offer(toll_total=60).status_code, 201)
        self.assertEqual(Ride.objects.get().toll_total, 60)
        self.assertEqual(self.offer(toll_total=5000).status_code, 400)

    def test_the_fare_adjustment_is_limited(self):
        self.assertEqual(self.offer(fare_adjustment=21).status_code, 400)
        self.assertEqual(self.offer(fare_adjustment=-20).status_code, 201)

    def test_a_maps_failure_is_a_clean_error_and_nothing_is_saved(self):
        with mock.patch.object(maps, "get_route", side_effect=maps.MapsError("Maps are down.")):
            response = self.offer()
        self.assertEqual(response.status_code, 503)
        self.assertEqual((response.data["detail"], response.data["code"]), ("Maps are down.", "maps_unavailable"))
        self.assertFalse(Ride.objects.exists())

    def test_a_suspended_driver_cannot_offer(self):
        from datetime import timedelta

        from django.utils import timezone

        self.driver.suspended_until = timezone.now() + timedelta(days=3)
        self.driver.save()
        response = self.offer()
        self.assertEqual((response.status_code, response.data["code"]), (403, "account_blocked"))
        self.assertFalse(Ride.objects.exists())

    def test_a_driver_under_review_cannot_offer(self):
        self.driver.under_review = True
        self.driver.save()
        self.assertEqual(self.offer().data["code"], "account_blocked")

    def test_documents_that_stop_being_approved_stop_new_offers(self):
        client = client_for(withdraw_approval(self.driver))
        self.assertEqual(client.post(URL, offer_body(), format="json").status_code, 403)

    def test_a_form_post_works_too(self):
        data = offer_body()
        data["office_days"] = ["0", "1"]
        response = self.client.post(URL, data, format="multipart")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Ride.objects.get().office_days, "0,1")

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(URL).status_code, 405)


class TwoWheelerOfferTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.client = client_for(make_driver("biker@acme.com", vehicle_type="bike"))

    def test_a_two_wheeler_ride_has_one_seat_whatever_is_sent(self):
        response = self.client.post(URL, bike_offer_body(seats=3), format="json")
        self.assertEqual(response.status_code, 201)
        ride = Ride.objects.get()
        self.assertEqual((ride.vehicle_type, ride.seats, ride.has_spare_helmet), ("bike", 1, True))
        self.assertTrue(response.data["rides"][0]["has_spare_helmet"])

    def test_a_spare_helmet_is_required(self):
        body = bike_offer_body()
        del body["has_spare_helmet"]
        response = self.client.post(URL, body, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"]["has_spare_helmet"], ["Riders must wear a helmet. Confirm that you carry a spare one."])
        self.assertFalse(Ride.objects.exists())

    def test_the_way_back_is_also_a_two_wheeler_ride(self):
        self.client.post(URL, bike_offer_body(offer_return=True, return_time="18:00"), format="json")
        self.assertEqual(list(Ride.objects.values_list("vehicle_type", "seats")), [("bike", 1), ("bike", 1)])

    def test_a_car_model_is_refused_for_a_two_wheeler_driver(self):
        response = self.client.post(URL, bike_offer_body(vehicle_model=get_model("car").pk), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("vehicle_model", response.data["errors"])


class CarDriverHelmetTests(FreshCache, TestCase):
    def test_a_car_driver_is_never_asked_for_a_helmet(self):
        client = client_for(make_driver())
        response = client.post(URL, offer_body(has_spare_helmet=True), format="json")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(Ride.objects.get().has_spare_helmet)