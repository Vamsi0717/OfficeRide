import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

TECH_PARKS = [
    ("bellandur_orr", "Bellandur / Outer Ring Road"),
    ("whitefield", "Whitefield"),
    ("manyata", "Manyata Tech Park"),
    ("electronic_city", "Electronic City"),
    ("sarjapur_road", "Sarjapur Road"),
    ("other", "Other"),
]


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("email_verified", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user that logs in with email."""

    username = None
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=10, blank=True)
    home_area = models.CharField(max_length=80, blank=True)
    techpark = models.CharField("tech park", max_length=20, choices=TECH_PARKS, blank=True)
    email_verified = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email

    @property
    def can_offer_rides(self):
        """True when the driver's documents are approved and the insurance is still valid."""
        doc = getattr(self, "driver_document", None)  # missing relation raises an AttributeError subclass
        return bool(doc and doc.is_usable)

    @property
    def offered_vehicle_type(self):
        """'car' or 'bike' from the driver's documents, or None when no documents were submitted."""
        doc = getattr(self, "driver_document", None)
        return doc.vehicle_type if doc else None


class EmailOTP(models.Model):
    """One-time code sent to a user's email. Only a hash of the code is stored."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_otps")
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"OTP for {self.user_id} at {self.created_at:%Y-%m-%d %H:%M}"


ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def validate_document_file(f):
    if getattr(f, "_committed", False):  # already stored earlier, nothing new to check
        return
    if Path(f.name).suffix.lower() not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValidationError("Upload a PDF, JPG or PNG file.")
    max_mb = settings.DOCUMENT_MAX_MB
    if f.size > max_mb * 1024 * 1024:
        raise ValidationError(f"File is too large. The limit is {max_mb} MB.")


def driver_doc_path(instance, filename):
    """Random file names keep uploads unguessable and avoid clashes."""
    return f"driver_docs/user_{instance.user_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class VehicleType(models.TextChoices):
    CAR = "car", "Car"
    BIKE = "bike", "Two-wheeler"


class DriverDocument(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="driver_document")
    vehicle_type = models.CharField(max_length=10, choices=VehicleType.choices, default=VehicleType.CAR)
    licence_number = models.CharField(max_length=30)
    licence_file = models.FileField(upload_to=driver_doc_path, validators=[validate_document_file])
    rc_number = models.CharField("vehicle RC number", max_length=30)
    rc_file = models.FileField("vehicle RC file", upload_to=driver_doc_path, validators=[validate_document_file])
    insurance_expiry = models.DateField()
    insurance_file = models.FileField(upload_to=driver_doc_path, validators=[validate_document_file])

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    rejection_reason = models.CharField(max_length=200, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Documents of {self.user} ({self.status})"

    @property
    def insurance_valid(self):
        return self.insurance_expiry >= timezone.localdate()

    @property
    def is_usable(self):
        return self.status == self.Status.APPROVED and self.insurance_valid