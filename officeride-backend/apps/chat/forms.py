from django import forms
from django.conf import settings


class MessageForm(forms.Form):
    text = forms.CharField(
        label="Message", max_length=settings.CHAT_MAX_CHARS,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Write a message", "autocomplete": "off"}),
        error_messages={"max_length": f"Messages can be up to {settings.CHAT_MAX_CHARS} characters."},
    )


class PickupForm(forms.Form):
    spot = forms.CharField(max_length=120)