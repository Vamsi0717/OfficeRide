import re

from django.core.exceptions import ValidationError


class PasswordMixValidator:
    """The password needs a letter, a digit and a symbol. Length is checked by Django's MinimumLengthValidator."""

    message = "Use at least one letter, one number and one symbol, for example Vamsi@2026."

    def validate(self, password, user=None):
        has_letter = re.search(r"[A-Za-z]", password)
        has_digit = re.search(r"\d", password)
        has_symbol = re.search(r"[^A-Za-z0-9]", password)
        if not (has_letter and has_digit and has_symbol):
            raise ValidationError(self.message, code="password_no_mix")

    def get_help_text(self):
        return "At least 8 characters with a letter, a number and a symbol."