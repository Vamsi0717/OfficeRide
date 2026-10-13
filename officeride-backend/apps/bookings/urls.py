from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("trips/", views.trips, name="trips"),
    path("request/<int:ride_pk>/", views.request_seat, name="request_seat"),
    path("plan/", views.plan, name="plan"),
    path("plan/<int:pk>/delete/", views.plan_override_delete, name="plan_override_delete"),
    path("<int:pk>/back/", views.request_back, name="request_back"),
    path("<int:pk>/<str:action>/", views.act, name="act"),
]