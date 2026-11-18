from django.test import TestCase
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from .helpers import client_for, make_person


class HealthAndLoginRequiredTests(TestCase):
    def test_health_needs_no_login(self):
        response = client_for().get(reverse("api:health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "name": "OfficeRide API", "version": 1})

    def test_the_api_lives_under_api_v1(self):
        self.assertEqual(reverse("api:health"), "/api/v1/health/")

    def test_a_private_address_without_a_token_is_401(self):
        response = client_for().get(reverse("api:me"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("detail", response.json())

    def test_a_made_up_token_is_401(self):
        client = client_for()
        client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        self.assertEqual(client.get(reverse("api:me")).status_code, 401)

    def test_answers_are_json_not_web_pages(self):
        response = client_for().get(reverse("api:health"))
        self.assertEqual(response["Content-Type"], "application/json")

    def test_a_token_works_for_the_person_it_was_made_for(self):
        person = make_person()
        response = client_for(person).get(reverse("api:me"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "anita@acme.com")


class RefreshTests(TestCase):
    def test_a_refresh_token_gives_a_new_access_token_and_a_new_refresh_token(self):
        person = make_person()
        refresh = str(RefreshToken.for_user(person))
        response = client_for().post(reverse("api:refresh"), {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        client = client_for()
        client.credentials(HTTP_AUTHORIZATION="Bearer " + data["access"])
        self.assertEqual(client.get(reverse("api:me")).status_code, 200)

    def test_a_bad_refresh_token_is_401(self):
        response = client_for().post(reverse("api:refresh"), {"refresh": "nonsense"}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_an_access_token_cannot_be_used_to_refresh(self):
        from apps.api.views import tokens_for
        access = tokens_for(make_person())["access"]
        response = client_for().post(reverse("api:refresh"), {"refresh": access}, format="json")
        self.assertEqual(response.status_code, 401)


class CorsTests(TestCase):
    def preflight(self, origin):
        return client_for().options(
            reverse("api:login"), HTTP_ORIGIN=origin, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,authorization",
        )

    def test_the_react_dev_server_may_call_the_api(self):
        response = self.preflight("http://localhost:5173")
        self.assertEqual(response["Access-Control-Allow-Origin"], "http://localhost:5173")

    def test_the_android_app_may_call_the_api(self):
        for origin in ("http://localhost", "https://localhost", "capacitor://localhost"):
            with self.subTest(origin=origin):
                self.assertEqual(self.preflight(origin)["Access-Control-Allow-Origin"], origin)

    def test_another_website_may_not(self):
        self.assertNotIn("Access-Control-Allow-Origin", self.preflight("https://evil.example.com"))

    def test_a_normal_answer_also_carries_the_header(self):
        response = client_for().get(reverse("api:health"), HTTP_ORIGIN="http://localhost:5173")
        self.assertEqual(response["Access-Control-Allow-Origin"], "http://localhost:5173")