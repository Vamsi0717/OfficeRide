from rest_framework import status
from rest_framework.response import Response


def form_errors(form):
    """Django form errors as {field: [messages]}. Errors that belong to no single field are under "__all__"."""
    return {field: [str(m) for m in messages] for field, messages in form.errors.items()}


def invalid(form):
    return Response(
        {"detail": "Please fix the marked fields.", "code": "invalid", "errors": form_errors(form)},
        status=status.HTTP_400_BAD_REQUEST,
    )


def problem(detail, code, http_status, **extra):
    """One plain message for the person, plus a short code the app can act on."""
    return Response({"detail": detail, "code": code, **extra}, status=http_status)