from datetime import time

from django.test import TestCase
from django.urls import reverse

from apps.bookings import services as booking_services
from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import bike_ride, car_ride, drop, future_monday, make_request, pickup
from apps.rides import matching
from apps.rides.models import Ride
from apps.rides.tests.helpers import get_rate, make_driver, make_user, point_along

S = RideRequest.Status


def edit_data(ride, **overrides):
    data = {
        "departure_time": ride.departure_time.strftime("%H:%M"),
        "office_days": ride.office_days.split(","),
        "seats": ride.seats,
        "car_model": ride.car_model,
        "mileage_rate": ride.mileage_rate_id,
        "toll_total": ride.toll_total,
        "fare_adjustment": ride.fare_adjustment,
    }
    if ride.is_bike:
        data["has_spare_helmet"] = "on"
    data.update(overrides)
    return data


class DetailPageTests(TestCase):
    def test_owner_sees_full_info_and_buttons(self):
        ride = car_ride()
        make_request(ride, make_user("r@acme.com", first_name="Anita"), status=S.ACCEPTED)
        self.client.force_login(ride.driver)
        page = self.client.get(reverse("rides:detail", args=[ride.pk]))
        self.assertContains(page, "Edit ride")
        self.assertContains(page, "Delete ride")
        self.assertContains(page, "Anita")
        self.assertContains(page, reverse("rides:fare", args=[ride.pk]))

    def test_rider_does_not_see_owner_controls(self):
        ride = car_ride()
        self.client.force_login(make_user("r@acme.com"))
        page = self.client.get(reverse("rides:detail", args=[ride.pk]))
        self.assertNotContains(page, "Delete ride")
        self.assertNotContains(page, reverse("rides:edit", args=[ride.pk]))


class EditTests(TestCase):
    def setUp(self):
        self.ride = car_ride()
        self.url = reverse("rides:edit", args=[self.ride.pk])
        self.client.force_login(self.ride.driver)

    def test_form_opens_with_current_values(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Maruti Swift")

    def test_edit_saves_fare_toll_and_vehicle(self):
        data = edit_data(self.ride, toll_total=40, fare_adjustment=-10, car_model="Honda City", seats=2)
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse("rides:detail", args=[self.ride.pk]))
        self.ride.refresh_from_db()
        self.assertEqual((self.ride.toll_total, self.ride.fare_adjustment, self.ride.car_model, self.ride.seats),
                         (40, -10, "Honda City", 2))

    def test_adjustment_over_limit_is_refused(self):
        response = self.client.post(self.url, edit_data(self.ride, fare_adjustment=21))
        self.assertEqual(response.status_code, 200)
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.fare_adjustment, 0)

    def test_time_and_days_can_change_with_no_bookings(self):
        self.client.post(self.url, edit_data(self.ride, departure_time="08:30", office_days=["0", "2"]))
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.departure_time, time(8, 30))
        self.assertEqual(self.ride.office_days, "0,2")

    def test_time_change_refused_while_a_booking_is_live(self):
        make_request(self.ride, make_user("r@acme.com"), status=S.ACCEPTED)
        response = self.client.post(self.url, edit_data(self.ride, departure_time="08:30"))
        self.assertContains(response, "pending or accepted booking")
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.departure_time, time(9, 0))

    def test_fare_change_allowed_while_a_booking_is_live_and_booking_keeps_its_fare(self):
        req = make_request(self.ride, make_user("r@acme.com"), status=S.ACCEPTED, fare=50)
        response = self.client.post(self.url, edit_data(self.ride, fare_adjustment=20, toll_total=60))
        self.assertEqual(response.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.fare, 50)

    def test_seats_cannot_drop_below_accepted_riders(self):
        monday = future_monday()
        for n in range(3):
            make_request(self.ride, make_user(f"r{n}@acme.com"), date=monday, status=S.ACCEPTED)
        response = self.client.post(self.url, edit_data(self.ride, seats=2))
        self.assertContains(response, "Keep at least 3 seats")
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.seats, 3)

    def test_vehicle_class_must_match_vehicle_type(self):
        response = self.client.post(self.url, edit_data(self.ride, mileage_rate=get_rate("bike").pk))
        self.assertEqual(response.status_code, 200)

    def test_no_days_chosen_is_refused(self):
        response = self.client.post(self.url, {k: v for k, v in edit_data(self.ride).items() if k != "office_days"})
        self.assertContains(response, "Choose at least one day")

    def test_strangers_get_404_and_riders_are_turned_away(self):
        other = make_driver("other@acme.com")
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(make_user("r@acme.com"))
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_anonymous_goes_to_login(self):
        self.client.logout()
        self.assertIn("/accounts/login/", self.client.get(self.url)["Location"])


