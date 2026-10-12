from decimal import Decimal
from itertools import product
from unittest import TestCase  # the engine touches no database, so plain unittest is enough

from apps.fares import engine

# The worked example from the plan: KR Puram to Bellandur, 15 km, SUV at 8 km/l, petrol at ₹103,
# wear ₹2/km, riders repay 90%, 3 seats offered.
SUV = dict(fuel_price=103, km_per_litre=8, wear_per_km=2, recovery_percent=90, seats=3)


def fare(**changes):
    values = {**SUV, "rider_km": 15, **changes}
    return engine.rider_fare(**values)


class CostPerKmTests(TestCase):
    def test_fuel_plus_wear(self):
        self.assertEqual(engine.cost_per_km(103, 8, 2), Decimal("14.875"))

    def test_zero_or_negative_mileage_is_refused(self):
        for bad in (0, -5):
            with self.assertRaises(ValueError):
                engine.cost_per_km(103, bad, 2)


class WorkedExampleTests(TestCase):
    def test_full_route_one_way_is_67(self):
        self.assertEqual(fare(), 67)

    def test_round_trip_is_134(self):
        self.assertEqual(fare(rider_km=30), 134)

    def test_breakdown_parts(self):
        b = engine.fare_breakdown(rider_km=15, **SUV)
        self.assertEqual(b.fuel, Decimal("57.94"))
        self.assertEqual(b.wear, Decimal("9.00"))
        self.assertEqual(b.toll, Decimal("0.00"))
        self.assertEqual(b.cost_per_km, Decimal("14.875"))
        self.assertEqual(b.total, 67)

    def test_floats_are_accepted(self):
        self.assertEqual(fare(fuel_price=103.0, km_per_litre=8.0, rider_km=15.0), 67)


class FareRulesTests(TestCase):
    def test_hatchback_sedan_and_suv_give_different_fares(self):
        hatchback, sedan, suv = (fare(km_per_litre=k) for k in (12, 10, 8))
        self.assertEqual((hatchback, sedan, suv), (48, 55, 67))

    def test_half_the_route_is_half_the_fare(self):
        half = fare(rider_km=Decimal("7.5"))
        self.assertEqual(half, 33)  # 66.9375 / 2 = 33.47
        self.assertLessEqual(abs(2 * half - fare()), 1)

    def test_fewer_seats_means_a_higher_fare_per_seat(self):
        self.assertEqual([fare(seats=s) for s in (3, 2, 1)], [67, 100, 201])

    def test_toll_is_split_between_the_seats(self):
        b = engine.fare_breakdown(rider_km=15, toll_total=90, **SUV)
        self.assertEqual(b.toll, Decimal("30.00"))
        self.assertEqual(b.total, 97)  # 66.9375 + 30 = 96.9375, rounded once

    def test_distance_above_the_route_is_capped(self):
        self.assertEqual(fare(rider_km=40, route_km=15), fare(rider_km=15))

    def test_a_shorter_distance_is_not_changed_by_the_cap(self):
        self.assertEqual(fare(rider_km=7.5, route_km=15), fare(rider_km=7.5))

    def test_a_higher_fuel_price_gives_a_higher_fare(self):
        self.assertGreater(fare(fuel_price=110), fare(fuel_price=103))

    def test_rounding_happens_once_and_half_goes_up(self):
        # exactly 2.5 must give 3 (not the banker's 2), and the parts are not rounded before adding
        kwargs = dict(fuel_price=10, km_per_litre=1, wear_per_km=0, recovery_percent=50, seats=2, rider_km=1)
        self.assertEqual(engine.rider_fare(**kwargs), 3)  # 10 x 0.5 / 2 = 2.5
        b = engine.fare_breakdown(fuel_price=1, km_per_litre=3, wear_per_km=0, recovery_percent=100, seats=1, rider_km=1)
        self.assertEqual(b.fuel, Decimal("0.33"))  # 0.333...: the shown part is rounded, the total uses the exact value

    def test_rounding_up_never_pushes_riders_above_the_cost(self):
        # 100% recovery on a 1 km trip: 2 seats x 2.5 would round to 3 + 3 = 6, but the trip costs only 5
        kwargs = dict(fuel_price=5, km_per_litre=1, wear_per_km=0, recovery_percent=100, seats=2, rider_km=1)
        self.assertEqual(engine.rider_fare(**kwargs), 2)

    def test_wear_and_fuel_both_scale_with_recovery(self):
        self.assertLess(fare(recovery_percent=70), fare(recovery_percent=90))


class TwoWheelerTests(TestCase):
    """A two-wheeler is just 1 seat and a bike's mileage and wear. Same formula."""

    BIKE = dict(fuel_price=103, km_per_litre=45, wear_per_km=Decimal("0.80"), recovery_percent=90, seats=1)

    def test_commuter_motorcycle_fare(self):
        # (103/45 + 0.80) x 0.9 x 15 = 41.70
        self.assertEqual(engine.rider_fare(rider_km=15, **self.BIKE), 42)

    def test_a_bike_rider_pays_less_than_a_suv_rider_alone_on_the_same_trip(self):
        self.assertLess(engine.rider_fare(rider_km=15, **self.BIKE), fare(seats=1))


class GuaranteeTests(TestCase):
    """With every seat filled and everyone riding the full route, riders never pay more than the trip cost."""

    def test_riders_never_pay_more_than_fuel_wear_and_toll(self):
        rides = product((8, 10, 12, 30, 40, 45), (1, 2, 3, 4, 5, 6), (1, 2.5, 7.3, 15, 30, 60, 120), (0, 40, 100, 333))
        for km_per_litre, seats, km, toll in rides:
            for wear in (Decimal("2"), Decimal("0.8")):
                with self.subTest(kmpl=km_per_litre, seats=seats, km=km, toll=toll, wear=wear):
                    paid = seats * engine.rider_fare(
                        fuel_price=103, km_per_litre=km_per_litre, wear_per_km=wear, recovery_percent=90,
                        seats=seats, rider_km=km, route_km=km, toll_total=toll,
                    )
                    cost = engine.cost_per_km(103, km_per_litre, wear) * Decimal(str(km)) + toll
                    self.assertLessEqual(paid, cost)


class InvalidInputTests(TestCase):
    def test_bad_values_are_refused(self):
        bad = [
            {"seats": 0}, {"rider_km": -1}, {"recovery_percent": 0}, {"recovery_percent": 101},
            {"toll_total": -10}, {"km_per_litre": 0},
        ]
        for change in bad:
            with self.subTest(change), self.assertRaises(ValueError):
                fare(**change)