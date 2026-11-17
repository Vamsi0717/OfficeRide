import json

from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import gateway, services


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