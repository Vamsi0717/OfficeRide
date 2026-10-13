from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse

from apps.bookings import services
from apps.bookings.models import RideRequest
from apps.rides import services as ride_services
from apps.rides.models import Ride
from apps.rides.tests.helpers import get_rate, make_driver, make_user, point_along

from .helpers import bike_ride, car_ride, future_monday, make_request

S = RideRequest.Status


class OfferBackTests(TestCase):
    def setUp(self):
        self.ride = car_ride(toll_total=40, fare_adjustment=10)
        self.driver = self.ride.driver
        self.url = reverse("rides:offer_back", args=[self.ride.pk])

    def test_the_way_back_is_its_own_ride_with_start_and_end_swapped(self):
        back = ride_services.create_return_ride(self.ride, time(18, 0))
        self.assertNotEqual(back.pk, self.ride.pk)
        self.assertEqual((back.origin_name, back.destination_name), (self.ride.destination_name, self.ride.origin_name))
        self.assertEqual((back.origin_lat, back.destination_lat), (self.ride.destination_lat, self.ride.origin_lat))
        self.assertEqual(back.departure_time, time(18, 0))

    def test_the_road_is_reversed_and_the_distance_is_the_same(self):
        back = ride_services.create_return_ride(self.ride, time(18, 0))
        self.assertEqual(back.route_points, list(reversed(self.ride.route_points)))
        self.assertEqual((back.route_distance_m, back.route_duration_s), (self.ride.route_distance_m, self.ride.route_duration_s))
        self.assertEqual((back.min_lat, back.max_lat), (self.ride.min_lat, self.ride.max_lat))

    def test_everything_else_is_copied_including_toll_class_and_the_fare_adjustment(self):
        back = ride_services.create_return_ride(self.ride, time(18, 0))
        for field in ("driver", "office_days", "seats", "vehicle_type", "car_model", "mileage_rate", "toll_total", "fare_adjustment"):
            self.assertEqual(getattr(back, field), getattr(self.ride, field), field)

    def test_a_two_wheeler_way_back_keeps_one_seat_and_the_helmet(self):
        ride = bike_ride()
        back = ride_services.create_return_ride(ride, time(18, 0))
        self.assertEqual((back.seats, back.has_spare_helmet, back.vehicle_type), (1, True, "bike"))

    def test_offering_the_same_way_back_twice_is_refused(self):
        ride_services.create_return_ride(self.ride, time(18, 0))
        with self.assertRaisesMessage(ride_services.ReturnRideError, "already offer"):
            ride_services.create_return_ride(self.ride, time(18, 0))
        ride_services.create_return_ride(self.ride, time(19, 0))  # another time is fine

    def test_the_button_on_my_rides_makes_the_way_back(self):
        self.client.force_login(self.driver)
        page = self.client.get(reverse("rides:mine"))
        self.assertContains(page, "Offer the same ride back")
        response = self.client.post(self.url, {"return_time": "18:15"}, follow=True)
        self.assertContains(response, "The way back is live")
        self.assertEqual(Ride.objects.filter(driver=self.driver).count(), 2)

    def test_a_missing_time_is_refused(self):
        self.client.force_login(self.driver)
        response = self.client.post(self.url, {"return_time": ""}, follow=True)
        self.assertContains(response, "Choose the time")
        self.assertEqual(Ride.objects.count(), 1)

    def test_only_the_owner_can_offer_the_way_back(self):
        self.client.force_login(make_user("other@acme.com"))
        self.assertEqual(self.client.post(self.url, {"return_time": "18:00"}).status_code, 302)  # not a driver
        self.client.force_login(make_driver("d2@acme.com"))
        self.assertEqual(self.client.post(self.url, {"return_time": "18:00"}).status_code, 404)
        self.assertEqual(Ride.objects.count(), 1)

    def test_the_button_needs_a_post(self):
        self.client.force_login(self.driver)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_the_way_back_has_its_own_bookings(self):
        back = ride_services.create_return_ride(self.ride, time(18, 0))
        rider = make_user("rider@acme.com")
        morning = make_request(self.ride, rider, future_monday(), S.ACCEPTED)
        a, b = point_along(0.9), point_along(0.1)  # the way back runs east to west... the road is reversed
        evening = services.request_seat(
            rider, back.pk, future_monday(),
            {"name": "Drop spot", "lat": a[0], "lng": a[1]}, {"name": "Pickup spot", "lat": b[0], "lng": b[1]},
        )
        self.assertNotEqual(evening.ride_id, morning.ride_id)
        self.assertEqual(services.seats_left(self.ride, future_monday()), 2)  # the morning seat count is separate


