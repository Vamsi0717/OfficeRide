from datetime import time, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.rides import matching
from apps.rides.models import CarUnavailableDate

from .helpers import line, make_driver, make_ride, make_user, next_weekday, point_along


class TimeDifferenceTests(TestCase):
    def test_simple_gap(self):
        self.assertEqual(matching.time_difference_min(time(9, 0), time(9, 10)), 10)

    def test_gap_across_midnight(self):
        self.assertEqual(matching.time_difference_min(time(23, 55), time(0, 5)), 10)


class FindRidesTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.rider = make_user("rider@acme.com")
        self.ride = make_ride(self.driver)  # 9:00, Monday to Friday, west to east
        self.monday = next_weekday(0)
        self.pickup = point_along(0.2, north_m=300)
        self.drop = point_along(0.8, north_m=-200)

    def search(self, pickup=None, drop=None, on_date=None, at=time(9, 0)):
        return matching.find_rides(
            self.rider, pickup or self.pickup, drop or self.drop, on_date or self.monday, at
        )

    def test_finds_a_ride_on_the_route(self):
        matches = self.search()
        self.assertEqual([m.ride for m in matches], [self.ride])
        match = matches[0]
        self.assertAlmostEqual(match.rider_distance_m / 1000, 0.6 * 10.85, delta=0.2)
        self.assertAlmostEqual(match.pickup_offset_m, 300, delta=10)
        self.assertAlmostEqual(match.drop_offset_m, 200, delta=10)
        self.assertEqual(match.time_diff_min, 0)

    def test_works_anywhere_in_the_city_not_just_one_corridor(self):
        # A completely different part of Bangalore: Yelahanka to Hebbal (north).
        north = line((13.1007, 77.5963), (13.0358, 77.5970))
        other = make_ride(make_driver("north@acme.com"), points=north, departure=time(8, 30))
        found = matching.find_rides(
            self.rider, (13.0900, 77.5964), (13.0450, 77.5969), self.monday, time(8, 30)
        )
        self.assertEqual([m.ride for m in found], [other])

    def test_wrong_direction_is_not_a_match(self):
        self.assertEqual(self.search(pickup=self.drop, drop=self.pickup), [])

    def test_pickup_too_far_from_the_route(self):
        self.assertEqual(self.search(pickup=point_along(0.2, north_m=2000)), [])

    def test_drop_too_far_from_the_route(self):
        self.assertEqual(self.search(drop=point_along(0.8, north_m=2000)), [])

    def test_just_inside_the_radius(self):
        self.assertEqual(len(self.search(pickup=point_along(0.2, north_m=1400))), 1)

    def test_pickup_and_drop_almost_the_same_place(self):
        self.assertEqual(self.search(pickup=point_along(0.5), drop=point_along(0.5, north_m=50)), [])

    def test_time_window_is_inclusive_at_15_minutes(self):
        self.assertEqual(len(self.search(at=time(9, 15))), 1)
        self.assertEqual(len(self.search(at=time(8, 45))), 1)
        self.assertEqual(self.search(at=time(9, 16)), [])

    def test_ride_does_not_run_on_that_weekday(self):
        saturday = next_weekday(5)
        self.assertEqual(self.search(on_date=saturday), [])

    def test_driver_car_unavailable_that_day(self):
        CarUnavailableDate.objects.create(driver=self.driver, date=self.monday)
        self.assertEqual(self.search(), [])
        self.assertEqual(len(self.search(on_date=self.monday + timedelta(days=7))), 1)

    def test_switched_off_ride_is_hidden(self):
        self.ride.is_active = False
        self.ride.save()
        self.assertEqual(self.search(), [])

    def test_driver_without_approved_documents_is_hidden(self):
        pending = make_driver("pending@acme.com", approved=False)
        make_ride(pending, departure=time(9, 5))
        self.assertEqual([m.ride for m in self.search()], [self.ride])

    def test_driver_with_expired_insurance_is_hidden(self):
        self.driver.driver_document.insurance_expiry = timezone.localdate() - timedelta(days=1)
        self.driver.driver_document.save()
        self.assertEqual(self.search(), [])

    def test_own_ride_is_not_offered_to_the_driver(self):
        found = matching.find_rides(self.driver, self.pickup, self.drop, self.monday, time(9, 0))
        self.assertEqual(found, [])

    def test_results_are_sorted_by_time_gap_then_distance(self):
        later = make_ride(make_driver("later@acme.com"), departure=time(9, 10))
        exact = make_ride(make_driver("exact@acme.com"), departure=time(9, 0))
        order = [m.ride for m in self.search()]
        # self.ride and exact are both 0 minutes away; the 9:10 ride comes last.
        self.assertEqual(order[-1], later)
        self.assertCountEqual(order[:2], [self.ride, exact])

    def test_vehicle_type_filter(self):
        bike = make_ride(make_driver("bike@acme.com", vehicle_type="bike"), seats=1, vehicle_type="bike", has_spare_helmet=True)
        both = self.search()
        self.assertCountEqual([m.ride for m in both], [self.ride, bike])
        only_bikes = matching.find_rides(self.rider, self.pickup, self.drop, self.monday, time(9, 0), vehicle_type="bike")
        self.assertEqual([m.ride for m in only_bikes], [bike])
        only_cars = matching.find_rides(self.rider, self.pickup, self.drop, self.monday, time(9, 0), vehicle_type="car")
        self.assertEqual([m.ride for m in only_cars], [self.ride])

    def test_route_far_away_is_filtered_before_the_detailed_check(self):
        far = line((12.80, 77.50), (12.80, 77.55))
        make_ride(make_driver("far@acme.com"), points=far)
        self.assertEqual([m.ride for m in self.search()], [self.ride])