"""What the API says about a person. Plain functions that return plain dictionaries."""

from apps.trust import services as trust_services


def documents_payload(user):
    doc = getattr(user, "driver_document", None)
    if doc is None:
        return None
    return {
        "status": doc.status,
        "vehicle_type": doc.vehicle_type,
        "rejection_reason": doc.rejection_reason,
        "insurance_expiry": doc.insurance_expiry.isoformat(),
        "usable": doc.is_usable,
    }


def user_payload(user):
    """The whole picture of one person that the app needs to draw its screens. The email is the login,
    and the phone is the 10 digits that are stored. Passwords and files are never in here."""
    return {
        "id": user.pk,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "country_code": "+91",
        "phone": user.phone,
        "home_area": user.home_area,
        "email_verified": user.email_verified,
        "can_offer_rides": user.can_offer_rides,
        "offered_vehicle_type": user.offered_vehicle_type,
        "blocked": {"is_blocked": user.is_blocked, "message": user.block_message},
        "documents": documents_payload(user),
        "stats": trust_services.rating_stats([user.pk])[user.pk],
        "strikes": trust_services.strike_summary(user),
    }


# ---- rides -----------------------------------------------------------------------------------------


def fare_payload(fare):
    """What one rider pays. Rupees are whole numbers; the parts are text with two decimals.
    The mileage the fare is worked out from is never in here."""
    if fare is None:
        return None
    return {
        "total": fare.total,
        "base_total": fare.base_total,
        "adjustment": fare.adjustment,
        "fuel": f"{fare.fuel:.2f}",
        "wear": f"{fare.wear:.2f}",
        "toll": f"{fare.toll:.2f}",
        "rider_km": f"{fare.rider_km:.1f}",
    }


def person_payload(user, stats=None):
    """A driver as a rider may see them: name and rating, never an email or a phone."""
    return {
        "id": user.pk,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "stats": stats if stats is not None else trust_services.rating_stats([user.pk])[user.pk],
    }


def ride_payload(ride, fare=None, include_route=False, include_driver=False, driver_stats=None):
    """One ride. fare is the full-route fare unless the caller worked out the fare for a rider's own trip."""
    data = {
        "id": ride.pk,
        "origin": {"name": ride.origin_name, "lat": ride.origin_lat, "lng": ride.origin_lng},
        "destination": {"name": ride.destination_name, "lat": ride.destination_lat, "lng": ride.destination_lng},
        "departure_time": ride.departure_time.strftime("%H:%M"),
        "office_days": sorted(ride.office_days_list),
        "office_days_display": ride.office_days_display,
        "seats": ride.seats,
        "vehicle_type": ride.vehicle_type,
        "vehicle_model": ride.car_model,
        "has_spare_helmet": ride.has_spare_helmet,
        "toll_total": ride.toll_total,
        "fare_adjustment": ride.fare_adjustment,
        "distance_km": ride.distance_km,
        "duration_min": ride.duration_min,
        "is_active": ride.is_active,
        "fare": fare_payload(fare),
    }
    if include_route:
        data["route_points"] = ride.route_points
    if include_driver:
        data["driver"] = person_payload(ride.driver, driver_stats)
    return data


def booking_summary_payload(ride):
    """Needs services.attach_booking_summary to have run on the ride."""
    nxt = ride.next_booked
    return {
        "runs_today": ride.runs_today,
        "runs_tomorrow": ride.runs_tomorrow,
        "booked_today": ride.booked_today,
        "booked_tomorrow": ride.booked_tomorrow,
        "waiting": ride.waiting,
        "next_booked": {"date": nxt[0].isoformat(), "riders": nxt[1]} if nxt else None,
    }


def match_payload(match):
    """One search result: the ride, the fare for THIS rider's trip, and how well it fits."""
    return {
        "ride": ride_payload(match.ride, fare=match.fare, include_driver=True, driver_stats=match.driver_stats),
        "rider_km": match.rider_km,
        "pickup_offset_km": match.pickup_offset_km,
        "drop_offset_km": match.drop_offset_km,
        "time_diff_min": match.time_diff_min,
    }


def unavailable_payload(entry):
    return {"id": entry.pk, "date": entry.date.isoformat(), "reason": entry.reason}