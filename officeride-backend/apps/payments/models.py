from django.conf import settings
from django.db import models
from django.db.models import Q


class Settlement(models.Model):
    """What OfficeRide owes one driver for one week, paid out by hand (bank or UPI transfer) at first."""

    class Status(models.TextChoices):
        PENDING = "pending", "To be paid"
        PAID = "paid", "Paid out"

    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="settlements")
    week_start = models.DateField(help_text="The Monday of the week.")
    week_end = models.DateField(help_text="The Sunday of the week.")
    rides = models.PositiveIntegerField(default=0)
    total_paise = models.PositiveIntegerField(default=0, help_text="What the driver is owed: the fares of the completed, paid rides.")
    platform_fee_paise = models.PositiveIntegerField(default=0, help_text="What OfficeRide keeps from the same rides.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)
    payout_reference = models.CharField(max_length=100, blank=True, help_text="The bank or UPI reference of the transfer.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-week_start", "driver"]
        constraints = [
            models.UniqueConstraint(fields=["driver", "week_start"], name="one_settlement_per_driver_week"),
        ]

    def __str__(self):
        return f"{self.driver} week of {self.week_start} ({self.status})"

    @property
    def total_rupees(self):
        return self.total_paise / 100

    @property
    def fee_rupees(self):
        return self.platform_fee_paise / 100


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

    # Refund (Phase 8 part 2). A failed refund attempt leaves the payment as paid with a note, so it can be retried.
    razorpay_refund_id = models.CharField(max_length=64, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    refund_note = models.CharField(max_length=200, blank=True)
    # Set when the payment is counted in a driver's weekly settlement, so it is never counted twice.
    settlement = models.ForeignKey(Settlement, null=True, blank=True, on_delete=models.PROTECT, related_name="payments")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # A booking can be paid only once.
            models.UniqueConstraint(fields=["request"], condition=Q(status="paid"), name="one_paid_payment_per_request"),
        ]

    def __str__(self):
        return f"Payment {self.razorpay_order_id} ({self.status})"

    @property
    def driver_rupees(self):
        return self.driver_amount_paise / 100

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