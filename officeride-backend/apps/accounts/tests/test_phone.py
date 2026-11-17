from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.forms import normalise_phone
from django import forms

User = get_user_model()

SIGNUP = {
    "first_name": "Anil", "last_name": "Kumar", "email": "anil@company.com", "phone": "98765 43210",
    "password1": "Str0ng-pass-91", "password2": "Str0ng-pass-91",
}
PROFILE = {"first_name": "Anil", "last_name": "Kumar", "phone": "9876543210", "home_area": ""}


class NormaliseTests(TestCase):
    def test_common_ways_of_writing_a_number_all_become_ten_digits(self):
        for raw in ("9876543210", "98765 43210", "98765-43210", "+91 98765 43210", "+919876543210", "09876543210", " 9876543210 "):
            self.assertEqual(normalise_phone(raw), "9876543210", raw)

    def test_bad_numbers_are_refused(self):
        for raw in ("12345", "5876543210", "98765432101", "abcdefghij", "98765 4321", "+1 9876543210"):
            with self.assertRaises(forms.ValidationError, msg=raw):
                normalise_phone(raw)

    def test_an_empty_number_is_refused_with_a_clear_message(self):
        for raw in ("", "   ", None):
            with self.assertRaisesMessage(forms.ValidationError, "Enter your 10-digit mobile number."):
                normalise_phone(raw)
