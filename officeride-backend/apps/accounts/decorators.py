from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def email_verified_required(view):
    """Require a logged-in user whose email is verified; otherwise send them to the OTP page."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.email_verified:
            messages.info(request, "Please verify your email first.")
            return redirect("accounts:verify")
        return view(request, *args, **kwargs)

    return wrapper  