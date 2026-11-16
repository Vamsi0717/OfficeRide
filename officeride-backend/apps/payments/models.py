from django.conf import settings
from django.db import models
from django.db.models import Q


class Payment(models.Model):
    """One attempt to pay for one booking. All money is stored as whole paise (100 paise = 1 rupee)."""

    class Status(models.TextChoices):
        CREATED = "created", "Waiting for payment"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    request = models.ForeignKey("bookings.RideRequest", on_delete=models.PROTECT, related_name="payments")
    rider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")

    # The breakdown, copied from the booking's saved fare when the payment is started.
    standard_fare_paise = models.PositiveIntegerField()
    adjustment_paise = models.IntegerField(default=0, help_text="The driver's change to the standard fare. Can be negative.")
    platform_fee_paise = models.PositiveIntegerField(default=0)
    amount_paise = models.PositiveIntegerField(help_text="What the rider is charged: the fare plus the platform fee.")
    driver_amount_paise = models.PositiveIntegerField(help_text="What the driver earns: the fare, without the platform fee.")

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED)
    razorpay_order_id = models.CharField(max_length=64, unique=True)
    razorpay_payment_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # A booking can be paid only once.
            models.UniqueConstraint(fields=["request"], condition=Q(status="paid"), name="one_paid_payment_per_request"),
        ]

    def __str__(self):
        return f"Payment {self.razorpay_order_id} ({self.status})"

    @property
    def standard_rupees(self):
        return self.standard_fare_paise / 100

    @property
    def adjustment_rupees(self):
        return self.adjustment_paise / 100

    @property
    def fee_rupees(self):
        return self.platform_fee_paise / 100

    @property
    def amount_rupees(self):
        return self.amount_paise / 100