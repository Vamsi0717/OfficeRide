from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.chat import services
from apps.chat.models import ChatRead, Message
from apps.rides.tests.helpers import make_user

from .helpers import S, ChatMixin


class AdminTests(ChatMixin, TestCase):
    def test_the_admin_can_read_messages_but_not_add_them(self):
        admin = make_user("admin@acme.com", is_staff=True, is_superuser=True)
        services.send(self.req, self.rider, "Hello")
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("admin:chat_message_changelist")), "Hello")
        self.assertEqual(self.client.get(reverse("admin:chat_message_add")).status_code, 403)