class RequestBackTests(TestCase):
    def setUp(self):
        self.morning = car_ride()
        self.evening = ride_services.create_return_ride(self.morning, time(18, 0))
        self.rider = make_user("rider@acme.com")
        self.day = future_monday()
        self.booking = make_request(self.morning, self.rider, self.day, S.ACCEPTED)
        self.url = reverse("bookings:request_back", args=[self.booking.pk])
        self.client.force_login(self.rider)

    def search(self, **extra):
        params = {"date": self.day.isoformat(), "time": "18:00", "window": "15"}
        params.update(extra)
        return self.client.get(self.url, params)

    def test_the_trips_page_offers_the_button_for_accepted_bookings(self):
        self.assertContains(self.client.get(reverse("bookings:trips")), self.url)

    def test_no_button_for_a_pending_booking_and_none_for_the_driver(self):
        self.booking.status = S.PENDING
        self.booking.save()
        self.assertNotContains(self.client.get(reverse("bookings:trips")), self.url)
        self.client.force_login(self.morning.driver)
        self.assertNotContains(self.client.get(reverse("bookings:trips")), self.url)

    def test_the_page_opens_with_the_date_of_the_booking(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Request the ride back")
        self.assertContains(response, f'value="{self.day.isoformat()}"')

    def test_it_finds_the_evening_ride_for_the_swapped_places(self):
        response = self.search()
        self.assertEqual([m.ride for m in response.context["matches"]], [self.evening])
        self.assertContains(response, "Request a seat")

    def test_the_request_button_carries_the_swapped_places(self):
        response = self.search()
        self.assertContains(response, 'name="pickup_name" value="Drop spot"')
        self.assertContains(response, 'name="drop_name" value="Pickup spot"')

    def test_the_time_window_decides_what_is_found(self):
        self.assertEqual(self.search(time="18:40", window="15").context["matches"], [])
        self.assertEqual(self.search(time="18:40", window="30").context["matches"], [])
        self.assertEqual(len(self.search(time="18:40", window="60").context["matches"]), 1)
        self.assertEqual(len(self.search(time="18:25", window="30").context["matches"]), 1)

    def test_the_morning_ride_is_not_offered_for_the_way_back(self):
        response = self.search(time="09:00", window="15")
        self.assertEqual(response.context["matches"], [])  # the morning ride runs the wrong way for the swapped places

    def test_a_request_from_this_page_makes_a_pending_booking_on_the_evening_ride(self):
        response = self.search()
        form_values = {"date": self.day.isoformat()}
        search = response.context["search"]
        form_values.update({k: v for k, v in search.items() if k != "date"})
        self.client.post(reverse("bookings:request_seat", args=[self.evening.pk]), form_values)
        req = RideRequest.objects.get(ride=self.evening)
        self.assertEqual((req.rider, req.status), (self.rider, S.PENDING))

    def test_only_the_rider_of_an_accepted_or_completed_booking_can_open_it(self):
        self.client.force_login(make_user("other@acme.com"))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(self.rider)
        self.booking.status = S.CANCELLED
        self.booking.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_a_past_date_is_refused(self):
        response = self.search(date=(self.day - timedelta(days=60)).isoformat())
        self.assertContains(response, "today or a future date")