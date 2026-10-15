import re

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils import timezone

from apps.core.forms import BootstrapFormMixin

from . import indian_ids
from .models import DriverDocument, User

DOCUMENT_ACCEPT = ".pdf,.jpg,.jpeg,.png"
COUNTRY_CODES = [("+91", "+91")]  # OfficeRide works inside Bangalore, so only India for now


def normalise_phone(raw):
    """'+91 98765-43210', '098765 43210' and '9876543210' all become '9876543210'. Anything else is refused."""
    raw = re.sub(r"[\s-]", "", raw or "")
    if not raw:
        raise forms.ValidationError("Enter your 10-digit mobile number.")
    if raw.startswith("+91"):
        raw = raw[3:]
    elif raw.startswith("0"):
        raw = raw[1:]
    if not re.fullmatch(r"[6-9]\d{9}", raw):
        raise forms.ValidationError("Enter a valid 10-digit Indian mobile number.")
    return raw


def phone_field():
    # Wider than the stored 10 digits so "+91 98765 43210" can be typed; normalise_phone() tidies it.
    return forms.CharField(
        max_length=20, required=True, label="Mobile number",
        widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel-national", "placeholder": "98765 43210"}),
        error_messages={"required": "Enter your 10-digit mobile number."},
    )


def country_code_field():
    """Shown as a small select in front of the number. Only +91 exists today and the number alone is what is stored."""
    return forms.ChoiceField(choices=COUNTRY_CODES, required=False, initial="+91", label="Country code")


class RegisterForm(BootstrapFormMixin, UserCreationForm):
    country_code = country_code_field()
    phone = phone_field()

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "email", "phone")

    field_order = ("first_name", "last_name", "email", "country_code", "phone", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name"):
            self.fields[name].required = True
        self.fields["email"].label = "Company email"
        self.fields["email"].widget.attrs["placeholder"] = "name@yourcompany.com"
        # One plain line instead of Django's list of four rules. PasswordMixValidator and the length rule enforce it.
        self.fields["password1"].help_text = "At least 8 characters with a letter, a number and a symbol."
        self.fields["password2"].label = "Confirm password"
        self.fields["password2"].help_text = "Type it once more so we know it is right."

    def clean_phone(self):
        return normalise_phone(self.cleaned_data.get("phone"))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        domain = email.rsplit("@", 1)[-1]
        if domain in settings.BLOCKED_EMAIL_DOMAINS:
            raise forms.ValidationError(
                "That looks like a personal email. Sign up with your office email, like name@yourcompany.com."
            )
        allowed = settings.ALLOWED_EMAIL_DOMAINS
        if allowed and domain not in allowed:
            raise forms.ValidationError("This company is not part of the pilot yet.")
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Company email"

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class OTPForm(BootstrapFormMixin, forms.Form):
    code = forms.RegexField(
        regex=r"^\d{6}$",
        label="6-digit code",
        error_messages={"invalid": "Enter the 6-digit code from the email."},
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "maxlength": "6"}),
    )


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    country_code = country_code_field()
    phone = phone_field()

    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone", "home_area")

    field_order = ("first_name", "last_name", "country_code", "phone", "home_area")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name"):
            self.fields[name].required = True

    def clean_phone(self):
        return normalise_phone(self.cleaned_data.get("phone"))


class DriverDocumentForm(BootstrapFormMixin, forms.ModelForm):
    FILE_FIELDS = ("licence_file", "rc_file", "insurance_file")

    class Meta:
        model = DriverDocument
        fields = (
            "vehicle_type", "licence_number", "licence_file", "rc_number", "rc_file", "insurance_expiry",
            "insurance_file",
        )
        labels = {
            "vehicle_type": "Vehicle you will offer rides in",
            "licence_number": "Driving licence number",
            "licence_file": "Driving licence (PDF, JPG or PNG)",
            "rc_number": "Vehicle RC number",
            "rc_file": "Vehicle RC (PDF, JPG or PNG)",
            "insurance_expiry": "Insurance expiry date",
            "insurance_file": "Insurance certificate (PDF, JPG or PNG)",
        }
        widgets = {
            "licence_number": forms.TextInput(attrs={"placeholder": "KA01 20110012345", "autocapitalize": "characters"}),
            "rc_number": forms.TextInput(attrs={"placeholder": "KA01AB1234", "autocapitalize": "characters"}),
            "licence_file": forms.FileInput(attrs={"accept": DOCUMENT_ACCEPT}),
            "rc_file": forms.FileInput(attrs={"accept": DOCUMENT_ACCEPT}),
            "insurance_file": forms.FileInput(attrs={"accept": DOCUMENT_ACCEPT}),
            "insurance_expiry": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remember stored file names so replaced files can be deleted after saving.
        self._old_files = (
            {name: getattr(self.instance, name).name for name in self.FILE_FIELDS} if self.instance.pk else {}
        )

    def clean_licence_number(self):
        try:
            return indian_ids.normalise_licence(self.cleaned_data["licence_number"], today=timezone.localdate())
        except ValueError:
            raise forms.ValidationError("Enter valid licence details.")

    def clean_rc_number(self):
        try:
            return indian_ids.normalise_rc(self.cleaned_data["rc_number"])
        except ValueError:
            raise forms.ValidationError("Enter valid RC details.")

    def clean_insurance_expiry(self):
        expiry = self.cleaned_data["insurance_expiry"]
        if expiry < timezone.localdate():
            raise forms.ValidationError("Your insurance has expired. Upload a valid policy.")
        return expiry

    def save(self, commit=True):
        doc = super().save(commit=False)
        # Any change sends the documents back for review.
        doc.status = DriverDocument.Status.PENDING
        doc.rejection_reason = ""
        doc.reviewed_by = None
        doc.reviewed_at = None
        if commit:
            doc.save()
            for name, old in self._old_files.items():
                if old and old != getattr(doc, name).name:
                    doc._meta.get_field(name).storage.delete(old)
        return doc