from django.test import TestCase
from django.urls import reverse

from apps.bookings.tests.helpers import bike_ride, make_request
from apps.rides.tests.helpers import make_user
from apps.trust import services
from apps.trust.models import Complaint, Strike

from .helpers import S, TripMixin


class ComplaintTests(TripMixin, TestCase):
    def test_the_rider_reports_the_driver_and_the_driver_reports_the_rider(self):
        req = self.booking(S.COMPLETED)
        a = services.file_complaint(req, self.rider, Complaint.Kind.UNSAFE, "Drove too fast")
        self.assertEqual((a.reporter, a.reported, a.status), (self.rider, self.driver, Complaint.Status.OPEN))
        b = services.file_complaint(req, self.driver, Complaint.Kind.RUDE, "Shouted")
        self.assertEqual(b.reported, self.rider)

    def test_completed_cancelled_and_no_show_trips_can_be_reported_others_cannot(self):
        for status in (S.COMPLETED, S.CANCELLED, S.NO_SHOW):
            req = self.booking(status, rider=make_user(f"{status}@acme.com"))
            services.file_complaint(req, req.rider, Complaint.Kind.OTHER, "x")
        for status in (S.PENDING, S.ACCEPTED, S.REJECTED):
            req = self.booking(status, rider=make_user(f"{status}@acme.com"))
            with self.assertRaises(services.TrustError):
                services.file_complaint(req, req.rider, Complaint.Kind.OTHER, "x")

    def test_outsiders_cannot_report(self):
        req = self.booking(S.COMPLETED)
        with self.assertRaisesMessage(services.TrustError, "not yours"):
            services.file_complaint(req, make_user("x@acme.com"), Complaint.Kind.OTHER, "x")

    def test_a_second_open_report_on_the_same_trip_is_refused(self):
        req = self.booking(S.COMPLETED)
        services.file_complaint(req, self.rider, Complaint.Kind.OTHER, "one")
        with self.assertRaisesMessage(services.TrustError, "already reported"):
            services.file_complaint(req, self.rider, Complaint.Kind.OTHER, "two")

    def test_the_helmet_complaint_is_for_two_wheelers_only(self):
        car_trip = self.booking(S.COMPLETED)
        with self.assertRaisesMessage(services.TrustError, "two-wheeler"):
            services.file_complaint(car_trip, self.rider, Complaint.Kind.HELMET, "no helmet")
        bike = bike_ride()
        bike_trip = make_request(bike, self.rider, self.day, status=S.COMPLETED)
        complaint = services.file_complaint(bike_trip, self.rider, Complaint.Kind.HELMET, "Rider had no helmet")
        self.assertEqual(complaint.reported, bike.driver)
