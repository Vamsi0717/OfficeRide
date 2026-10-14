from django.conf import settings
from django.db import models


class Message(models.Model):
    """One chat message on a booking. Only the rider and the driver of that booking can read or write."""

    request = models.ForeignKey("bookings.RideRequest", on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    text = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["request", "created_at"])]

    def __str__(self):
        return f"{self.sender} on request {self.request_id}: {self.text[:30]}"


class ChatRead(models.Model):
    """When a person last opened a thread. Messages from the other person after that are unread."""

    request = models.ForeignKey("bookings.RideRequest", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    last_read_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["request", "user"], name="one_read_marker_per_user_request")]