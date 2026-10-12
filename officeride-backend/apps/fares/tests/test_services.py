from datetime import time
from decimal import Decimal

from django.test import TestCase

from apps.fares import services
from apps.fares.models import FareSettings
from apps.rides.matching import find_rides
from apps.rides.tests.helpers import get_rate, make_driver, make_ride, make_user, next_weekday, point_along


def expected_total(km, kmpl, wear, seats, toll=0, recovery=90, fuel=103):
    """The same arithmetic written out separately from the engine, rounded half up."""
    cost = (Decimal(fuel) / Decimal(kmpl) + Decimal(wear)) * Decimal(recovery) / 100
    value = cost * Decimal(km) / seats + Decimal(toll) / seats
    return int(value.quantize(Decimal("1"), rounding="ROUND_HALF_UP"))


class FareForTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.ride = make_ride(self.driver, seats=3, mileage_rate=get_rate("car", "Sedan"))
        self.km = Decimal(self.ride.route_distance_m) / 1000

    def test_full_route_fare_for_a_sedan(self):
        fare = services.full_route_fare(self.ride)
        self.assertEqual(fare.total, expected_total(self.km, 10, 2, 3))

    def test_a_shorter_trip_costs_less(self):
        half = services.fare_for(self.ride, self.ride.route_distance_m // 2)
        self.assertLess(half.total, services.full_route_fare(self.ride).total)
        self.assertEqual(half.total, expected_total(self.km / 2, 10, 2, 3))

    def test_distance_beyond_the_route_is_capped(self):
        self.assertEqual(
            services.fare_for(self.ride, self.ride.route_distance_m * 3).total,
            services.full_route_fare(self.ride).total,
        )

    def test_toll_is_added_per_seat(self):
        self.ride.toll_total = 60
        fare = services.full_route_fare(self.ride)
        self.assertEqual(fare.toll, Decimal("20.00"))
        self.assertEqual(fare.total, expected_total(self.km, 10, 2, 3, toll=60))

    def test_vehicle_class_changes_the_fare(self):
        totals = {}
        for name in ("Hatchback", "Sedan", "SUV or MUV"):
            self.ride.mileage_rate = get_rate("car", name)
            totals[name] = services.full_route_fare(self.ride).total
        self.assertLess(totals["Hatchback"], totals["Sedan"])
        self.assertLess(totals["Sedan"], totals["SUV or MUV"])

    def test_changing_the_fuel_price_in_the_database_changes_the_fare(self):
        before = services.full_route_fare(self.ride).total
        s = FareSettings.get_solo()
        s.fuel_price_per_litre = Decimal("120")
        s.save()
        after = services.full_route_fare(self.ride)
        self.assertGreater(after.total, before)
        self.assertEqual(after.total, expected_total(self.km, 10, 2, 3, fuel=120))

    def test_changing_the_recovery_percent_changes_the_fare(self):
        s = FareSettings.get_solo()
        s.recovery_percent = 60
        s.save()
        self.assertEqual(services.full_route_fare(self.ride).total, expected_total(self.km, 10, 2, 3, recovery=60))

    def test_a_ride_without_a_vehicle_class_has_no_fare(self):
        self.ride.mileage_rate = None
        self.assertIsNone(services.full_route_fare(self.ride))


class TwoWheelerFareTests(TestCase):
    def test_a_two_wheeler_uses_its_own_wear_and_one_seat(self):
        biker = make_driver("biker@acme.com", vehicle_type="bike")
        ride = make_ride(biker, seats=1, vehicle_type="bike", has_spare_helmet=True,
                         mileage_rate=get_rate("bike", "Commuter motorcycle"))
        km = Decimal(ride.route_distance_m) / 1000
        self.assertEqual(services.full_route_fare(ride).total, expected_total(km, 45, Decimal("0.80"), 1))

    def test_the_two_wheeler_wear_can_be_changed_separately(self):
        biker = make_driver("biker@acme.com", vehicle_type="bike")
        ride = make_ride(biker, seats=1, vehicle_type="bike", has_spare_helmet=True, mileage_rate=get_rate("bike"))
        car_ride = make_ride(make_driver("c@acme.com"), seats=1, mileage_rate=get_rate("car", "Sedan"))
        before_car = services.full_route_fare(car_ride).total
        before = services.full_route_fare(ride).total
        s = FareSettings.get_solo()
        s.bike_wear_per_km = Decimal("3.00")
        s.save()
        self.assertGreater(services.full_route_fare(ride).total, before)
        self.assertEqual(services.full_route_fare(car_ride).total, before_car)  # car wear untouched


class GuaranteeTests(TestCase):
    def test_all_seats_filled_riders_never_pay_more_than_the_trip_cost(self):
        for seats in range(1, 7):
            for toll in (0, 75):
                ride = make_ride(
                    make_driver(f"d{seats}{toll}@acme.com"), seats=seats, toll_total=toll,
                    mileage_rate=get_rate("car", "SUV or MUV"),
                )
                with self.subTest(seats=seats, toll=toll):
                    paid = seats * services.full_route_fare(ride).total
                    cost = (Decimal(103) / 8 + 2) * Decimal(ride.route_distance_m) / 1000 + toll
                    self.assertLessEqual(paid, cost)


class AttachFaresTests(TestCase):
    def test_every_match_gets_a_fare_for_its_own_distance_with_one_settings_read(self):
        driver = make_driver()
        make_ride(driver, seats=3, mileage_rate=get_rate("car", "Sedan"))
        rider = make_user("rider@acme.com")
        day = next_weekday(0)
        matches = find_rides(
            rider, point_along(0.0), point_along(1.0), day, time(9, 0)
        ) + find_rides(rider, point_along(0.2), point_along(0.6), day, time(9, 0))
        self.assertEqual(len(matches), 2)
        with self.assertNumQueries(1):
            services.attach_fares(matches)
        full, part = matches
        self.assertGreater(full.fare.total, part.fare.total)
        km = Decimal(part.rider_distance_m) / 1000
        self.assertEqual(part.fare.total, expected_total(km, 10, 2, 3))