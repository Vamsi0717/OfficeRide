from datetime import time, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import bike_ride, car_ride, future_monday, make_request
from apps.rides.models import CarUnavailableDate, Ride
from apps.rides.tests.helpers import get_model, make_driver, make_user

from .helpers import FreshCache, client_for
from .ride_helpers import withdraw_approval

S = RideRequest.Status
ALL_DAYS = "0,1,2,3,4,5,6"


def url(ride, suffix=""):
    return f"/api/v1/rides/{ride.pk}/{suffix}"


class MyRidesTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.driver = make_driver()
        self.ride = car_ride(self.driver, days=ALL_DAYS)
        self.today = timezone.localdate()
        self.client = client_for(self.driver)

    def mine(self):
        response = self.client.get("/api/v1/rides/mine/")
        self.assertEqual(response.status_code, 200)
        return response.data

    def booking(self, status, offset, email):
        return make_request(self.ride, make_user(email), self.today + timedelta(days=offset), status=status)

    def test_live_and_switched_off_rides_are_in_separate_lists(self):
        off = car_ride(self.driver, is_active=False, origin_name="Old")
        data = self.mine()
        self.assertEqual([r["id"] for r in data["live"]], [self.ride.pk])
        self.assertEqual([r["id"] for r in data["off"]], [off.pk])

    def test_a_person_with_no_rides_gets_two_empty_lists(self):
        data = client_for(make_user()).get("/api/v1/rides/mine/").data
        self.assertEqual(data, {"live": [], "off": [], "waiting_total": 0})

    def test_only_my_rides_are_listed(self):
        car_ride(make_driver("other@acme.com"), origin_name="Not mine")
        self.assertEqual([r["id"] for r in self.mine()["live"]], [self.ride.pk])

    def test_a_deleted_ride_is_not_listed(self):
        self.client.delete(url(self.ride))
        data = self.mine()
        self.assertEqual((data["live"], data["off"]), ([], []))

    def test_each_ride_says_what_a_rider_pays(self):
        ride = self.mine()["live"][0]
        self.assertGreater(ride["fare"]["total"], 0)

    def test_today_tomorrow_and_the_next_booked_day(self):
        self.booking(S.ACCEPTED, 0, "a@acme.com")
        self.booking(S.ACCEPTED, 0, "b@acme.com")
        self.booking(S.ACCEPTED, 1, "c@acme.com")
        self.booking(S.ACCEPTED, 5, "d@acme.com")
        summary = self.mine()["live"][0]["summary"]
        self.assertEqual((summary["booked_today"], summary["booked_tomorrow"], summary["waiting"]), (2, 1, 0))
        self.assertEqual(summary["next_booked"], {"date": (self.today + timedelta(days=5)).isoformat(), "riders": 1})
        self.assertTrue(summary["runs_today"] and summary["runs_tomorrow"])

    def test_requests_nobody_answered_are_counted_as_waiting(self):
        self.booking(S.PENDING, 2, "a@acme.com")
        self.booking(S.PENDING, 3, "b@acme.com")
        data = self.mine()
        self.assertEqual((data["live"][0]["summary"]["waiting"], data["waiting_total"]), (2, 2))

    def test_cancelled_rejected_completed_and_past_bookings_do_not_count(self):
        self.booking(S.CANCELLED, 0, "a@acme.com")
        self.booking(S.REJECTED, 1, "b@acme.com")
        self.booking(S.COMPLETED, 0, "c@acme.com")
        self.booking(S.ACCEPTED, -3, "d@acme.com")
        summary = self.mine()["live"][0]["summary"]
        self.assertEqual((summary["booked_today"], summary["booked_tomorrow"], summary["waiting"], summary["next_booked"]),
                         (0, 0, 0, None))

    def test_a_ride_that_does_not_run_today_says_so(self):
        only_today = str(self.today.weekday())
        ride = car_ride(self.driver, days=str((self.today.weekday() + 3) % 7), origin_name="Later")
        mine = {r["id"]: r for r in self.mine()["live"]}
        self.assertFalse(mine[ride.pk]["summary"]["runs_today"])
        self.assertEqual(only_today, str(self.today.weekday()))

    def test_the_query_count_does_not_grow_with_the_number_of_rides(self):
        self.booking(S.ACCEPTED, 0, "a@acme.com")
        with CaptureQueriesContext(connection) as few:
            self.mine()
        for i in range(5):
            ride = car_ride(self.driver, days=ALL_DAYS, origin_name=f"R{i}")
            make_request(ride, make_user(f"x{i}@acme.com"), self.today, status=S.ACCEPTED)
            make_request(ride, make_user(f"y{i}@acme.com"), self.today + timedelta(days=2), status=S.PENDING)
        with CaptureQueriesContext(connection) as many:
            self.mine()
        self.assertEqual(len(few), len(many))


class RideDetailTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.ride = car_ride()
        self.rider_client = client_for(make_user("rider@acme.com"))
        self.owner_client = client_for(self.ride.driver)

    def test_a_rider_sees_the_ride_the_route_and_the_driver_without_contact_details(self):
        response = self.rider_client.get(url(self.ride))
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual((data["id"], data["is_owner"], data["departure_time"]), (self.ride.pk, False, "09:00"))
        self.assertEqual(data["driver"]["first_name"], "Ravi")
        self.assertEqual(len(data["route_points"]), 51)
        self.assertGreater(data["fare"]["total"], 0)
        text = response.content.decode()
        for private in ("driver@acme.com", "phone", "email"):
            self.assertNotIn(private, text)
        self.assertNotIn("summary", data)

    def test_nobody_sees_the_mileage_not_even_the_owner(self):
        for client in (self.rider_client, self.owner_client):
            text = client.get(url(self.ride)).content.decode().lower()
            self.assertNotIn("mileage", text)
            self.assertNotIn("km_per_litre", text)

    def test_the_owner_sees_the_booking_summary_and_the_fare_limit(self):
        make_request(self.ride, make_user("r@acme.com"), status=S.PENDING)
        data = self.owner_client.get(url(self.ride)).data
        self.assertTrue(data["is_owner"])
        self.assertEqual((data["summary"]["waiting"], data["max_adjustment"]), (1, 20))

    def test_a_switched_off_ride_is_hidden_from_riders_but_not_from_its_owner(self):
        self.ride.is_active = False
        self.ride.save()
        self.assertEqual(self.rider_client.get(url(self.ride)).status_code, 404)
        owner = self.owner_client.get(url(self.ride))
        self.assertEqual((owner.status_code, owner.data["is_active"]), (200, False))

    def test_a_deleted_ride_is_gone_for_everybody(self):
        self.owner_client.delete(url(self.ride))
        for client in (self.rider_client, self.owner_client):
            self.assertEqual(client.get(url(self.ride)).status_code, 404)

    def test_a_ride_that_does_not_exist_is_404(self):
        self.assertEqual(self.rider_client.get("/api/v1/rides/99999/").status_code, 404)

    def test_a_two_wheeler_says_it_carries_a_spare_helmet(self):
        ride = bike_ride()
        data = self.rider_client.get(url(ride)).data
        self.assertEqual((data["vehicle_type"], data["has_spare_helmet"], data["seats"]), ("bike", True, 1))


class EditTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.ride = car_ride(mileage_rate=get_model("car", "Swift"), car_model="Maruti Suzuki Swift")
        self.client = client_for(self.ride.driver)
        self.url = url(self.ride)

    def edit(self, **body):
        return self.client.patch(self.url, body, format="json")

    def test_edit_saves_fare_toll_vehicle_and_seats(self):
        city = get_model("car", "City")
        response = self.edit(toll_total=40, fare_adjustment=-10, vehicle_model=city.pk, seats=2)
        self.assertEqual(response.status_code, 200)
        self.ride.refresh_from_db()
        self.assertEqual((self.ride.toll_total, self.ride.fare_adjustment, self.ride.car_model, self.ride.seats),
                         (40, -10, "Honda City", 2))
        self.assertEqual(self.ride.mileage_rate, city)
        self.assertEqual((response.data["seats"], response.data["vehicle_model"]), (2, "Honda City"))

    def test_only_what_is_sent_changes(self):
        self.edit(toll_total=30)
        self.ride.refresh_from_db()
        self.assertEqual((self.ride.toll_total, self.ride.seats, self.ride.departure_time, self.ride.office_days),
                         (30, 3, time(9, 0), "0,1,2,3,4"))

    def test_the_start_and_end_cannot_be_changed(self):
        self.edit(origin_name="Somewhere else", destination_lat=12.0)
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.origin_name, "Start")

    def test_an_adjustment_over_the_limit_is_refused(self):
        response = self.edit(fare_adjustment=21)
        self.assertEqual(response.status_code, 400)
        self.assertIn("fare_adjustment", response.data["errors"])
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.fare_adjustment, 0)

    def test_time_and_days_can_change_with_no_bookings(self):
        self.assertEqual(self.edit(departure_time="08:30", office_days=[0, 2]).status_code, 200)
        self.ride.refresh_from_db()
        self.assertEqual((self.ride.departure_time, self.ride.office_days), (time(8, 30), "0,2"))

    def test_a_time_change_is_refused_while_a_booking_is_live(self):
        make_request(self.ride, make_user("r@acme.com"), status=S.ACCEPTED)
        response = self.edit(departure_time="08:30")
        self.assertEqual((response.status_code, response.data["code"]), (409, "ride_change_refused"))
        self.assertIn("pending or accepted booking", response.data["detail"])
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.departure_time, time(9, 0))

    def test_a_fare_change_is_allowed_while_a_booking_is_live_and_the_booking_keeps_its_fare(self):
        req = make_request(self.ride, make_user("r@acme.com"), status=S.ACCEPTED, fare=50)
        self.assertEqual(self.edit(fare_adjustment=20, toll_total=60).status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.fare, 50)

    def test_seats_cannot_drop_below_the_accepted_riders(self):
        for n in range(3):
            make_request(self.ride, make_user(f"r{n}@acme.com"), date=future_monday(), status=S.ACCEPTED)
        response = self.edit(seats=2)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Keep at least 3 seats", response.data["detail"])
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.seats, 3)

    def test_the_model_must_match_the_vehicle_type(self):
        response = self.edit(vehicle_model=get_model("bike").pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("vehicle_model", response.data["errors"])

    def test_no_days_chosen_is_refused(self):
        response = self.edit(office_days=[])
        self.assertEqual(response.data["errors"]["office_days"], ["Choose at least one day."])

    def test_a_ride_from_before_the_model_list_needs_a_model_chosen(self):
        old = car_ride(make_driver("old@acme.com"))  # still points at the old "Sedan" class
        client = client_for(old.driver)
        response = client.patch(url(old), {"toll_total": 5}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("vehicle_model", response.data["errors"])
        self.assertEqual(client.patch(url(old), {"toll_total": 5, "vehicle_model": get_model("car").pk}, format="json").status_code, 200)

    def test_strangers_get_404_and_riders_are_turned_away(self):
        self.assertEqual(client_for(make_driver("other@acme.com")).patch(self.url, {}, format="json").status_code, 404)
        self.assertEqual(client_for(make_user("r@acme.com")).patch(self.url, {}, format="json").status_code, 403)
        self.assertEqual(client_for().patch(self.url, {}, format="json").status_code, 401)

    def test_a_deleted_ride_cannot_be_edited(self):
        self.client.delete(self.url)
        self.assertEqual(self.edit(toll_total=5).status_code, 404)


class BikeEditTests(FreshCache, TestCase):
    def test_bike_seats_stay_one_and_the_helmet_is_required(self):
        ride = bike_ride()
        ride.mileage_rate = get_model("bike")
        ride.save()
        client = client_for(ride.driver)
        response = client.patch(url(ride), {"seats": 3, "toll_total": 10}, format="json")
        self.assertEqual(response.status_code, 200)
        ride.refresh_from_db()
        self.assertEqual((ride.seats, ride.toll_total, ride.has_spare_helmet), (1, 10, True))
        refused = client.patch(url(ride), {"has_spare_helmet": False}, format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("has_spare_helmet", refused.data["errors"])


class QuickFareTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.ride = car_ride()
        self.client = client_for(self.ride.driver)
        self.url = url(self.ride, "fare/")

    def test_accepts_the_whole_range(self):
        for value in (-20, 0, 20):
            response = self.client.post(self.url, {"fare_adjustment": value}, format="json")
            self.assertEqual((response.status_code, response.data["fare_adjustment"]), (200, value))
            self.ride.refresh_from_db()
            self.assertEqual(self.ride.fare_adjustment, value)

    def test_the_answer_has_the_new_fare(self):
        low = self.client.post(self.url, {"fare_adjustment": -20}, format="json").data["fare"]["total"]
        high = self.client.post(self.url, {"fare_adjustment": 20}, format="json").data["fare"]["total"]
        self.assertGreater(high, low)

    def test_refuses_outside_the_range(self):
        for value in (21, -21, "abc", None):
            response = self.client.post(self.url, {"fare_adjustment": value}, format="json")
            self.assertEqual(response.status_code, 400, value)
            self.assertEqual(response.data["code"], "invalid")
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.fare_adjustment, 0)

    def test_needs_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_other_drivers_cannot_change_it(self):
        other = client_for(make_driver("other@acme.com"))
        self.assertEqual(other.post(self.url, {"fare_adjustment": 5}, format="json").status_code, 404)
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.fare_adjustment, 0)

    def test_an_existing_booking_keeps_its_fare(self):
        req = make_request(self.ride, make_user("r@acme.com"), status=S.ACCEPTED, fare=50, fare_adjustment=0)
        self.client.post(self.url, {"fare_adjustment": 20}, format="json")
        req.refresh_from_db()
        self.assertEqual((req.fare, req.fare_adjustment), (50, 0))


class ToggleTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.ride = car_ride()
        self.driver = self.ride.driver
        self.client = client_for(self.driver)
        self.url = url(self.ride, "toggle/")

    def test_switch_off_and_on(self):
        self.assertFalse(self.client.post(self.url).data["is_active"])
        self.ride.refresh_from_db()
        self.assertFalse(self.ride.is_active)
        self.assertTrue(self.client.post(self.url).data["is_active"])
        self.ride.refresh_from_db()
        self.assertTrue(self.ride.is_active)

    def test_needs_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_cannot_switch_someone_elses_ride(self):
        self.assertEqual(client_for(make_driver("other@acme.com")).post(self.url).status_code, 404)
        self.ride.refresh_from_db()
        self.assertTrue(self.ride.is_active)

    def test_cannot_switch_on_without_approved_documents(self):
        self.ride.is_active = False
        self.ride.save()
        response = client_for(withdraw_approval(self.driver)).post(self.url)
        self.assertEqual((response.status_code, response.data["code"]), (403, "driver_not_approved"))
        self.ride.refresh_from_db()
        self.assertFalse(self.ride.is_active)

    def test_can_switch_off_even_without_approved_documents(self):
        response = client_for(withdraw_approval(self.driver)).post(self.url)
        self.assertEqual((response.status_code, response.data["is_active"]), (200, False))

    def test_a_blocked_driver_cannot_switch_on(self):
        self.ride.is_active = False
        self.ride.save()
        self.driver.under_review = True
        self.driver.save()
        response = client_for(self.driver).post(self.url)
        self.assertEqual((response.status_code, response.data["code"]), (403, "account_blocked"))


class DeleteTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.ride = car_ride()
        self.client = client_for(self.ride.driver)
        self.url = url(self.ride)

    def test_delete_cancels_live_bookings_and_hides_the_ride(self):
        live = make_request(self.ride, make_user("a@acme.com"), status=S.ACCEPTED)
        waiting = make_request(self.ride, make_user("b@acme.com"), status=S.PENDING)
        done = make_request(self.ride, make_user("c@acme.com"), status=S.COMPLETED, date=future_monday())
        response = self.client.delete(self.url)
        self.assertEqual((response.status_code, response.data), (200, {"deleted": True, "cancelled_bookings": 2}))
        self.ride.refresh_from_db()
        self.assertTrue(self.ride.is_deleted)
        self.assertFalse(self.ride.is_active)
        for req in (live, waiting):
            req.refresh_from_db()
            self.assertEqual(req.status, S.CANCELLED)
        done.refresh_from_db()
        self.assertEqual(done.status, S.COMPLETED)

    def test_the_row_is_kept_for_history(self):
        self.client.delete(self.url)
        self.assertTrue(Ride.objects.filter(pk=self.ride.pk).exists())

    def test_a_deleted_ride_is_gone_from_search(self):
        from apps.api.tests.ride_helpers import search_params
        from apps.rides.tests.helpers import next_weekday

        self.client.delete(self.url)
        found = client_for(make_user("r@acme.com")).get("/api/v1/rides/search/", search_params(next_weekday(0)))
        self.assertEqual(found.data["count"], 0)

    def test_a_ride_with_no_bookings_says_zero_cancelled(self):
        self.assertEqual(self.client.delete(self.url).data["cancelled_bookings"], 0)

    def test_strangers_get_404_and_riders_are_turned_away(self):
        self.assertEqual(client_for(make_driver("other@acme.com")).delete(self.url).status_code, 404)
        self.assertEqual(client_for(make_user("r@acme.com")).delete(self.url).status_code, 403)
        self.ride.refresh_from_db()
        self.assertIsNone(self.ride.deleted_at)

    def test_deleting_twice_is_404(self):
        self.client.delete(self.url)
        self.assertEqual(self.client.delete(self.url).status_code, 404)


class ReturnRideTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.ride = car_ride()
        self.client = client_for(self.ride.driver)
        self.url = url(self.ride, "return/")

    def test_makes_the_way_back_in_reverse(self):
        response = self.client.post(self.url, {"return_time": "18:00"}, format="json")
        self.assertEqual(response.status_code, 201)
        back = Ride.objects.get(pk=response.data["id"])
        self.assertEqual((back.origin_name, back.destination_name, back.departure_time), ("End", "Start", time(18, 0)))
        self.assertEqual((back.seats, back.office_days, back.mileage_rate), (3, "0,1,2,3,4", self.ride.mileage_rate))
        self.assertEqual(back.route_points[0], self.ride.route_points[-1])

    def test_the_same_way_back_twice_is_refused(self):
        self.client.post(self.url, {"return_time": "18:00"}, format="json")
        response = self.client.post(self.url, {"return_time": "18:00"}, format="json")
        self.assertEqual((response.status_code, response.data["code"]), (409, "return_exists"))
        self.assertEqual(Ride.objects.count(), 2)

    def test_a_missing_or_bad_time_is_refused(self):
        for body in ({}, {"return_time": "late"}):
            response = self.client.post(self.url, body, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("return_time", response.data["errors"])

    def test_someone_elses_ride_is_404(self):
        self.assertEqual(client_for(make_driver("other@acme.com")).post(self.url, {"return_time": "18:00"}, format="json").status_code, 404)

    def test_a_blocked_driver_cannot_add_it(self):
        self.ride.driver.under_review = True
        self.ride.driver.save()
        response = client_for(self.ride.driver).post(self.url, {"return_time": "18:00"}, format="json")
        self.assertEqual(response.data["code"], "account_blocked")


class UnavailableDatesTests(FreshCache, TestCase):
    URL = "/api/v1/unavailable-dates/"

    def setUp(self):
        super().setUp()
        self.driver = make_driver()
        self.client = client_for(self.driver)
        self.tomorrow = timezone.localdate() + timedelta(days=1)

    def add(self, date=None, **extra):
        return self.client.post(self.URL, {"date": (date or self.tomorrow).isoformat(), **extra}, format="json")

    def test_add_a_date(self):
        response = self.add(reason="Service")
        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.data["date"], response.data["reason"]), (self.tomorrow.isoformat(), "Service"))
        self.assertEqual(CarUnavailableDate.objects.get().driver, self.driver)

    def test_the_same_date_twice_is_kept_once(self):
        self.add()
        again = self.add()
        self.assertEqual(again.status_code, 200)
        self.assertEqual(CarUnavailableDate.objects.count(), 1)

    def test_a_past_date_is_refused(self):
        response = self.add(timezone.localdate() - timedelta(days=1))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"]["date"], ["Choose today or a future date."])

    def test_a_missing_date_is_refused(self):
        self.assertEqual(self.client.post(self.URL, {}, format="json").status_code, 400)

    def test_the_list_shows_only_my_coming_dates_in_order(self):
        self.add(self.tomorrow + timedelta(days=3))
        self.add()
        CarUnavailableDate.objects.create(driver=self.driver, date=timezone.localdate() - timedelta(days=2))
        CarUnavailableDate.objects.create(driver=make_driver("other@acme.com"), date=self.tomorrow)
        dates = [d["date"] for d in self.client.get(self.URL).data["dates"]]
        self.assertEqual(dates, [self.tomorrow.isoformat(), (self.tomorrow + timedelta(days=3)).isoformat()])

    def test_remove_a_date(self):
        entry_id = self.add().data["id"]
        response = self.client.delete(f"{self.URL}{entry_id}/")
        self.assertEqual((response.status_code, response.data), (200, {"deleted": True}))
        self.assertFalse(CarUnavailableDate.objects.exists())

    def test_cannot_remove_someone_elses_date(self):
        entry = CarUnavailableDate.objects.create(driver=make_driver("other@acme.com"), date=self.tomorrow)
        self.assertEqual(self.client.delete(f"{self.URL}{entry.pk}/").status_code, 404)
        self.assertTrue(CarUnavailableDate.objects.filter(pk=entry.pk).exists())

    def test_a_rider_cannot_use_it(self):
        self.assertEqual(client_for(make_user("r@acme.com")).get(self.URL).status_code, 403)