import os
import sys

from .base import *  # noqa: F401,F403

DEBUG = True

# 10.0.2.2 is how the Android emulator reaches this computer. To try the app on a real phone, add your
# computer's address on the Wi-Fi to EXTRA_ALLOWED_HOSTS in .env, for example EXTRA_ALLOWED_HOSTS=192.168.1.5
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "10.0.2.2"] + [h.strip() for h in os.getenv("EXTRA_ALLOWED_HOSTS", "").split(",") if h.strip()]

# Emails (including the OTP code) are printed in the terminal that runs `runserver`.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Password hashing is deliberately slow. A fast hasher makes `manage.py test` much quicker.
# It is used only while running tests, never for a real server.
if "test" in sys.argv:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]