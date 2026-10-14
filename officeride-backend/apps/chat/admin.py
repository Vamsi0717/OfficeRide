from django.contrib import admin

from .models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Read only, for the admin to look into a complaint. Nobody writes messages here."""

    list_display = ("id", "request", "sender", "created_at", "short_text")
    search_fields = ("sender__email", "text")
    list_filter = ("created_at",)
    readonly_fields = ("request", "sender", "text", "created_at")

    @admin.display(description="Message")
    def short_text(self, obj):
        return obj.text[:60]

    def has_add_permission(self, request):
        return False