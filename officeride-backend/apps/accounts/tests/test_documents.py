import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.signals import request_finished
from django.db import close_old_connections
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import DriverDocument

User = get_user_model()


def pdf(name="file.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")


class DocumentTestCase(TestCase):
    """A driver with documents already saved. The files go to a temporary folder that is deleted afterwards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(
            "driver@company.com", "S3cure-pass!", first_name="Ravi", last_name="K", email_verified=True,
        )
        self.doc = DriverDocument.objects.create(
            user=self.user, vehicle_type="car", licence_number="KA0120110012345", licence_file=pdf("licence.pdf"),
            rc_number="KA01AB1234", rc_file=pdf("rc.pdf"), insurance_expiry=timezone.localdate() + timedelta(days=200),
            insurance_file=pdf("insurance.pdf"),
        )
        self.staff = User.objects.create_superuser("admin@company.com", "S3cure-pass!")


def close_quietly(response):
    # Closing a streaming response fires request_finished, which would close the test database
    # connection on PostgreSQL. The test client does the same disconnect itself.
    request_finished.disconnect(close_old_connections)
    try:
        response.close()
    finally:
        request_finished.connect(close_old_connections)


class StaffFileAccessTests(DocumentTestCase):
    def file_url(self, kind="licence"):
        return reverse("accounts:document_file", args=[self.doc.pk, kind])

    def test_staff_can_open_a_document(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.file_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 test")
        close_quietly(response)

    def test_owner_can_open_their_own_document_any_time(self):
        self.client.force_login(self.user)
        response = self.client.get(self.file_url("rc"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        close_quietly(response)

    def test_another_user_cannot_open_a_document(self):
        other = User.objects.create_user("rider@company.com", "S3cure-pass!", email_verified=True)
        self.client.force_login(other)
        for kind in ("licence", "rc", "insurance"):
            with self.subTest(kind):
                self.assertEqual(self.client.get(self.file_url(kind)).status_code, 404)

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(self.file_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_unknown_kind_is_404(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.file_url("passport")).status_code, 404)


class AdminReviewTests(DocumentTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff)

    def test_approve_action(self):
        response = self.client.post(reverse("admin:accounts_driverdocument_changelist"), {
            "action": "approve_documents",
            "_selected_action": [self.doc.pk],
        })
        self.assertEqual(response.status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, DriverDocument.Status.APPROVED)
        self.assertEqual(self.doc.reviewed_by, self.staff)
        self.assertIsNotNone(self.doc.reviewed_at)
        self.assertTrue(User.objects.get(pk=self.user.pk).can_offer_rides)

    def test_reject_with_reason_from_detail_page(self):
        url = reverse("admin:accounts_driverdocument_change", args=[self.doc.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"status": "rejected", "rejection_reason": "Photo is blurry"})
        self.assertEqual(response.status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, DriverDocument.Status.REJECTED)
        self.assertEqual(self.doc.rejection_reason, "Photo is blurry")
        self.assertEqual(self.doc.reviewed_by, self.staff)
        self.assertFalse(User.objects.get(pk=self.user.pk).can_offer_rides)

    def test_staff_cannot_add_documents_for_users(self):
        self.assertEqual(self.client.get(reverse("admin:accounts_driverdocument_add")).status_code, 403)

    def test_the_admin_page_links_to_the_files(self):
        page = self.client.get(reverse("admin:accounts_driverdocument_change", args=[self.doc.pk]))
        self.assertContains(page, "View file")