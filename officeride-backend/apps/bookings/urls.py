from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("trips/", views.trips, name="trips"),
    path("request/<int:ride_pk>/", views.request_seat, name="request_seat"),
    path("<int:pk>/<str:action>/", views.act, name="act"),
]