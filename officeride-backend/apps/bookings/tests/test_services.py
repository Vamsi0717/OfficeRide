from datetime import datetime, timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.bookings import services
from apps.bookings.models import RideRequest
from apps.fares import services as fare_services
from apps.fares.models import FareSettings
from apps.rides.models import CarUnavailableDate
from apps.rides.tests.helpers import get_rate, make_driver, make_ride, make_user, next_weekday

from .helpers import bike_ride, car_ride, drop, future_monday, make_request, pickup

S = RideRequest.Status


def at(date, hour, minute=0):
    return timezone.make_aware(datetime.combine(date, datetime.min.time().replace(hour=hour, minute=minute)))


class RequestSeatTests(TestCase):
    def setUp(self):
        self.ride = car_ride()
        self.rider = make_user("rider@acme.com")
        self.day = future_monday()

    def request(self, rider=None, ride=None, date=None, **places):
        return services.request_seat(
            rider or self.rider, (ride or self.ride).pk, date or self.day,
            places.get("pickup", pickup()), places.get("drop", drop()),
        )

    def test_a_request_is_saved_as_pending_with_the_fare_for_the_riders_own_distance(self):
        req = self.request()
        self.assertEqual(req.status, S.PENDING)
        expected = fare_services.fare_for(self.ride, req.rider_distance_m)
        self.assertEqual((req.fare, req.standard_fare, req.fare_adjustment), (expected.total, expected.base_total, 0))
        self.assertLess(req.fare, fare_services.full_route_fare(self.ride).total)  # a shorter trip costs less
        self.assertEqual((req.pickup_name, req.drop_name), ("Pickup spot", "Drop spot"))

    def test_the_drivers_adjustment_is_part_of_the_saved_fare(self):
        ride = car_ride(make_driver("d2@acme.com"), fare_adjustment=20)
        req = self.request(ride=ride)
        self.assertEqual(req.fare, req.standard_fare + 20)
        self.assertEqual(req.fare_adjustment, 20)

    def test_a_two_wheeler_ride_can_be_requested(self):
        ride = bike_ride()
        req = self.request(ride=ride)
        self.assertGreater(req.fare, 0)

    def test_the_fare_does_not_change_when_the_fuel_price_or_the_adjustment_changes(self):
        req = self.request()
        before = req.fare
        settings_row = FareSettings.get_solo()
        settings_row.fuel_price_per_litre = 150
        settings_row.save()
        self.ride.fare_adjustment = 20
        self.ride.save()
        req.refresh_from_db()
        self.assertEqual(req.fare, before)
        self.assertGreater(fare_services.fare_for(self.ride, req.rider_distance_m).total, before)  # a new request would cost more

    def test_you_cannot_request_your_own_ride(self):
        with self.assertRaisesMessage(services.BookingError, "your own ride"):
            self.request(rider=self.ride.driver)

    def test_a_second_request_for_the_same_ride_and_day_is_refused(self):
        self.request()
        with self.assertRaisesMessage(services.BookingError, "already have a request"):
            self.request()

    def test_you_can_request_again_after_cancelling(self):
        first = self.request()
        services.cancel(first.pk, self.rider)
        self.assertEqual(self.request().status, S.PENDING)

    def test_the_database_allows_only_one_live_request_per_rider_ride_day(self):
        from django.db import IntegrityError, transaction
        make_request(self.ride, self.rider, self.day)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_request(self.ride, self.rider, self.day)

    def test_two_rides_around_the_same_time_on_one_day_are_refused(self):
        other = car_ride(make_driver("d3@acme.com"), departure=self.ride.departure_time.replace(minute=30))
        self.request()
        with self.assertRaisesMessage(services.BookingError, "around that time"):
            self.request(ride=other)

    def test_two_rides_far_apart_on_one_day_are_allowed(self):
        evening = car_ride(make_driver("d4@acme.com"), departure=self.ride.departure_time.replace(hour=18))
        self.request()
        self.assertEqual(self.request(ride=evening).status, S.PENDING)

    def test_a_ride_that_does_not_pass_the_riders_places_is_refused(self):
        with self.assertRaisesMessage(services.BookingError, "not on this ride's route"):
            self.request(pickup=drop(), drop=pickup())  # wrong direction

    def test_a_ride_that_does_not_run_on_that_day_is_refused(self):
        with self.assertRaisesMessage(services.BookingError, "does not run"):
            self.request(date=self.day + timedelta(days=5))  # a Saturday

    def test_a_day_the_car_is_unavailable_is_refused(self):
        CarUnavailableDate.objects.create(driver=self.ride.driver, date=self.day)
        with self.assertRaisesMessage(services.BookingError, "not available on that day"):
            self.request()

    def test_the_past_and_the_far_future_are_refused(self):
        with self.assertRaises(services.BookingError):
            self.request(date=timezone.localdate() - timedelta(days=1))
        with self.assertRaises(services.BookingError):
            self.request(date=timezone.localdate() + timedelta(days=90))

    def test_a_ride_that_has_already_left_today_is_refused(self):
        monday = next_weekday(0)
        with mock.patch("django.utils.timezone.now", return_value=at(monday, 9, 30)):
            with self.assertRaisesMessage(services.BookingError, "already left"):
                self.request(date=monday)

    def test_a_switched_off_ride_is_refused(self):
        self.ride.is_active = False
        self.ride.save()
        with self.assertRaisesMessage(services.BookingError, "not available"):
            self.request()

    def test_a_driver_whose_documents_are_no_longer_valid_is_refused(self):
        doc = self.ride.driver.driver_document
        doc.status = "pending"
        doc.save()
        with self.assertRaisesMessage(services.BookingError, "not available"):
            self.request()

    def test_a_ride_without_a_vehicle_class_has_no_fare_and_is_refused(self):
        ride = make_ride(make_driver("old@acme.com"))
        with self.assertRaisesMessage(services.BookingError, "fare is not available"):
            self.request(ride=ride)

    def test_a_ride_that_does_not_exist_is_refused(self):
        with self.assertRaisesMessage(services.BookingError, "does not exist"):
            services.request_seat(self.rider, 99999, self.day, pickup(), drop())


