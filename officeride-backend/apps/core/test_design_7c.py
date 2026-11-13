from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import DriverDocument
from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import car_ride, make_request
from apps.chat import services as chat_services
from apps.rides.tests.helpers import make_driver, make_user


def person(email, first, last, phone="9845012345"):
    return make_user(email, first_name=first, last_name=last, phone=phone)


class TripsPageDesignTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.driver.phone = "9845012300"
        self.driver.save()
        self.ride = car_ride(self.driver)
        self.rider = person("anita@acme.com", "Anita", "Rao")
        self.req = make_request(self.ride, self.rider, status=RideRequest.Status.ACCEPTED)

    def page(self, user, view):
        self.client.force_login(user)
        return self.client.get(reverse("bookings:trips"), {"view": view})

    def test_the_two_groups_are_a_segmented_switch_and_the_active_one_is_marked(self):
        page = self.page(self.rider, "riding")
        self.assertContains(page, "or-seg")
        self.assertContains(page, "I'm riding")
        self.assertContains(page, "I'm driving")
        self.assertContains(page, "active", count=2)  # the switch and the bottom menu tab

    def test_a_trip_card_has_the_timeline_status_driver_and_fare(self):
        page = self.page(self.rider, "riding")
        self.assertContains(page, "or-trip")
        self.assertContains(page, "or-timeline")
        self.assertContains(page, "Accepted")
        self.assertContains(page, "Driver: Ravi K.")
        self.assertContains(page, "&#8377;50")
        self.assertContains(page, "9:00 AM")

    def test_the_card_keeps_its_chat_button_and_the_way_back_link(self):
        page = self.page(self.rider, "riding")
        self.assertContains(page, reverse("chat:thread", args=[self.req.pk]))
        self.assertContains(page, 'aria-label="Chat"')
        self.assertContains(page, "Request the ride back")

    def test_the_driver_sees_the_rider_and_the_you_drive_note(self):
        page = self.page(self.driver, "driving")
        self.assertContains(page, "Rider: Anita R.")
        self.assertContains(page, "You drive")

    def test_a_waiting_request_shows_the_amber_status_and_the_accept_button(self):
        self.req.status = RideRequest.Status.PENDING
        self.req.save()
        page = self.page(self.driver, "driving")
        self.assertContains(page, "or-status pending")
        self.assertContains(page, "Accept")
        self.assertContains(page, "Reject")

    def test_the_counts_are_three_small_tiles(self):
        page = self.page(self.rider, "riding")
        self.assertContains(page, "or-count", count=4)  # the wrapper class and three tiles
        for label in ("Today", "Tomorrow", "Waiting"):
            self.assertContains(page, f"<small>{label}</small>")

    def test_an_empty_list_has_a_friendly_card_and_a_button(self):
        newcomer = person("new@acme.com", "Nina", "Shah")
        page = self.page(newcomer, "riding")
        self.assertContains(page, "or-empty")
        self.assertContains(page, "You have not asked for a ride yet")
        self.assertContains(page, reverse("rides:find"))

    def test_the_riding_tab_points_to_rides_i_offer(self):
        self.assertContains(self.page(self.rider, "riding"), reverse("rides:mine"))


class ChatPageDesignTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.driver.phone = "9845012300"
        self.driver.save()
        self.ride = car_ride(self.driver)
        self.rider = person("anita@acme.com", "Anita", "Rao")
        self.req = make_request(self.ride, self.rider, status=RideRequest.Status.ACCEPTED)
        self.url = reverse("chat:thread", args=[self.req.pk])

    def test_the_navy_header_has_the_other_persons_name_and_the_ride(self):
        self.client.force_login(self.driver)
        page = self.client.get(self.url)
        self.assertContains(page, "or-chat-head")
        self.assertContains(page, "Chat with Anita R.")
        self.assertContains(page, "AR")
        self.assertContains(page, "Start")

    def test_my_messages_are_green_on_the_right_and_theirs_are_white_on_the_left(self):
        chat_services.send(self.req, self.rider, "Where are you?")
        chat_services.send(self.req, self.driver, "Two minutes away")
        self.client.force_login(self.driver)
        page = self.client.get(self.url)
        self.assertContains(page, "or-msg me")
        self.assertContains(page, "or-msg them")
        self.assertContains(page, "Where are you?")

    def test_the_privacy_note_the_quick_replies_and_the_send_button(self):
        self.client.force_login(self.driver)
        page = self.client.get(self.url)
        self.assertContains(page, "Phone numbers and emails are never shown here")
        self.assertContains(page, "or-quick")
        self.assertContains(page, 'aria-label="Send"')
        self.assertContains(page, "Confirm pickup point")

    def test_no_phone_number_appears_on_the_page(self):
        self.client.force_login(self.driver)
        page = self.client.get(self.url)
        for secret in ("9845012345", "9845012300"):
            self.assertNotContains(page, secret)

    def test_a_closed_chat_says_so_and_has_no_form(self):
        self.req.status = RideRequest.Status.COMPLETED
        self.req.save()
        self.client.force_login(self.driver)
        page = self.client.get(self.url)
        self.assertContains(page, "This chat is closed")
        self.assertNotContains(page, "Confirm pickup point")
        self.assertNotContains(page, "or-compose")


