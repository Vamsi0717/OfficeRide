from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

from .helpers import FreshCache, PASSWORD, client_for, make_person, signup_body


class RegisterTests(FreshCache, TestCase):
    def register(self, **overrides):
        return client_for().post(reverse("api:register"), signup_body(**overrides), format="json")

    def test_a_good_signup_makes_an_unverified_account_sends_a_code_and_logs_in(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["otp_sent"])
        self.assertFalse(data["user"]["email_verified"])
        self.assertEqual(data["user"]["phone"], "9876543210")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["anita@acme.com"])
        user = User.objects.get(email="anita@acme.com")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.email_verified)

    def test_the_tokens_from_signup_work_straight_away(self):
        tokens = self.register().json()["tokens"]
        client = client_for()
        client.credentials(HTTP_AUTHORIZATION="Bearer " + tokens["access"])
        self.assertEqual(client.get(reverse("api:me")).json()["email"], "anita@acme.com")

    def test_the_phone_is_tidied_to_ten_digits(self):
        for typed in ("+91 98765-43210", "098765 43210", "9876543210"):
            with self.subTest(typed=typed):
                User.objects.all().delete()
                self.assertEqual(self.register(phone=typed).json()["user"]["phone"], "9876543210")

    def test_a_personal_email_is_refused_with_the_same_message_as_before(self):
        response = self.register(email="anita@gmail.com")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "invalid")
        self.assertIn("personal email", body["errors"]["email"][0])
        self.assertFalse(User.objects.exists())

    def test_an_email_that_is_already_used_is_refused(self):
        make_person()
        response = self.register()
        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.json()["errors"]["email"][0])

    def test_the_email_is_not_case_sensitive(self):
        make_person()
        self.assertEqual(self.register(email="ANITA@acme.com").status_code, 400)

    def test_a_weak_password_is_refused(self):
        for weak in ("short1!", "onlyletters", "12345678"):
            with self.subTest(password=weak):
                response = self.register(password1=weak, password2=weak)
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.json()["errors"])

    def test_two_different_passwords_are_refused(self):
        response = self.register(password2="Different-pass1!")
        self.assertEqual(response.status_code, 400)
        self.assertIn("password2", response.json()["errors"])

    def test_a_bad_phone_is_refused(self):
        for bad in ("12345", "5876543210", "abc", ""):
            with self.subTest(phone=bad):
                response = self.register(phone=bad)
                self.assertEqual(response.status_code, 400)
                self.assertIn("phone", response.json()["errors"])

    def test_names_are_required(self):
        response = self.register(first_name="", last_name="")
        self.assertEqual(sorted(response.json()["errors"]), ["first_name", "last_name"])

    def test_every_mistake_is_reported_at_once(self):
        response = self.register(email="a@gmail.com", phone="1", first_name="")
        self.assertEqual(sorted(response.json()["errors"]), ["email", "first_name", "phone"])

    @override_settings(ALLOWED_EMAIL_DOMAINS={"acme.com"})
    def test_only_the_pilot_companies_may_sign_up_when_a_list_is_set(self):
        self.assertEqual(self.register(email="a@other.com").status_code, 400)
        self.assertEqual(self.register(email="a@acme.com").status_code, 201)

    def test_if_the_email_cannot_be_sent_the_account_is_still_made_and_the_app_is_told(self):
        with mock.patch("apps.api.views.account_services.send_otp", side_effect=RuntimeError("mail server down")), \
                self.assertLogs("apps.api.views", level="ERROR"):
            response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()["otp_sent"])
        self.assertTrue(User.objects.filter(email="anita@acme.com").exists())

    def test_a_signup_needs_no_login(self):
        self.assertEqual(self.register().status_code, 201)

    def test_the_password_never_comes_back_in_an_answer(self):
        self.assertNotIn(PASSWORD, self.register().content.decode())


class LoginTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.person = make_person()

    def login(self, email="anita@acme.com", password=PASSWORD):
        return client_for().post(reverse("api:login"), {"email": email, "password": password}, format="json")

    def test_a_good_login_gives_tokens_and_the_person(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["user"]["email"], "anita@acme.com")
        self.assertTrue(data["user"]["email_verified"])
        self.assertTrue(data["tokens"]["access"] and data["tokens"]["refresh"])

    def test_the_email_may_have_capitals_and_spaces(self):
        self.assertEqual(self.login(email="  ANITA@Acme.com ").status_code, 200)

    def test_a_wrong_password_and_an_unknown_email_get_the_same_answer(self):
        wrong = self.login(password="Wrong-pass1!")
        unknown = self.login(email="nobody@acme.com")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(wrong.json()["code"], "bad_credentials")

    def test_a_missing_password_is_401_not_a_crash(self):
        response = client_for().post(reverse("api:login"), {"email": "anita@acme.com"}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_a_switched_off_account_cannot_log_in(self):
        self.person.is_active = False
        self.person.save()
        self.assertEqual(self.login().status_code, 401)

    def test_an_unverified_person_can_log_in_and_is_told_to_verify(self):
        make_person("new@acme.com", verified=False)
        data = self.login(email="new@acme.com").json()
        self.assertFalse(data["user"]["email_verified"])

    def test_a_suspended_person_can_log_in_and_sees_why(self):
        from datetime import timedelta
        from django.utils import timezone
        self.person.suspended_until = timezone.now() + timedelta(days=3)
        self.person.save()
        data = self.login().json()
        self.assertTrue(data["user"]["blocked"]["is_blocked"])
        self.assertIn("suspended until", data["user"]["blocked"]["message"])

    @override_settings(API_AUTH_RATE="3/min")
    def test_too_many_tries_in_a_minute_are_slowed_down(self):
        for _ in range(3):
            self.assertEqual(self.login(password="Wrong-pass1!").status_code, 401)
        response = self.login()  # even the right password has to wait
        self.assertEqual(response.status_code, 429)

    def test_last_login_is_recorded(self):
        self.login()
        self.person.refresh_from_db()
        self.assertIsNotNone(self.person.last_login)