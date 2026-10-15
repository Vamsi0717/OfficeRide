"""Settings shared by every environment. Environment-specific values live in dev.py and prod.py."""

import os
from pathlib import Path

from django.contrib.messages import constants as message_constants
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# config/settings/base.py -> project root is three levels up
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY is missing. Copy .env.example to .env and set it.")

DEBUG = False
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.bookings",
    "apps.chat",
    "apps.core",
    "apps.fares",
    "apps.rides",
    "apps.trust",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

# A name inside the password is fine ("Vamsi@2026"), so there is no similarity check. A password needs 8
# characters with a letter, a number and a symbol, and must not be one of the most common passwords.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "apps.accounts.validators.PasswordMixValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Uploaded driver documents are private. MEDIA_URL is deliberately NOT set and the files are
# never served publicly; only staff can open them through accounts:document_file.
MEDIA_ROOT = BASE_DIR / "media"
DOCUMENT_MAX_MB = 5

# Login and messages
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:profile"
LOGOUT_REDIRECT_URL = "home"
MESSAGE_TAGS = {message_constants.ERROR: "danger"}

# Company-email rules
BLOCKED_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.in", "yahoo.co.in", "ymail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com",
    "proton.me", "protonmail.com", "aol.com", "rediffmail.com",
}
# Optional pilot allow-list, e.g. ALLOWED_EMAIL_DOMAINS=acme.com,globex.com. Empty means any
# company domain is accepted (personal domains above are always blocked).
ALLOWED_EMAIL_DOMAINS = {
    d.strip().lower() for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()
}

# Email OTP
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "OfficeRide <no-reply@officeride.local>")
OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60

# Maps and rides (Phase 3)
# "fake" works offline with sample Bangalore places. "google" needs GOOGLE_MAPS_API_KEY.
MAPS_PROVIDER = os.getenv("MAPS_PROVIDER", "fake")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
MAPS_TIMEOUT_SECONDS = 8
# Rides must start and end inside this box, which covers all of Bangalore.
BANGALORE_BOUNDS = {"south": 12.70, "west": 77.35, "north": 13.25, "east": 77.85}
BANGALORE_CENTER = (12.9716, 77.5946)

MAX_SEATS = 6
RIDE_MIN_DISTANCE_M = 1000      # start and end must be at least this far apart
MATCH_RADIUS_M = 1500           # rider's pickup and drop must be within this of the driver's route
MATCH_TIME_WINDOW_MIN = 15      # departure may differ from the rider's time by this many minutes
MATCH_MIN_TRIP_M = 500          # shortest shared stretch worth showing
PLACE_SEARCH_PER_MINUTE = 30    # place searches per user per minute (protects the maps bill)

# Fares (Phase 4)
FARE_MAX_TOLL_RS = 1000         # most a driver can enter as the toll for one trip

# Phase 5: booking
BOOKING_CLASH_MIN = 60          # a rider cannot hold two active requests whose rides leave within this many minutes
LATE_CANCEL_MIN = 60            # cancelling an accepted ride less than this many minutes before departure is "late"
BOOKING_DAYS_AHEAD = 60         # how far ahead a seat can be requested

# Strikes (Phase 6). Only strikes that are not waived and are younger than STRIKE_WINDOW_DAYS count.
STRIKE_WINDOW_DAYS = 90
STRIKE_SUSPEND_AT = 3           # the 3rd active strike suspends the account
STRIKE_REVIEW_AT = 5            # the 5th sends the account to an admin
SUSPENSION_DAYS = 7

# Chat (Phase 6)
CHAT_MAX_CHARS = 500            # one message
CHAT_MAX_MESSAGES = 200         # per booking, so a thread cannot be flooded
CALL_WINDOW_DAYS = 1            # the call button works from the ride day until this many days ahead (1 = today and tomorrow)