from django.contrib import admin

from .models import FareSettings, MileageRate


@admin.register(FareSettings)
class FareSettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "fuel_price_per_litre", "car_wear_per_km", "bike_wear_per_km", "recovery_percent")

    def has_add_permission(self, request):
        return not FareSettings.objects.exists()  # one row only

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MileageRate)
class MileageRateAdmin(admin.ModelAdmin):
    list_display = ("name", "vehicle_type", "km_per_litre")
    list_filter = ("vehicle_type",)