"""The hybrid-work planner: who is driving, riding or staying home on which day.

For one person and one date the plan is read in this order:
  1. the car is marked unavailable that day  -> riding
  2. a one-off override for that exact date
  3. the weekly plan for that weekday
  4. nothing planned                         -> None (no restriction)
"""

from apps.rides.models import CarUnavailableDate

from .models import PlanDay

Mode = PlanDay.Mode
WORK_DAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday")]


def mode_for(user, date):
    """'driving', 'riding', 'not_going' or None."""
    if CarUnavailableDate.objects.filter(driver=user, date=date).exists():
        return Mode.RIDING
    override = PlanDay.objects.filter(user=user, date=date).values_list("mode", flat=True).first()
    if override:
        return override
    return PlanDay.objects.filter(user=user, weekday=date.weekday()).values_list("mode", flat=True).first()


def drivers_not_driving(driver_ids, date):
    """The ids, out of driver_ids, whose plan for this date says they are not driving. Two queries in all."""
    driver_ids = set(driver_ids)
    if not driver_ids:
        return set()
    modes = {}
    for user_id, mode in PlanDay.objects.filter(user_id__in=driver_ids, weekday=date.weekday()).values_list("user_id", "mode"):
        modes[user_id] = mode
    for user_id, mode in PlanDay.objects.filter(user_id__in=driver_ids, date=date).values_list("user_id", "mode"):
        modes[user_id] = mode  # a one-off override beats the weekly plan
    for user_id in CarUnavailableDate.objects.filter(driver_id__in=driver_ids, date=date).values_list("driver_id", flat=True):
        modes[user_id] = Mode.RIDING  # the car is not available
    return {user_id for user_id, mode in modes.items() if mode != Mode.DRIVING}


def save_weekly(user, modes):
    """modes maps weekday number to a mode, or to '' to clear that day."""
    for weekday, mode in modes.items():
        if mode:
            PlanDay.objects.update_or_create(user=user, weekday=weekday, defaults={"mode": mode, "date": None})
        else:
            PlanDay.objects.filter(user=user, weekday=weekday).delete()


def set_override(user, date, mode):
    PlanDay.objects.update_or_create(user=user, date=date, defaults={"mode": mode, "weekday": None})


def clear_override(user, date):
    PlanDay.objects.filter(user=user, date=date).delete()


def weekly_modes(user):
    return dict(PlanDay.objects.filter(user=user, weekday__isnull=False).values_list("weekday", "mode"))