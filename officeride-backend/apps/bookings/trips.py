"""How the My trips page groups bookings: by what the person needs to do or look at next.

Pure functions with no screens, so the rules are easy to test."""

from datetime import timedelta

from django.utils import timezone

from .models import RideRequest

S = RideRequest.Status

# The order the sections appear in. The first two ask the person to do something.
ORDER = ["update", "pending", "today", "tomorrow", "later", "completed", "closed"]

# Old bookings are folded away so the page stays short.
COLLAPSED = {"completed", "closed"}

TITLES = {
    "update": ("Update needed", "The ride has left. Tell us how it went."),
    "pending": {"driver": ("Waiting for your reply", "Accept or reject these requests."),
                "rider": ("Waiting for the driver", "The driver has not replied yet.")},
    "today": ("Today", ""),
    "tomorrow": ("Tomorrow", ""),
    "later": ("Coming up", ""),
    "completed": ("Completed", "Rate the ride or report a problem."),
    "closed": ("Cancelled or declined", ""),
}


def bucket_for(req, now=None):
    """Which section a booking belongs in."""
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    has_left = req.departure_at <= now
    if req.status == S.PENDING:
        return "closed" if has_left else "pending"  # a request nobody answered before the ride left has expired
    if req.status == S.ACCEPTED:
        if has_left:
            return "update"
        if req.date == today:
            return "today"
        if req.date == today + timedelta(days=1):
            return "tomorrow"
        return "later"
    if req.status in (S.COMPLETED, S.NO_SHOW):
        return "completed"
    return "closed"  # cancelled or rejected


def group(requests, as_driver, now=None):
    """A list of sections {key, title, hint, items, collapsed}, empty sections left out."""
    now = now or timezone.now()
    buckets = {key: [] for key in ORDER}
    for req in requests:
        buckets[bucket_for(req, now)].append(req)
    sections = []
    for key in ORDER:
        items = buckets[key]
        if not items:
            continue
        # Things still to come read soonest first; things that are over read newest first.
        items.sort(key=lambda r: r.departure_at, reverse=key in ("update", "completed", "closed"))
        title, hint = TITLES[key]["driver" if as_driver else "rider"] if key == "pending" else TITLES[key]
        sections.append({"key": key, "title": title, "hint": hint, "items": items, "collapsed": key in COLLAPSED})
    return sections


def counts(sections):
    """What the summary tiles show."""
    by_key = {s["key"]: len(s["items"]) for s in sections}
    return {
        "today": by_key.get("today", 0),
        "tomorrow": by_key.get("tomorrow", 0),
        "waiting": by_key.get("pending", 0),
        "update": by_key.get("update", 0),
        "active": sum(by_key.get(k, 0) for k in ("update", "pending", "today", "tomorrow", "later")),
    }