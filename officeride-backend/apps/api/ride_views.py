"""Rides over the API: places, vehicles, fare preview, search, offer, my rides, one ride, and days the car is off.

The rules are the ones the old pages used. The forms check the input, and apps.rides.services,
apps.rides.matching and apps.fares.services do the work."""

import logging

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import VehicleType
from apps.fares import services as fare_services
from apps.fares.engine import MAX_ADJUSTMENT_RS
from apps.fares.models import MileageRate
from apps.rides import maps, matching, services
from apps.rides.forms import EditRideForm, FareAdjustmentForm, OfferRideForm, ReturnTimeForm, SearchForm, UnavailableDateForm
from apps.rides.models import CarUnavailableDate, Ride
from apps.trust import services as trust_services

from .permissions import IsApprovedDriver, IsEmailVerified
from .responses import invalid, problem
from .serializers import (
    booking_summary_payload, fare_payload, match_payload, ride_payload, unavailable_payload,
)

logger = logging.getLogger(__name__)


def blocked_response(user):
    """A suspended person, or one under review, may not offer rides. None when the person is fine."""
    if user.is_blocked:
        return problem(user.block_message, "account_blocked", status.HTTP_403_FORBIDDEN)
    return None


def ride_form_data(request_data, rename=True):
    """The request body as a plain dictionary the forms can read.

    The app says `vehicle_model` (the id of the model). The form calls it mileage_rate, and also wants the
    make, which always follows the model, so it is filled in here."""
    data = dict(request_data.items()) if hasattr(request_data, "items") else {}
    if hasattr(request_data, "getlist") and "office_days" in data:  # a form post: every ticked day, not just the last
        data["office_days"] = request_data.getlist("office_days")
    if rename and "vehicle_model" in data:
        data["mileage_rate"] = data.pop("vehicle_model")
    rate = MileageRate.objects.filter(pk=data.get("mileage_rate")).first() if str(data.get("mileage_rate", "")).isdigit() else None
    if rate is not None:
        data.setdefault("make", rate.make)
    return data


def ride_errors(form):
    """Form errors, with the form's own field name swapped for the one the app uses."""
    response = invalid(form)
    errors = response.data["errors"]
    if "mileage_rate" in errors:
        errors["vehicle_model"] = errors.pop("mileage_rate")
    if "make" in errors:
        errors.setdefault("vehicle_model", errors.pop("make"))
    return response


def one_ride(ride, **extra):
    return ride_payload(ride, fare=fare_services.full_route_fare(ride), **extra)


def own_live_ride(request, pk):
    """A ride of the logged-in driver that has not been deleted, or a 404."""
    return get_object_or_404(
        Ride.objects.select_related("driver", "mileage_rate"), pk=pk, driver=request.user, deleted_at__isnull=True
    )


# ---- places, vehicles, fare preview -----------------------------------------------------------------


class PlaceSearchView(APIView):
    """GET /places/?q=kor. Limited per person because map searches cost money."""

    permission_classes = [IsEmailVerified]

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if len(query) < 3:
            return Response({"results": []})
        key = f"api_place_search:{request.user.pk}:{timezone.now():%Y%m%d%H%M}"
        cache.add(key, 0, timeout=90)
        if cache.incr(key) > settings.PLACE_SEARCH_PER_MINUTE:
            return problem("Too many searches. Wait a moment.", "too_many_requests", status.HTTP_429_TOO_MANY_REQUESTS)
        try:
            places = maps.search_places(query)
        except maps.MapsError as exc:
            return problem(str(exc), "maps_unavailable", status.HTTP_502_BAD_GATEWAY)
        return Response({"results": [{"name": p.name, "address": p.address, "lat": p.lat, "lng": p.lng} for p in places]})


class VehicleListView(APIView):
    """GET /vehicles/?type=car. The makes and models to choose from. Never any mileage."""

    permission_classes = [IsEmailVerified]

    def get(self, request):
        kind = request.query_params.get("type") or request.user.offered_vehicle_type or VehicleType.CAR
        if kind not in (VehicleType.CAR, VehicleType.BIKE):
            return problem("type must be car or bike.", "invalid", status.HTTP_400_BAD_REQUEST)
        rates = MileageRate.objects.filter(vehicle_type=kind).exclude(make="").order_by("id")
        makes = {}
        for rate in rates:
            makes.setdefault(rate.make, []).append({"id": rate.pk, "name": rate.name, "full_name": rate.full_name})
        return Response({"vehicle_type": kind, "makes": [{"make": m, "models": models} for m, models in makes.items()]})


