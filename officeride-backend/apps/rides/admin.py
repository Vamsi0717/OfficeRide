from django.contrib import admin

from .models import CarUnavailableDate, Ride


@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    list_display = ("origin_name", "destination_name", "vehicle_type", "mileage_rate", "departure_time", "office_days_display", "seats", "driver", "is_active")
    list_filter = ("is_active", "vehicle_type")
    search_fields = ("origin_name", "destination_name", "driver__email", "car_model")
    # The route is a long list of map points. Keep it out of the edit form.
    exclude = ("route_points",)
    readonly_fields = ("route_distance_m", "route_duration_s", "min_lat", "max_lat", "min_lng", "max_lng", "created_at")


@admin.register(CarUnavailableDate)
class CarUnavailableDateAdmin(admin.ModelAdmin):
    list_display = ("driver", "date", "reason")
    search_fields = ("driver__email",)