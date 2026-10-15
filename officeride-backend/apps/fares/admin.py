from django.contrib import admin

from .models import FareSettings, MileageRate


@admin.register(FareSettings)
class FareSettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "fuel_price_per_litre", "diesel_price_per_litre", "cng_price_per_kg", "traffic_cut_percent", "car_wear_per_km", "bike_wear_per_km", "recovery_percent")

    def has_add_permission(self, request):
        return not FareSettings.objects.exists()  # one row only

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MileageRate)
class MileageRateAdmin(admin.ModelAdmin):
    list_display = ("make", "name", "vehicle_type", "fuel_type", "km_per_litre", "is_maker_figure")
    list_filter = ("vehicle_type", "fuel_type", "make")
    search_fields = ("make", "name")