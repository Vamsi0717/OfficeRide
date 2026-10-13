from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import email_verified_required

from . import services
from .forms import RequestSeatForm
from .models import RideRequest

DONE_MESSAGES = {
    "accept": "Request accepted. The rider has a seat.",
    "reject": "Request rejected.",
    "cancel": "Request cancelled.",
    "complete": "Ride marked completed.",
    "no-show": "No-show reported.",
}


@email_verified_required
@require_POST
def request_seat(request, ride_pk):
    form = RequestSeatForm(request.POST)
    if not form.is_valid():
        first = next(iter(form.errors.values()))[0]
        messages.error(request, first)
        return redirect("rides:find")
    data = form.cleaned_data
    try:
        services.request_seat(
            request.user, ride_pk, data["date"],
            pickup={"name": data["pickup_name"], "lat": data["pickup_lat"], "lng": data["pickup_lng"]},
            drop={"name": data["drop_name"], "lat": data["drop_lat"], "lng": data["drop_lng"]},
        )
    except services.BookingError as exc:
        messages.error(request, str(exc))
        return redirect("rides:find")
    messages.success(request, "Request sent. The driver will accept or reject it.")
    return redirect("bookings:trips")


@email_verified_required
def trips(request):
    user = request.user
    base = RideRequest.objects.select_related("ride", "ride__driver", "rider")
    requested = list(base.filter(rider=user)[:50])
    for_my_rides = list(base.filter(ride__driver=user)[:50])
    for req in requested + for_my_rides:
        req.actions = services.allowed_actions(req, user)
    return render(request, "bookings/trips.html", {"requested": requested, "for_my_rides": for_my_rides})


@email_verified_required
@require_POST
def act(request, pk, action):
    handler = services.ACTIONS.get(action)
    if handler is None:
        raise Http404
    # Someone who is neither the rider nor the driver gets a 404, so they cannot even tell the request exists.
    get_object_or_404(RideRequest.objects.filter(Q(rider=request.user) | Q(ride__driver=request.user)), pk=pk)
    try:
        handler(pk, request.user)
    except services.BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, DONE_MESSAGES[action])
    return redirect("bookings:trips")