class SeatTests(TestCase):
    def setUp(self):
        self.ride = car_ride(seats=2)
        self.day = future_monday()
        self.riders = [make_user(f"r{i}@acme.com") for i in range(3)]

    def test_pending_requests_do_not_hold_seats_only_accepted_ones_do(self):
        for rider in self.riders:
            make_request(self.ride, rider, self.day)
        self.assertEqual(services.seats_left(self.ride, self.day), 2)

    def test_seats_left_counts_accepted_requests_on_that_date_only(self):
        a = make_request(self.ride, self.riders[0], self.day)
        services.accept(a.pk, self.ride.driver)
        self.assertEqual(services.seats_left(self.ride, self.day), 1)
        self.assertEqual(services.seats_left(self.ride, self.day + timedelta(days=7)), 2)

    def test_the_driver_cannot_accept_more_requests_than_seats(self):
        requests = [make_request(self.ride, rider, self.day) for rider in self.riders]
        services.accept(requests[0].pk, self.ride.driver)
        services.accept(requests[1].pk, self.ride.driver)
        with self.assertRaisesMessage(services.BookingError, "No seat is left"):
            services.accept(requests[2].pk, self.ride.driver)
        requests[2].refresh_from_db()
        self.assertEqual(requests[2].status, S.PENDING)

    def test_a_cancelled_seat_can_be_taken_by_someone_else(self):
        requests = [make_request(self.ride, rider, self.day) for rider in self.riders]
        services.accept(requests[0].pk, self.ride.driver)
        services.accept(requests[1].pk, self.ride.driver)
        services.cancel(requests[0].pk, self.riders[0])
        services.accept(requests[2].pk, self.ride.driver)
        self.assertEqual(services.seats_left(self.ride, self.day), 0)

    def test_a_full_ride_refuses_new_requests(self):
        ride = car_ride(make_driver("full@acme.com"), seats=1)
        first = make_request(ride, self.riders[0], self.day)
        services.accept(first.pk, ride.driver)
        with self.assertRaisesMessage(services.BookingError, "full"):
            services.request_seat(self.riders[1], ride.pk, self.day, pickup(), drop())

    def test_a_two_wheeler_ride_is_full_after_one_accepted_booking(self):
        ride = bike_ride()
        a = make_request(ride, self.riders[0], self.day)
        b = make_request(ride, self.riders[1], self.day)
        services.accept(a.pk, ride.driver)
        self.assertEqual(services.seats_left(ride, self.day), 0)
        with self.assertRaisesMessage(services.BookingError, "No seat is left"):
            services.accept(b.pk, ride.driver)


