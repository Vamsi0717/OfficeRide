from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


class RegisterTests(TestCase):
    url = reverse("accounts:register")

    def payload(self, **overrides):
        data = {
            "first_name": "Anil",
            "last_name": "Kumar",
            "email": "anil@company.com",
            "techpark": "whitefield",
            "password1": "Str0ng-pass-91",
            "password2": "Str0ng-pass-91",
        }
        data.update(overrides)
        return data

    def test_register_creates_user_logs_in_and_sends_otp(self):
        response = self.client.post(self.url, self.payload())
        self.assertRedirects(response, reverse("accounts:verify"))
        user = User.objects.get(email="anil@company.com")
        self.assertFalse(user.email_verified)
        self.assertEqual(user.techpark, "whitefield")
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["anil@company.com"])

    def test_personal_email_is_rejected(self):
        response = self.client.post(self.url, self.payload(email="anil@gmail.com"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "company email")
        self.assertFalse(User.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(ALLOWED_EMAIL_DOMAINS={"acme.com"})
    def test_pilot_allow_list(self):
        rejected = self.client.post(self.url, self.payload(email="anil@other.com"))
        self.assertEqual(rejected.status_code, 200)
        self.assertFalse(User.objects.exists())
        accepted = self.client.post(self.url, self.payload(email="anil@acme.com"))
        self.assertEqual(accepted.status_code, 302)
        self.assertTrue(User.objects.filter(email="anil@acme.com").exists())

    def test_duplicate_email_ignores_case(self):
        User.objects.create_user("anil@company.com", "S3cure-pass!")
        response = self.client.post(self.url, self.payload(email="ANIL@Company.com"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertEqual(User.objects.count(), 1)

    def test_weak_password_is_rejected(self):
        response = self.client.post(self.url, self.payload(password1="12345678", password2="12345678"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_tech_park_is_required(self):
        response = self.client.post(self.url, self.payload(techpark=""))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_logged_in_user_is_sent_away_from_register(self):
        user = User.objects.create_user("a@company.com", "S3cure-pass!")
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "anil@company.com", "S3cure-pass!", first_name="Anil", last_name="K", techpark="whitefield"
        )

    def test_login_with_email_is_case_insensitive(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "ANIL@Company.com", "password": "S3cure-pass!"}
        )
        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))

    def test_wrong_password(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "anil@company.com", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_profile_requires_login(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertRedirects(
            response, f"{reverse('accounts:login')}?next={reverse('accounts:profile')}", fetch_redirect_response=False
        )

    def test_unverified_user_is_sent_to_verify(self):
        self.client.force_login(self.user)
        for name in ("accounts:profile", "accounts:documents"):
            response = self.client.get(reverse(name))
            self.assertRedirects(response, reverse("accounts:verify"), fetch_redirect_response=False)


class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "anil@company.com", "S3cure-pass!", first_name="Anil", last_name="K",
            techpark="whitefield", email_verified=True,
        )
        self.client.force_login(self.user)
        self.url = reverse("accounts:profile")

    def test_profile_page_loads(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "anil@company.com")

    def test_update_profile_and_normalise_phone(self):
        response = self.client.post(self.url, {
            "first_name": "Anil", "last_name": "Kumar", "phone": "+91 98765-43210",
            "home_area": "KR Puram", "techpark": "bellandur_orr",
        })
        self.assertRedirects(response, self.url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "9876543210")
        self.assertEqual(self.user.home_area, "KR Puram")
        self.assertEqual(self.user.techpark, "bellandur_orr")

    def test_invalid_phone_is_rejected(self):
        response = self.client.post(self.url, {
            "first_name": "Anil", "last_name": "Kumar", "phone": "12345",
            "home_area": "", "techpark": "whitefield",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "valid 10-digit")
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "")