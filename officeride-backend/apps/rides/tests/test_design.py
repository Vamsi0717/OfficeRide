from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.rides.tests.helpers import get_model, make_driver, make_ride, make_user, next_weekday, point_along

STATIC = Path(settings.BASE_DIR) / "static"


class FindPageDesignTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("rider@acme.com"))
        self.page = self.client.get(reverse("rides:find"))

    def test_the_page_asks_where_to(self):
        self.assertContains(self.page, "Where to today?")
        self.assertContains(self.page, "Find rides")

    def test_pickup_and_drop_are_two_rows_with_a_start_dot_and_an_end_dot(self):
        self.assertContains(self.page, 'class="or-dot"')
        self.assertContains(self.page, 'class="or-dot end"')
        self.assertContains(self.page, 'for="id_pickup_name_text"')
        self.assertContains(self.page, 'for="id_drop_name_text"')

    def test_there_is_a_swap_button_and_its_script(self):
        self.assertContains(self.page, "data-swap-places")
        self.assertContains(self.page, "js/swap_places.js")
        script = (STATIC / "js" / "swap_places.js").read_text(encoding="utf-8")
        for part in ("data-swap-places", "place-input", "_lat", "_lng"):
            self.assertIn(part, script)

    def test_the_time_wheel_and_the_place_picker_are_still_there(self):
        self.assertContains(self.page, "js/place_picker.js")
        self.assertContains(self.page, "js/time_wheel.js")
        self.assertContains(self.page, "data-time-wheel")


class FindResultsDesignTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.rider = make_user("rider@acme.com")
        self.client.force_login(self.rider)

    def search(self):
        pickup, drop = point_along(0.2, 300), point_along(0.8, -200)
        return self.client.get(reverse("rides:find"), {
            "pickup_name": "Near start", "pickup_lat": pickup[0], "pickup_lng": pickup[1],
            "drop_name": "Near end", "drop_lat": drop[0], "drop_lng": drop[1],
            "date": next_weekday(0).isoformat(), "time": "09:05",
        })

    def test_a_result_is_a_card_with_driver_vehicle_price_and_buttons(self):
        make_ride(self.driver, mileage_rate=get_model("car"), car_model="Maruti Suzuki Swift")
        page = self.search()
        self.assertContains(page, "or-ride")
        self.assertContains(page, "Ravi K.")
        self.assertContains(page, "Maruti Suzuki Swift")
        self.assertContains(page, "Documents verified")
        self.assertContains(page, "3 seats")
        self.assertContains(page, "for your trip")
        self.assertContains(page, "Request a seat")
        self.assertContains(page, "View ride")

    def test_the_price_is_shown_once_at_the_top_of_the_card(self):
        make_ride(self.driver, mileage_rate=get_model("car"))
        page = self.search()
        self.assertContains(page, "or-price")
        self.assertNotContains(page, "or-fare-total")

    def test_a_two_wheeler_card_has_the_bike_mark_and_the_helmet_chip(self):
        biker = make_driver("biker@acme.com", vehicle_type="bike")
        make_ride(biker, seats=1, vehicle_type="bike", has_spare_helmet=True, mileage_rate=get_model("bike"),
                  car_model="Honda Activa 6G")
        page = self.search()
        self.assertContains(page, "bi-bicycle")
        self.assertContains(page, "spare helmet carried")

    def test_the_drivers_fare_change_is_explained_on_the_card(self):
        make_ride(self.driver, mileage_rate=get_model("car"), fare_adjustment=10)
        page = self.search()
        self.assertContains(page, "The driver set it")
        self.assertNotContains(page, "Riders never pay more than the trip cost.")

    def test_the_never_more_than_the_cost_line_shows_when_the_fare_is_not_raised(self):
        make_ride(self.driver, mileage_rate=get_model("car"))
        self.assertContains(self.search(), "Riders never pay more than the trip cost.")

    def test_no_card_shows_the_mileage(self):
        make_ride(self.driver, mileage_rate=get_model("car"))
        page = self.search()
        for hidden in ("km per litre", "km/l", "Mileage"):
            self.assertNotContains(page, hidden)

    def test_no_results_gives_a_friendly_note(self):
        page = self.search()
        self.assertContains(page, "No rides match yet")
        self.assertContains(page, "or-info")


class OfferPageDesignTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.client.force_login(self.driver)
        self.page = self.client.get(reverse("rides:offer"))

    def test_the_page_title_and_button(self):
        self.assertContains(self.page, "Offer a ride")
        self.assertContains(self.page, "Going to the office anyway?")
        self.assertContains(self.page, "Publish ride")

    def test_the_days_are_seven_chips_and_the_working_week_is_ticked(self):
        self.assertContains(self.page, 'class="or-day"', count=7)
        self.assertContains(self.page, "or-days")
        ticked = [line for line in self.page.content.decode().splitlines() if 'name="office_days"' in line and "checked" in line]
        self.assertEqual(len(ticked), 5)

    def test_both_times_use_the_time_wheel(self):
        self.assertContains(self.page, "data-time-wheel", count=2)
        self.assertContains(self.page, "Leaving at")
        self.assertContains(self.page, "Way back (optional)")
        self.assertContains(self.page, 'placeholder="Starting point"')

    def test_a_car_driver_sees_the_car_note(self):
        self.assertContains(self.page, "Vehicle type: <b>Car</b>")
        self.assertContains(self.page, "bi-car-front")
        self.assertNotContains(self.page, "spare helmet")

    def test_the_make_and_model_dropdowns_are_still_there_and_hide_the_mileage(self):
        self.assertContains(self.page, 'name="make"')
        self.assertContains(self.page, 'name="mileage_rate"')
        self.assertContains(self.page, "js/vehicle_picker.js")
        self.assertContains(self.page, "data-vehicle-picker")
        for hidden in ("km per litre", "km/l", "Mileage"):
            self.assertNotContains(self.page, hidden)

    def test_a_two_wheeler_driver_sees_the_helmet_box_and_one_seat(self):
        biker = make_driver("biker@acme.com", vehicle_type="bike")
        self.client.force_login(biker)
        page = self.client.get(reverse("rides:offer"))
        self.assertContains(page, "A two-wheeler carries one rider.")
        self.assertContains(page, "bi-bicycle")
        self.assertContains(page, "I will carry a spare helmet for the rider")

    def test_a_missing_day_shows_the_error_in_the_new_style(self):
        from apps.rides.tests.test_views import offer_payload

        data = offer_payload()
        data.pop("office_days", None)
        page = self.client.post(reverse("rides:offer"), data)
        self.assertContains(page, "Choose at least one day.")
        self.assertContains(page, "or-error")


class EditPageDesignTests(TestCase):
    def test_the_edit_page_has_day_chips_and_the_new_button(self):
        driver = make_driver()
        ride = make_ride(driver, mileage_rate=get_model("car"), car_model="Maruti Suzuki Swift")
        self.client.force_login(driver)
        page = self.client.get(reverse("rides:edit", args=[ride.pk]))
        self.assertContains(page, 'class="or-day"', count=7)
        self.assertContains(page, "Save changes")
        self.assertContains(page, "data-time-wheel")


class RideDetailsDesignTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.ride = make_ride(self.driver, mileage_rate=get_model("car", "Creta (diesel)"), car_model="Hyundai Creta (diesel)")
        self.rider = make_user("rider@acme.com")

    def page(self, user, ride=None):
        self.client.force_login(user)
        return self.client.get(reverse("rides:detail", args=[(ride or self.ride).pk]))

    def test_the_navy_header_has_the_time_the_route_and_the_week(self):
        page = self.page(self.rider)
        self.assertContains(page, "or-hero-card")
        self.assertContains(page, "Leaves at")
        self.assertContains(page, "or-hero-days")
        self.assertContains(page, "Leaves at 9:00 AM")

    def test_the_four_tiles(self):
        page = self.page(self.rider)
        for text in ("Seats offered", "Distance", "Trip time", "Fuel", "Diesel"):
            self.assertContains(page, text)

    def test_the_fuel_tile_needs_a_vehicle_class(self):
        ride = make_ride(self.driver, mileage_rate=None)
        self.assertNotContains(self.page(self.rider, ride), "<small>Fuel</small>")

    def test_a_rider_sees_the_driver_card_and_the_back_to_search_button(self):
        page = self.page(self.rider)
        self.assertContains(page, "or-driver")
        self.assertContains(page, "Documents verified")
        self.assertContains(page, "Back to search")

    def test_the_owner_sees_their_own_vehicle_and_the_controls(self):
        page = self.page(self.driver)
        self.assertContains(page, "Your car")
        self.assertContains(page, "Save fare")
        self.assertContains(page, "Edit ride")
        self.assertContains(page, "Switch off")
        self.assertContains(page, "Delete ride")
        self.assertNotContains(page, "Back to search")

    def test_the_fare_card_explains_a_drivers_change(self):
        ride = make_ride(self.driver, mileage_rate=get_model("car"), fare_adjustment=-5)
        page = self.page(self.rider, ride)
        self.assertContains(page, "Fare for the full route")
        self.assertContains(page, "The driver set it")
        self.assertContains(page, "lower")

    def test_there_is_no_style_block_in_the_page_any_more(self):
        self.assertNotContains(self.page(self.rider), "<style>")

    def test_the_stylesheet_has_the_7b_pieces(self):
        css = (STATIC / "css" / "officeride.css").read_text(encoding="utf-8")
        for name in (".or-box", ".or-day", ".or-ride", ".or-hero-card", ".or-tile", ".or-driver", ".or-fare"):
            with self.subTest(name):
                self.assertIn(name, css)