from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import DriverDocument

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_user_logs_in_with_email(self):
        user = User.objects.create_user("anil@company.com", "S3cure-pass!")
        self.assertEqual(user.email, "anil@company.com")
        self.assertTrue(user.check_password("S3cure-pass!"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.email_verified)

    def test_email_is_required(self):
        with self.assertRaises(ValueError):
            User.objects.create_user("", "S3cure-pass!")

    def test_email_is_stored_in_lowercase(self):
        user = User.objects.create_user("Anil.Kumar@Company.COM", "S3cure-pass!")
        self.assertEqual(user.email, "anil.kumar@company.com")

    def test_create_superuser(self):
        admin = User.objects.create_superuser("admin@company.com", "S3cure-pass!")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.email_verified)


class CanOfferRidesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("driver@company.com", "S3cure-pass!", email_verified=True)

    def make_doc(self, status, days_until_expiry):
        doc = DriverDocument(
            user=self.user,
            licence_number="KA0120110012345",
            rc_number="KA01AB1234",
            insurance_expiry=timezone.localdate() + timedelta(days=days_until_expiry),
            status=status,
        )
        for name in ("licence_file", "rc_file", "insurance_file"):
            getattr(doc, name).save(f"{name}.pdf", ContentFile(b"x"), save=False)
        doc.save()
        self.addCleanup(lambda: [getattr(doc, n).delete(save=False) for n in ("licence_file", "rc_file", "insurance_file")])
        return doc

    def test_no_documents(self):
        self.assertFalse(self.user.can_offer_rides)

    def test_pending_documents(self):
        self.make_doc(DriverDocument.Status.PENDING, 100)
        self.assertFalse(User.objects.get(pk=self.user.pk).can_offer_rides)

    def test_approved_with_valid_insurance(self):
        self.make_doc(DriverDocument.Status.APPROVED, 100)
        self.assertTrue(User.objects.get(pk=self.user.pk).can_offer_rides)

    def test_approved_but_insurance_expired(self):
        self.make_doc(DriverDocument.Status.APPROVED, -1)
        self.assertFalse(User.objects.get(pk=self.user.pk).can_offer_rides)