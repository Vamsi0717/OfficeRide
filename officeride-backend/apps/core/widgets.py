from datetime import datetime, time

from django import forms

TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p")

# The four quick buttons in the time popup. Each page picks the set that suits it.
MORNING_PRESETS = ("08:00", "09:00", "10:00", "12:00")  # the way there
EVENING_PRESETS = ("16:00", "17:00", "18:00", "19:00")  # the way back
SEARCH_PRESETS = ("08:00", "09:00", "18:00", "19:00")  # finding a ride


def as_time(value):
    """A time from a time object or text like '18:05' or '6:05 PM'. None when it is neither."""
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, str):
        for fmt in TIME_FORMATS:
            try:
                return datetime.strptime(value.strip(), fmt).time()
            except ValueError:
                continue
    return None


class TimeWheelWidget(forms.TimeInput):
    """A time field that opens a small popup with scroll wheels (hour, minute, am/pm) and quick buttons.

    The page's JavaScript (static/js/time_wheel.js) draws the popup. Without JavaScript this is a normal
    browser time box, so the form still works. Either way one value such as "18:15" is posted, which a
    normal forms.TimeField reads."""

    input_type = "time"

    def __init__(self, attrs=None, presets=MORNING_PRESETS):
        super().__init__(attrs, format="%H:%M")
        self.presets = tuple(presets)

    def format_value(self, value):
        current = as_time(value)
        return current.strftime("%H:%M") if current else super().format_value(value)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["attrs"]["data-time-wheel"] = "true"
        context["widget"]["attrs"]["data-presets"] = ",".join(self.presets)
        return context