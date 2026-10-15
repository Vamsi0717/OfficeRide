from datetime import datetime, time

from django import forms

TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p")


class TimePickerWidget(forms.MultiWidget):
    """Three dropdowns, hour, minute and AM or PM, instead of the browser's clock box.

    It works with a normal forms.TimeField: the widget hands the field one string like "18:05".
    A plain "09:30" sent under the field's own name (an old bookmark, a test) is still understood."""

    MINUTE_STEP = 5

    def __init__(self, attrs=None):
        select = {"class": "form-select d-inline-block w-auto me-1"}
        hours = [("", "Hr")] + [(str(h), str(h)) for h in range(1, 13)]
        minutes = [("", "Min")] + [(str(m), f"{m:02d}") for m in range(0, 60, self.MINUTE_STEP)]
        meridiem = [("AM", "AM"), ("PM", "PM")]
        super().__init__(
            [
                forms.Select(attrs=select, choices=hours),
                forms.Select(attrs=select, choices=minutes),
                forms.Select(attrs=select, choices=meridiem),
            ],
            attrs=attrs,
        )

    @staticmethod
    def _as_time(value):
        if isinstance(value, time):
            return value
        if isinstance(value, str):
            for fmt in TIME_FORMATS:
                try:
                    return datetime.strptime(value.strip(), fmt).time()
                except ValueError:
                    continue
        return None

    def decompress(self, value):
        t = self._as_time(value)
        if t is None:
            return ["", "", "AM"]
        hour12 = t.hour % 12 or 12
        # Minutes that are not on a 5 minute step (a ride saved earlier) are shown rounded down.
        return [str(hour12), str(t.minute - t.minute % self.MINUTE_STEP), "PM" if t.hour >= 12 else "AM"]

    def value_from_datadict(self, data, files, name):
        single = data.get(name)
        if single:
            return single
        hour, minute, meridiem = (data.get(f"{name}_{i}") for i in range(3))
        if not hour or minute in (None, ""):
            return None
        try:
            hour, minute = int(hour), int(minute)
        except ValueError:
            return "invalid"
        if not (1 <= hour <= 12) or meridiem not in ("AM", "PM"):
            return "invalid"
        hour24 = hour % 12 + (12 if meridiem == "PM" else 0)
        return f"{hour24:02d}:{minute:02d}"

    def value_omitted_from_data(self, data, files, name):
        return name not in data and f"{name}_0" not in data