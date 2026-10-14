from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("rides/", include("apps.rides.urls")),
    path("bookings/", include("apps.bookings.urls")),
    path("trust/", include("apps.trust.urls")),
    path("chat/", include("apps.chat.urls")),
    path("", include("apps.core.urls")),
]