from datetime import time

from django import forms
from django.test import SimpleTestCase

from apps.core.forms import BootstrapFormMixin
from apps.core.widgets import TimePickerWidget


class DemoForm(BootstrapFormMixin, forms.Form):
    at = forms.TimeField(widget=TimePickerWidget())


class TimePickerTests(SimpleTestCase):
    def parse(self, **data):
        form = DemoForm(data)
        return form, (form.cleaned_data["at"] if form.is_valid() else None)

    def test_hour_minute_and_am_pm_make_a_time(self):
        for (h, m, ap), expected in {
            ("9", "30", "AM"): time(9, 30), ("9", "30", "PM"): time(21, 30), ("12", "0", "AM"): time(0, 0),
            ("12", "0", "PM"): time(12, 0), ("6", "5", "PM"): time(18, 5), ("11", "55", "AM"): time(11, 55),
        }.items():
            with self.subTest((h, m, ap)):
                self.assertEqual(self.parse(at_0=h, at_1=m, at_2=ap)[1], expected)

    def test_a_plain_time_under_the_field_name_still_works(self):
        self.assertEqual(self.parse(at="08:30")[1], time(8, 30))

    def test_missing_or_broken_parts_are_refused(self):
        for data in ({}, {"at_0": "9"}, {"at_1": "30", "at_2": "AM"}, {"at_0": "13", "at_1": "0", "at_2": "AM"},
                     {"at_0": "9", "at_1": "x", "at_2": "AM"}, {"at_0": "9", "at_1": "0", "at_2": "XX"}):
            with self.subTest(data):
                self.assertFalse(DemoForm(data).is_valid())

    def test_it_draws_three_dropdowns_with_the_right_one_chosen(self):
        html = str(DemoForm(initial={"at": time(18, 5)})["at"])
        self.assertEqual(html.count("<select"), 3)
        self.assertIn('<option value="6" selected>6</option>', html)
        self.assertIn('<option value="5" selected>05</option>', html)
        self.assertIn('<option value="PM" selected>PM</option>', html)

    def test_an_empty_form_asks_for_an_hour_and_minute(self):
        html = str(DemoForm()["at"])
        self.assertIn(">Hr<", html)
        self.assertIn(">Min<", html)

    def test_it_keeps_what_was_typed_when_the_form_comes_back_with_an_error(self):
        form = DemoForm({"at_0": "7", "at_1": "45", "at_2": "PM"})
        self.assertIn('<option value="7" selected>7</option>', str(form["at"]))

    def test_the_selects_are_not_given_form_control_by_the_bootstrap_mixin(self):
        self.assertNotIn("form-control", str(DemoForm()["at"]))
        self.assertIn("form-select", str(DemoForm()["at"]))

    def test_a_time_off_the_five_minute_step_is_shown_rounded_down(self):
        self.assertIn('<option value="35" selected>35</option>', str(DemoForm(initial={"at": time(9, 37)})["at"]))