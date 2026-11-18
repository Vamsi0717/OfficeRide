import logging

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import services as account_services
from apps.accounts.forms import OTPForm, ProfileForm, RegisterForm

from .permissions import IsEmailVerified
from .responses import invalid, problem
from .serializers import user_payload
from .throttles import AuthThrottle

logger = logging.getLogger(__name__)

OTP_MESSAGES = {
    account_services.INVALID: "That code is not correct. Please try again.",
    account_services.EXPIRED: "That code has expired. Request a new one.",
    account_services.LOCKED: "Too many wrong attempts. Request a new code.",
    account_services.NO_CODE: "No active code. Request a new one.",
}


def tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def try_to_send_code(user):
    try:
        account_services.send_otp(user)
    except Exception:
        logger.exception("Could not send OTP email to user %s", user.pk)
        return False
    return True


class HealthView(APIView):
    """For the app to check that the server is there, and for you to check in a browser."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok", "name": "OfficeRide API", "version": 1})


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AuthThrottle]

    def post(self, request):
        form = RegisterForm(request.data)
        if not form.is_valid():
            return invalid(form)
        user = form.save()
        otp_sent = try_to_send_code(user)  # if the email fails the person can ask for the code again
        return Response(
            {"user": user_payload(user), "tokens": tokens_for(user), "otp_sent": otp_sent},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AuthThrottle]

    def post(self, request):
        email = str(request.data.get("email", "")).strip().lower()
        password = str(request.data.get("password", ""))
        user = authenticate(request, username=email, password=password)
        if user is None:
            # The same words whether the email is unknown or the password is wrong, so nobody can test which emails exist.
            return problem("Wrong email or password.", "bad_credentials", status.HTTP_401_UNAUTHORIZED)
        update_last_login(None, user)
        return Response({"user": user_payload(user), "tokens": tokens_for(user)})


class VerifyEmailView(APIView):
    """The person is logged in but has not typed the code yet, so this needs a login and nothing more."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.email_verified:
            return Response({"user": user_payload(user)})
        form = OTPForm(request.data)
        if not form.is_valid():
            return invalid(form)
        result = account_services.verify_otp(user, form.cleaned_data["code"])
        if result != account_services.OK:
            return problem(OTP_MESSAGES[result], result, status.HTTP_400_BAD_REQUEST)
        user.refresh_from_db()
        return Response({"user": user_payload(user)})


class ResendCodeView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthThrottle]

    def post(self, request):
        user = request.user
        if user.email_verified:
            return Response({"detail": "Your email is already verified."})
        wait = account_services.seconds_until_resend(user)
        if wait:
            return problem(
                f"Please wait {wait} seconds before asking for a new code.", "wait", status.HTTP_429_TOO_MANY_REQUESTS,
                wait=wait,
            )
        if not try_to_send_code(user):
            return problem(
                "We could not send the email. Please try again in a moment.", "email_failed",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"detail": "A new code has been sent.", "wait": settings.OTP_RESEND_SECONDS})


class MeView(APIView):
    """GET: who am I. PATCH: change my name, phone or area. Looking is allowed before the email is verified,
    because that is how the app learns that it must show the code screen. Changing needs a verified email."""

    def get_permissions(self):
        return [IsEmailVerified()] if self.request.method == "PATCH" else [IsAuthenticated()]

    def get(self, request):
        return Response(user_payload(request.user))

    def patch(self, request):
        user = request.user
        current = {
            "first_name": user.first_name, "last_name": user.last_name, "country_code": "+91",
            "phone": user.phone, "home_area": user.home_area,
        }
        form = ProfileForm({**current, **{k: v for k, v in request.data.items() if k in current}}, instance=user)
        if not form.is_valid():
            return invalid(form)
        form.save()
        return Response(user_payload(user))