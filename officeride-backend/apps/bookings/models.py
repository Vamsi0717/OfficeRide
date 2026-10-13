from datetime import datetime

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class RideRequest(models.Model):
    """One rider asking for one seat on one ride on one date. It also keeps the fare the rider was shown."""

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for the driver"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"
        NO_SHOW = "no_show", "No-show"

    ACTIVE = (Status.PENDING, Status.ACCEPTED)

    ride = models.ForeignKey("rides.Ride", on_delete=models.PROTECT, related_name="requests")
    rider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ride_requests")
    date = models.DateField()

    # Where the rider gets in and out, so the driver knows.
    pickup_name = models.CharField(max_length=200)
    pickup_lat = models.FloatField()
    pickup_lng = models.FloatField()
    drop_name = models.CharField(max_length=200)
    drop_lat = models.FloatField()
    drop_lng = models.FloatField()
    rider_distance_m = models.PositiveIntegerField()

    # The fare snapshot. Worked out once, when the request is made, and never changed afterwards,
    # so a later petrol price change or a change of the driver's adjustment cannot alter a booking.
    standard_fare = models.PositiveIntegerField()
    fare_adjustment = models.SmallIntegerField(default=0)
    fare = models.PositiveIntegerField(help_text="What the rider pays: the standard fare plus the driver's adjustment.")

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    late_cancel = models.BooleanField(default=False)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [
            # A rider can have only one live (pending or accepted) request per ride and date.
            models.UniqueConstraint(
                fields=["ride", "rider", "date"],
                condition=Q(status__in=["pending", "accepted"]),
                name="one_active_request_per_rider_ride_date",
            ),
        ]

    def __str__(self):
        return f"{self.rider} on ride {self.ride_id} for {self.date} ({self.status})"

    @property
    def departure_at(self):
        """The moment the ride leaves on this date, in local time."""
        return timezone.make_aware(datetime.combine(self.date, self.ride.departure_time))

    @property
    def is_active(self):
        return self.status in self.ACTIVE