class StatusRuleTests(TestCase):
    def setUp(self):
        self.ride = car_ride()
        self.driver = self.ride.driver
        self.rider = make_user("rider@acme.com")
        self.other = make_user("other@acme.com")
        self.day = future_monday()
        self.departure = at(self.day, 9)

    def test_the_owner_accepts_and_rejects(self):
        a = make_request(self.ride, self.rider, self.day)
        self.assertEqual(services.accept(a.pk, self.driver).status, S.ACCEPTED)
        b = make_request(self.ride, make_user("b@acme.com"), self.day)
        self.assertEqual(services.reject(b.pk, self.driver).status, S.REJECTED)

    def test_only_the_owner_can_accept_or_reject(self):
        a = make_request(self.ride, self.rider, self.day)
        for who in (self.rider, self.other):
            with self.subTest(who=who.email):
                with self.assertRaisesMessage(services.BookingError, "Only the driver"):
                    services.accept(a.pk, who)
                with self.assertRaisesMessage(services.BookingError, "Only the driver"):
                    services.reject(a.pk, who)

    def test_only_the_two_people_involved_can_cancel(self):
        a = make_request(self.ride, self.rider, self.day)
        with self.assertRaisesMessage(services.BookingError, "not yours"):
            services.cancel(a.pk, self.other)
        self.assertEqual(services.cancel(a.pk, self.rider).status, S.CANCELLED)
        b = make_request(self.ride, self.rider, self.day)
        self.assertEqual(services.cancel(b.pk, self.driver).status, S.CANCELLED)

    def test_invalid_transitions_are_refused_with_a_clear_message(self):
        a = make_request(self.ride, self.rider, self.day, status=S.REJECTED)
        for action in (services.accept, services.reject, services.cancel):
            with self.subTest(action=action.__name__):
                with self.assertRaisesMessage(services.BookingError, "rejected cannot be changed"):
                    action(a.pk, self.driver)

    def test_the_allowed_transitions_are_in_one_table(self):
        self.assertTrue(services.can_transition(S.PENDING, S.ACCEPTED))
        self.assertTrue(services.can_transition(S.ACCEPTED, S.COMPLETED))
        self.assertFalse(services.can_transition(S.PENDING, S.COMPLETED))
        self.assertFalse(services.can_transition(S.COMPLETED, S.CANCELLED))
        self.assertFalse(services.can_transition(S.NO_SHOW, S.ACCEPTED))

    def test_cancelling_an_accepted_ride_under_an_hour_before_departure_is_a_late_cancel(self):
        a = make_request(self.ride, self.rider, self.day, status=S.ACCEPTED)
        with mock.patch("django.utils.timezone.now", return_value=self.departure - timedelta(minutes=30)):
            req = services.cancel(a.pk, self.rider)
        self.assertTrue(req.late_cancel)
        self.assertEqual(req.cancelled_by, self.rider)

    def test_cancelling_more_than_an_hour_before_departure_is_not_late(self):
        a = make_request(self.ride, self.rider, self.day, status=S.ACCEPTED)
        with mock.patch("django.utils.timezone.now", return_value=self.departure - timedelta(minutes=90)):
            self.assertFalse(services.cancel(a.pk, self.rider).late_cancel)

    def test_cancelling_a_pending_request_is_never_late(self):
        a = make_request(self.ride, self.rider, self.day)
        with mock.patch("django.utils.timezone.now", return_value=self.departure - timedelta(minutes=10)):
            self.assertFalse(services.cancel(a.pk, self.rider).late_cancel)

    def test_a_ride_that_has_left_cannot_be_cancelled(self):
        a = make_request(self.ride, self.rider, self.day, status=S.ACCEPTED)
        with mock.patch("django.utils.timezone.now", return_value=self.departure + timedelta(minutes=5)):
            with self.assertRaisesMessage(services.BookingError, "already left"):
                services.cancel(a.pk, self.rider)

    def test_complete_only_after_departure_and_only_by_the_owner(self):
        a = make_request(self.ride, self.rider, self.day, status=S.ACCEPTED)
        with self.assertRaisesMessage(services.BookingError, "only after it has left"):
            services.complete(a.pk, self.driver)
        with mock.patch("django.utils.timezone.now", return_value=self.departure + timedelta(hours=1)):
            with self.assertRaisesMessage(services.BookingError, "Only the driver"):
                services.complete(a.pk, self.rider)
            self.assertEqual(services.complete(a.pk, self.driver).status, S.COMPLETED)

    def test_either_side_can_report_a_no_show_after_departure(self):
        with mock.patch("django.utils.timezone.now", return_value=self.departure + timedelta(minutes=20)):
            a = make_request(self.ride, self.rider, self.day, status=S.ACCEPTED)
            req = services.report_no_show(a.pk, self.rider)
            self.assertEqual((req.status, req.reported_by), (S.NO_SHOW, self.rider))
            b = make_request(self.ride, make_user("c@acme.com"), self.day, status=S.ACCEPTED)
            self.assertEqual(services.report_no_show(b.pk, self.driver).status, S.NO_SHOW)
            c = make_request(self.ride, make_user("d@acme.com"), self.day, status=S.ACCEPTED)
            with self.assertRaisesMessage(services.BookingError, "not yours"):
                services.report_no_show(c.pk, self.other)

    def test_a_no_show_cannot_be_reported_before_departure(self):
        a = make_request(self.ride, self.rider, self.day, status=S.ACCEPTED)
        with self.assertRaisesMessage(services.BookingError, "after the ride has left"):
            services.report_no_show(a.pk, self.rider)

    def test_a_ride_that_has_left_cannot_be_accepted(self):
        a = make_request(self.ride, self.rider, self.day)
        with mock.patch("django.utils.timezone.now", return_value=self.departure + timedelta(minutes=5)):
            with self.assertRaisesMessage(services.BookingError, "already left"):
                services.accept(a.pk, self.driver)

    def test_allowed_actions_follow_the_same_rules(self):
        a = make_request(self.ride, self.rider, self.day)
        self.assertEqual(services.allowed_actions(a, self.driver), ["accept", "reject", "cancel"])
        self.assertEqual(services.allowed_actions(a, self.rider), ["cancel"])
        self.assertEqual(services.allowed_actions(a, self.other), [])
        a.status = S.ACCEPTED
        self.assertEqual(services.allowed_actions(a, self.rider), ["cancel"])
        with mock.patch("django.utils.timezone.now", return_value=self.departure + timedelta(hours=1)):
            self.assertEqual(services.allowed_actions(a, self.driver), ["complete", "no-show"])
            self.assertEqual(services.allowed_actions(a, self.rider), ["no-show"])
        a.status = S.COMPLETED
        self.assertEqual(services.allowed_actions(a, self.driver), [])