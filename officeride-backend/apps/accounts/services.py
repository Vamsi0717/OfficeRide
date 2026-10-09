"""Business rules for email OTP. Views call these functions and never touch the codes directly."""

import math
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import EmailOTP

OK = "ok"
INVALID = "invalid"
EXPIRED = "expired"
LOCKED = "locked"
NO_CODE = "no_code"


def _hash(user, code):
    return salted_hmac("accounts.emailotp", f"{user.pk}:{code}", algorithm="sha256").hexdigest()


def seconds_until_resend(user):
    """Seconds the user must still wait before a new code may be requested (0 = allowed now)."""
    last = EmailOTP.objects.filter(user=user).first()  # newest first (Meta.ordering)
    if last is None:
        return 0
    waited = (timezone.now() - last.created_at).total_seconds()
    return max(0, math.ceil(settings.OTP_RESEND_SECONDS - waited))


@transaction.atomic
def send_otp(user):
    """Create a fresh 6-digit code, invalidate older ones, and email it. Rolls back if sending fails."""
    code = f"{secrets.randbelow(10**6):06d}"
    EmailOTP.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())
    EmailOTP.objects.create(user=user, code_hash=_hash(user, code))
    send_mail(
        subject="Your OfficeRide verification code",
        message=(
            f"Your OfficeRide verification code is {code}.\n"
            f"It expires in {settings.OTP_EXPIRY_MINUTES} minutes. "
            "If you did not sign up, you can ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


@transaction.atomic
def verify_otp(user, code):
    """Check a code. Returns OK, INVALID, EXPIRED, LOCKED or NO_CODE."""
    otp = (
        EmailOTP.objects.select_for_update()
        .filter(user=user, used_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if otp is None:
        return NO_CODE
    if timezone.now() > otp.created_at + timedelta(minutes=settings.OTP_EXPIRY_MINUTES):
        return EXPIRED
    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        return LOCKED
    if not constant_time_compare(otp.code_hash, _hash(user, code.strip())):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        return LOCKED if otp.attempts >= settings.OTP_MAX_ATTEMPTS else INVALID
    otp.used_at = timezone.now()
    otp.save(update_fields=["used_at"])
    user.email_verified = True
    user.save(update_fields=["email_verified"])
    return OK