import logging
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from . import services
from .decorators import email_verified_required
from .forms import DriverDocumentForm, OTPForm, ProfileForm, RegisterForm
from .models import DriverDocument

logger = logging.getLogger(__name__)

OTP_MESSAGES = {
    services.INVALID: "That code is not correct. Please try again.",
    services.EXPIRED: "That code has expired. Request a new one.",
    services.LOCKED: "Too many wrong attempts. Request a new code.",
    services.NO_CODE: "No active code. Request a new one.",
}


def _send_otp_or_warn(request, user):
    try:
        services.send_otp(user)
    except Exception:
        logger.exception("Could not send OTP email to user %s", user.pk)
        messages.error(request, "We could not send the email. Please try again in a moment.")
        return False
    return True


def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:profile")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        if _send_otp_or_warn(request, user):
            messages.success(request, "Account created. We emailed you a 6-digit code.")
        return redirect("accounts:verify")
    return render(request, "accounts/register.html", {"form": form})


@login_required
def verify_email(request):
    user = request.user
    if user.email_verified:
        return redirect("accounts:profile")

    if request.method == "POST" and "resend" in request.POST:
        wait = services.seconds_until_resend(user)
        if wait:
            messages.warning(request, f"Please wait {wait} seconds before requesting a new code.")
        elif _send_otp_or_warn(request, user):
            messages.success(request, "A new code has been sent.")
        return redirect("accounts:verify")

    form = OTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        result = services.verify_otp(user, form.cleaned_data["code"])
        if result == services.OK:
            messages.success(request, "Email verified. Welcome to OfficeRide!")
            return redirect("accounts:profile")
        messages.error(request, OTP_MESSAGES[result])
        return redirect("accounts:verify")

    context = {
        "form": form,
        "wait": services.seconds_until_resend(user),
        "expiry_minutes": settings.OTP_EXPIRY_MINUTES,
        "dev_hint": settings.DEBUG,
    }
    return render(request, "accounts/verify.html", context)


@email_verified_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile saved.")
        return redirect("accounts:profile")
    doc = DriverDocument.objects.filter(user=request.user).first()
    return render(request, "accounts/profile.html", {"form": form, "doc": doc})


@email_verified_required
def documents(request):
    doc = DriverDocument.objects.filter(user=request.user).first()
    form = DriverDocumentForm(
        request.POST or None, request.FILES or None, instance=doc or DriverDocument(user=request.user)
    )
    if request.method == "POST" and form.is_valid():
        if doc and not form.has_changed():
            messages.info(request, "No changes to save.")
        else:
            form.save()
            messages.success(request, "Documents submitted. An admin will review them shortly.")
        return redirect("accounts:documents")
    return render(request, "accounts/documents.html", {"form": form, "doc": doc})


@login_required
@require_http_methods(["GET"])
def document_file(request, pk, kind):
    """Staff-only view of an uploaded document. Files are never exposed through a public URL."""
    if not request.user.has_perm("accounts.view_driverdocument"):
        raise Http404
    if kind not in ("licence", "rc", "insurance"):
        raise Http404
    doc = get_object_or_404(DriverDocument, pk=pk)
    stored = getattr(doc, f"{kind}_file")
    if not stored:
        raise Http404
    return FileResponse(stored.open("rb"), filename=Path(stored.name).name)