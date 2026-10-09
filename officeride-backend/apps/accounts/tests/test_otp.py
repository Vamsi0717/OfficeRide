import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import EmailOTP

User = get_user_model()


def last_code():
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


def age_codes(minutes):
    EmailOTP.objects.update(created_at=timezone.now() - timedelta(minutes=minutes))


class OTPServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("o@company.com", "S3cure-pass!")

    def test_code_is_emailed_but_only_a_hash_is_stored(self):
        services.send_otp(self.user)
        code = last_code()
        otp = EmailOTP.objects.get(user=self.user)
        self.assertEqual(len(code), 6)
        self.assertEqual(len(otp.code_hash), 64)
        self.assertNotEqual(otp.code_hash, code)

    def test_correct_code_verifies_the_email_once(self):
        services.send_otp(self.user)
        code = last_code()
        self.assertEqual(services.verify_otp(self.user, code), services.OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        self.assertEqual(services.verify_otp(self.user, code), services.NO_CODE)  # cannot be reused

    def test_wrong_code_counts_an_attempt(self):
        services.send_otp(self.user)
        wrong = "000000" if last_code() != "000000" else "111111"
        self.assertEqual(services.verify_otp(self.user, wrong), services.INVALID)
        self.assertEqual(EmailOTP.objects.get(user=self.user).attempts, 1)
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)

    def test_code_locks_after_too_many_attempts(self):
        services.send_otp(self.user)
        code = last_code()
        wrong = "000000" if code != "000000" else "111111"
        results = [services.verify_otp(self.user, wrong) for _ in range(settings.OTP_MAX_ATTEMPTS)]
        self.assertEqual(results[-1], services.LOCKED)
        self.assertEqual(services.verify_otp(self.user, code), services.LOCKED)  # even the right code
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)

    def test_expired_code(self):
        services.send_otp(self.user)
        code = last_code()
        age_codes(settings.OTP_EXPIRY_MINUTES + 1)
        self.assertEqual(services.verify_otp(self.user, code), services.EXPIRED)

    def test_new_code_replaces_the_old_one(self):
        services.send_otp(self.user)
        first = last_code()
        age_codes(5)
        services.send_otp(self.user)
        second = last_code()
        if first != second:
            self.assertNotEqual(services.verify_otp(self.user, first), services.OK)
        self.assertEqual(services.verify_otp(self.user, second), services.OK)

    def test_no_code_requested(self):
        self.assertEqual(services.verify_otp(self.user, "123456"), services.NO_CODE)

    def test_resend_cooldown(self):
        self.assertEqual(services.seconds_until_resend(self.user), 0)
        services.send_otp(self.user)
        self.assertTrue(0 < services.seconds_until_resend(self.user) <= settings.OTP_RESEND_SECONDS)
        age_codes(2)
        self.assertEqual(services.seconds_until_resend(self.user), 0)


class VerifyViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("v@company.com", "S3cure-pass!", first_name="V")
        self.client.force_login(self.user)
        self.url = reverse("accounts:verify")

    def test_page_loads_for_unverified_user(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_correct_code_verifies_and_redirects_to_profile(self):
        services.send_otp(self.user)
        response = self.client.post(self.url, {"code": last_code()})
        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)

    def test_wrong_code_shows_error(self):
        services.send_otp(self.user)
        wrong = "000000" if last_code() != "000000" else "111111"
        response = self.client.post(self.url, {"code": wrong}, follow=True)
        self.assertContains(response, "not correct")
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)

    def test_badly_formatted_code(self):
        response = self.client.post(self.url, {"code": "12ab"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "6-digit code")

    def test_resend_respects_cooldown(self):
        services.send_otp(self.user)
        self.assertEqual(len(mail.outbox), 1)
        self.client.post(self.url, {"resend": "1"})
        self.assertEqual(len(mail.outbox), 1)  # too soon, nothing sent
        age_codes(2)
        self.client.post(self.url, {"resend": "1"})
        self.assertEqual(len(mail.outbox), 2)

    def test_verified_user_is_redirected_away(self):
        self.user.email_verified = True
        self.user.save()
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)

    def test_anonymous_user_must_log_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])