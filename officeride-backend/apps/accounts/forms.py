import re

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils import timezone

from apps.core.forms import BootstrapFormMixin

from .models import DriverDocument, User

DOCUMENT_ACCEPT = ".pdf,.jpg,.jpeg,.png"
ID_NUMBER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9 /-]{3,29}$")


class RegisterForm(BootstrapFormMixin, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "email", "techpark")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "techpark"):
            self.fields[name].required = True
        self.fields["email"].label = "Company email"
        self.fields["email"].help_text = "Personal addresses such as Gmail are not accepted."

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        domain = email.rsplit("@", 1)[-1]
        if domain in settings.BLOCKED_EMAIL_DOMAINS:
            raise forms.ValidationError("Please use your company email, not a personal one.")
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
    # Wider than the stored 10 digits so "+91 98765 43210" can be typed; clean_phone() tidies it.
    phone = forms.CharField(max_length=20, required=False, label="Phone")

    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone", "home_area", "techpark")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "techpark"):
            self.fields[name].required = True
        self.fields["phone"].help_text = "10-digit mobile number (optional)."

    def clean_phone(self):
        raw = re.sub(r"[\s-]", "", self.cleaned_data.get("phone", ""))
        if not raw:
            return ""
        if raw.startswith("+91"):
            raw = raw[3:]
        elif raw.startswith("0"):
            raw = raw[1:]
        if not re.fullmatch(r"[6-9]\d{9}", raw):
            raise forms.ValidationError("Enter a valid 10-digit Indian mobile number.")
        return raw


class DriverDocumentForm(BootstrapFormMixin, forms.ModelForm):
    FILE_FIELDS = ("licence_file", "rc_file", "insurance_file")

    class Meta:
        model = DriverDocument
        fields = (
            "licence_number", "licence_file", "rc_number", "rc_file", "insurance_expiry", "insurance_file",
        )
        labels = {
            "licence_number": "Driving licence number",
            "licence_file": "Driving licence (PDF, JPG or PNG)",
            "rc_number": "Vehicle RC number",
            "rc_file": "Vehicle RC (PDF, JPG or PNG)",
            "insurance_expiry": "Insurance expiry date",
            "insurance_file": "Insurance certificate (PDF, JPG or PNG)",
        }
        widgets = {
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

    def _clean_number(self, name, label):
        value = self.cleaned_data[name].strip().upper()
        if not ID_NUMBER_PATTERN.match(value):
            raise forms.ValidationError(f"Enter a valid {label} number (letters, digits, spaces, - or /).")
        return value

    def clean_licence_number(self):
        return self._clean_number("licence_number", "licence")

    def clean_rc_number(self):
        return self._clean_number("rc_number", "RC")

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