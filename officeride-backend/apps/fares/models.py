"""Numbers the fare formula needs. Staff edit them in the admin; no code change or deploy is needed."""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.accounts.models import VehicleType


class FareSettings(models.Model):
    """One row only. Fuel price, wear per km and the share of the cost riders repay."""

    fuel_price_per_litre = models.DecimalField(
        "Petrol price per litre (₹)", max_digits=6, decimal_places=2, default=Decimal("103.00"),
        validators=[MinValueValidator(Decimal("1"))],
    )
    car_wear_per_km = models.DecimalField(
        "Car wear and tear per km (₹)", max_digits=5, decimal_places=2, default=Decimal("2.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    bike_wear_per_km = models.DecimalField(
        "Two-wheeler wear and tear per km (₹)", max_digits=5, decimal_places=2, default=Decimal("0.80"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    recovery_percent = models.PositiveSmallIntegerField(
        "Share of the cost riders repay (%)", default=90,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="90 means riders together repay 90% of fuel and wear. Never set it above 100.",
    )

    class Meta:
        verbose_name = "fare settings"
        verbose_name_plural = "fare settings"

    def __str__(self):
        return "Fare settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # there is only ever one row
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MileageRate(models.Model):
    """Standard km per litre for a class of vehicle, e.g. Sedan 10 or Scooter 40."""

    vehicle_type = models.CharField(max_length=10, choices=VehicleType.choices)
    name = models.CharField(max_length=60)
    km_per_litre = models.DecimalField(
        max_digits=5, decimal_places=1, validators=[MinValueValidator(Decimal("1"))],
    )

    class Meta:
        ordering = ["vehicle_type", "name"]
        constraints = [
            models.UniqueConstraint(fields=["vehicle_type", "name"], name="one_mileage_rate_per_vehicle_class"),
        ]

    def __str__(self):
        return f"{self.name} ({self.km_per_litre} km/l)"