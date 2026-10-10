from datetime import time, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.rides import maps
from apps.rides.models import CarUnavailableDate, Ride

from .helpers import make_driver, make_ride, make_user, next_weekday, point_along

KR_PURAM = ("KR Puram", 13.0076, 77.6954)
BELLANDUR = ("Bellandur", 12.9260, 77.6760)


def offer_payload(**overrides):
    data = {
        "origin_name": KR_PURAM[0], "origin_lat": KR_PURAM[1], "origin_lng": KR_PURAM[2],
        "destination_name": BELLANDUR[0], "destination_lat": BELLANDUR[1], "destination_lng": BELLANDUR[2],
        "departure_time": "08:30", "office_days": ["0", "1", "2", "3", "4"],
        "seats": "3", "car_model": "Hyundai i20",
    }
    data.update(overrides)
    return data


class AccessTests(TestCase):
    def test_anonymous_users_go_to_login(self):
        for name in ("rides:offer", "rides:mine", "rides:find", "rides:unavailable", "rides:places_search"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("accounts:login"), response["Location"], name)

    def test_unverified_email_goes_to_verify(self):
        self.client.force_login(make_user(verified=False))
        for name in ("rides:offer", "rides:mine", "rides:find", "rides:places_search"):
            self.assertRedirects(self.client.get(reverse(name)), reverse("accounts:verify"), fetch_redirect_response=False)

    def test_rider_without_documents_cannot_offer_rides(self):
        self.client.force_login(make_user())
        self.assertRedirects(self.client.get(reverse("rides:offer")), reverse("accounts:documents"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("rides:unavailable")), reverse("accounts:documents"), fetch_redirect_response=False)

    def test_driver_with_pending_documents_cannot_offer_rides(self):
        self.client.force_login(make_driver(approved=False))
        self.assertRedirects(self.client.get(reverse("rides:offer")), reverse("accounts:documents"), fetch_redirect_response=False)

    def test_rider_can_open_search_and_my_rides(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(reverse("rides:find")).status_code, 200)
        self.assertEqual(self.client.get(reverse("rides:mine")).status_code, 200)


class OfferRideTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.client.force_login(self.driver)
        self.url = reverse("rides:offer")

    def test_page_loads_with_the_place_picker(self):
        response = self.client.get(self.url)
        self.assertContains(response, "data-place-picker")
        self.assertContains(response, "place_picker.js")

    def test_valid_offer_saves_a_ride_with_its_route(self):
        response = self.client.post(self.url, offer_payload())
        self.assertRedirects(response, reverse("rides:mine"))
        ride = Ride.objects.get()
        self.assertEqual(ride.driver, self.driver)
        self.assertEqual(ride.origin_name, "KR Puram")
        self.assertEqual(ride.office_days, "0,1,2,3,4")
        self.assertEqual(ride.departure_time, time(8, 30))
        self.assertEqual(ride.seats, 3)
        self.assertGreater(len(ride.route_points), 10)
        self.assertGreater(ride.route_distance_m, 5000)
        self.assertLessEqual(ride.min_lat, ride.max_lat)
        self.assertTrue(ride.is_active)

    def test_offer_with_the_way_back_creates_two_rides(self):
        self.client.post(self.url, offer_payload(offer_return="on", return_time="18:00"))
        out, back = Ride.objects.order_by("departure_time")
        self.assertEqual((out.origin_name, out.destination_name, out.departure_time), ("KR Puram", "Bellandur", time(8, 30)))
        self.assertEqual((back.origin_name, back.destination_name, back.departure_time), ("Bellandur", "KR Puram", time(18, 0)))
        self.assertEqual(back.route_points[0], out.route_points[-1])
        self.assertEqual(back.route_distance_m, out.route_distance_m)

    def test_way_back_needs_a_time(self):
        response = self.client.post(self.url, offer_payload(offer_return="on"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter the time for the way back")
        self.assertFalse(Ride.objects.exists())

    def test_place_must_be_picked_from_suggestions(self):
        response = self.client.post(self.url, offer_payload(origin_lat="", origin_lng="", origin_name=""))
        self.assertContains(response, "Pick the start place from the suggestions")
        self.assertFalse(Ride.objects.exists())

    def test_place_outside_bangalore_is_refused(self):
        response = self.client.post(self.url, offer_payload(destination_lat="13.0827", destination_lng="80.2707"))
        self.assertContains(response, "works inside Bangalore only")
        self.assertFalse(Ride.objects.exists())

    def test_start_and_end_too_close(self):
        response = self.client.post(self.url, offer_payload(
            destination_lat=KR_PURAM[1] + 0.001, destination_lng=KR_PURAM[2]))
        self.assertContains(response, "too close")
        self.assertFalse(Ride.objects.exists())

    def test_at_least_one_day_is_required(self):
        data = offer_payload()
        del data["office_days"]
        response = self.client.post(self.url, data)
        self.assertContains(response, "Choose at least one day")

    def test_seats_must_be_between_1_and_6(self):
        for seats in ("0", "7"):
            response = self.client.post(self.url, offer_payload(seats=seats))
            self.assertEqual(response.status_code, 200)
        self.assertFalse(Ride.objects.exists())

    def test_maps_failure_shows_a_message_and_saves_nothing(self):
        with mock.patch.object(maps, "get_route", side_effect=maps.MapsError("Maps are down.")):
            response = self.client.post(self.url, offer_payload())
        self.assertContains(response, "Maps are down.")
        self.assertFalse(Ride.objects.exists())


class MyRidesTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.ride = make_ride(self.driver)
        self.client.force_login(self.driver)

    def test_lists_only_my_rides(self):
        make_ride(make_driver("other@acme.com"), origin_name="Someone else's start")
        response = self.client.get(reverse("rides:mine"))
        self.assertContains(response, "Start")
        self.assertNotContains(response, "Someone else")

    def test_switch_off_and_on(self):
        url = reverse("rides:toggle", args=[self.ride.pk])
        self.client.post(url)
        self.ride.refresh_from_db()
        self.assertFalse(self.ride.is_active)
        self.client.post(url)
        self.ride.refresh_from_db()
        self.assertTrue(self.ride.is_active)

    def test_toggle_needs_post(self):
        self.assertEqual(self.client.get(reverse("rides:toggle", args=[self.ride.pk])).status_code, 405)

    def test_cannot_toggle_someone_elses_ride(self):
        self.client.force_login(make_user("rider@acme.com"))
        self.assertEqual(self.client.post(reverse("rides:toggle", args=[self.ride.pk])).status_code, 404)
        self.ride.refresh_from_db()
        self.assertTrue(self.ride.is_active)

    def test_cannot_switch_on_without_approved_documents(self):
        self.ride.is_active = False
        self.ride.save()
        self.driver.driver_document.status = "pending"
        self.driver.driver_document.save()
        self.client.post(reverse("rides:toggle", args=[self.ride.pk]))
        self.ride.refresh_from_db()
        self.assertFalse(self.ride.is_active)


class RideDetailTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.ride = make_ride(self.driver)
        self.rider = make_user("rider@acme.com")

    def test_rider_sees_details_without_the_drivers_contact_details(self):
        self.client.force_login(self.rider)
        response = self.client.get(reverse("rides:detail", args=[self.ride.pk]))
        self.assertContains(response, "Maruti Swift")
        self.assertContains(response, "Ravi K.")
        self.assertNotContains(response, "driver@acme.com")

    def test_switched_off_ride_is_hidden_from_riders(self):
        self.ride.is_active = False
        self.ride.save()
        self.client.force_login(self.rider)
        self.assertRedirects(self.client.get(reverse("rides:detail", args=[self.ride.pk])), reverse("rides:find"), fetch_redirect_response=False)

    def test_owner_still_sees_a_switched_off_ride(self):
        self.ride.is_active = False
        self.ride.save()
        self.client.force_login(self.driver)
        self.assertEqual(self.client.get(reverse("rides:detail", args=[self.ride.pk])).status_code, 200)


class FindRideTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.ride = make_ride(self.driver)
        self.rider = make_user("rider@acme.com")
        self.client.force_login(self.rider)
        self.url = reverse("rides:find")
        self.monday = next_weekday(0)

    def params(self, **overrides):
        pickup, drop = point_along(0.2, 300), point_along(0.8, -200)
        data = {
            "pickup_name": "Near start", "pickup_lat": pickup[0], "pickup_lng": pickup[1],
            "drop_name": "Near end", "drop_lat": drop[0], "drop_lng": drop[1],
            "date": self.monday.isoformat(), "time": "09:05",
        }
        data.update(overrides)
        return data

    def test_empty_search_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["matches"])

    def test_search_finds_the_ride(self):
        response = self.client.get(self.url, self.params())
        self.assertContains(response, "1 ride found")
        self.assertContains(response, "Maruti Swift")
        self.assertContains(response, "5 min from your time")

    def test_search_with_no_match_explains_why(self):
        response = self.client.get(self.url, self.params(time="14:00"))
        self.assertContains(response, "No rides match yet")

    def test_place_must_be_picked(self):
        response = self.client.get(self.url, self.params(pickup_lat="", pickup_lng="", pickup_name=""))
        self.assertContains(response, "Pick the pickup place from the suggestions")
        self.assertIsNone(response.context["matches"])

    def test_past_date_is_refused(self):
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        response = self.client.get(self.url, self.params(date=yesterday))
        self.assertContains(response, "today or a future date")

    def test_own_ride_is_not_shown_to_its_driver(self):
        self.client.force_login(self.driver)
        response = self.client.get(self.url, self.params())
        self.assertContains(response, "No rides match yet")


class UnavailableDatesTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.client.force_login(self.driver)
        self.url = reverse("rides:unavailable")
        self.tomorrow = timezone.localdate() + timedelta(days=1)

    def test_add_a_date(self):
        response = self.client.post(self.url, {"date": self.tomorrow.isoformat(), "reason": "Service"})
        self.assertRedirects(response, self.url)
        item = CarUnavailableDate.objects.get()
        self.assertEqual((item.driver, item.date, item.reason), (self.driver, self.tomorrow, "Service"))
        self.assertContains(self.client.get(self.url), "Service")

    def test_same_date_twice_is_kept_once(self):
        for _ in range(2):
            self.client.post(self.url, {"date": self.tomorrow.isoformat()})
        self.assertEqual(CarUnavailableDate.objects.count(), 1)

    def test_past_date_is_refused(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        response = self.client.post(self.url, {"date": yesterday.isoformat()})
        self.assertContains(response, "today or a future date")
        self.assertFalse(CarUnavailableDate.objects.exists())

    def test_remove_a_date(self):
        item = CarUnavailableDate.objects.create(driver=self.driver, date=self.tomorrow)
        self.client.post(reverse("rides:unavailable_delete", args=[item.pk]))
        self.assertFalse(CarUnavailableDate.objects.exists())

    def test_cannot_remove_someone_elses_date(self):
        other = make_driver("other@acme.com")
        item = CarUnavailableDate.objects.create(driver=other, date=self.tomorrow)
        self.assertEqual(self.client.post(reverse("rides:unavailable_delete", args=[item.pk])).status_code, 404)
        self.assertTrue(CarUnavailableDate.objects.exists())


class PlaceSearchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.force_login(make_user())
        self.url = reverse("rides:places_search")

    def test_returns_places_as_json(self):
        data = self.client.get(self.url, {"q": "bellan"}).json()
        self.assertEqual([r["name"] for r in data["results"]], ["Bellandur"])
        self.assertEqual(set(data["results"][0]), {"name", "address", "lat", "lng"})

    def test_short_query_returns_nothing(self):
        self.assertEqual(self.client.get(self.url, {"q": "be"}).json(), {"results": []})

    @override_settings(PLACE_SEARCH_PER_MINUTE=3)
    def test_rate_limit(self):
        for _ in range(3):
            self.assertEqual(self.client.get(self.url, {"q": "bellan"}).status_code, 200)
        response = self.client.get(self.url, {"q": "bellan"})
        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many", response.json()["error"])

    def test_maps_failure_is_a_clean_error(self):
        with mock.patch.object(maps, "search_places", side_effect=maps.MapsError("Maps are down.")):
            response = self.client.get(self.url, {"q": "bellan"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "Maps are down.")

    def test_post_is_not_allowed(self):
        self.assertEqual(self.client.post(self.url, {"q": "bellan"}).status_code, 405)


class ModelTests(TestCase):
    def test_office_days_display_and_runs_on(self):
        ride = make_ride(make_driver(), days="0,2,4")
        self.assertEqual(ride.office_days_display, "Mon, Wed, Fri")
        self.assertTrue(ride.runs_on(next_weekday(2)))
        self.assertFalse(ride.runs_on(next_weekday(1)))

    def test_seats_constraint(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            make_ride(make_driver(), seats=9)