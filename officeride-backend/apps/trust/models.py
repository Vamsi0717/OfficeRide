from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class Strike(models.Model):
    """A mark against someone for a late cancellation or a no-show. Strikes older than 90 days, or waived, do not count."""

    class Reason(models.TextChoices):
        LATE_CANCEL = "late_cancel", "Cancelled less than an hour before departure"
        NO_SHOW = "no_show", "Did not show up"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="strikes")
    reason = models.CharField(max_length=12, choices=Reason.choices)
    request = models.ForeignKey("bookings.RideRequest", on_delete=models.PROTECT, related_name="strikes")
    created_at = models.DateTimeField(auto_now_add=True)
    explanation = models.CharField(max_length=300, blank=True, help_text="What the person told us about it.")
    waived = models.BooleanField(default=False)
    waived_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    waived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "request", "reason"], name="one_strike_per_user_request_reason"),
        ]

    def __str__(self):
        return f"{self.user} - {self.get_reason_display()}"


class Rating(models.Model):
    """One person rating the other on a completed ride. Each person rates once."""

    TAGS = [("punctual", "Punctual"), ("safe_driving", "Safe driving"), ("friendly", "Friendly")]

    request = models.ForeignKey("bookings.RideRequest", on_delete=models.CASCADE, related_name="ratings")
    rater = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ratings_given")
    rated = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ratings_received")
    stars = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    tags = models.JSONField(default=list, blank=True)
    comment = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["request", "rater"], name="one_rating_per_rater_per_request"),
            models.CheckConstraint(condition=Q(stars__gte=1, stars__lte=5), name="rating_stars_1_to_5"),
        ]

    def __str__(self):
        return f"{self.rater} rated {self.rated}: {self.stars}"


class Complaint(models.Model):
    class Kind(models.TextChoices):
        UNSAFE = "unsafe", "Unsafe driving or behaviour"
        RUDE = "rude", "Rude or uncomfortable behaviour"
        HELMET = "helmet", "Helmet not worn or not provided"
        OTHER = "other", "Something else"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="complaints_made")
    reported = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="complaints_received")
    request = models.ForeignKey("bookings.RideRequest", null=True, blank=True, on_delete=models.SET_NULL, related_name="complaints")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    text = models.CharField(max_length=1000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    admin_notes = models.TextField(blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    handled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} about {self.reported} ({self.status})"