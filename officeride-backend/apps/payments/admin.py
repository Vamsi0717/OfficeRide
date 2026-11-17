from django.contrib import admin, messages

from . import services
from .models import Payment, Settlement


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("razorpay_order_id", "rider", "request", "status", "fare", "fee", "total", "created_at", "paid_at", "refund_note")
    list_filter = ("status", "created_at")
    search_fields = ("razorpay_order_id", "razorpay_payment_id", "rider__email")
    readonly_fields = [f.name for f in Payment._meta.fields]
    actions = ["retry_refunds"]

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

    @admin.action(description="Retry the refund for the selected payments")
    def retry_refunds(self, request, queryset):
        done = 0
        for payment in queryset.filter(status=Payment.Status.PAID).select_related("request"):
            if services.refund_due(payment.request):
                done += services.refund_payment(payment.pk).status == Payment.Status.REFUNDED
        self.message_user(request, f"{done} payment(s) refunded.", messages.SUCCESS if done else messages.WARNING)


class SettlementPaymentInline(admin.TabularInline):
    model = Payment
    fk_name = "settlement"
    extra = 0
    can_delete = False
    fields = ("request", "razorpay_payment_id", "standard_fare_paise", "adjustment_paise", "platform_fee_paise", "driver_amount_paise")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ("driver", "week_start", "rides", "owed", "fee", "status", "paid_at", "payout_reference")
    list_filter = ("status", "week_start")
    search_fields = ("driver__email", "payout_reference")
    readonly_fields = ("driver", "week_start", "week_end", "rides", "total_paise", "platform_fee_paise", "status", "paid_at", "created_at")
    inlines = [SettlementPaymentInline]
    actions = ["mark_paid"]

    def has_add_permission(self, request):
        return False  # made by `python manage.py make_settlements`

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Owed to driver (Rs)")
    def owed(self, obj):
        return obj.total_paise / 100

    @admin.display(description="OfficeRide fee (Rs)")
    def fee(self, obj):
        return obj.platform_fee_paise / 100

    @admin.action(description="Mark the selected settlements as paid out (type the reference on each first)")
    def mark_paid(self, request, queryset):
        done = 0
        for settlement in queryset.filter(status=Settlement.Status.PENDING):
            try:
                services.mark_settlement_paid(settlement, settlement.payout_reference)
            except services.PaymentError:
                self.message_user(request, f"{settlement.driver}: type the payout reference first.", messages.ERROR)
            else:
                done += 1
        if done:
            self.message_user(request, f"{done} settlement(s) marked as paid out.", messages.SUCCESS)