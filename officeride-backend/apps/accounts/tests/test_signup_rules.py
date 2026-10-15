from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.forms import RegisterForm

User = get_user_model()

SIGN_UP = {
    "first_name": "Vamsi", "last_name": "Kumar", "email": "vamsi@company.com", "country_code": "+91",
    "phone": "9876543210", "password1": "Vamsi@2026", "password2": "Vamsi@2026",
}


class PasswordRuleTests(TestCase):
    """A password needs 8 characters with a letter, a number and a symbol. A name inside it is fine."""

    def post(self, password):
        return self.client.post(reverse("accounts:register"), {**SIGN_UP, "password1": password, "password2": password})

    def test_a_name_with_a_number_and_a_symbol_is_allowed(self):
        self.assertEqual(self.post("Vamsi@2026").status_code, 302)  # the person's own name, no similarity check
        self.assertTrue(User.objects.filter(email="vamsi@company.com").exists())

    def test_each_missing_part_is_refused(self):
        for bad in ("Vamsi2026", "Vamsi@Kumar", "12345@678", "@@@@@@@@@"):
            with self.subTest(bad):
                response = self.post(bad)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "one letter, one number and one symbol")
                self.assertFalse(User.objects.exists())

    def test_fewer_than_eight_characters_is_refused(self):
        response = self.post("Ab@1xyz")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at least 8 characters")
        self.assertFalse(User.objects.exists())

    def test_a_very_common_password_is_still_refused(self):
        response = self.post("password")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_two_different_passwords_are_refused(self):
        response = self.client.post(reverse("accounts:register"), {**SIGN_UP, "password2": "Other@2026"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())


class SignUpPageTextTests(TestCase):
    def setUp(self):
        self.page = self.client.get(reverse("accounts:register"))

    def test_the_four_default_password_rules_are_gone(self):
        for old in (
            "too similar to your other personal information", "can’t be a commonly used password",
            "can’t be entirely numeric", "Enter the same password as before, for verification.",
        ):
            with self.subTest(old):
                self.assertNotContains(self.page, old)
        self.assertContains(self.page, "At least 8 characters with a letter, a number and a symbol.")
        self.assertContains(self.page, "Type it once more so we know it is right.")

    def test_the_gmail_note_and_the_phone_note_are_gone(self):
        self.assertNotContains(self.page, "Personal addresses such as Gmail are not accepted.")
        self.assertNotContains(self.page, "Only the person you share a ride with can call you")

    def test_the_mobile_number_has_a_country_code_select(self):
        self.assertContains(self.page, '<select name="country_code"')
        self.assertContains(self.page, 'value="+91"')

    def test_tech_park_is_not_asked(self):
        self.assertNotContains(self.page, "Tech park")
        self.assertNotIn("techpark", RegisterForm().fields)

    def test_a_personal_email_gets_the_new_message(self):
        response = self.client.post(reverse("accounts:register"), {**SIGN_UP, "email": "me@gmail.com"})
        self.assertContains(response, "That looks like a personal email. Sign up with your office email")
        self.assertFalse(User.objects.exists())

    def test_the_country_code_is_not_needed_in_the_post(self):
        data = {k: v for k, v in SIGN_UP.items() if k != "country_code"}
        self.assertEqual(self.client.post(reverse("accounts:register"), data).status_code, 302)


class ProfilePageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "anil@company.com", "S3cure-pass!", first_name="Anil", last_name="K", phone="9876543210",
            email_verified=True,
        )
        self.client.force_login(self.user)

    def test_profile_has_no_tech_park_and_keeps_the_country_code(self):
        page = self.client.get(reverse("accounts:profile"))
        self.assertNotContains(page, "Tech park")
        self.assertContains(page, '<select name="country_code"')

    def test_profile_saves_without_a_tech_park(self):
        response = self.client.post(reverse("accounts:profile"), {
            "first_name": "Anil", "last_name": "Kumar", "country_code": "+91", "phone": "9876543210", "home_area": "HSR",
        })
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_area, "HSR")