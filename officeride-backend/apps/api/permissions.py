from rest_framework.permissions import BasePermission


class IsEmailVerified(BasePermission):
    """The person is logged in AND has typed the code from the email. Everything except signing up,
    logging in, entering the code and looking at your own profile needs this."""

    message = "Please verify your email first."
    code = "email_not_verified"

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.email_verified)


class IsApprovedDriver(BasePermission):
    """Verified email AND driver documents approved with valid insurance. Offering and managing rides needs this."""

    message = "To offer rides, your driver documents must be approved first."
    code = "driver_not_approved"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if not user.email_verified:
            self.message = IsEmailVerified.message  # the first thing to fix is the email code
            return False
        self.message = type(self).message
        return user.can_offer_rides