class BikeEditTests(TestCase):
    def test_bike_seats_stay_one_and_helmet_is_required(self):
        ride = bike_ride()
        self.client.force_login(ride.driver)
        url = reverse("rides:edit", args=[ride.pk])
        data = edit_data(ride, seats=3)
        data.pop("has_spare_helmet")
        self.assertContains(self.client.post(url, data), "spare one")
        self.client.post(url, edit_data(ride, seats=3, toll_total=0))
        ride.refresh_from_db()
        self.assertEqual(ride.seats, 1)


class QuickFareTests(TestCase):
    def setUp(self):
        self.ride = car_ride()
        self.url = reverse("rides:fare", args=[self.ride.pk])
        self.client.force_login(self.ride.driver)

    def test_accepts_the_whole_range(self):
        for value in (-20, 0, 20):
            self.client.post(self.url, {"fare_adjustment": value})
            self.ride.refresh_from_db()
            self.assertEqual(self.ride.fare_adjustment, value)

    def test_refuses_outside_the_range(self):
        for value in (21, -21, "abc"):
            self.client.post(self.url, {"fare_adjustment": value})
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.fare_adjustment, 0)

    def test_needs_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_other_drivers_cannot_change_it(self):
        self.client.force_login(make_driver("other@acme.com"))
        self.assertEqual(self.client.post(self.url, {"fare_adjustment": 5}).status_code, 404)
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.fare_adjustment, 0)

    def test_existing_booking_keeps_its_fare(self):
        req = make_request(self.ride, make_user("r@acme.com"), status=S.ACCEPTED, fare=50, fare_adjustment=0)
        self.client.post(self.url, {"fare_adjustment": 20})
        req.refresh_from_db()
        self.assertEqual((req.fare, req.fare_adjustment), (50, 0))


class DeleteTests(TestCase):
    def setUp(self):
        self.ride = car_ride()
        self.url = reverse("rides:delete", args=[self.ride.pk])
        self.client.force_login(self.ride.driver)

    def test_confirm_page_lists_bookings_and_deletes_nothing(self):
        make_request(self.ride, make_user("r@acme.com", first_name="Anita"), status=S.PENDING)
        page = self.client.get(self.url)
        self.assertContains(page, "Anita")
        self.ride.refresh_from_db()
        self.assertIsNone(self.ride.deleted_at)

    def test_delete_cancels_live_bookings_and_hides_the_ride(self):
        live = make_request(self.ride, make_user("a@acme.com"), status=S.ACCEPTED)
        waiting = make_request(self.ride, make_user("b@acme.com"), status=S.PENDING)
        done = make_request(self.ride, make_user("c@acme.com"), status=S.COMPLETED, date=future_monday())
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("rides:mine"))
        self.ride.refresh_from_db()
        self.assertTrue(self.ride.is_deleted)
        self.assertFalse(self.ride.is_active)
        for req in (live, waiting):
            req.refresh_from_db()
            self.assertEqual(req.status, S.CANCELLED)
        done.refresh_from_db()
        self.assertEqual(done.status, S.COMPLETED)

    def test_deleted_ride_is_gone_from_my_rides_search_and_detail(self):
        self.client.post(self.url)
        self.assertNotContains(self.client.get(reverse("rides:mine")), "Maruti Swift")
        self.assertEqual(self.client.get(reverse("rides:detail", args=[self.ride.pk])).status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        found = matching.find_rides(
            make_user("r@acme.com"), point_along(0.1)[:2], point_along(0.9)[:2], future_monday(), time(9, 0))
        self.assertEqual(found, [])

    def test_row_is_kept_for_history(self):
        self.client.post(self.url)
        self.assertTrue(Ride.objects.filter(pk=self.ride.pk).exists())

    def test_cannot_book_a_deleted_ride(self):
        self.client.post(self.url)
        with self.assertRaises(booking_services.BookingError):
            booking_services.request_seat(make_user("r@acme.com"), self.ride.pk, future_monday(), pickup(), drop())

    def test_get_does_not_delete_and_strangers_get_404(self):
        self.client.get(self.url)
        self.ride.refresh_from_db()
        self.assertIsNone(self.ride.deleted_at)
        self.client.force_login(make_driver("other@acme.com"))
        self.assertEqual(self.client.post(self.url).status_code, 404)