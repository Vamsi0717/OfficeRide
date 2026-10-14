from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.chat import services
from apps.chat.models import ChatRead, Message
from apps.rides.tests.helpers import make_user

from .helpers import S, ChatMixin


class ThreadPageTests(ChatMixin, TestCase):
    def url(self, name="thread", *extra):
        return reverse(f"chat:{name}", args=[self.req.pk, *extra])

    def test_anonymous_goes_to_login(self):
        self.assertIn("/accounts/login/", self.client.get(self.url())["Location"])

    def test_outsiders_get_a_404_on_every_page(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.client.post(self.url(), {"text": "hi"}).status_code, 404)
        self.assertEqual(self.client.post(self.url("quick", "midpoint")).status_code, 404)
        self.assertEqual(self.client.post(self.url("confirm_pickup"), {"spot": "x"}).status_code, 404)
        self.assertEqual(Message.objects.count(), 0)

    def test_the_two_people_see_each_others_messages_by_first_name(self):
        services.send(self.req, self.rider, "Where are you?")
        self.client.force_login(self.driver)
        page = self.client.get(self.url())
        self.assertContains(page, "Where are you?")
        self.assertContains(page, "Chat with Anita R.")

    def test_phone_numbers_and_emails_are_never_shown(self):
        services.send(self.req, self.rider, "Hello")
        for person in (self.rider, self.driver):
            self.client.force_login(person)
            html = self.client.get(self.url()).content.decode()
            for secret in ("9876543210", "9123456780", "rider@acme.com", "driver@acme.com"):
                self.assertNotIn(secret, html)

    def test_sending_a_message(self):
        self.client.force_login(self.rider)
        response = self.client.post(self.url(), {"text": "On my way"})
        self.assertRedirects(response, self.url())
        self.assertEqual(Message.objects.get().sender, self.rider)

    def test_an_over_long_message_is_refused_with_a_message(self):
        self.client.force_login(self.rider)
        response = self.client.post(self.url(), {"text": "a" * 501}, follow=True)
        self.assertContains(response, "up to 500 characters")
        self.assertEqual(Message.objects.count(), 0)

    def test_an_empty_message_is_refused(self):
        self.client.force_login(self.rider)
        self.client.post(self.url(), {"text": "   "})
        self.assertEqual(Message.objects.count(), 0)

    def test_quick_replies_and_unknown_keys(self):
        self.client.force_login(self.driver)
        self.client.post(self.url("quick", "at-pickup"))
        self.assertEqual(Message.objects.get().text, "I'm at the pickup point")
        response = self.client.post(self.url("quick", "nope"), follow=True)
        self.assertContains(response, "does not exist")
        self.assertEqual(Message.objects.count(), 1)

    def test_quick_replies_need_a_post(self):
        self.client.force_login(self.driver)
        self.assertEqual(self.client.get(self.url("quick", "midpoint")).status_code, 405)

    def test_confirming_the_pickup_point_shows_it_on_the_thread_and_on_my_trips(self):
        self.client.force_login(self.rider)
        self.client.post(self.url("confirm_pickup"), {"spot": "Gate 3"})
        self.assertContains(self.client.get(self.url()), "Gate 3")
        self.assertContains(self.client.get(reverse("bookings:trips")), "Meeting spot")

    def test_a_closed_thread_is_readable_but_has_no_form(self):
        services.send(self.req, self.rider, "Thanks")
        self.req.status = S.COMPLETED
        self.req.save()
        self.client.force_login(self.rider)
        page = self.client.get(self.url())
        self.assertContains(page, "Thanks")
        self.assertContains(page, "This chat is closed")
        self.assertNotContains(page, "Confirm pickup point")
        self.client.post(self.url(), {"text": "late"}, follow=True)
        self.assertEqual(Message.objects.count(), 1)

    def test_opening_the_thread_marks_it_read(self):
        services.send(self.req, self.rider, "Hello")
        self.client.force_login(self.driver)
        self.client.get(self.url())
        self.assertEqual(ChatRead.objects.get().user, self.driver)
        self.assertEqual(services.summary(self.driver, [self.req.pk])[self.req.pk]["unread"], 0)


class TripsPageTests(ChatMixin, TestCase):
    def test_the_trips_page_shows_chat_buttons_and_unread_counts(self):
        services.send(self.req, self.rider, "One")
        services.send(self.req, self.rider, "Two")
        self.client.force_login(self.driver)
        page = self.client.get(reverse("bookings:trips"))
        self.assertContains(page, reverse("chat:thread", args=[self.req.pk]))
        self.assertContains(page, "You have 2 unread messages")
        self.client.get(reverse("chat:thread", args=[self.req.pk]))
        self.assertNotContains(self.client.get(reverse("bookings:trips")), "unread message")

    def test_my_own_messages_are_not_unread_for_me(self):
        services.send(self.req, self.rider, "One")
        self.client.force_login(self.rider)
        self.assertNotContains(self.client.get(reverse("bookings:trips")), "unread message")

    def test_finished_trips_show_view_chat_only_when_there_are_messages(self):
        done = self.make_booking(S.COMPLETED, "done@acme.com")
        quiet = self.make_booking(S.COMPLETED, "quiet@acme.com")
        services.send(self.req, self.rider, "x")  # a different, active booking
        done.status = S.ACCEPTED
        done.save()
        services.send(done, done.rider, "Thanks for the ride")
        done.status = S.COMPLETED
        done.save()
        self.client.force_login(self.driver)
        page = self.client.get(reverse("bookings:trips"))
        self.assertContains(page, reverse("chat:thread", args=[done.pk]))
        self.assertNotContains(page, reverse("chat:thread", args=[quiet.pk]))
        self.assertContains(page, "View chat")

    def test_the_trips_page_query_count_does_not_grow_with_messages(self):
        self.client.force_login(self.driver)
        services.send(self.req, self.rider, "first")
        with CaptureQueriesContext(connection) as few:
            self.client.get(reverse("bookings:trips"))
        for i in range(10):
            services.send(self.req, self.rider, f"m{i}")
        with CaptureQueriesContext(connection) as many:
            self.client.get(reverse("bookings:trips"))
        self.assertEqual(len(few), len(many))


class AdminTests(ChatMixin, TestCase):
    def test_the_admin_can_read_messages_but_not_add_them(self):
        admin = make_user("admin@acme.com", is_staff=True, is_superuser=True)
        services.send(self.req, self.rider, "Hello")
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("admin:chat_message_changelist")), "Hello")
        self.assertEqual(self.client.get(reverse("admin:chat_message_add")).status_code, 403)