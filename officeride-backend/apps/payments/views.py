import json

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.decorators import email_verified_required
from apps.bookings.models import RideRequest

from . import gateway, services
from .models import Payment


@email_verified_required
@require_POST
def pay(request, pk):
    """The rider pressed Pay. Make the order on the server, then show the checkout page."""
    req = get_object_or_404(RideRequest, pk=pk, rider=request.user)
    try:
        payment = services.start_payment(req, request.user)
    except services.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect("bookings:trips")
    return redirect("payments:checkout", pk=payment.pk)


@email_verified_required
def checkout(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("request", "request__ride"), pk=pk, rider=request.user)
    if payment.status != Payment.Status.CREATED:
        return redirect("payments:receipt", pk=payment.pk)
    return render(request, "payments/checkout.html", {
        "payment": payment, "key_id": settings.RAZORPAY_KEY_ID, "fake": gateway.is_fake(),
    })


@email_verified_required
@require_POST
def practice(request, pk):
    """Practice mode only: the two buttons that pretend to pay or to fail. Not found in any other mode."""
    if not gateway.is_fake():
        raise Http404
    payment = get_object_or_404(Payment, pk=pk, rider=request.user)
    if request.POST.get("result") == "fail":
        services.mark_failed(payment.razorpay_order_id, "pay_fake_failed")
    else:
        services.mark_paid(payment.razorpay_order_id, f"pay_fake_{payment.pk}")
    return redirect("payments:receipt", pk=payment.pk)


@email_verified_required
@require_POST
def confirm(request):
    """Razorpay Checkout sends the rider back here with a signature."""
    order_id = request.POST.get("razorpay_order_id", "")
    try:
        payment = services.confirm_checkout(
            request.user, order_id, request.POST.get("razorpay_payment_id", ""), request.POST.get("razorpay_signature", ""),
        )
    except services.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect("bookings:trips")
    return redirect("payments:receipt", pk=payment.pk)


@email_verified_required
def receipt(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("request", "request__ride"), pk=pk, rider=request.user)
    return render(request, "payments/receipt.html", {"payment": payment})


@csrf_exempt
@require_POST
def webhook(request):
    """Razorpay tells us about a payment. No login and no CSRF token here: the signature is the proof."""
    if not gateway.webhook_signature_ok(request.body, request.headers.get("X-Razorpay-Signature", "")):
        return HttpResponse(status=400)
    try:
        event = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest()
    services.handle_webhook_event(event)
    return HttpResponse(status=200)