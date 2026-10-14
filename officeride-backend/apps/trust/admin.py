from django.contrib import admin
from django.utils import timezone

from . import services
from .models import Complaint, Rating, Strike


@admin.register(Strike)
class StrikeAdmin(admin.ModelAdmin):
    list_display = ("user", "reason", "created_at", "counts_now", "waived", "waived_by", "has_note")
    list_filter = ("waived", "reason", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("user", "reason", "request", "created_at", "explanation", "waived_by", "waived_at")
    actions = ["waive_strikes", "suspend_users", "clear_suspensions", "send_users_to_review", "clear_reviews"]

    def has_add_permission(self, request):
        return False  # strikes come from late cancellations and no-shows

    @admin.display(boolean=True, description="Counts now")
    def counts_now(self, obj):
        return obj in services.active_strikes(obj.user)

    @admin.display(boolean=True, description="Has a note")
    def has_note(self, obj):
        return bool(obj.explanation)

    def save_model(self, request, obj, form, change):
        if "waived" in form.changed_data and obj.waived:
            obj.waived = False  # let the service do it, so it records who and when and lifts the suspension
            obj.save()
            services.waive(obj, request.user)
            return
        super().save_model(request, obj, form, change)

    def _users(self, queryset):
        return {s.user for s in queryset.select_related("user")}

    @admin.action(description="Waive selected strikes")
    def waive_strikes(self, request, queryset):
        done = sum(services.waive(s, request.user) for s in queryset)
        self.message_user(request, f"{done} strike(s) waived.")

    @admin.action(description="Suspend these people for 7 days")
    def suspend_users(self, request, queryset):
        users = self._users(queryset)
        for user in users:
            services.suspend(user)
        self.message_user(request, f"{len(users)} person(s) suspended.")

    @admin.action(description="Clear the suspension of these people")
    def clear_suspensions(self, request, queryset):
        users = self._users(queryset)
        for user in users:
            services.clear_suspension(user)
        self.message_user(request, f"{len(users)} suspension(s) cleared.")

    @admin.action(description="Send these people to admin review")
    def send_users_to_review(self, request, queryset):
        users = self._users(queryset)
        for user in users:
            services.send_to_review(user)
        self.message_user(request, f"{len(users)} account(s) sent to review.")

    @admin.action(description="Finish the review of these people (let them back in)")
    def clear_reviews(self, request, queryset):
        users = self._users(queryset)
        for user in users:
            services.clear_review(user)
        self.message_user(request, f"{len(users)} review(s) finished.")


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "reported", "reporter", "status", "created_at", "handled_by")
    list_filter = ("status", "kind", "created_at")
    search_fields = ("reporter__email", "reported__email", "text")
    fields = ("reporter", "reported", "request", "kind", "text", "created_at", "status", "admin_notes", "handled_by", "handled_at")
    readonly_fields = ("reporter", "reported", "request", "kind", "text", "created_at", "handled_by", "handled_at")

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        if {"status", "admin_notes"} & set(form.changed_data):
            obj.handled_by = request.user
            obj.handled_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ("rated", "rater", "stars", "created_at")
    list_filter = ("stars",)
    search_fields = ("rated__email", "rater__email")
    readonly_fields = ("request", "rater", "rated", "stars", "tags", "comment", "created_at")

    def has_add_permission(self, request):
        return False