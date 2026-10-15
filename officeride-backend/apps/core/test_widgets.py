from datetime import time

from django import forms
from django.test import SimpleTestCase

from apps.core.forms import BootstrapFormMixin
from apps.core.widgets import EVENING_PRESETS, MORNING_PRESETS, SEARCH_PRESETS, TimeWheelWidget


class DemoForm(BootstrapFormMixin, forms.Form):
    at = forms.TimeField(widget=TimeWheelWidget())


class TimeWheelTests(SimpleTestCase):
    def parse(self, value):
        form = DemoForm({"at": value})
        return form.cleaned_data["at"] if form.is_valid() else None

    def test_a_chosen_time_becomes_the_time(self):
        for value, expected in {
            "09:30": time(9, 30), "00:00": time(0, 0), "12:00": time(12, 0), "18:15": time(18, 15), "23:59": time(23, 59),
        }.items():
            with self.subTest(value):
                self.assertEqual(self.parse(value), expected)

    def test_nothing_chosen_or_nonsense_is_refused(self):
        for bad in ("", "x", "25:00", "9"):
            with self.subTest(bad):
                self.assertFalse(DemoForm({"at": bad}).is_valid())

    def test_it_is_one_time_box_that_the_popup_script_can_find(self):
        html = str(DemoForm()["at"])
        self.assertEqual(html.count("<input"), 1)
        self.assertEqual(html.count("<select"), 0)
        self.assertIn('type="time"', html)  # the fallback when JavaScript is off
        self.assertIn("data-time-wheel", html)
        self.assertIn("form-control", html)

    def test_the_four_quick_buttons_are_handed_to_the_page(self):
        self.assertIn(f'data-presets="{",".join(MORNING_PRESETS)}"', str(DemoForm()["at"]))

        class Evening(forms.Form):
            at = forms.TimeField(widget=TimeWheelWidget(presets=EVENING_PRESETS))

        self.assertIn(f'data-presets="{",".join(EVENING_PRESETS)}"', str(Evening()["at"]))

    def test_each_set_has_four_real_times(self):
        for presets in (MORNING_PRESETS, EVENING_PRESETS, SEARCH_PRESETS):
            with self.subTest(presets):
                self.assertEqual(len(presets), 4)
                for value in presets:
                    self.assertIsNotNone(forms.TimeField().clean(value))

    def test_the_current_time_is_filled_in_as_hours_and_minutes(self):
        self.assertIn('value="18:15"', str(DemoForm(initial={"at": time(18, 15)})["at"]))
        self.assertIn('value="09:37"', str(DemoForm(initial={"at": time(9, 37, 20)})["at"]))  # seconds are dropped

    def test_it_keeps_what_was_chosen_when_the_form_comes_back_with_an_error(self):
        self.assertIn('value="07:45"', str(DemoForm({"at": "07:45"})["at"]))

    def test_text_such_as_6_05_pm_is_understood_as_an_initial_value(self):
        self.assertIn('value="18:05"', str(DemoForm(initial={"at": "6:05 PM"})["at"]))

    def test_an_empty_box_has_no_value(self):
        self.assertNotIn("value=", str(DemoForm()["at"]))