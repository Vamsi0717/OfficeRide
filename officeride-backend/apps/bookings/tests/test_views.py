from datetime import timedelta

from django.test import TestCase
from django.urls import reverse

from apps.bookings import services
from apps.bookings.models import RideRequest
from apps.rides.tests.helpers import make_driver, make_user, point_along

from .helpers import bike_ride, car_ride, future_monday, make_request

S = RideRequest.Status


def request_payload(**overrides):
    a, b = point_along(0.1), point_along(0.9)
    data = {
        "date": future_monday().isoformat(),
        "pickup_name": "Pickup spot", "pickup_lat": a[0], "pickup_lng": a[1],
        "drop_name": "Drop spot", "drop_lat": b[0], "drop_lng": b[1],
    }
    data.update(overrides)
    return data


class AccessTests(TestCase):
    def test_anonymous_users_go_to_login(self):
        ride = car_ride()
        req = make_request(ride, make_user("r@acme.com"))
        for url in (reverse("bookings:trips"), reverse("bookings:request_seat", args=[ride.pk]),
                    reverse("bookings:act", args=[req.pk, "accept"])):
            self.assertEqual(self.client.get(url).status_code, 302)
            self.assertIn("/accounts/login/", self.client.get(url)["Location"])

    def test_actions_need_a_post(self):
        ride = car_ride()
        req = make_request(ride, make_user("r@acme.com"))
        self.client.force_login(ride.driver)
        self.assertEqual(self.client.get(reverse("bookings:act", args=[req.pk, "accept"])).status_code, 405)

    def test_unverified_email_is_sent_to_verify(self):
        self.client.force_login(make_user("u@acme.com", verified=False))
        self.assertRedirects(self.client.get(reverse("bookings:trips")), reverse("accounts:verify"))


class RequestSeatViewTests(TestCase):
    def setUp(self):
        self.ride = car_ride()
        self.rider = make_user("rider@acme.com")
        self.url = reverse("bookings:request_seat", args=[self.ride.pk])
        self.client.force_login(self.rider)

    def test_posting_a_request_saves_it_and_shows_the_trips_page(self):
        response = self.client.post(self.url, request_payload(), follow=True)
        self.assertRedirects(response, reverse("bookings:trips"))
        req = RideRequest.objects.get()
        self.assertEqual((req.rider, req.ride, req.status), (self.rider, self.ride, S.PENDING))
        self.assertContains(response, "Request sent")
        self.assertContains(response, "Waiting for the driver")
        self.assertContains(response, f"&#8377;{req.fare}")

    def test_a_refused_request_shows_the_reason_and_saves_nothing(self):
        self.client.post(self.url, request_payload())
        response = self.client.post(self.url, request_payload(), follow=True)
        self.assertContains(response, "already have a request")
        self.assertEqual(RideRequest.objects.count(), 1)

    def test_a_request_without_places_is_refused(self):
        response = self.client.post(self.url, request_payload(pickup_name="", pickup_lat="", pickup_lng=""), follow=True)
        self.assertContains(response, "Pick the pickup place")
        self.assertFalse(RideRequest.objects.exists())

    def test_the_request_button_needs_a_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_your_own_ride_cannot_be_requested(self):
        self.client.force_login(self.ride.driver)
        response = self.client.post(self.url, request_payload(), follow=True)
        self.assertContains(response, "your own ride")


