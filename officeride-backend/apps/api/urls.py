from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

app_name = "api"

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("auth/verify-email/", views.VerifyEmailView.as_view(), name="verify_email"),
    path("auth/resend-code/", views.ResendCodeView.as_view(), name="resend_code"),
    path("me/", views.MeView.as_view(), name="me"),
]