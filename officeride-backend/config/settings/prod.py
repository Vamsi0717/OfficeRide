import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

# Production hardening (HTTPS, hosts, static files) is added in Phase 10.
DEBUG = False

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1") == "1"

# Sample places and straight-line routes must never reach real users.
if MAPS_PROVIDER != "google" or not GOOGLE_MAPS_API_KEY:  # noqa: F405
    raise ImproperlyConfigured("Production needs MAPS_PROVIDER=google and GOOGLE_MAPS_API_KEY.")