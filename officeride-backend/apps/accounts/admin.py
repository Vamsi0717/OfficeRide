from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import DriverDocument, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "techpark", "email_verified", "is_staff")
    list_filter = ("email_verified", "techpark", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone", "home_area", "techpark")}),
        ("Verification", {"fields": ("email_verified",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )


@admin.register(DriverDocument)
class DriverDocumentAdmin(admin.ModelAdmin):
    list_display = ("user", "vehicle_type", "status", "insurance_expiry", "submitted_at", "reviewed_by")
    list_filter = ("status", "vehicle_type")
    search_fields = ("user__email", "licence_number", "rc_number")
    ordering = ("status", "-updated_at")
    actions = ["approve_documents"]

    fields = (
        "user", "vehicle_type", "licence_number", "licence_link", "rc_number", "rc_link",
        "insurance_expiry", "insurance_link",
        "status", "rejection_reason", "submitted_at", "updated_at", "reviewed_by", "reviewed_at",
    )
    readonly_fields = (
        "user", "vehicle_type", "licence_number", "licence_link", "rc_number", "rc_link",
        "insurance_expiry", "insurance_link", "submitted_at", "updated_at", "reviewed_by", "reviewed_at",
    )

    def has_add_permission(self, request):
        return False  # drivers submit their own documents

    def _link(self, obj, kind):
        url = reverse("accounts:document_file", args=[obj.pk, kind])
        return format_html('<a href="{}" target="_blank" rel="noopener">View file</a>', url)

    @admin.display(description="Licence file")
    def licence_link(self, obj):
        return self._link(obj, "licence")

    @admin.display(description="RC file")
    def rc_link(self, obj):
        return self._link(obj, "rc")

    @admin.display(description="Insurance file")
    def insurance_link(self, obj):
        return self._link(obj, "insurance")

    def save_model(self, request, obj, form, change):
        if "status" in form.changed_data and obj.status != DriverDocument.Status.PENDING:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
            if obj.status == DriverDocument.Status.APPROVED:
                obj.rejection_reason = ""
        super().save_model(request, obj, form, change)

    @admin.action(description="Approve selected documents")
    def approve_documents(self, request, queryset):
        updated = queryset.update(
            status=DriverDocument.Status.APPROVED,
            rejection_reason="",
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"{updated} document set(s) approved.")