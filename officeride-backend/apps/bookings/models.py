from datetime import datetime

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class PlanDay(models.Model):
    """What a person plans to do on a day: drive, ride with someone, or not go to the office.

    A row with a weekday repeats every week. A row with a date is a one-off override for that day."""

    class Mode(models.TextChoices):
        DRIVING = "driving", "Driving"
        RIDING = "riding", "Riding with someone"
        NOT_GOING = "not_going", "Not going to the office"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="plan_days")
    weekday = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Monday is 0. Empty for a one-off date.")
    date = models.DateField(null=True, blank=True, help_text="Set for a one-off override. Empty for a weekly row.")
    mode = models.CharField(max_length=10, choices=Mode.choices)

    class Meta:
        ordering = ["weekday", "date"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(weekday__isnull=False, date__isnull=True) & Q(weekday__lte=6))
                | (Q(weekday__isnull=True, date__isnull=False)),
                name="plan_day_is_weekly_or_one_off",
            ),
            models.UniqueConstraint(fields=["user", "weekday"], condition=Q(weekday__isnull=False), name="one_plan_per_user_weekday"),
            models.UniqueConstraint(fields=["user", "date"], condition=Q(date__isnull=False), name="one_override_per_user_date"),
        ]

    def __str__(self):
        return f"{self.user} {self.date or self.weekday}: {self.mode}"


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
    # The spot the two people agreed on in chat. Empty until someone confirms it.
    agreed_pickup = models.CharField(max_length=120, blank=True)
    agreed_pickup_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    agreed_pickup_at = models.DateTimeField(null=True, blank=True)
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