class SearchTests(TestCase):
    def setUp(self):
        self.rider = make_user("rider@acme.com")
        self.client.force_login(self.rider)
        self.day = future_monday()

    def search(self):
        a, b = point_along(0.1), point_along(0.9)
        return self.client.get(reverse("rides:find"), {
            "pickup_name": "A", "pickup_lat": a[0], "pickup_lng": a[1],
            "drop_name": "B", "drop_lat": b[0], "drop_lng": b[1],
            "date": self.day.isoformat(), "time": "09:00",
        })

    def test_each_result_has_a_request_button_that_sends_the_search(self):
        ride = car_ride()
        response = self.search()
        self.assertContains(response, "Request a seat")
        self.assertContains(response, reverse("bookings:request_seat", args=[ride.pk]))
        self.assertContains(response, f'name="date" value="{self.day.isoformat()}"')

    def test_a_full_ride_is_hidden_from_search(self):
        ride = car_ride(seats=1)
        first = make_request(ride, make_user("first@acme.com"), self.day)
        self.assertEqual(len(self.search().context["matches"]), 1)
        services.accept(first.pk, ride.driver)
        self.assertEqual(self.search().context["matches"], [])

    def test_a_ride_with_a_seat_left_is_still_shown(self):
        ride = car_ride(seats=2)
        first = make_request(ride, make_user("first@acme.com"), self.day)
        services.accept(first.pk, ride.driver)
        self.assertEqual(len(self.search().context["matches"]), 1)

    def test_a_ride_full_on_one_date_still_shows_on_another(self):
        ride = car_ride(seats=1)
        services.accept(make_request(ride, make_user("first@acme.com"), self.day).pk, ride.driver)
        self.day = self.day + timedelta(days=7)
        self.assertEqual(len(self.search().context["matches"]), 1)

    def test_a_two_wheeler_ride_is_full_after_one_accepted_booking(self):
        ride = bike_ride()
        services.accept(make_request(ride, make_user("first@acme.com"), self.day).pk, ride.driver)
        self.assertEqual(self.search().context["matches"], [])

    def test_a_cancelled_booking_puts_the_ride_back_in_search(self):
        ride = car_ride(seats=1)
        first = make_request(ride, make_user("first@acme.com"), self.day)
        services.accept(first.pk, ride.driver)
        services.cancel(first.pk, ride.driver)
        self.assertEqual(len(self.search().context["matches"]), 1)


class TripsPageTests(TestCase):
    def setUp(self):
        self.ride = car_ride()
        self.driver = self.ride.driver
        self.rider = make_user("rider@acme.com")
        self.other = make_user("other@acme.com")
        self.req = make_request(self.ride, self.rider)

    def test_the_rider_sees_the_request_with_cancel_only(self):
        self.client.force_login(self.rider)
        response = self.client.get(reverse("bookings:trips"))
        self.assertContains(response, "Rides I requested")
        self.assertContains(response, "Waiting for the driver")
        self.assertContains(response, reverse("bookings:act", args=[self.req.pk, "cancel"]))
        self.assertNotContains(response, reverse("bookings:act", args=[self.req.pk, "accept"]))

    def test_the_driver_sees_it_under_requests_for_my_rides_with_accept_and_reject(self):
        self.client.force_login(self.driver)
        response = self.client.get(reverse("bookings:trips"))
        for action in ("accept", "reject", "cancel"):
            self.assertContains(response, reverse("bookings:act", args=[self.req.pk, action]))
        self.assertContains(response, "Pickup spot")

    def test_someone_else_sees_nothing(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("bookings:trips"))
        self.assertNotContains(response, "Pickup spot")

    def test_the_fare_and_the_drivers_adjustment_are_shown(self):
        self.req.fare_adjustment, self.req.standard_fare, self.req.fare = 20, 50, 70
        self.req.save()
        self.client.force_login(self.rider)
        response = self.client.get(reverse("bookings:trips"))
        self.assertContains(response, "&#8377;70")
        self.assertContains(response, "standard &#8377;50")


class ActionViewTests(TestCase):
    def setUp(self):
        self.ride = car_ride()
        self.driver = self.ride.driver
        self.rider = make_user("rider@acme.com")
        self.other = make_user("other@acme.com")
        self.req = make_request(self.ride, self.rider)

    def act(self, user, action):
        self.client.force_login(user)
        return self.client.post(reverse("bookings:act", args=[self.req.pk, action]), follow=True)

    def test_the_driver_accepts(self):
        response = self.act(self.driver, "accept")
        self.assertContains(response, "Request accepted")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, S.ACCEPTED)

    def test_the_driver_rejects(self):
        self.act(self.driver, "reject")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, S.REJECTED)

    def test_the_rider_cancels(self):
        self.act(self.rider, "cancel")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, S.CANCELLED)

    def test_the_rider_cannot_accept_their_own_request(self):
        response = self.act(self.rider, "accept")
        self.assertContains(response, "Only the driver")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, S.PENDING)

    def test_a_stranger_gets_a_404_and_changes_nothing(self):
        self.client.force_login(self.other)
        for action in ("accept", "reject", "cancel", "complete", "no-show"):
            response = self.client.post(reverse("bookings:act", args=[self.req.pk, action]))
            self.assertEqual(response.status_code, 404, action)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, S.PENDING)

    def test_an_unknown_action_is_a_404(self):
        self.client.force_login(self.driver)
        self.assertEqual(self.client.post(reverse("bookings:act", args=[self.req.pk, "delete"])).status_code, 404)

    def test_an_invalid_move_shows_the_message(self):
        self.act(self.driver, "reject")
        response = self.act(self.driver, "accept")
        self.assertContains(response, "cannot be changed")