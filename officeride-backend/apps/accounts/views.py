from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from .models import DriverDocument


@login_required
@require_http_methods(["GET"])
def document_file(request, pk, kind):
    """An uploaded document, for its owner (any time) and for admin staff. Nobody else, riders included.

    Files are never exposed through a public URL. A 404 (not a 403) hides that the document exists."""
    if kind not in ("licence", "rc", "insurance"):
        raise Http404
    doc = get_object_or_404(DriverDocument, pk=pk)
    if doc.user_id != request.user.pk and not request.user.has_perm("accounts.view_driverdocument"):
        raise Http404
    stored = getattr(doc, f"{kind}_file")
    if not stored:
        raise Http404
    response = FileResponse(stored.open("rb"), filename=Path(stored.name).name)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response