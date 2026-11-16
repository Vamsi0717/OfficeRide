from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("razorpay_order_id", "rider", "request", "status", "fare", "fee", "total", "created_at", "paid_at")
    list_filter = ("status", "created_at")
    search_fields = ("razorpay_order_id", "razorpay_payment_id", "rider__email")
    readonly_fields = [f.name for f in Payment._meta.fields]

    def has_add_permission(self, request):
        return False  # payments come from the checkout, never from typing

    def has_delete_permission(self, request, obj=None):
        return False  # money records are kept

    @admin.display(description="Fare (Rs)")
    def fare(self, obj):
        return (obj.standard_fare_paise + obj.adjustment_paise) / 100

    @admin.display(description="Fee (Rs)")
    def fee(self, obj):
        return obj.platform_fee_paise / 100

    @admin.display(description="Total (Rs)")
    def total(self, obj):
        return obj.amount_paise / 100