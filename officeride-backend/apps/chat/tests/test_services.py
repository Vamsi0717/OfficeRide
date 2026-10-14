from django.test import TestCase, override_settings
from datetime import timedelta

from django.utils import timezone

from apps.chat import services
from apps.chat.models import ChatRead, Message

from .helpers import S, ChatMixin


class SendTests(ChatMixin, TestCase):
    def test_either_person_can_send(self):
        services.send(self.req, self.rider, "Hello")
        services.send(self.req, self.driver, "Hi Anita")
        self.assertEqual([m.text for m in Message.objects.all()], ["Hello", "Hi Anita"])

    def test_outsiders_cannot_send(self):
        with self.assertRaisesMessage(services.ChatError, "not yours"):
            services.send(self.req, self.outsider, "hi")
        self.assertEqual(Message.objects.count(), 0)

    def test_text_is_trimmed_and_cannot_be_empty(self):
        self.assertEqual(services.send(self.req, self.rider, "  hello  ").text, "hello")
        for blank in ("", "   ", None):
            with self.assertRaisesMessage(services.ChatError, "Write a message"):
                services.send(self.req, self.rider, blank)

    def test_500_characters_are_fine_501_are_not(self):
        services.send(self.req, self.rider, "a" * 500)
        with self.assertRaisesMessage(services.ChatError, "up to 500 characters"):
            services.send(self.req, self.rider, "a" * 501)
        self.assertEqual(Message.objects.count(), 1)

    @override_settings(CHAT_MAX_MESSAGES=3)
    def test_a_thread_has_a_message_limit(self):
        for _ in range(3):
            services.send(self.req, self.rider, "x")
        with self.assertRaisesMessage(services.ChatError, "message limit"):
            services.send(self.req, self.rider, "one more")

    def test_pending_and_accepted_can_write_everything_else_is_read_only(self):
        for status, writable in ((S.PENDING, True), (S.ACCEPTED, True), (S.COMPLETED, False), (S.CANCELLED, False),
                                 (S.REJECTED, False), (S.NO_SHOW, False)):
            req = self.make_booking(status, f"{status}@acme.com")
            if writable:
                services.send(req, req.rider, "hello")
            else:
                with self.assertRaisesMessage(services.ChatError, "closed"):
                    services.send(req, req.rider, "hello")

    def test_a_thread_stays_readable_after_the_ride_is_completed(self):
        services.send(self.req, self.rider, "See you")
        self.req.status = S.COMPLETED
        self.req.save()
        self.assertEqual(Message.objects.filter(request=self.req).count(), 1)

    def test_quick_replies(self):
        self.assertEqual(
            set(services.QUICK_REPLIES.values()),
            {"I'm at the pickup point", "Running 5 minutes late", "Can we meet at the midpoint?"},
        )
        services.send_quick(self.req, self.rider, "running-late")
        self.assertEqual(Message.objects.get().text, "Running 5 minutes late")
        with self.assertRaisesMessage(services.ChatError, "does not exist"):
            services.send_quick(self.req, self.rider, "make-me-rich")


class PickupTests(ChatMixin, TestCase):
    def test_confirming_saves_the_spot_on_the_booking_and_tells_the_other_person(self):
        services.confirm_pickup(self.req, self.driver, "Gate 3, Embassy Tech Village")
        self.req.refresh_from_db()
        self.assertEqual(self.req.agreed_pickup, "Gate 3, Embassy Tech Village")
        self.assertEqual(self.req.agreed_pickup_by, self.driver)
        self.assertIsNotNone(self.req.agreed_pickup_at)
        self.assertEqual(Message.objects.get().text, "Pickup point confirmed: Gate 3, Embassy Tech Village")

    def test_the_spot_can_be_changed_later(self):
        services.confirm_pickup(self.req, self.driver, "Gate 3")
        services.confirm_pickup(self.req, self.rider, "Gate 4")
        self.req.refresh_from_db()
        self.assertEqual((self.req.agreed_pickup, self.req.agreed_pickup_by), ("Gate 4", self.rider))

    def test_refusals(self):
        with self.assertRaisesMessage(services.ChatError, "not yours"):
            services.confirm_pickup(self.req, self.outsider, "Gate 3")
        with self.assertRaisesMessage(services.ChatError, "Write the pickup point"):
            services.confirm_pickup(self.req, self.rider, "  ")
        with self.assertRaisesMessage(services.ChatError, "under 120"):
            services.confirm_pickup(self.req, self.rider, "x" * 121)
        self.req.status = S.COMPLETED
        with self.assertRaisesMessage(services.ChatError, "closed"):
            services.confirm_pickup(self.req, self.rider, "Gate 3")


class UnreadTests(ChatMixin, TestCase):
    def test_a_new_message_is_unread_for_the_other_person_only(self):
        services.send(self.req, self.rider, "Hello")
        self.assertEqual(services.summary(self.driver, [self.req.pk])[self.req.pk], {"total": 1, "unread": 1})
        self.assertEqual(services.summary(self.rider, [self.req.pk])[self.req.pk], {"total": 1, "unread": 0})

    def test_opening_the_thread_marks_it_read_and_later_messages_are_unread_again(self):
        services.send(self.req, self.rider, "one")
        services.mark_read(self.req, self.driver)
        self.assertEqual(services.summary(self.driver, [self.req.pk])[self.req.pk]["unread"], 0)
        ChatRead.objects.filter(user=self.driver).update(last_read_at=timezone.now() - timedelta(minutes=5))
        services.send(self.req, self.rider, "two")
        self.assertEqual(services.summary(self.driver, [self.req.pk])[self.req.pk]["unread"], 2)

    def test_one_read_marker_per_person_per_booking(self):
        services.mark_read(self.req, self.driver)
        services.mark_read(self.req, self.driver)
        self.assertEqual(ChatRead.objects.count(), 1)

    def test_the_summary_uses_one_query_for_many_bookings(self):
        bookings = [self.make_booking(S.ACCEPTED, f"r{i}@acme.com") for i in range(5)]
        for b in bookings:
            services.send(b, b.rider, "hi")
        with self.assertNumQueries(1):
            result = services.summary(self.driver, [b.pk for b in bookings])
        self.assertEqual(len(result), 5)
        self.assertEqual(services.summary(self.driver, [self.req.pk]), {})  # no messages, no entry