from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.views.defaults import server_error

from apps.accounts import services as account_services
from apps.accounts.models import User
from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import car_ride, make_request
from apps.rides.tests.helpers import make_driver, make_user

S = RideRequest.Status


class RemainingPagesSetup(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.ride = car_ride(self.driver)
        self.rider = make_user("anita@acme.com", first_name="Anita", last_name="Rao")


class MyWeekAndWayBackDesignTests(RemainingPagesSetup):
    def test_my_week_is_a_card_with_one_row_for_each_day(self):
        self.client.force_login(self.rider)
        page = self.client.get(reverse("bookings:plan"))
        self.assertContains(page, "or-title")
        self.assertContains(page, "or-planrow", count=5)
        self.assertContains(page, "Save my week")
        self.assertContains(page, "Change one day")

    def test_the_way_back_page_keeps_its_search_and_time_wheel(self):
        req = make_request(self.ride, self.rider, status=S.ACCEPTED)
        self.client.force_login(self.rider)
        page = self.client.get(reverse("bookings:request_back", args=[req.pk]))
        self.assertContains(page, "Request the ride back")
        self.assertContains(page, "or-box")
        self.assertContains(page, "time_wheel.js")


class RidesIOfferDesignTests(RemainingPagesSetup):
    def test_a_live_ride_is_a_card_with_status_and_counts(self):
        self.client.force_login(self.driver)
        page = self.client.get(reverse("rides:mine"))
        self.assertContains(page, "or-trip")
        self.assertContains(page, "Live")
        self.assertContains(page, "or-counts")
        self.assertContains(page, "Offer the same ride back")

    def test_a_switched_off_ride_is_grey(self):
        self.ride.is_active = False
        self.ride.save()
        self.client.force_login(self.driver)
        page = self.client.get(reverse("rides:mine"))
        self.assertContains(page, "Switched off")
        self.assertContains(page, "or-status off")

    def test_waiting_requests_show_an_amber_note(self):
        make_request(self.ride, self.rider)
        self.client.force_login(self.driver)
        page = self.client.get(reverse("rides:mine"))
        self.assertContains(page, "or-warn")
        self.assertContains(page, "1 request waiting for your reply")

    def test_a_new_driver_sees_the_friendly_empty_card(self):
        self.client.force_login(make_driver("new@acme.com"))
        page = self.client.get(reverse("rides:mine"))
        self.assertContains(page, "or-empty")
        self.assertContains(page, "You have not offered any rides yet")


class DeleteAndUnavailableDesignTests(RemainingPagesSetup):
    def test_the_delete_page_warns_in_amber_and_lists_the_bookings(self):
        make_request(self.ride, self.rider, status=S.ACCEPTED)
        self.client.force_login(self.driver)
        page = self.client.get(reverse("rides:delete", args=[self.ride.pk]))
        self.assertContains(page, "Delete this ride?")
        self.assertContains(page, "or-warn")
        self.assertContains(page, "Anita R.")

    def test_the_unavailable_page_keeps_its_form_and_empty_text(self):
        self.client.force_login(self.driver)
        page = self.client.get(reverse("rides:unavailable"))
        self.assertContains(page, "or-card")
        self.assertContains(page, "No upcoming dates")


class RateAndReportDesignTests(RemainingPagesSetup):
    def setUp(self):
        super().setUp()
        self.req = make_request(self.ride, self.rider, status=S.COMPLETED)

    def test_the_stars_and_tags_are_choice_buttons(self):
        self.client.force_login(self.rider)
        page = self.client.get(reverse("trust:rate", args=[self.req.pk]))
        self.assertContains(page, "or-choice")
        self.assertContains(page, 'type="radio"', count=5)
        self.assertContains(page, "Safe driving")

    def test_a_missing_star_count_still_shows_the_error(self):
        self.client.force_login(self.rider)
        page = self.client.post(reverse("trust:rate", args=[self.req.pk]), {"comment": "x"})
        self.assertContains(page, "Choose 1 to 5 stars")

    def test_the_report_page_has_the_red_send_button(self):
        self.client.force_login(self.rider)
        page = self.client.get(reverse("trust:report", args=[self.req.pk]))
        self.assertContains(page, "Report a problem")
        self.assertContains(page, "btn-danger")
        self.assertContains(page, "Unsafe driving or behaviour")


class VerifyPageDesignTests(TestCase):
    def test_the_code_box_is_big_and_the_countdown_is_kept(self):
        user = User.objects.create_user("v@company.com", "S3cure-pass!", first_name="V")
        self.client.force_login(user)
        account_services.send_otp(user)
        page = self.client.get(reverse("accounts:verify"))
        self.assertContains(page, "or-code")
        self.assertContains(page, "6-digit code")
        self.assertContains(page, "resend-btn")


class ErrorPagesTests(TestCase):
    def test_a_missing_page_shows_the_friendly_404(self):
        page = self.client.get("/there-is-nothing-here/")
        self.assertContains(page, "We could not find that page", status_code=404)
        self.assertContains(page, "or-lost", status_code=404)

    def test_a_missing_page_for_a_logged_in_person_keeps_the_menu(self):
        self.client.force_login(make_user())
        page = self.client.get("/there-is-nothing-here/")
        self.assertContains(page, "or-tabs", status_code=404)

    def test_the_500_page_stands_alone_and_says_it_is_not_the_users_fault(self):
        request = RequestFactory().get("/")
        response = server_error(request)
        self.assertEqual(response.status_code, 500)
        body = response.content.decode()
        self.assertIn("Something went wrong on our side", body)
        self.assertIn("or-lost", body)