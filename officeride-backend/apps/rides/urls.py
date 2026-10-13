from django.urls import path

from . import views

app_name = "rides"

urlpatterns = [
    path("offer/", views.offer_ride, name="offer"),
    path("mine/", views.my_rides, name="mine"),
    path("find/", views.find_a_ride, name="find"),
    path("unavailable/", views.unavailable_dates, name="unavailable"),
    path("unavailable/<int:pk>/delete/", views.unavailable_delete, name="unavailable_delete"),
    path("places/search/", views.place_search, name="places_search"),
    path("<int:pk>/", views.ride_detail, name="detail"),
    path("<int:pk>/toggle/", views.toggle_ride, name="toggle"),
    path("<int:pk>/edit/", views.ride_edit, name="edit"),
    path("<int:pk>/fare/", views.ride_fare, name="fare"),
    path("<int:pk>/delete/", views.ride_delete, name="delete"),
    path("<int:pk>/back/", views.offer_back, name="offer_back"),
]