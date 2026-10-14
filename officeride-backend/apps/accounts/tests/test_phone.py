from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.forms import normalise_phone
from django import forms

User = get_user_model()

SIGNUP = {
    "first_name": "Anil", "last_name": "Kumar", "email": "anil@company.com", "phone": "98765 43210",
    "techpark": "whitefield", "password1": "Str0ng-pass-91", "password2": "Str0ng-pass-91",
}
PROFILE = {"first_name": "Anil", "last_name": "Kumar", "phone": "9876543210", "home_area": "", "techpark": "whitefield"}


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


class SignupPhoneTests(TestCase):
    url = reverse("accounts:register")

    def test_the_signup_page_asks_for_a_mobile_number(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Mobile number")
        self.assertContains(page, 'inputmode="tel"')

    def test_signup_saves_the_number_as_ten_digits(self):
        self.client.post(self.url, SIGNUP)
        self.assertEqual(User.objects.get(email="anil@company.com").phone, "9876543210")

    def test_signup_without_a_number_is_refused_and_creates_no_account(self):
        response = self.client.post(self.url, {**SIGNUP, "phone": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter your 10-digit mobile number.")
        self.assertFalse(User.objects.exists())

    def test_signup_with_a_bad_number_is_refused(self):
        response = self.client.post(self.url, {**SIGNUP, "phone": "12345"})
        self.assertContains(response, "valid 10-digit")
        self.assertFalse(User.objects.exists())


class ProfilePhoneTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "old@company.com", "S3cure-pass!", first_name="Old", last_name="User", techpark="whitefield", email_verified=True)
        self.client.force_login(self.user)
        self.url = reverse("accounts:profile")

    def test_saving_the_profile_without_a_number_is_refused(self):
        response = self.client.post(self.url, {**PROFILE, "phone": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter your 10-digit mobile number.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "")

    def test_an_existing_user_without_a_number_can_add_one(self):
        response = self.client.post(self.url, {**PROFILE, "phone": "+91 98765 43210"})
        self.assertRedirects(response, self.url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "9876543210")

    def test_the_number_cannot_be_removed_later(self):
        self.user.phone = "9876543210"
        self.user.save()
        self.client.post(self.url, {**PROFILE, "phone": ""})
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "9876543210")

    def test_the_profile_field_is_labelled_mobile_number(self):
        self.assertContains(self.client.get(self.url), "Mobile number")


class MissingNumberBannerTests(TestCase):
    """People who signed up before the number was required are asked on every page until they add it."""

    def user(self, phone="", verified=True):
        user = User.objects.create_user(f"u{User.objects.count()}@company.com", "S3cure-pass!", phone=phone,
                                        first_name="A", last_name="B", techpark="whitefield", email_verified=verified)
        self.client.force_login(user)
        return user

    def test_a_verified_user_without_a_number_sees_the_banner_with_a_link_to_the_profile(self):
        self.user()
        page = self.client.get(reverse("rides:find"))
        self.assertContains(page, "Add your mobile number")
        self.assertContains(page, reverse("accounts:profile"))

    def test_nobody_else_sees_it(self):
        self.user(phone="9876543210")
        self.assertNotContains(self.client.get(reverse("rides:find")), "Add your mobile number")

    def test_an_unverified_user_is_not_nagged_before_verifying_their_email(self):
        self.user(verified=False)
        self.assertNotContains(self.client.get(reverse("accounts:verify")), "Add your mobile number")

    def test_the_banner_goes_away_once_a_number_is_saved(self):
        user = self.user()
        self.client.post(reverse("accounts:profile"), {**PROFILE, "phone": "9876543210"})
        user.refresh_from_db()
        self.assertNotContains(self.client.get(reverse("rides:find")), "Add your mobile number")