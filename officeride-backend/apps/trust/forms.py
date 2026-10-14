from django import forms

from apps.core.forms import BootstrapFormMixin

from .models import Complaint, Rating


class RatingForm(BootstrapFormMixin, forms.Form):
    stars = forms.TypedChoiceField(
        label="How was it?", coerce=int, choices=[(n, f"{n} star{'s' if n > 1 else ''}") for n in range(5, 0, -1)],
        widget=forms.RadioSelect, error_messages={"required": "Choose 1 to 5 stars."},
    )
    tags = forms.MultipleChoiceField(label="What went well? (optional)", choices=Rating.TAGS, required=False, widget=forms.CheckboxSelectMultiple)
    comment = forms.CharField(label="Comment (optional)", max_length=300, required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, rating_driver=True, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("stars", "tags"):
            self.fields[name].widget.attrs["class"] = "form-check-input"
        if not rating_driver:
            # Riders do not drive, so "Safe driving" is only offered when you rate a driver.
            self.fields["tags"].choices = [(k, v) for k, v in Rating.TAGS if k != "safe_driving"]


class ComplaintForm(BootstrapFormMixin, forms.Form):
    kind = forms.ChoiceField(label="What happened?", choices=Complaint.Kind.choices)
    text = forms.CharField(label="Tell us more", max_length=1000, widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, is_bike=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not is_bike:
            self.fields["kind"].choices = [(k, v) for k, v in Complaint.Kind.choices if k != Complaint.Kind.HELMET]


class ExplanationForm(forms.Form):
    explanation = forms.CharField(max_length=300, widget=forms.Textarea)