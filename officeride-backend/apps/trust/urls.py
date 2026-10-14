from django.urls import path

from . import views

app_name = "trust"

urlpatterns = [
    path("rate/<int:pk>/", views.rate, name="rate"),
    path("report/<int:pk>/", views.report, name="report"),
    path("strike/<int:pk>/explain/", views.explain_strike, name="explain_strike"),
]