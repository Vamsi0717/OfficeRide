from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.bookings.tests.helpers import make_request
from apps.rides.tests.helpers import make_user, point_along
from apps.trust import services
from apps.trust.models import Rating

from .helpers import S, TripMixin


class RatingServiceTests(TripMixin, TestCase):
    def test_the_rider_rates_the_driver_and_the_driver_rates_the_rider(self):
        req = self.booking(S.COMPLETED)
        a = services.rate(req, self.rider, 5, ["punctual"], "Great")
        b = services.rate(req, self.driver, 4)
        self.assertEqual((a.rated, a.tags, a.comment), (self.driver, ["punctual"], "Great"))
        self.assertEqual(b.rated, self.rider)

    def test_each_person_rates_once(self):
        req = self.booking(S.COMPLETED)
        services.rate(req, self.rider, 5)
        with self.assertRaisesMessage(services.TrustError, "already rated"):
            services.rate(req, self.rider, 1)
        self.assertEqual(Rating.objects.count(), 1)

    def test_outsiders_cannot_rate(self):
        req = self.booking(S.COMPLETED)
        with self.assertRaisesMessage(services.TrustError, "not yours"):
            services.rate(req, make_user("x@acme.com"), 5)

    def test_only_a_completed_ride_can_be_rated(self):
        for status in (S.PENDING, S.ACCEPTED, S.CANCELLED, S.NO_SHOW):
            req = self.booking(status, rider=make_user(f"{status}@acme.com"))
            with self.assertRaisesMessage(services.TrustError, "after it is completed"):
                services.rate(req, req.rider, 5)

    def test_stars_must_be_one_to_five(self):
        req = self.booking(S.COMPLETED)
        for bad in (0, 6):
            with self.assertRaises(services.TrustError):
                services.rate(req, self.rider, bad)

    def test_unknown_tags_are_dropped(self):
        req = self.booking(S.COMPLETED)
        self.assertEqual(services.rate(req, self.rider, 5, ["friendly", "hacker"]).tags, ["friendly"])

    def test_the_database_refuses_a_double_rating_and_a_bad_star_count(self):
        req = self.booking(S.COMPLETED)
        Rating.objects.create(request=req, rater=self.rider, rated=self.driver, stars=5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Rating.objects.create(request=req, rater=self.rider, rated=self.driver, stars=4)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Rating.objects.create(request=req, rater=self.driver, rated=self.rider, stars=9)

    def test_average_count_and_rides_shared(self):
        for i, stars in enumerate((5, 4, 3)):
            rider = make_user(f"r{i}@acme.com")
            req = make_request(self.ride, rider, self.day, status=S.COMPLETED)
            services.rate(req, rider, stars)
        make_request(self.ride, make_user("c@acme.com"), self.day, status=S.CANCELLED)
        stats = services.rating_stats([self.driver.id, self.rider.id])
        self.assertEqual(stats[self.driver.id], {"average": 4.0, "count": 3, "rides": 3})
        self.assertEqual(stats[self.rider.id], {"average": None, "count": 0, "rides": 0})

    def test_stats_use_a_fixed_number_of_queries(self):
        for i in range(4):
            make_request(self.ride, make_user(f"r{i}@acme.com"), self.day, status=S.COMPLETED)
        with self.assertNumQueries(2):
            services.rating_stats([self.driver.id, self.rider.id])
