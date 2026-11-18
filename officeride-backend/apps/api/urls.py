from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import ride_views, views

app_name = "api"

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("auth/verify-email/", views.VerifyEmailView.as_view(), name="verify_email"),
    path("auth/resend-code/", views.ResendCodeView.as_view(), name="resend_code"),
    path("me/", views.MeView.as_view(), name="me"),
    path("places/", ride_views.PlaceSearchView.as_view(), name="places"),
    path("vehicles/", ride_views.VehicleListView.as_view(), name="vehicles"),
    path("fare-preview/", ride_views.FarePreviewView.as_view(), name="fare_preview"),
    path("rides/", ride_views.RideListView.as_view(), name="rides"),
    path("rides/search/", ride_views.SearchView.as_view(), name="ride_search"),
    path("rides/mine/", ride_views.MyRidesView.as_view(), name="rides_mine"),
    path("rides/<int:pk>/", ride_views.RideDetailView.as_view(), name="ride_detail"),
    path("rides/<int:pk>/toggle/", ride_views.RideToggleView.as_view(), name="ride_toggle"),
    path("rides/<int:pk>/fare/", ride_views.RideFareView.as_view(), name="ride_fare"),
    path("rides/<int:pk>/return/", ride_views.RideReturnView.as_view(), name="ride_return"),
    path("unavailable-dates/", ride_views.UnavailableDatesView.as_view(), name="unavailable_dates"),
    path("unavailable-dates/<int:pk>/", ride_views.UnavailableDateDeleteView.as_view(), name="unavailable_date_delete"),
]