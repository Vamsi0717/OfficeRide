from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import email_verified_required
from apps.bookings.models import RideRequest

from . import services
from .forms import MessageForm, PickupForm
from .models import Message


class TelRedirect(HttpResponseRedirect):
    """Django only redirects to http and https unless told otherwise."""

    allowed_schemes = ["tel"]


def _my_request(request, pk):
    """A booking the logged-in person is part of, or a 404, so outsiders cannot tell it exists."""
    return get_object_or_404(
        RideRequest.objects.select_related("ride", "ride__driver", "rider").filter(Q(rider=request.user) | Q(ride__driver=request.user)),
        pk=pk,
    )


@email_verified_required
def thread(request, pk):
    req = _my_request(request, pk)
    form = MessageForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            try:
                services.send(req, request.user, form.cleaned_data["text"])
            except services.ChatError as exc:
                messages.error(request, str(exc))
            return redirect("chat:thread", pk=req.pk)
        for error in form.errors.get("text", []):
            messages.error(request, error)
        return redirect("chat:thread", pk=req.pk)
    thread_messages = list(Message.objects.filter(request=req).select_related("sender"))
    services.mark_read(req, request.user)
    context = {
        "req": req, "other": services.other_person(req, request.user), "thread": thread_messages,
        "form": MessageForm(), "can_write": services.can_write(req), "quick": services.QUICK_REPLIES,
        "can_call": services.call_window_open(req) and len(services.other_person(req, request.user).phone) == 10,
    }
    return render(request, "chat/thread.html", context)


@email_verified_required
@require_POST
def quick(request, pk, key):
    req = _my_request(request, pk)
    try:
        services.send_quick(req, request.user, key)
    except services.ChatError as exc:
        messages.error(request, str(exc))
    return redirect("chat:thread", pk=req.pk)


@email_verified_required
@require_POST
def confirm_pickup(request, pk):
    req = _my_request(request, pk)
    form = PickupForm(request.POST)
    try:
        if not form.is_valid():
            raise services.ChatError("Write the pickup point you agreed on, up to 120 characters.")
        services.confirm_pickup(req, request.user, form.cleaned_data["spot"])
    except services.ChatError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Pickup point confirmed.")
    return redirect("chat:thread", pk=req.pk)


@email_verified_required
def call(request, pk):
    """Opens the phone's dialler with the other person's number, after checking the rules."""
    req = _my_request(request, pk)
    try:
        number = services.call_number(req, request.user)
    except services.ChatError as exc:
        messages.error(request, str(exc))
        return redirect("bookings:trips")
    return TelRedirect(f"tel:+91{number}")