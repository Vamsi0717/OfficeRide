from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

WEEKDAYS = [(0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri"), (5, "Sat"), (6, "Sun")]


class Ride(models.Model):
    """A commute a driver already makes and is willing to share. It repeats on the chosen weekdays."""

    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rides")

    origin_name = models.CharField(max_length=200)
    origin_lat = models.FloatField()
    origin_lng = models.FloatField()
    destination_name = models.CharField(max_length=200)
    destination_lat = models.FloatField()
    destination_lng = models.FloatField()

    departure_time = models.TimeField()
    office_days = models.CharField(max_length=13, help_text="Weekday numbers, Monday is 0, e.g. 0,1,2,3,4")
    seats = models.PositiveSmallIntegerField()
    car_model = models.CharField(max_length=60)

    # The driving route from the maps service, kept so searches need no map calls.
    route_points = models.JSONField(default=list)
    route_distance_m = models.PositiveIntegerField()
    route_duration_s = models.PositiveIntegerField()
    min_lat = models.FloatField()
    max_lat = models.FloatField()
    min_lng = models.FloatField()
    max_lng = models.FloatField()

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["departure_time", "id"]
        indexes = [models.Index(fields=["is_active", "departure_time"])]
        constraints = [
            models.CheckConstraint(condition=Q(seats__gte=1) & Q(seats__lte=6), name="ride_seats_1_to_6"),
        ]

    def __str__(self):
        return f"{self.origin_name} to {self.destination_name} at {self.departure_time:%H:%M}"

    @property
    def office_days_list(self):
        return [int(d) for d in self.office_days.split(",") if d != ""]

    @property
    def office_days_display(self):
        names = dict(WEEKDAYS)
        return ", ".join(names[d] for d in sorted(self.office_days_list))

    @property
    def distance_km(self):
        return round(self.route_distance_m / 1000, 1)

    @property
    def duration_min(self):
        return round(self.route_duration_s / 60)

    def runs_on(self, date):
        return date.weekday() in self.office_days_list


class CarUnavailableDate(models.Model):
    """A day the driver's car is not available (service, repair, leave). Rides do not appear that day."""

    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="unavailable_dates")
    date = models.DateField()
    reason = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["driver", "date"], name="one_unavailable_entry_per_driver_day"),
        ]

    def __str__(self):
        return f"{self.driver} unavailable on {self.date}"

    @property
    def is_past(self):
        return self.date < timezone.localdate()