from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.rides.tests.helpers import make_driver, make_user

TAB_NAMES = ("Find", "Offer", "My trips", "My week", "Profile")


class FoundationTests(TestCase):
    def test_the_stylesheet_has_the_fresh_green_colours(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "officeride.css").read_text(encoding="utf-8")
        for colour in ("#10B981", "#0F172A", "#F0FDF4", "#047857"):
            with self.subTest(colour):
                self.assertIn(colour, css)

    def test_every_page_loads_the_fonts_and_the_stylesheet(self):
        page = self.client.get(reverse("home"))
        self.assertContains(page, "css/officeride.css")
        self.assertContains(page, "Bricolage+Grotesque")
        self.assertContains(page, "DM+Sans")

    def test_the_logo_mark_is_in_the_top_bar(self):
        self.assertContains(self.client.get(reverse("home")), "or-mark")


class BottomMenuTests(TestCase):
    def setUp(self):
        self.user = make_driver()
        self.user.phone = "9845012345"
        self.user.save()

    def test_a_visitor_has_no_bottom_menu(self):
        page = self.client.get(reverse("home"))
        self.assertNotContains(page, "or-tabs")
        self.assertContains(page, "Log in")
        self.assertContains(page, "Sign up")

    def test_a_logged_in_person_sees_the_five_tabs(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("rides:find"))
        self.assertContains(page, 'class="or-tabs"')
        for name in TAB_NAMES:
            with self.subTest(name):
                self.assertContains(page, f"</span>{name}</a>")

    def test_the_tab_of_the_page_you_are_on_is_marked(self):
        self.client.force_login(self.user)
        for url_name, label in (
            ("rides:find", "Find"), ("rides:offer", "Offer"), ("bookings:trips", "My trips"),
            ("bookings:plan", "My week"), ("accounts:profile", "Profile"),
        ):
            with self.subTest(url_name):
                page = self.client.get(reverse(url_name))
                self.assertContains(page, "or-tab active", count=1)
                self.assertContains(page, f"or-tab active\" href=\"{reverse(url_name)}\"")
                self.assertContains(page, f"</span>{label}</a>")

    def test_the_top_bar_keeps_only_the_logo_and_log_out(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("rides:find"))
        self.assertContains(page, "Log out")
        self.assertNotContains(page, 'title="Rides I offer"')
        self.assertNotContains(page, 'title="My documents"')

    def test_rides_i_offer_and_documents_are_in_the_profile_menu(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("accounts:profile"))
        self.assertContains(page, f'href="{reverse("rides:mine")}"')
        self.assertContains(page, f'href="{reverse("accounts:documents")}"')
        self.assertContains(page, "Rides I offer")
        self.assertContains(page, "My documents")


class LoginPageTests(TestCase):
    def setUp(self):
        self.page = self.client.get(reverse("accounts:login"))

    def test_it_has_the_green_hero_and_welcome(self):
        self.assertContains(self.page, "Share the ride to work.")
        self.assertContains(self.page, "Welcome back")
        self.assertContains(self.page, "Only work email addresses can join.")

    def test_it_has_no_top_bar_or_bottom_menu(self):
        self.assertNotContains(self.page, "or-top")
        self.assertNotContains(self.page, "or-tabs")

    def test_it_links_to_sign_up(self):
        self.assertContains(self.page, reverse("accounts:register"))
        self.assertContains(self.page, "Create an account")

    def test_it_still_logs_people_in(self):
        make_user("login@acme.com")
        response = self.client.post(reverse("accounts:login"), {"username": "login@acme.com", "password": "S3cure-pass!"})
        self.assertEqual(response.status_code, 302)

    def test_a_wrong_password_shows_an_error_on_the_same_page(self):
        make_user("login2@acme.com")
        response = self.client.post(reverse("accounts:login"), {"username": "login2@acme.com", "password": "nope"})
        self.assertContains(response, "Welcome back")
        self.assertContains(response, "Please enter a correct email and password")


class SignUpPageTests(TestCase):
    def setUp(self):
        self.page = self.client.get(reverse("accounts:register"))

    def test_it_shows_the_progress_header_and_the_new_button(self):
        self.assertContains(self.page, "Step 1 of 2")
        self.assertContains(self.page, "Create your account")
        self.assertContains(self.page, "Create account</button>")
        self.assertContains(self.page, reverse("accounts:login"))

    def test_the_password_field_is_marked_for_the_strength_meter(self):
        self.assertContains(self.page, "data-password-meter")
        self.assertContains(self.page, "js/password_meter.js")

    def test_the_plain_help_line_stays_as_the_fallback_without_javascript(self):
        self.assertContains(self.page, "At least 8 characters with a letter, a number and a symbol.")

    def test_the_meter_script_checks_the_same_four_rules_as_the_server(self):
        js = (Path(settings.BASE_DIR) / "static" / "js" / "password_meter.js").read_text(encoding="utf-8")
        for fragment in ("v.length >= 8", "[A-Za-z]", "\\d", "[^A-Za-z0-9]", "Strong password."):
            with self.subTest(fragment):
                self.assertIn(fragment, js)

    def test_there_is_no_tech_park_and_the_phone_still_has_its_country_code(self):
        self.assertNotContains(self.page, "tech park")
        self.assertContains(self.page, "+91")

    def test_a_personal_email_still_gets_the_clear_error(self):
        response = self.client.post(reverse("accounts:register"), {
            "first_name": "Ravi", "last_name": "Kumar", "email": "ravi@gmail.com",
            "country_code": "+91", "phone": "9845012345", "password1": "Ride@2026", "password2": "Ride@2026",
        })
        self.assertContains(response, "That looks like a personal email")