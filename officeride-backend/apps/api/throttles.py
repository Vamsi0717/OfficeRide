from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class AuthThrottle(SimpleRateThrottle):
    """Slows down guessing on register, login and resend-code. One counter for each address the request comes from."""

    scope = "auth"

    def get_rate(self):
        return settings.API_AUTH_RATE  # for example "30/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}