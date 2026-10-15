from decimal import Decimal

from django.db import migrations

from apps.fares.catalog import CATALOG


def add_catalog(apps, schema_editor):
    MileageRate = apps.get_model("fares", "MileageRate")
    for vehicle_type, make, name, fuel_type, figure in CATALOG:
        MileageRate.objects.get_or_create(
            vehicle_type=vehicle_type, make=make, name=name,
            defaults={
                "fuel_type": fuel_type, "km_per_litre": Decimal(str(figure)),
                # A maker's printed figure gets the Bangalore traffic cut. An electric model's figure is already a standard.
                "is_maker_figure": fuel_type != "electric",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("fares", "0003_vehicle_models_and_fuels")]
    operations = [migrations.RunPython(add_catalog, migrations.RunPython.noop)]