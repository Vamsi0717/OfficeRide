import threading
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from apps.bookings import services
from apps.bookings.models import RideRequest
from apps.rides.tests.helpers import make_user

from .helpers import car_ride, future_monday, make_request


@skipUnless(connection.vendor == "postgresql", "SQLite ignores row locks, so this test only means something on PostgreSQL")
class NobodyCanOverbookTests(TransactionTestCase):
    """Several accepts at the same moment for the last seat: exactly one wins."""

    # This kind of test empties the tables when it finishes. This puts the starting values
    # (vehicle classes and the petrol price) back before the next test.
    serialized_rollback = True

    def test_two_requests_for_the_last_seat_cannot_both_be_accepted(self):
        ride = car_ride(seats=1)
        day = future_monday()
        requests = [make_request(ride, make_user(f"r{i}@acme.com"), day) for i in range(2)]
        self.race(ride, [r.pk for r in requests])
        self.assertEqual(RideRequest.objects.filter(ride=ride, date=day, status="accepted").count(), 1)

    def test_many_accepts_never_exceed_the_seats(self):
        ride = car_ride(seats=3)
        day = future_monday()
        requests = [make_request(ride, make_user(f"r{i}@acme.com"), day) for i in range(8)]
        self.race(ride, [r.pk for r in requests])
        self.assertEqual(RideRequest.objects.filter(ride=ride, date=day, status="accepted").count(), 3)

    def race(self, ride, request_ids):
        outcomes, barrier = [], threading.Barrier(len(request_ids))

        def worker(request_id):
            try:
                barrier.wait()
                services.accept(request_id, ride.driver)
                outcomes.append("accepted")
            except services.BookingError:
                outcomes.append("refused")
            finally:
                close_old_connections()
                connection.close()

        threads = [threading.Thread(target=worker, args=(rid,)) for rid in request_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(outcomes), len(request_ids))