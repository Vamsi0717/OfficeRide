from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import email_verified_required
from apps.bookings.models import RideRequest

from . import services
from .forms import ComplaintForm, ExplanationForm, RatingForm
from .models import Strike


def _my_request(request, pk):
    """A request the logged-in person is part of (as rider or driver), or a 404."""
    return get_object_or_404(
        RideRequest.objects.select_related("ride", "ride__driver", "rider").filter(Q(rider=request.user) | Q(ride__driver=request.user)),
        pk=pk,
    )


@email_verified_required
def rate(request, pk):
    req = _my_request(request, pk)
    rated = services.other_person(req, request.user)
    form = RatingForm(request.POST or None, rating_driver=rated.id == req.ride.driver_id)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.rate(req, request.user, data["stars"], data["tags"], data["comment"])
        except services.TrustError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Thank you. Your rating is saved.")
        return redirect("bookings:trips")
    return render(request, "trust/rate.html", {"form": form, "req": req, "rated": rated})


@email_verified_required
def report(request, pk):
    req = _my_request(request, pk)
    reported = services.other_person(req, request.user)
    form = ComplaintForm(request.POST or None, is_bike=req.ride.is_bike)
    if request.method == "POST" and form.is_valid():
        try:
            services.file_complaint(req, request.user, form.cleaned_data["kind"], form.cleaned_data["text"])
        except services.TrustError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Thank you. Our team will look into it.")
        return redirect("bookings:trips")
    return render(request, "trust/report.html", {"form": form, "req": req, "reported": reported})


@email_verified_required
@require_POST
def explain_strike(request, pk):
    strike = get_object_or_404(Strike, pk=pk, user=request.user)
    form = ExplanationForm(request.POST)
    if form.is_valid():
        services.add_explanation(strike, request.user, form.cleaned_data["explanation"])
        messages.success(request, "Your explanation is saved for the team to read.")
    else:
        messages.error(request, "Write a short explanation, up to 300 characters.")
    return redirect("accounts:profile")