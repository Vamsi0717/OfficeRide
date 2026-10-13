from django.contrib import admin

from .models import PlanDay, RideRequest


@admin.register(RideRequest)
class RideRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "ride", "rider", "status", "fare", "late_cancel")
    list_filter = ("status", "late_cancel", "date")
    search_fields = ("rider__email", "ride__driver__email")
    readonly_fields = ("standard_fare", "fare_adjustment", "fare", "rider_distance_m", "created_at", "updated_at")


@admin.register(PlanDay)
class PlanDayAdmin(admin.ModelAdmin):
    list_display = ("user", "weekday", "date", "mode")
    list_filter = ("mode",)