from django.test import TestCase
from django.urls import reverse

from apps.bookings.tests.helpers import car_ride
from apps.rides.tests.helpers import get_model, make_driver, make_ride, make_user


class RideDetailDesignTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.ride = make_ride(
            self.driver, days="0,1,2,3,4", seats=3, mileage_rate=get_model("car", "Creta (diesel)"),
            car_model="Hyundai Creta (diesel)",
        )
        self.rider = make_user("rider@acme.com")

    def page(self, user, ride=None):
        self.client.force_login(user)
        return self.client.get(reverse("rides:detail", args=[(ride or self.ride).pk]))

    def test_the_hero_shows_time_route_distance_and_the_days(self):
        page = self.page(self.rider)
        self.assertContains(page, "9:00 AM")
        self.assertContains(page, "Start")
        self.assertContains(page, "End")
        self.assertContains(page, "10.8 km")
        self.assertContains(page, "about 25 min")

    def test_working_days_are_highlighted_and_the_weekend_is_not(self):
        chips = self.page(self.rider).context["weekday_chips"]
        self.assertEqual(
            [(label, on) for label, on in chips],
            [("Mon", True), ("Tue", True), ("Wed", True), ("Thu", True), ("Fri", True), ("Sat", False), ("Sun", False)],
        )

    def test_the_old_runs_on_text_stays_for_screen_readers(self):
        self.assertContains(self.page(self.rider), "Runs on Mon, Tue, Wed, Thu, Fri")

    def test_rider_sees_the_vehicle_and_the_driver_card(self):
        page = self.page(self.rider)
        self.assertContains(page, "Hyundai Creta (diesel)")
        self.assertContains(page, "Documents verified")
        self.assertContains(page, "Ravi K.")

    def test_nobody_sees_the_mileage_not_even_the_owner(self):
        for user in (self.driver, self.rider):
            with self.subTest(user.email):
                page = self.page(user)
                for hidden in ("km per litre", "km/l", "mileage", "Mileage", "21.8", "17.4"):
                    self.assertNotContains(page, hidden)
        self.assertContains(self.page(self.driver), "Edit ride")

    def test_the_fare_card_is_there_for_both(self):
        for user in (self.rider, self.driver):
            with self.subTest(user.email):
                self.assertContains(self.page(user), "Fare for the full route")

    def test_a_two_wheeler_page_uses_the_bike_icon_and_the_helmet_note(self):
        biker = make_driver("biker@acme.com", vehicle_type="bike")
        bike = make_ride(biker, seats=1, vehicle_type="bike", has_spare_helmet=True, mileage_rate=get_model("bike"),
                         car_model="Honda Activa 6G")
        page = self.page(self.rider, bike)
        self.assertContains(page, "bi-bicycle")
        self.assertContains(page, "The driver carries a spare one")

    def test_a_switched_off_ride_says_so_to_its_owner(self):
        self.ride.is_active = False
        self.ride.save()
        self.assertContains(self.page(self.driver), "This ride is switched off.")


class TimePickerOnPagesTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.client.force_login(self.driver)

    def test_offer_page_uses_the_dropdown_time_picker_for_both_times(self):
        page = self.client.get(reverse("rides:offer"))
        for name in ("departure_time", "return_time"):
            with self.subTest(name):
                self.assertContains(page, f'name="{name}_0"')
                self.assertContains(page, f'name="{name}_1"')
                self.assertContains(page, f'name="{name}_2"')
        self.assertNotContains(page, 'type="time"')

    def test_find_page_uses_it_too(self):
        page = self.client.get(reverse("rides:find"))
        self.assertContains(page, 'name="time_0"')
        self.assertContains(page, "Around what time?")
        self.assertNotContains(page, 'type="time"')

    def test_edit_page_opens_on_the_rides_current_time(self):
        ride = car_ride(self.driver)
        page = self.client.get(reverse("rides:edit", args=[ride.pk]))
        self.assertContains(page, 'name="departure_time_0"')
        self.assertContains(page, '<option value="9" selected>9</option>')
        self.assertContains(page, '<option value="AM" selected>AM</option>')

    def test_a_search_with_the_dropdowns_works(self):
        response = self.client.get(reverse("rides:find"), {
            "pickup_name": "A", "pickup_lat": "12.95", "pickup_lng": "77.61",
            "drop_name": "B", "drop_lat": "12.95", "drop_lng": "77.69",
            "date": "2099-01-01", "time_0": "9", "time_1": "0", "time_2": "AM",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "This field is required")

    def test_an_offer_with_the_dropdowns_saves_the_right_time(self):
        from apps.rides.models import Ride
        from apps.rides.tests.test_views import offer_payload

        data = offer_payload()
        del data["departure_time"]
        data.update({"departure_time_0": "8", "departure_time_1": "45", "departure_time_2": "AM"})
        self.client.post(reverse("rides:offer"), data)
        self.assertEqual(Ride.objects.get().departure_time.strftime("%H:%M"), "08:45")