import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.signals import request_finished
from django.db import close_old_connections
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import DriverDocument

User = get_user_model()


def pdf(name="file.pdf", size=None):
    content = b"%PDF-1.4 test" if size is None else b"0" * size
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class DocumentTestCase(TestCase):
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
            "driver@company.com", "S3cure-pass!", first_name="Ravi", last_name="K",
            email_verified=True,
        )
        self.client.force_login(self.user)
        self.url = reverse("accounts:documents")

    def payload(self, **overrides):
        data = {
            "vehicle_type": "car",
            "licence_number": "ka01 20110012345",
            "licence_file": pdf("licence.pdf"),
            "rc_number": "KA01AB1234",
            "rc_file": pdf("rc.pdf"),
            "insurance_expiry": (timezone.localdate() + timedelta(days=200)).isoformat(),
            "insurance_file": pdf("insurance.pdf"),
        }
        data.update(overrides)
        return data

    def submit(self, **overrides):
        return self.client.post(self.url, self.payload(**overrides))


class SubmitDocumentsTests(DocumentTestCase):
    def test_page_loads(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_valid_submission_is_saved_as_pending(self):
        response = self.submit()
        self.assertRedirects(response, self.url)
        doc = DriverDocument.objects.get(user=self.user)
        self.assertEqual(doc.status, DriverDocument.Status.PENDING)
        self.assertEqual(doc.licence_number, "KA0120110012345")  # upper-cased, spaces removed
        for field in (doc.licence_file, doc.rc_file, doc.insurance_file):
            self.assertTrue(field.name.startswith(f"driver_docs/user_{self.user.pk}/"))
            self.assertTrue(field.name.endswith(".pdf"))
            self.assertTrue(default_storage.exists(field.name))
        self.assertNotIn("licence", doc.licence_file.name)  # original name is not kept

    def test_two_wheeler_documents_are_saved_with_their_vehicle_type(self):
        self.submit(vehicle_type="bike")
        doc = DriverDocument.objects.get(user=self.user)
        self.assertEqual(doc.vehicle_type, "bike")
        self.assertEqual(User.objects.get(pk=self.user.pk).offered_vehicle_type, "bike")

    def test_unknown_vehicle_type_is_rejected(self):
        response = self.submit(vehicle_type="truck")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DriverDocument.objects.exists())

    def test_expired_insurance_is_rejected(self):
        response = self.submit(insurance_expiry=(timezone.localdate() - timedelta(days=1)).isoformat())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "insurance has expired")
        self.assertFalse(DriverDocument.objects.exists())

    def test_wrong_file_type_is_rejected(self):
        bad = SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")
        response = self.submit(licence_file=bad)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PDF, JPG or PNG")
        self.assertFalse(DriverDocument.objects.exists())

    def test_oversized_file_is_rejected(self):
        response = self.submit(rc_file=pdf("rc.pdf", size=6 * 1024 * 1024))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "too large")
        self.assertFalse(DriverDocument.objects.exists())

    def test_invalid_licence_number_is_rejected(self):
        response = self.submit(licence_number="??")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DriverDocument.objects.exists())

    def test_missing_files_on_first_submission(self):
        data = self.payload()
        del data["licence_file"]
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DriverDocument.objects.exists())


class ResubmitDocumentsTests(DocumentTestCase):
    def setUp(self):
        super().setUp()
        self.submit()
        self.doc = DriverDocument.objects.get(user=self.user)
        self.doc.status = DriverDocument.Status.APPROVED
        self.doc.save()

    def same_values(self, **overrides):
        data = {
            "vehicle_type": self.doc.vehicle_type,
            "licence_number": self.doc.licence_number,
            "rc_number": self.doc.rc_number,
            "insurance_expiry": self.doc.insurance_expiry.isoformat(),
        }
        data.update(overrides)
        return data

    def test_unchanged_resubmission_keeps_approval(self):
        self.client.post(self.url, self.same_values())
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, DriverDocument.Status.APPROVED)

    def test_changing_the_vehicle_type_sends_documents_back_for_review(self):
        self.client.post(self.url, self.same_values(vehicle_type="bike"))
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.vehicle_type, "bike")
        self.assertEqual(self.doc.status, DriverDocument.Status.PENDING)

    def test_changed_number_sends_documents_back_for_review(self):
        self.client.post(self.url, self.same_values(rc_number="KA05XY9999"))
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, DriverDocument.Status.PENDING)
        self.assertEqual(self.doc.rc_number, "KA05XY9999")

    def test_replaced_file_is_deleted_from_storage(self):
        old_name = self.doc.licence_file.name
        self.client.post(self.url, {**self.same_values(), "licence_file": pdf("new-licence.pdf")})
        self.doc.refresh_from_db()
        self.assertNotEqual(self.doc.licence_file.name, old_name)
        self.assertFalse(default_storage.exists(old_name))
        self.assertTrue(default_storage.exists(self.doc.licence_file.name))
        self.assertEqual(self.doc.status, DriverDocument.Status.PENDING)

    def test_rejection_reason_is_cleared_on_resubmission(self):
        self.doc.status = DriverDocument.Status.REJECTED
        self.doc.rejection_reason = "Blurry"
        self.doc.save()
        self.client.post(self.url, self.same_values(rc_number="KA05XY9999"))
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, DriverDocument.Status.PENDING)
        self.assertEqual(self.doc.rejection_reason, "")


