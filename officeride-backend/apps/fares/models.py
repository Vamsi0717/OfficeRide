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
    diesel_price_per_litre = models.DecimalField(
        "Diesel price per litre (₹)", max_digits=6, decimal_places=2, default=Decimal("89.00"),
        validators=[MinValueValidator(Decimal("1"))],
    )
    cng_price_per_kg = models.DecimalField(
        "CNG price per kg (₹)", max_digits=6, decimal_places=2, default=Decimal("90.00"),
        validators=[MinValueValidator(Decimal("1"))],
    )
    traffic_cut_percent = models.PositiveSmallIntegerField(
        "Mileage cut for Bangalore traffic (%)", default=20,
        validators=[MaxValueValidator(60)],
        help_text="Makers print a test-track mileage. This share is taken off it, so 20 turns a printed 30 km per litre into 24. Drivers never see these numbers.",
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


class FuelType(models.TextChoices):
    PETROL = "petrol", "Petrol"
    DIESEL = "diesel", "Diesel"
    CNG = "cng", "CNG"
    ELECTRIC = "electric", "Electric"


class MileageRate(models.Model):
    """Km per litre for one vehicle model, e.g. Hyundai Creta (diesel) 17.

    Rows without a make are the older vehicle classes (Sedan, Scooter ...). Rides made before the
    make and model lists still point at them, so they are kept, but new rides choose a real model."""

    vehicle_type = models.CharField(max_length=10, choices=VehicleType.choices)
    make = models.CharField(max_length=40, blank=True)
    name = models.CharField("model", max_length=60)
    fuel_type = models.CharField(max_length=10, choices=FuelType.choices, default=FuelType.PETROL)
    km_per_litre = models.DecimalField(
        max_digits=5, decimal_places=1, validators=[MinValueValidator(Decimal("1"))],
        help_text="The figure the maker prints. For an electric model it is the standard equivalent used for every electric vehicle.",
    )
    is_maker_figure = models.BooleanField(
        default=False,
        help_text="Tick when km per litre is the maker's printed figure, so the Bangalore traffic cut is taken off it before pricing.",
    )

    class Meta:
        ordering = ["vehicle_type", "make", "name"]
        constraints = [
            models.UniqueConstraint(fields=["vehicle_type", "make", "name"], name="one_mileage_rate_per_vehicle_model"),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.km_per_litre} km/l)"

    @property
    def full_name(self):
        return f"{self.make} {self.name}".strip()