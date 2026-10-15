from decimal import Decimal
from unittest import TestCase as PlainTestCase

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.fares import engine, services
from apps.rides.models import Ride
from apps.rides.tests.helpers import get_model, get_rate, make_driver, make_ride, make_user
from apps.rides.tests.test_views import offer_payload


def fare(**changes):
    values = dict(fuel_price=103, km_per_litre=8, wear_per_km=2, recovery_percent=90, seats=3, rider_km=15)
    values.update(changes)
    return engine.fare_breakdown(**values)


class EngineAdjustmentTests(PlainTestCase):
    def test_no_adjustment_changes_nothing(self):
        result = fare()
        self.assertEqual((result.total, result.base_total, result.adjustment), (67, 67, 0))

    def test_adjustment_moves_the_fare_up_and_down(self):
        self.assertEqual(fare(adjustment=20).total, 87)
        self.assertEqual(fare(adjustment=-20).total, 47)
        self.assertEqual(fare(adjustment=5).total, 72)

    def test_the_standard_fare_is_kept_beside_the_adjusted_one(self):
        result = fare(adjustment=-20)
        self.assertEqual((result.base_total, result.adjustment, result.adjustment_abs), (67, -20, 20))

    def test_more_than_twenty_either_way_is_refused(self):
        for bad in (21, -21, 100):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    fare(adjustment=bad)

    def test_the_limit_is_twenty_rupees(self):
        self.assertEqual(engine.MAX_ADJUSTMENT_RS, 20)

    def test_a_fare_never_goes_below_zero(self):
        short = fare(rider_km=Decimal("0.5"), adjustment=-20)  # standard fare is about 2 rupees
        self.assertEqual(short.total, 0)
        self.assertEqual(short.total, short.base_total + short.adjustment)  # the recorded adjustment is what really applied

    def test_the_adjustment_is_added_after_rounding_and_the_cap(self):
        base = fare(seats=6, toll_total=75, rider_km=1).base_total
        self.assertEqual(fare(seats=6, toll_total=75, rider_km=1, adjustment=20).total, base + 20)


class ServiceAdjustmentTests(TestCase):
    def setUp(self):
        self.driver = make_driver()

    def test_a_rides_adjustment_changes_its_fare(self):
        plain = make_ride(self.driver, seats=3, mileage_rate=get_rate("car", "Sedan"))
        cheaper = make_ride(self.driver, seats=3, mileage_rate=get_rate("car", "Sedan"), fare_adjustment=-20)
        dearer = make_ride(self.driver, seats=3, mileage_rate=get_rate("car", "Sedan"), fare_adjustment=20)
        base = services.full_route_fare(plain).total
        self.assertEqual(services.full_route_fare(cheaper).total, base - 20)
        self.assertEqual(services.full_route_fare(dearer).total, base + 20)

    def test_a_partial_trip_gets_the_same_rupee_adjustment(self):
        plain = make_ride(self.driver, seats=3, mileage_rate=get_rate("car", "Sedan"))
        dearer = make_ride(self.driver, seats=3, mileage_rate=get_rate("car", "Sedan"), fare_adjustment=10)
        half = plain.route_distance_m // 2
        self.assertEqual(services.fare_for(dearer, half).total, services.fare_for(plain, half).total + 10)

    def test_two_wheelers_can_be_adjusted_too(self):
        biker = make_driver("biker@acme.com", vehicle_type="bike")
        ride = make_ride(biker, seats=1, vehicle_type="bike", has_spare_helmet=True,
                         mileage_rate=get_rate("bike"), fare_adjustment=-20)
        self.assertEqual(services.full_route_fare(ride).adjustment, -20)

    def test_the_database_refuses_an_adjustment_beyond_the_limit(self):
        for bad in (21, -21):
            with self.subTest(bad), self.assertRaises(IntegrityError), transaction.atomic():
                make_ride(self.driver, mileage_rate=get_rate("car", "Sedan"), fare_adjustment=bad)


class OfferAndShowTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.rider = make_user("rider@acme.com")
        self.offer_url = reverse("rides:offer")

    def test_offer_form_has_the_adjustment_field(self):
        self.client.force_login(self.driver)
        self.assertContains(self.client.get(self.offer_url), "Change the fare by")

    def test_adjustment_is_saved(self):
        self.client.force_login(self.driver)
        self.client.post(self.offer_url, offer_payload(fare_adjustment="-15"))
        self.assertEqual(Ride.objects.get().fare_adjustment, -15)

    def test_adjustment_is_optional(self):
        self.client.force_login(self.driver)
        self.client.post(self.offer_url, offer_payload())
        self.assertEqual(Ride.objects.get().fare_adjustment, 0)

    def test_more_than_twenty_or_not_a_number_is_refused(self):
        self.client.force_login(self.driver)
        for bad in ("21", "-21", "abc"):
            with self.subTest(bad):
                response = self.client.post(self.offer_url, offer_payload(fare_adjustment=bad))
                self.assertEqual(response.status_code, 200)
                self.assertFalse(Ride.objects.exists())

    def test_the_way_back_has_the_same_adjustment(self):
        self.client.force_login(self.driver)
        self.client.post(self.offer_url, offer_payload(fare_adjustment="10", offer_return="on", return_time="18:00"))
        self.assertEqual(list(Ride.objects.values_list("fare_adjustment", flat=True)), [10, 10])

    def test_two_wheeler_driver_can_adjust_the_fare(self):
        self.client.force_login(make_driver("biker@acme.com", vehicle_type="bike"))
        self.client.post(self.offer_url, offer_payload(
            seats="1", has_spare_helmet="on", mileage_rate=get_model("bike").pk, make="Honda",
            fare_adjustment="-20"))
        self.assertEqual(Ride.objects.get().fare_adjustment, -20)

    def test_ride_page_says_when_the_driver_changed_the_fare(self):
        up = make_ride(self.driver, mileage_rate=get_rate("car", "Sedan"), fare_adjustment=20)
        down = make_ride(self.driver, mileage_rate=get_rate("car", "Sedan"), fare_adjustment=-20)
        self.client.force_login(self.rider)
        page_up = self.client.get(reverse("rides:detail", args=[up.pk]))
        self.assertContains(page_up, "The driver set it &#8377;20 higher")
        self.assertNotContains(page_up, "Riders never pay more than the trip cost.")
        page_down = self.client.get(reverse("rides:detail", args=[down.pk]))
        self.assertContains(page_down, "The driver set it &#8377;20 lower")

    def test_ride_page_keeps_the_promise_when_there_is_no_adjustment(self):
        ride = make_ride(self.driver, mileage_rate=get_rate("car", "Sedan"))
        self.client.force_login(self.rider)
        response = self.client.get(reverse("rides:detail", args=[ride.pk]))
        self.assertContains(response, "Riders never pay more than the trip cost.")
        self.assertNotContains(response, "The driver set it")