class FarePreviewForm(forms.Form):
    vehicle_model = forms.ModelChoiceField(queryset=MileageRate.objects.exclude(make=""))
    distance_km = forms.FloatField(min_value=1, max_value=200)
    seats = forms.IntegerField(min_value=1, max_value=settings.MAX_SEATS, required=False)
    toll_total = forms.IntegerField(min_value=0, max_value=settings.FARE_MAX_TOLL_RS, required=False)
    fare_adjustment = forms.IntegerField(min_value=-MAX_ADJUSTMENT_RS, max_value=MAX_ADJUSTMENT_RS, required=False)


class FarePreviewView(APIView):
    """GET /fare-preview/?vehicle_model=ID&distance_km=12&seats=3. What a rider would pay, with no map call."""

    permission_classes = [IsEmailVerified]

    def get(self, request):
        form = FarePreviewForm(request.query_params)
        if not form.is_valid():
            return ride_errors(form)
        data = form.cleaned_data
        rate = data["vehicle_model"]
        is_bike = rate.vehicle_type == VehicleType.BIKE
        ride = Ride(
            vehicle_type=rate.vehicle_type, mileage_rate=rate, seats=1 if is_bike else (data["seats"] or 3),
            route_distance_m=round(data["distance_km"] * 1000), toll_total=data["toll_total"] or 0,
            fare_adjustment=data["fare_adjustment"] or 0,
        )
        return Response({"fare": fare_payload(fare_services.full_route_fare(ride))})


# ---- search -----------------------------------------------------------------------------------------


class SearchView(APIView):
    """GET /rides/search/?pickup_name=..&pickup_lat=..&pickup_lng=..&drop_name=..&drop_lat=..&drop_lng=..&date=..&time=.."""

    permission_classes = [IsEmailVerified]

    def get(self, request):
        form = SearchForm(request.query_params)
        if not form.is_valid():
            return invalid(form)
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
        trust_services.attach_driver_stats(matches)
        return Response({
            "count": len(matches),
            "window_min": settings.MATCH_TIME_WINDOW_MIN,
            "results": [match_payload(m) for m in matches],
        })


# ---- offering and managing rides ----------------------------------------------------------------------


