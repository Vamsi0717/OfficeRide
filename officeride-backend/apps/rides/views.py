import logging
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.decorators import email_verified_required
from apps.fares import services as fare_services

from . import maps, matching, services
from .forms import OfferRideForm, ReturnTimeForm, SearchForm, UnavailableDateForm
from .models import CarUnavailableDate, Ride

logger = logging.getLogger(__name__)


def driver_required(view):
    """Email verified AND documents approved with valid insurance."""

    @email_verified_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.can_offer_rides:
            messages.warning(request, "To offer rides, your driver documents must be approved first.")
            return redirect("accounts:documents")
        return view(request, *args, **kwargs)

    return wrapper


@driver_required
def offer_ride(request):
    vehicle_type = request.user.driver_document.vehicle_type
    form = OfferRideForm(request.POST or None, vehicle_type=vehicle_type)
    if request.method == "POST" and form.is_valid():
        try:
            rides = services.create_ride(request.user, form.cleaned_data)
        except maps.MapsError as exc:
            form.add_error(None, str(exc))
        else:
            count = len(rides)
            text = "Your ride is live." if count == 1 else "Your ride and the way back are live."
            fare = fare_services.full_route_fare(rides[0])
            if fare:
                text += f" Each rider pays about ₹{fare.total} for the full route."
            messages.success(request, text)
            return redirect("rides:mine")
    vehicle_label = request.user.driver_document.get_vehicle_type_display()
    return render(request, "rides/offer.html", {"form": form, "vehicle_label": vehicle_label})


@email_verified_required
def my_rides(request):
    rides = list(Ride.objects.filter(driver=request.user).select_related("mileage_rate"))
    rates = fare_services.load_rates()
    for ride in rides:
        ride.full_fare = fare_services.full_route_fare(ride, rates)
    return render(request, "rides/mine.html", {"rides": rides})


@driver_required
@require_POST
def offer_back(request, pk):
    ride = get_object_or_404(Ride, pk=pk, driver=request.user)
    form = ReturnTimeForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose the time you leave for the way back.")
        return redirect("rides:mine")
    try:
        back = services.create_return_ride(ride, form.cleaned_data["return_time"])
    except services.ReturnRideError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"The way back is live: {back.origin_name} to {back.destination_name} at {back.departure_time:%I:%M %p}.")
    return redirect("rides:mine")


@email_verified_required
@require_POST
def toggle_ride(request, pk):
    ride = get_object_or_404(Ride, pk=pk, driver=request.user)
    if not ride.is_active and not request.user.can_offer_rides:
        messages.warning(request, "Your documents must be approved before this ride can go live again.")
        return redirect("rides:mine")
    ride.is_active = not ride.is_active
    ride.save(update_fields=["is_active"])
    messages.success(request, "Ride is live again." if ride.is_active else "Ride is switched off.")
    return redirect("rides:mine")


@email_verified_required
def ride_detail(request, pk):
    ride = get_object_or_404(Ride.objects.select_related("driver", "mileage_rate"), pk=pk)
    if not ride.is_active and ride.driver_id != request.user.id:
        return redirect("rides:find")
    fare = fare_services.full_route_fare(ride)
    return render(request, "rides/detail.html", {"ride": ride, "fare": fare, "is_owner": ride.driver_id == request.user.id})


def _search_values(form):
    """The rider's search, passed on to the Request button of each result."""
    return {name: form[name].value() or "" for name in (
        "date", "pickup_name", "pickup_lat", "pickup_lng", "drop_name", "drop_lat", "drop_lng",
    )}


@email_verified_required
def find_a_ride(request):
    searched = "date" in request.GET
    form = SearchForm(request.GET if searched else None, initial={"date": timezone.localdate()})
    matches = None
    if searched and form.is_valid():
        data = form.cleaned_data
        matches = matching.find_rides(
            rider=request.user,
            pickup=(data["pickup_lat"], data["pickup_lng"]),
            drop=(data["drop_lat"], data["drop_lng"]),
            on_date=data["date"],
            at_time=data["time"],
            vehicle_type=data["vehicle"] or None,
        )
        fare_services.attach_fares(matches)
    return render(
        request,
        "rides/find.html",
        {"form": form, "matches": matches, "window": settings.MATCH_TIME_WINDOW_MIN, "search": _search_values(form)},
    )


@driver_required
def unavailable_dates(request):
    form = UnavailableDateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        _, created = CarUnavailableDate.objects.get_or_create(
            driver=request.user,
            date=form.cleaned_data["date"],
            defaults={"reason": form.cleaned_data["reason"]},
        )
        messages.success(request, "Date saved." if created else "That date is already on your list.")
        return redirect("rides:unavailable")
    dates = CarUnavailableDate.objects.filter(driver=request.user, date__gte=timezone.localdate())
    return render(request, "rides/unavailable.html", {"form": form, "dates": dates})


@driver_required
@require_POST
def unavailable_delete(request, pk):
    get_object_or_404(CarUnavailableDate, pk=pk, driver=request.user).delete()
    messages.success(request, "Date removed.")
    return redirect("rides:unavailable")


@email_verified_required
@require_GET
def place_search(request):
    """JSON endpoint used by the place picker. Limited per user because map searches cost money."""
    query = request.GET.get("q", "").strip()
    if len(query) < 3:
        return JsonResponse({"results": []})

    key = f"place_search:{request.user.pk}:{timezone.now():%Y%m%d%H%M}"
    cache.add(key, 0, timeout=90)
    if cache.incr(key) > settings.PLACE_SEARCH_PER_MINUTE:
        return JsonResponse({"error": "Too many searches. Wait a moment."}, status=429)

    try:
        places = maps.search_places(query)
    except maps.MapsError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    return JsonResponse(
        {"results": [{"name": p.name, "address": p.address, "lat": p.lat, "lng": p.lng} for p in places]}
    )