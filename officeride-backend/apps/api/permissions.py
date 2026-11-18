from rest_framework.permissions import BasePermission


class IsEmailVerified(BasePermission):
    """The person is logged in AND has typed the code from the email. Everything except signing up,
    logging in, entering the code and looking at your own profile needs this."""

    message = "Please verify your email first."
    code = "email_not_verified"

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.email_verified)