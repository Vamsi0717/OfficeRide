import re

from django.core import mail
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.api.views import tokens_for

PASSWORD = "S3cure-pass!"


def make_person(email="anita@acme.com", verified=True, **extra):
    extra.setdefault("first_name", "Anita")
    extra.setdefault("last_name", "Rao")
    extra.setdefault("phone", "9876543210")
    return User.objects.create_user(email, PASSWORD, email_verified=verified, **extra)


def client_for(user=None):
    """An API client. With a person it carries that person's login token, like the app does."""
    client = APIClient()
    if user is not None:
        client.credentials(HTTP_AUTHORIZATION="Bearer " + tokens_for(user)["access"])
    return client


def signup_body(**overrides):
    body = {
        "first_name": "Anita", "last_name": "Rao", "email": "anita@acme.com", "country_code": "+91",
        "phone": "98765 43210", "password1": PASSWORD, "password2": PASSWORD,
    }
    body.update(overrides)
    return body


def code_from_last_email():
    """The 6-digit code in the newest email, like a person reading their inbox."""
    return re.search(r"code is (\d{6})", mail.outbox[-1].body).group(1)


class FreshCache:
    """Each test starts with empty throttle counters."""

    def setUp(self):
        super().setUp()
        cache.clear()