class RideListView(APIView):
    """POST /rides/ offers a ride (and the way back when asked)."""

    permission_classes = [IsApprovedDriver]

    def post(self, request):
        blocked = blocked_response(request.user)
        if blocked:
            return blocked
        form = OfferRideForm(ride_form_data(request.data), vehicle_type=request.user.driver_document.vehicle_type)
        if not form.is_valid():
            return ride_errors(form)
        try:
            rides = services.create_ride(request.user, form.cleaned_data)
        except maps.MapsError as exc:
            return problem(str(exc), "maps_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)
        rates = fare_services.load_rates()
        return Response(
            {"rides": [ride_payload(r, fare=fare_services.full_route_fare(r, rates)) for r in rides]},
            status=status.HTTP_201_CREATED,
        )


class MyRidesView(APIView):
    """GET /rides/mine/ the rides I offer: live ones, switched-off ones, and what is booked."""

    permission_classes = [IsEmailVerified]

    def get(self, request):
        rides = list(Ride.objects.filter(driver=request.user, deleted_at__isnull=True).select_related("mileage_rate"))
        rates = fare_services.load_rates()
        services.attach_booking_summary(rides)
        items = [
            {**ride_payload(r, fare=fare_services.full_route_fare(r, rates)), "summary": booking_summary_payload(r)}
            for r in rides
        ]
        return Response({
            "live": [i for i in items if i["is_active"]],
            "off": [i for i in items if not i["is_active"]],
            "waiting_total": sum(r.waiting for r in rides),
        })


class RideDetailView(APIView):
    """GET /rides/<id>/ anyone verified. PATCH and DELETE only the driver, who needs approved documents."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsEmailVerified()]
        return [IsApprovedDriver()]

    def get(self, request, pk):
        ride = get_object_or_404(Ride.objects.select_related("driver", "mileage_rate"), pk=pk, deleted_at__isnull=True)
        is_owner = ride.driver_id == request.user.id
        if not ride.is_active and not is_owner:
            return problem("This ride is not available.", "not_found", status.HTTP_404_NOT_FOUND)
        data = one_ride(ride, include_route=True, include_driver=True)
        data["is_owner"] = is_owner
        if is_owner:
            services.attach_booking_summary([ride])
            data["summary"] = booking_summary_payload(ride)
            data["max_adjustment"] = MAX_ADJUSTMENT_RS
        return Response(data)

    def patch(self, request, pk):
        ride = own_live_ride(request, pk)
        current = {
            "departure_time": ride.departure_time.strftime("%H:%M"),
            "office_days": [str(d) for d in ride.office_days_list],
            "seats": ride.seats,
            "mileage_rate": ride.mileage_rate_id,
            "toll_total": ride.toll_total,
            "fare_adjustment": ride.fare_adjustment,
            "has_spare_helmet": ride.has_spare_helmet,
        }
        sent = ride_form_data(request.data)
        if "mileage_rate" in sent:
            sent.pop("make", None)
            sent.setdefault("make", MileageRate.objects.filter(pk=sent["mileage_rate"]).values_list("make", flat=True).first() or "")
        else:
            current["make"] = ride.mileage_rate.make if ride.mileage_rate else ""
        current.update(sent)
        form = EditRideForm(current, ride=ride)
        if not form.is_valid():
            return ride_errors(form)
        try:
            ride = services.update_ride(ride, form.cleaned_data)
        except services.RideChangeError as exc:
            return problem(str(exc), "ride_change_refused", status.HTTP_409_CONFLICT)
        ride = Ride.objects.select_related("driver", "mileage_rate").get(pk=ride.pk)
        return Response(one_ride(ride))

    def delete(self, request, pk):
        ride = own_live_ride(request, pk)
        cancelled = services.delete_ride(ride)
        return Response({"deleted": True, "cancelled_bookings": cancelled})


class RideToggleView(APIView):
    """POST /rides/<id>/toggle/ switch a ride off, or on again."""

    permission_classes = [IsEmailVerified]

    def post(self, request, pk):
        ride = get_object_or_404(
            Ride.objects.select_related("mileage_rate"), pk=pk, driver=request.user, deleted_at__isnull=True
        )
        if not ride.is_active:
            if not request.user.can_offer_rides:
                return problem(
                    "Your documents must be approved before this ride can go live again.",
                    "driver_not_approved", status.HTTP_403_FORBIDDEN,
                )
            blocked = blocked_response(request.user)
            if blocked:
                return blocked
        ride.is_active = not ride.is_active
        ride.save(update_fields=["is_active"])
        return Response(one_ride(ride))


class RideFareView(APIView):
    """POST /rides/<id>/fare/ {"fare_adjustment": -5} the quick way to move the fare."""

    permission_classes = [IsApprovedDriver]

    def post(self, request, pk):
        ride = own_live_ride(request, pk)
        form = FareAdjustmentForm(ride_form_data(request.data, rename=False))
        if not form.is_valid():
            return problem(
                f"Enter a whole number from -{MAX_ADJUSTMENT_RS} to {MAX_ADJUSTMENT_RS}.", "invalid",
                status.HTTP_400_BAD_REQUEST, errors={"fare_adjustment": [m for e in form.errors.values() for m in e]},
            )
        try:
            ride = services.set_fare_adjustment(ride, form.cleaned_data["fare_adjustment"])
        except services.RideChangeError as exc:
            return problem(str(exc), "ride_change_refused", status.HTTP_409_CONFLICT)
        ride = Ride.objects.select_related("driver", "mileage_rate").get(pk=ride.pk)
        return Response(one_ride(ride))


class RideReturnView(APIView):
    """POST /rides/<id>/return/ {"return_time": "18:00"} offer the way back of a ride I already offer."""

    permission_classes = [IsApprovedDriver]

    def post(self, request, pk):
        blocked = blocked_response(request.user)
        if blocked:
            return blocked
        ride = own_live_ride(request, pk)
        form = ReturnTimeForm(ride_form_data(request.data, rename=False))
        if not form.is_valid():
            return invalid(form)
        try:
            back = services.create_return_ride(ride, form.cleaned_data["return_time"])
        except services.ReturnRideError as exc:
            return problem(str(exc), "return_exists", status.HTTP_409_CONFLICT)
        return Response(one_ride(back), status=status.HTTP_201_CREATED)


# ---- days the car is off -----------------------------------------------------------------------------


class UnavailableDatesView(APIView):
    """GET /unavailable-dates/ the coming days my car is off. POST adds one."""

    permission_classes = [IsApprovedDriver]

    def get(self, request):
        dates = CarUnavailableDate.objects.filter(driver=request.user, date__gte=timezone.localdate())
        return Response({"dates": [unavailable_payload(d) for d in dates]})

    def post(self, request):
        form = UnavailableDateForm(ride_form_data(request.data, rename=False))
        if not form.is_valid():
            return invalid(form)
        entry, created = CarUnavailableDate.objects.get_or_create(
            driver=request.user, date=form.cleaned_data["date"], defaults={"reason": form.cleaned_data["reason"]},
        )
        return Response(unavailable_payload(entry), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class UnavailableDateDeleteView(APIView):
    permission_classes = [IsApprovedDriver]

    def delete(self, request, pk):
        get_object_or_404(CarUnavailableDate, pk=pk, driver=request.user).delete()
        return Response({"deleted": True})