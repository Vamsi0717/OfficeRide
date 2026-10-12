from django.db import migrations

# Rides made before Phase 4 have no vehicle class. Give them a sensible default so they get a fare.
DEFAULTS = {"car": "Sedan", "bike": "Commuter motorcycle"}


def backfill(apps, schema_editor):
    Ride = apps.get_model("rides", "Ride")
    MileageRate = apps.get_model("fares", "MileageRate")
    for vehicle_type, name in DEFAULTS.items():
        rate = MileageRate.objects.filter(vehicle_type=vehicle_type, name=name).first()
        if rate:
            Ride.objects.filter(vehicle_type=vehicle_type, mileage_rate__isnull=True).update(mileage_rate=rate)


class Migration(migrations.Migration):
    dependencies = [
        ("rides", "0003_fares_mileage_and_toll"),
        ("fares", "0002_starting_values"),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]