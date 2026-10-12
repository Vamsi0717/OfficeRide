from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.fares.models import FareSettings, MileageRate
from apps.rides.tests.helpers import make_user


class StartingValuesTests(TestCase):
    """The data migration creates these, so a fresh database can price a ride straight away."""

    def test_fare_settings_start_with_the_plan_values(self):
        s = FareSettings.get_solo()
        self.assertEqual(
            (s.fuel_price_per_litre, s.car_wear_per_km, s.bike_wear_per_km, s.recovery_percent),
            (Decimal("103.00"), Decimal("2.00"), Decimal("0.80"), 90),
        )

    def test_car_and_two_wheeler_mileage_classes_exist(self):
        rates = {(r.vehicle_type, r.name): r.km_per_litre for r in MileageRate.objects.all()}
        self.assertEqual(rates[("car", "Hatchback")], Decimal("12.0"))
        self.assertEqual(rates[("car", "Sedan")], Decimal("10.0"))
        self.assertEqual(rates[("car", "SUV or MUV")], Decimal("8.0"))
        self.assertEqual(rates[("bike", "Scooter")], Decimal("40.0"))
        self.assertEqual(rates[("bike", "Commuter motorcycle")], Decimal("45.0"))
        self.assertEqual(rates[("bike", "Performance motorcycle")], Decimal("30.0"))


class FareSettingsTests(TestCase):
    def test_there_is_only_ever_one_row(self):
        FareSettings(fuel_price_per_litre=Decimal("110")).save()
        FareSettings(fuel_price_per_litre=Decimal("111")).save()
        self.assertEqual(FareSettings.objects.count(), 1)
        self.assertEqual(FareSettings.get_solo().fuel_price_per_litre, Decimal("111"))

    def test_recovery_must_be_between_1_and_100(self):
        for bad in (0, 101):
            s = FareSettings.get_solo()
            s.recovery_percent = bad
            with self.subTest(bad), self.assertRaises(ValidationError):
                s.full_clean()

    def test_negative_wear_is_refused(self):
        s = FareSettings.get_solo()
        s.bike_wear_per_km = Decimal("-1")
        with self.assertRaises(ValidationError):
            s.full_clean()


class MileageRateTests(TestCase):
    def test_a_class_name_is_unique_within_a_vehicle_type(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MileageRate.objects.create(vehicle_type="car", name="Sedan", km_per_litre=Decimal("11"))

    def test_the_same_name_is_allowed_for_the_other_vehicle_type(self):
        MileageRate.objects.create(vehicle_type="bike", name="Sedan", km_per_litre=Decimal("11"))

    def test_mileage_must_be_at_least_one(self):
        with self.assertRaises(ValidationError):
            MileageRate(vehicle_type="car", name="Odd", km_per_litre=Decimal("0")).full_clean()


class AdminTests(TestCase):
    def setUp(self):
        self.admin = make_user("boss@acme.com", is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)

    def test_staff_can_edit_the_fuel_price(self):
        url = reverse("admin:fares_faresettings_change", args=[1])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {
            "fuel_price_per_litre": "108.50", "car_wear_per_km": "2.00", "bike_wear_per_km": "0.80", "recovery_percent": "90",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(FareSettings.get_solo().fuel_price_per_litre, Decimal("108.50"))

    def test_a_second_settings_row_cannot_be_added_and_the_row_cannot_be_deleted(self):
        self.assertEqual(self.client.get(reverse("admin:fares_faresettings_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:fares_faresettings_delete", args=[1])).status_code, 403)

    def test_mileage_classes_are_listed_in_the_admin(self):
        response = self.client.get(reverse("admin:fares_mileagerate_changelist"))
        self.assertContains(response, "Commuter motorcycle")