class ProfilePageDesignTests(TestCase):
    def setUp(self):
        self.user = person("anita@acme.com", "Anita", "Rao")
        self.client.force_login(self.user)
        self.page = self.client.get(reverse("accounts:profile"))

    def test_the_navy_header_has_the_initials_name_email_and_phone(self):
        self.assertContains(self.page, "or-profile-head")
        self.assertContains(self.page, ">AR<")
        self.assertContains(self.page, "anita@acme.com")
        self.assertContains(self.page, "+91 9845012345")

    def test_three_small_tiles(self):
        for label in ("Rides shared", "Rating", "Strikes"):
            self.assertContains(self.page, f"<small>{label}</small>")

    def test_the_menu_has_documents_rides_i_offer_my_week_and_log_out(self):
        self.assertContains(self.page, "or-menu")
        for text in ("My documents", "Rides I offer", "My week", "Log out"):
            self.assertContains(self.page, text)
        self.assertContains(self.page, reverse("accounts:logout"))

    def test_someone_without_documents_sees_not_submitted(self):
        self.assertContains(self.page, "Not submitted")

    def test_a_driver_with_approved_documents_sees_approved(self):
        driver = make_driver()
        self.client.force_login(driver)
        self.assertContains(self.client.get(reverse("accounts:profile")), "Approved")

    def test_the_edit_form_and_the_record_are_still_there(self):
        self.assertContains(self.page, "Edit profile")
        self.assertContains(self.page, "Mobile number")
        self.assertContains(self.page, "Save profile")
        self.assertContains(self.page, "Your record")
        self.assertContains(self.page, "How strikes work")

    def test_saving_the_profile_still_works(self):
        response = self.client.post(reverse("accounts:profile"), {
            "first_name": "Anita", "last_name": "Rao", "country_code": "+91", "phone": "9845011111",
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "9845011111")


class DocumentsPageDesignTests(TestCase):
    def test_an_approved_driver_sees_the_verified_banner_and_three_saved_cards(self):
        driver = make_driver()
        self.client.force_login(driver)
        page = self.client.get(reverse("accounts:documents"))
        self.assertContains(page, "or-verified")
        self.assertContains(page, "Documents verified")
        self.assertContains(page, "Driving licence")
        self.assertContains(page, "Vehicle RC")
        self.assertContains(page, "Insurance")
        for kind in ("licence", "rc", "insurance"):
            self.assertContains(page, reverse("accounts:document_file", args=[driver.driver_document.pk, kind]))
        self.assertContains(page, "Only you and OfficeRide staff can open these.")

    def test_a_pending_driver_sees_the_amber_banner(self):
        driver = make_driver(approved=False)
        self.client.force_login(driver)
        page = self.client.get(reverse("accounts:documents"))
        self.assertContains(page, "or-verified pending")
        self.assertContains(page, "Pending review")
        self.assertNotContains(page, "Documents verified")

    def test_a_rejected_driver_sees_the_reason(self):
        driver = make_driver(approved=False)
        DriverDocument.objects.filter(user=driver).update(status=DriverDocument.Status.REJECTED, rejection_reason="Photo is blurry")
        self.client.force_login(driver)
        page = self.client.get(reverse("accounts:documents"))
        self.assertContains(page, "or-verified rejected")
        self.assertContains(page, "Photo is blurry")

    def test_a_new_person_sees_the_explanation_the_form_and_no_saved_cards(self):
        self.client.force_login(person("new@acme.com", "Nina", "Shah"))
        page = self.client.get(reverse("accounts:documents"))
        self.assertContains(page, "Only needed if you want to offer rides")
        self.assertContains(page, "Submit documents")
        self.assertContains(page, "PDF, JPG or PNG")
        self.assertNotContains(page, "View licence")
        self.assertNotContains(page, "or-doc")

    def test_the_form_still_checks_the_licence_and_rc(self):
        self.client.force_login(person("new2@acme.com", "Nia", "Shah"))
        response = self.client.post(reverse("accounts:documents"), {"vehicle_type": "car", "licence_number": "x", "rc_number": "y"})
        self.assertContains(response, "Enter valid licence details.")
        self.assertContains(response, "Enter valid RC details.")