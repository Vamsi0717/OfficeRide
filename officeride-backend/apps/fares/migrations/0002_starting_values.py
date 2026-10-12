from decimal import Decimal

from django.db import migrations

CARS = [("Hatchback", "12.0"), ("Sedan", "10.0"), ("SUV or MUV", "8.0")]
BIKES = [("Scooter", "40.0"), ("Commuter motorcycle", "45.0"), ("Performance motorcycle", "30.0")]


def add_starting_values(apps, schema_editor):
    FareSettings = apps.get_model("fares", "FareSettings")
    MileageRate = apps.get_model("fares", "MileageRate")
    FareSettings.objects.get_or_create(pk=1)
    for vehicle_type, rows in (("car", CARS), ("bike", BIKES)):
        for name, kmpl in rows:
            MileageRate.objects.get_or_create(
                vehicle_type=vehicle_type, name=name, defaults={"km_per_litre": Decimal(kmpl)}
            )


class Migration(migrations.Migration):
    dependencies = [("fares", "0001_initial")]
    operations = [migrations.RunPython(add_starting_values, migrations.RunPython.noop)]