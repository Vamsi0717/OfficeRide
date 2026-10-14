from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.chat import services
from apps.rides.tests.helpers import make_user

from .helpers import S, ChatMixin


class CallTests(ChatMixin, TestCase):
    """The Call button. The number is never on a page: the button goes through a view that checks the rules."""

    def setUp(self):
        super().setUp()
        self.req.date = timezone.localdate()
        self.req.save()
        self.url = reverse("chat:call", args=[self.req.pk])

    def test_the_rider_calls_the_driver_and_the_driver_calls_the_rider(self):
        self.assertEqual(services.call_number(self.req, self.rider), "9876543210")
        self.assertEqual(services.call_number(self.req, self.driver), "9123456780")

    def test_the_view_redirects_to_the_dialler_with_the_indian_country_code(self):
        self.client.force_login(self.rider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "tel:+919876543210")

    def test_calling_is_open_today_and_tomorrow_only(self):
        for offset, allowed in ((0, True), (1, True), (2, False), (-1, False)):
            self.req.date = timezone.localdate() + timedelta(days=offset)
            if allowed:
                services.call_number(self.req, self.rider)
            else:
                with self.assertRaisesMessage(services.ChatError, "from the day it runs"):
                    services.call_number(self.req, self.rider)

    def test_only_an_accepted_booking_can_be_called(self):
        for status in (S.PENDING, S.COMPLETED, S.CANCELLED, S.REJECTED, S.NO_SHOW):
            self.req.status = status
            with self.assertRaises(services.ChatError):
                services.call_number(self.req, self.rider)

    def test_outsiders_cannot_call(self):
        with self.assertRaisesMessage(services.ChatError, "not yours"):
            services.call_number(self.req, self.outsider)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_a_missing_or_bad_phone_number_is_explained(self):
        for bad in ("", "12345", "abcdefghij"):
            self.driver.phone = bad
            self.driver.save()
            self.req = type(self.req).objects.select_related("ride__driver", "rider").get(pk=self.req.pk)
            with self.assertRaisesMessage(services.ChatError, "has not added a phone number"):
                services.call_number(self.req, self.rider)
        self.client.force_login(self.rider)
        response = self.client.get(self.url, follow=True)
        self.assertContains(response, "has not added a phone number")

    def test_anonymous_goes_to_login(self):
        self.assertIn("/accounts/login/", self.client.get(self.url)["Location"])

    def test_the_chat_page_shows_a_call_icon_but_never_the_number(self):
        self.client.force_login(self.rider)
        page = self.client.get(reverse("chat:thread", args=[self.req.pk]))
        self.assertContains(page, self.url)
        self.assertContains(page, "bi-telephone-fill")
        for secret in ("9876543210", "9123456780"):
            self.assertNotContains(page, secret)

    def test_the_chat_page_has_no_call_icon_when_calling_is_closed(self):
        self.req.date = timezone.localdate() + timedelta(days=5)
        self.req.save()
        self.client.force_login(self.rider)
        self.assertNotContains(self.client.get(reverse("chat:thread", args=[self.req.pk])), self.url)