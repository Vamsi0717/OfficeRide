from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("pay/<int:pk>/", views.pay, name="pay"),
    path("checkout/<int:pk>/", views.checkout, name="checkout"),
    path("practice/<int:pk>/", views.practice, name="practice"),
    path("confirm/", views.confirm, name="confirm"),
    path("receipt/<int:pk>/", views.receipt, name="receipt"),
    path("webhook/", views.webhook, name="webhook"),
]