class StaffFileAccessTests(DocumentTestCase):
    def setUp(self):
        super().setUp()
        self.submit()
        self.doc = DriverDocument.objects.get(user=self.user)
        self.staff = User.objects.create_superuser("admin@company.com", "S3cure-pass!")

    def file_url(self, kind="licence"):
        return reverse("accounts:document_file", args=[self.doc.pk, kind])

    def test_staff_can_open_a_document(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.file_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 test")
        # Closing a streaming response fires request_finished, which would close the test
        # database connection on PostgreSQL. The test client does the same disconnect itself.
        request_finished.disconnect(close_old_connections)
        try:
            response.close()
        finally:
            request_finished.connect(close_old_connections)

    def test_owner_can_open_their_own_document_any_time(self):
        response = self.client.get(self.file_url("rc"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        request_finished.disconnect(close_old_connections)
        try:
            response.close()
        finally:
            request_finished.connect(close_old_connections)

    def test_another_user_cannot_open_a_document(self):
        other = User.objects.create_user("rider@company.com", "S3cure-pass!", email_verified=True)
        self.client.force_login(other)
        for kind in ("licence", "rc", "insurance"):
            with self.subTest(kind):
                self.assertEqual(self.client.get(self.file_url(kind)).status_code, 404)

    def test_anonymous_user_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(self.file_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_unknown_kind_is_404(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.file_url("passport")).status_code, 404)


class AdminReviewTests(DocumentTestCase):
    def setUp(self):
        super().setUp()
        self.submit()
        self.doc = DriverDocument.objects.get(user=self.user)
        self.staff = User.objects.create_superuser("admin@company.com", "S3cure-pass!")
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


class IndianNumberFormTests(DocumentTestCase):
    """The RC and licence numbers must look like real Indian ones, from any state."""

    def test_the_numbers_from_the_old_screenshot_are_refused(self):
        response = self.submit(licence_number="CWCQAAC", rc_number="KCWCQINCIQ")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter valid licence details.")
        self.assertContains(response, "Enter valid RC details.")
        self.assertFalse(DriverDocument.objects.exists())

    def test_vehicles_and_licences_from_other_states_are_accepted(self):
        response = self.submit(licence_number="tn07 20181234567", rc_number="ap 39 ud 0001")
        self.assertRedirects(response, self.url)
        doc = DriverDocument.objects.get()
        self.assertEqual((doc.licence_number, doc.rc_number), ("TN0720181234567", "AP39UD0001"))

    def test_a_wrong_state_code_gets_the_same_simple_message(self):
        response = self.submit(rc_number="ZZ01AB1234")
        self.assertContains(response, "Enter valid RC details.")
        self.assertNotContains(response, "state code")

    def test_the_page_shows_an_example_in_each_box(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'placeholder="KA01 20110012345"')
        self.assertContains(page, 'placeholder="KA01AB1234"')


class DriverCanSeeOwnFilesTests(DocumentTestCase):
    def test_saved_files_have_view_buttons_for_the_driver(self):
        self.submit()
        doc = DriverDocument.objects.get()
        page = self.client.get(self.url)
        for kind, label in (("licence", "View licence"), ("rc", "View RC"), ("insurance", "View insurance")):
            with self.subTest(kind):
                self.assertContains(page, reverse("accounts:document_file", args=[doc.pk, kind]))
                self.assertContains(page, label)

    def test_a_new_driver_sees_no_view_buttons(self):
        self.assertNotContains(self.client.get(self.url), "View licence")

    def test_riders_see_only_the_verified_badge_never_the_files(self):
        from apps.rides.tests.helpers import make_driver, make_ride, make_user

        driver = make_driver("verified@acme.com")
        ride = make_ride(driver)
        rider = make_user("rider2@acme.com")
        self.client.force_login(rider)
        page = self.client.get(reverse("rides:detail", args=[ride.pk]))
        self.assertContains(page, "Documents verified")
        self.assertNotContains(page, "driver_docs")
        self.assertNotContains(page, "document_file")
        self.assertNotContains(page, f"/accounts/documents/{driver.driver_document.pk}/")