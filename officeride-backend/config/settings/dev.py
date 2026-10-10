import sys

from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Emails (including the OTP code) are printed in the terminal that runs `runserver`.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Password hashing is deliberately slow. A fast hasher makes `manage.py test` much quicker.
# It is used only while running tests, never for a real server.
if "test" in sys.argv:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]