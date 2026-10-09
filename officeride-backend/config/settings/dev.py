from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Emails (including the OTP code) are printed in the terminal that runs `runserver`.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"