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


class ComplaintViewTests(TripMixin, TestCase):
    def test_the_report_page_and_saving(self):
        req = self.booking(S.COMPLETED)
        self.client.force_login(self.rider)
        url = reverse("trust:report", args=[req.pk])
        self.assertNotContains(self.client.get(url), "Helmet")  # a car ride has no helmet option
        response = self.client.post(url, {"kind": "rude", "text": "Was rude"})
        self.assertRedirects(response, reverse("bookings:trips"))
        self.assertEqual(Complaint.objects.get().text, "Was rude")

    def test_a_bike_ride_offers_the_helmet_option(self):
        bike = bike_ride()
        req = make_request(bike, self.rider, self.day, status=S.COMPLETED)
        self.client.force_login(self.rider)
        self.assertContains(self.client.get(reverse("trust:report", args=[req.pk])), "Helmet not worn")

    def test_text_is_required(self):
        req = self.booking(S.COMPLETED)
        self.client.force_login(self.rider)
        response = self.client.post(reverse("trust:report", args=[req.pk]), {"kind": "rude", "text": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Complaint.objects.count(), 0)

    def test_outsiders_get_a_404(self):
        req = self.booking(S.COMPLETED)
        self.client.force_login(make_user("x@acme.com"))
        self.assertEqual(self.client.get(reverse("trust:report", args=[req.pk])).status_code, 404)

    def test_the_trips_page_links_to_report_only_when_it_makes_sense(self):
        done, waiting = self.booking(S.COMPLETED), self.booking(S.PENDING, rider=make_user("w@acme.com"))
        self.client.force_login(self.rider)
        self.assertContains(self.client.get(reverse("bookings:trips")), reverse("trust:report", args=[done.pk]))
        self.assertNotContains(self.client.get(reverse("bookings:trips")), reverse("trust:report", args=[waiting.pk]))

    def test_a_person_can_add_a_note_to_a_strike_from_the_profile(self):
        req = self.booking(S.CANCELLED)
        strike = services.record_strike(self.rider, Strike.Reason.LATE_CANCEL, req)
        self.client.force_login(self.rider)
        self.assertContains(self.client.get(reverse("accounts:profile")), "1 of 5")
        self.client.post(reverse("trust:explain_strike", args=[strike.pk]), {"explanation": "Family emergency"})
        strike.refresh_from_db()
        self.assertEqual(strike.explanation, "Family emergency")

    def test_nobody_else_can_add_a_note_to_someones_strike(self):
        req = self.booking(S.CANCELLED)
        strike = services.record_strike(self.rider, Strike.Reason.LATE_CANCEL, req)
        self.client.force_login(self.driver)
        self.assertEqual(self.client.post(reverse("trust:explain_strike", args=[strike.pk]), {"explanation": "hi"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("trust:explain_strike", args=[strike.pk])).status_code, 405)