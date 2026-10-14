from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("<int:pk>/", views.thread, name="thread"),
    path("<int:pk>/quick/<str:key>/", views.quick, name="quick"),
    path("<int:pk>/pickup/", views.confirm_pickup, name="confirm_pickup"),
]