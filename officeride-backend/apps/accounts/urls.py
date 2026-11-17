from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("documents/<int:pk>/<str:kind>/", views.document_file, name="document_file"),
]