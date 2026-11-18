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