from django.contrib.admin.sites import site
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.bookings.tests.helpers import make_request
from apps.rides.tests.helpers import make_user
from apps.trust import services
from apps.trust.models import Complaint, Strike

from .helpers import S, TripMixin


class AdminToolTests(TripMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = make_user("admin@acme.com", is_staff=True, is_superuser=True)
        self.client.force_login(self.admin_user)
        req = self.booking(S.CANCELLED)
        self.strike = services.record_strike(self.rider, Strike.Reason.NO_SHOW, req)

    def run_action(self, name, queryset=None):
        model_admin = site._registry[Strike]
        request = RequestFactory().post("/")
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        getattr(model_admin, name)(request, queryset if queryset is not None else Strike.objects.all())

    def test_the_admin_pages_open(self):
        for name in ("trust_strike", "trust_complaint", "trust_rating"):
            self.assertEqual(self.client.get(reverse(f"admin:{name}_changelist")).status_code, 200)

    def test_strike_filters_work(self):
        url = reverse("admin:trust_strike_changelist")
        self.assertEqual(self.client.get(url, {"waived__exact": "0"}).status_code, 200)
        self.assertEqual(self.client.get(url, {"reason": "no_show"}).status_code, 200)

    def test_waive_records_who_and_when(self):
        self.run_action("waive_strikes")
        self.strike.refresh_from_db()
        self.assertTrue(self.strike.waived)
        self.assertEqual(self.strike.waived_by, self.admin_user)
        self.assertIsNotNone(self.strike.waived_at)

    def test_suspend_clear_review_and_finish_review(self):
        self.run_action("suspend_users")
        self.rider.refresh_from_db()
        self.assertTrue(self.rider.is_suspended)
        self.run_action("clear_suspensions")
        self.rider.refresh_from_db()
        self.assertFalse(self.rider.is_blocked)
        self.run_action("send_users_to_review")
        self.rider.refresh_from_db()
        self.assertTrue(self.rider.under_review)
        self.run_action("clear_reviews")
        self.rider.refresh_from_db()
        self.assertFalse(self.rider.under_review)

    def test_ticking_waived_in_the_edit_page_goes_through_the_same_rules(self):
        response = self.client.post(reverse("admin:trust_strike_change", args=[self.strike.pk]), {"waived": "on"})
        self.assertEqual(response.status_code, 302)
        self.strike.refresh_from_db()
        self.assertTrue(self.strike.waived)
        self.assertEqual(self.strike.waived_by, self.admin_user)

    def test_changing_a_complaint_records_who_handled_it(self):
        req = self.booking(S.COMPLETED, rider=make_user("c@acme.com"))
        complaint = services.file_complaint(req, req.rider, Complaint.Kind.RUDE, "Rude")
        response = self.client.post(
            reverse("admin:trust_complaint_change", args=[complaint.pk]), {"status": "resolved", "admin_notes": "Spoke to the driver"})
        self.assertEqual(response.status_code, 302)
        complaint.refresh_from_db()
        self.assertEqual((complaint.status, complaint.admin_notes, complaint.handled_by), ("resolved", "Spoke to the driver", self.admin_user))
        self.assertIsNotNone(complaint.handled_at)

    def test_the_user_page_shows_the_trust_fields(self):
        self.assertContains(self.client.get(reverse("admin:accounts_user_change", args=[self.rider.pk])), "Suspended until")

    def test_a_normal_user_cannot_open_the_admin(self):
        self.client.force_login(self.rider)
        self.assertEqual(self.client.get(reverse("admin:trust_strike_changelist")).status_code, 302)