from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import email_verified_required
from apps.fares import services as fare_services
from apps.chat import services as chat_services
from apps.rides import matching
from apps.trust import services as trust_services
from apps.trust.models import Rating

from . import planner, services
from . import trips as trip_groups
from .forms import BackSearchForm, OverrideForm, RequestSeatForm, WeeklyPlanForm
from .models import PlanDay, RideRequest

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
    """My trips: two tabs, Riding (seats I asked for) and Driving (people who asked for a seat on my rides)."""
    user = request.user
    base = RideRequest.objects.select_related("ride", "ride__driver", "rider")
    riding = list(base.filter(rider=user)[:100])
    driving = list(base.filter(ride__driver=user)[:100])
    everything = riding + driving
    rated = set(Rating.objects.filter(rater=user, request__in=everything).values_list("request_id", flat=True))
    chat = chat_services.summary(user, [r.pk for r in everything])
    for reqs, other_is_driver in ((riding, True), (driving, False)):
        for req in reqs:
            req.other = req.ride.driver if other_is_driver else req.rider
            req.actions = services.allowed_actions(req, user)
            req.rated = req.pk in rated
            req.chat_total = chat.get(req.pk, {}).get("total", 0)
            req.chat_unread = chat.get(req.pk, {}).get("unread", 0)
            req.can_call = chat_services.call_window_open(req)
            req.other_has_phone = len(req.other.phone) == 10
    now = timezone.now()
    riding_sections = trip_groups.group(riding, as_driver=False, now=now)
    driving_sections = trip_groups.group(driving, as_driver=True, now=now)
    riding_counts, driving_counts = trip_groups.counts(riding_sections), trip_groups.counts(driving_sections)

    tab = request.GET.get("view")
    if tab not in ("riding", "driving"):
        # Open on the side that needs attention: people waiting for my reply, or the only side I use.
        tab = "driving" if driving_counts["waiting"] or (driving and not riding) else "riding"
    context = {
        "tab": tab, "is_driving": tab == "driving",
        "sections": driving_sections if tab == "driving" else riding_sections,
        "counts": driving_counts if tab == "driving" else riding_counts,
        "riding_counts": riding_counts, "driving_counts": driving_counts,
        "riding_unread": sum(r.chat_unread for r in riding), "driving_unread": sum(r.chat_unread for r in driving),
        "unread_total": sum(r.chat_unread for r in everything),
        "needs_phone": not user.phone and any(r.status == RideRequest.Status.ACCEPTED for r in everything),
    }
    return render(request, "bookings/trips.html", context)


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


@email_verified_required
def plan(request):
    """The weekly planner and one-off overrides."""
    can_drive = request.user.can_offer_rides
    initial = {f"day_{day}": mode for day, mode in planner.weekly_modes(request.user).items()}
    weekly = WeeklyPlanForm(request.POST if request.POST.get("form") == "weekly" else None, initial=initial, can_drive=can_drive, prefix="")
    override = OverrideForm(request.POST if request.POST.get("form") == "override" else None, can_drive=can_drive)
    if request.method == "POST":
        if request.POST.get("form") == "weekly" and weekly.is_valid():
            planner.save_weekly(request.user, weekly.modes())
            messages.success(request, "Your weekly plan is saved. It repeats every week.")
            return redirect("bookings:plan")
        if request.POST.get("form") == "override" and override.is_valid():
            planner.set_override(request.user, override.cleaned_data["date"], override.cleaned_data["mode"])
            messages.success(request, "That day is saved.")
            return redirect("bookings:plan")
    overrides = PlanDay.objects.filter(user=request.user, date__gte=timezone.localdate()).order_by("date")
    return render(request, "bookings/plan.html", {"weekly": weekly, "override": override, "overrides": overrides})


@email_verified_required
@require_POST
def plan_override_delete(request, pk):
    entry = get_object_or_404(PlanDay, pk=pk, user=request.user, date__isnull=False)
    entry.delete()
    messages.success(request, "That day is back to your weekly plan.")
    return redirect("bookings:plan")


@email_verified_required
def request_back(request, pk):
    """Find a ride for the way back: the same two places swapped, on a date and at a time the rider chooses."""
    booking = get_object_or_404(RideRequest, pk=pk, rider=request.user, status__in=[RideRequest.Status.ACCEPTED, RideRequest.Status.COMPLETED])
    searched = "date" in request.GET
    form = BackSearchForm(request.GET if searched else None, initial={"date": booking.date, "time": "18:00", "window": "30"})
    matches = None
    if searched and form.is_valid():
        data = form.cleaned_data
        matches = matching.find_rides(
            rider=request.user,
            pickup=(booking.drop_lat, booking.drop_lng),
            drop=(booking.pickup_lat, booking.pickup_lng),
            on_date=data["date"], at_time=data["time"], window_min=int(data["window"]),
        )
        fare_services.attach_fares(matches)
        trust_services.attach_driver_stats(matches)
    search = {
        "date": form["date"].value() or "", "pickup_name": booking.drop_name, "pickup_lat": booking.drop_lat,
        "pickup_lng": booking.drop_lng, "drop_name": booking.pickup_name, "drop_lat": booking.pickup_lat,
        "drop_lng": booking.pickup_lng,
    }
    return render(request, "bookings/back.html", {"booking": booking, "form": form, "matches": matches, "search": search})