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
