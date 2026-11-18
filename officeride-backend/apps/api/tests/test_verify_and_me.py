from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import DriverDocument, EmailOTP, User

from .helpers import FreshCache, client_for, code_from_last_email, make_person, signup_body


class VerifyEmailTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        response = client_for().post(reverse("api:register"), signup_body(), format="json")
        self.user = User.objects.get(email="anita@acme.com")
        self.client_ = client_for(self.user)
        self.verify_url = reverse("api:verify_email")

    def verify(self, code):
        return self.client_.post(self.verify_url, {"code": code}, format="json")

    def test_the_right_code_verifies_the_email(self):
        response = self.verify(code_from_last_email())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["user"]["email_verified"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)

    def test_a_wrong_code_is_refused_with_a_reason_the_app_can_act_on(self):
        response = self.verify("000000")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid")
        self.assertIn("not correct", response.json()["detail"])

    def test_five_wrong_codes_lock_the_code(self):
        for _ in range(5):
            response = self.verify("000000")
        self.assertEqual(response.json()["code"], "locked")
        self.assertEqual(self.verify(code_from_last_email()).json()["code"], "locked")

    def test_an_old_code_has_expired(self):
        EmailOTP.objects.filter(user=self.user).update(created_at=timezone.now() - timedelta(minutes=11))
        response = self.verify(code_from_last_email())
        self.assertEqual(response.json()["code"], "expired")

    def test_with_no_code_asked_for_the_answer_says_so(self):
        EmailOTP.objects.all().delete()
        self.assertEqual(self.verify("123456").json()["code"], "no_code")

    def test_a_code_that_is_not_six_digits_is_a_field_error(self):
        for bad in ("12345", "1234567", "abcdef", ""):
            with self.subTest(code=bad):
                response = self.verify(bad)
                self.assertEqual(response.status_code, 400)
                self.assertIn("code", response.json()["errors"])

    def test_verifying_twice_is_fine(self):
        code = code_from_last_email()
        self.verify(code)
        self.assertEqual(self.verify(code).status_code, 200)

    def test_it_needs_a_login(self):
        self.assertEqual(client_for().post(self.verify_url, {"code": "123456"}, format="json").status_code, 401)


class ResendCodeTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        client_for().post(reverse("api:register"), signup_body(), format="json")
        self.user = User.objects.get(email="anita@acme.com")
        self.client_ = client_for(self.user)
        self.url = reverse("api:resend_code")

    def make_old(self):
        EmailOTP.objects.filter(user=self.user).update(created_at=timezone.now() - timedelta(minutes=2))

    def test_asking_again_straight_away_must_wait(self):
        response = self.client_.post(self.url)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "wait")
        self.assertTrue(0 < response.json()["wait"] <= 60)
        self.assertEqual(len(mail.outbox), 1)

    def test_after_the_wait_a_new_code_is_sent_and_the_old_one_stops_working(self):
        old = code_from_last_email()
        self.make_old()
        response = self.client_.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 2)
        new = code_from_last_email()
        if new != old:
            self.assertEqual(self.client_.post(reverse("api:verify_email"), {"code": old}, format="json").status_code, 400)
        self.assertEqual(self.client_.post(reverse("api:verify_email"), {"code": new}, format="json").status_code, 200)

    def test_a_mail_problem_is_503_with_a_plain_message(self):
        self.make_old()
        with mock.patch("apps.api.views.account_services.send_otp", side_effect=RuntimeError("down")), \
                self.assertLogs("apps.api.views", level="ERROR"):
            response = self.client_.post(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "email_failed")

    def test_a_verified_person_is_not_sent_another_code(self):
        self.user.email_verified = True
        self.user.save()
        self.make_old()
        response = self.client_.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_it_needs_a_login(self):
        self.assertEqual(client_for().post(self.url).status_code, 401)


class MeTests(FreshCache, TestCase):
    def setUp(self):
        super().setUp()
        self.person = make_person(home_area="Hebbal")
        self.client_ = client_for(self.person)
        self.url = reverse("api:me")

    def test_me_shows_the_person_and_never_a_password(self):
        response = self.client_.get(self.url)
        data = response.json()
        self.assertEqual(data["email"], "anita@acme.com")
        self.assertEqual((data["first_name"], data["last_name"]), ("Anita", "Rao"))
        self.assertEqual((data["country_code"], data["phone"], data["home_area"]), ("+91", "9876543210", "Hebbal"))
        self.assertNotIn("password", response.content.decode().lower())

    def test_a_new_person_has_no_rating_no_strikes_and_no_documents(self):
        data = self.client_.get(self.url).json()
        self.assertEqual(data["stats"], {"average": None, "count": 0, "rides": 0})
        self.assertEqual(data["strikes"]["count"], 0)
        self.assertIsNone(data["documents"])
        self.assertFalse(data["can_offer_rides"])
        self.assertIsNone(data["offered_vehicle_type"])
        self.assertEqual(data["blocked"], {"is_blocked": False, "message": ""})

    def test_an_approved_driver_shows_their_vehicle_and_documents(self):
        DriverDocument.objects.create(
            user=self.person, vehicle_type="bike", licence_number="KA0120110012345", rc_number="KA01AB1234",
            insurance_expiry=timezone.localdate() + timedelta(days=100), status="approved",
            licence_file="x.pdf", rc_file="y.pdf", insurance_file="z.pdf",
        )
        data = self.client_.get(self.url).json()
        self.assertTrue(data["can_offer_rides"])
        self.assertEqual(data["offered_vehicle_type"], "bike")
        self.assertEqual(data["documents"]["status"], "approved")
        self.assertTrue(data["documents"]["usable"])
        self.assertNotIn("licence_file", data["documents"])

    def test_the_rating_shows_up(self):
        from apps.bookings.tests.helpers import car_ride, make_request
        from apps.rides.tests.helpers import make_driver
        from apps.trust.models import Rating
        driver = make_driver("d@acme.com")
        req = make_request(car_ride(driver), self.person, status="completed")
        Rating.objects.create(request=req, rater=driver, rated=self.person, stars=4)
        stats = self.client_.get(self.url).json()["stats"]
        self.assertEqual((stats["average"], stats["count"], stats["rides"]), (4.0, 1, 1))

    def test_an_unverified_person_can_still_look_at_me(self):
        person = make_person("new@acme.com", verified=False)
        response = client_for(person).get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["email_verified"])

    def test_changing_the_profile_saves_and_tidies_the_phone(self):
        response = self.client_.patch(self.url, {"first_name": "Anitha", "phone": "+91 91234-56789", "home_area": "Yelahanka"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.person.refresh_from_db()
        self.assertEqual((self.person.first_name, self.person.phone, self.person.home_area), ("Anitha", "9123456789", "Yelahanka"))
        self.assertEqual(response.json()["phone"], "9123456789")

    def test_a_change_of_one_field_keeps_the_others(self):
        self.client_.patch(self.url, {"home_area": "Whitefield"}, format="json")
        self.person.refresh_from_db()
        self.assertEqual((self.person.first_name, self.person.phone, self.person.home_area), ("Anita", "9876543210", "Whitefield"))

    def test_a_bad_phone_is_refused_and_nothing_changes(self):
        response = self.client_.patch(self.url, {"phone": "123", "first_name": "Changed"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.json()["errors"])
        self.person.refresh_from_db()
        self.assertEqual(self.person.first_name, "Anita")

    def test_the_names_cannot_be_emptied(self):
        response = self.client_.patch(self.url, {"first_name": ""}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_the_email_and_the_rights_cannot_be_changed_from_the_profile(self):
        self.client_.patch(self.url, {"email": "other@acme.com", "is_staff": True, "email_verified": False, "is_superuser": True}, format="json")
        self.person.refresh_from_db()
        self.assertEqual(self.person.email, "anita@acme.com")
        self.assertFalse(self.person.is_staff)
        self.assertFalse(self.person.is_superuser)
        self.assertTrue(self.person.email_verified)

    def test_an_unverified_person_cannot_change_the_profile(self):
        person = make_person("new@acme.com", verified=False)
        response = client_for(person).patch(self.url, {"home_area": "X"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Please verify your email first.")

    def test_me_needs_a_login(self):
        self.assertEqual(client_for().get(self.url).status_code, 401)
        self.assertEqual(client_for().patch(self.url, {}, format="json").status_code, 401)