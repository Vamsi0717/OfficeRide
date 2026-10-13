from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.bookings import planner, services
from apps.bookings.models import PlanDay
from apps.rides.models import CarUnavailableDate
from apps.rides.tests.helpers import make_driver, make_user, point_along

from .helpers import car_ride, drop, future_monday, pickup

Mode = PlanDay.Mode


class ModeForTests(TestCase):
    def setUp(self):
        self.user = make_driver()
        self.monday = future_monday()

    def test_no_plan_means_none(self):
        self.assertIsNone(planner.mode_for(self.user, self.monday))

    def test_the_weekly_plan_applies_to_that_weekday_every_week(self):
        planner.save_weekly(self.user, {0: Mode.DRIVING, 1: Mode.RIDING})
        self.assertEqual(planner.mode_for(self.user, self.monday), Mode.DRIVING)
        self.assertEqual(planner.mode_for(self.user, self.monday + timedelta(days=7)), Mode.DRIVING)
        self.assertEqual(planner.mode_for(self.user, self.monday + timedelta(days=1)), Mode.RIDING)
        self.assertIsNone(planner.mode_for(self.user, self.monday + timedelta(days=2)))

    def test_a_one_off_override_beats_the_weekly_plan_for_that_date_only(self):
        planner.save_weekly(self.user, {0: Mode.DRIVING})
        planner.set_override(self.user, self.monday, Mode.NOT_GOING)
        self.assertEqual(planner.mode_for(self.user, self.monday), Mode.NOT_GOING)
        self.assertEqual(planner.mode_for(self.user, self.monday + timedelta(days=7)), Mode.DRIVING)

    def test_clearing_an_override_goes_back_to_the_weekly_plan(self):
        planner.save_weekly(self.user, {0: Mode.DRIVING})
        planner.set_override(self.user, self.monday, Mode.RIDING)
        planner.clear_override(self.user, self.monday)
        self.assertEqual(planner.mode_for(self.user, self.monday), Mode.DRIVING)

    def test_a_car_marked_unavailable_switches_that_day_to_riding(self):
        planner.save_weekly(self.user, {0: Mode.DRIVING})
        CarUnavailableDate.objects.create(driver=self.user, date=self.monday)
        self.assertEqual(planner.mode_for(self.user, self.monday), Mode.RIDING)
        planner.set_override(self.user, self.monday, Mode.DRIVING)  # even an override cannot make a car that is in the garage drive
        self.assertEqual(planner.mode_for(self.user, self.monday), Mode.RIDING)

    def test_saving_again_changes_the_day_and_an_empty_choice_clears_it(self):
        planner.save_weekly(self.user, {0: Mode.DRIVING})
        planner.save_weekly(self.user, {0: Mode.RIDING})
        self.assertEqual(PlanDay.objects.filter(user=self.user, weekday=0).count(), 1)
        planner.save_weekly(self.user, {0: ""})
        self.assertFalse(PlanDay.objects.filter(user=self.user).exists())

    def test_the_database_refuses_a_row_that_is_both_weekly_and_one_off_or_neither(self):
        from django.db import IntegrityError, transaction
        for values in ({"weekday": 1, "date": self.monday}, {"weekday": None, "date": None}):
            with self.subTest(values), self.assertRaises(IntegrityError), transaction.atomic():
                PlanDay.objects.create(user=self.user, mode=Mode.DRIVING, **values)


class DriversNotDrivingTests(TestCase):
    def test_only_drivers_whose_plan_says_riding_or_not_going_are_returned(self):
        day = future_monday()
        drivers = [make_driver(f"d{i}@acme.com") for i in range(5)]
        planner.save_weekly(drivers[0], {0: Mode.DRIVING})
        planner.save_weekly(drivers[1], {0: Mode.RIDING})
        planner.save_weekly(drivers[2], {0: Mode.NOT_GOING})
        planner.save_weekly(drivers[3], {0: Mode.RIDING})
        planner.set_override(drivers[3], day, Mode.DRIVING)  # override: driving after all
        hidden = planner.drivers_not_driving([d.pk for d in drivers], day)
        self.assertEqual(hidden, {drivers[1].pk, drivers[2].pk})  # drivers[4] has no plan, so is not hidden

    def test_it_needs_a_fixed_number_of_queries_however_many_drivers(self):
        day = future_monday()
        drivers = [make_driver(f"d{i}@acme.com") for i in range(6)]
        with self.assertNumQueries(3):
            planner.drivers_not_driving([d.pk for d in drivers], day)

    def test_an_empty_list_costs_nothing(self):
        with self.assertNumQueries(0):
            self.assertEqual(planner.drivers_not_driving([], future_monday()), set())


class PlannerAndSearchTests(TestCase):
    def setUp(self):
        self.ride = car_ride()
        self.driver = self.ride.driver
        self.rider = make_user("rider@acme.com")
        self.day = future_monday()
        self.client.force_login(self.rider)

    def search(self):
        a, b = point_along(0.1), point_along(0.9)
        return self.client.get(reverse("rides:find"), {
            "pickup_name": "A", "pickup_lat": a[0], "pickup_lng": a[1],
            "drop_name": "B", "drop_lat": b[0], "drop_lng": b[1],
            "date": self.day.isoformat(), "time": "09:00",
        })

    def test_a_driver_with_no_plan_is_shown(self):
        self.assertEqual(len(self.search().context["matches"]), 1)

    def test_a_driver_who_plans_to_drive_is_shown(self):
        planner.save_weekly(self.driver, {0: Mode.DRIVING})
        self.assertEqual(len(self.search().context["matches"]), 1)

    def test_seats_are_hidden_on_a_day_the_driver_plans_to_ride_or_stay_home(self):
        for mode in (Mode.RIDING, Mode.NOT_GOING):
            with self.subTest(mode):
                planner.save_weekly(self.driver, {0: mode})
                self.assertEqual(self.search().context["matches"], [])

    def test_a_one_off_day_off_hides_only_that_date(self):
        planner.set_override(self.driver, self.day, Mode.NOT_GOING)
        self.assertEqual(self.search().context["matches"], [])
        self.day += timedelta(days=7)
        self.assertEqual(len(self.search().context["matches"]), 1)

    def test_a_car_marked_unavailable_hides_that_drivers_rides(self):
        CarUnavailableDate.objects.create(driver=self.driver, date=self.day)
        self.assertEqual(self.search().context["matches"], [])

    def test_a_seat_cannot_be_requested_on_a_day_the_driver_is_not_driving(self):
        planner.save_weekly(self.driver, {0: Mode.RIDING})
        with self.assertRaisesMessage(services.BookingError, "not driving"):
            services.request_seat(self.rider, self.ride.pk, self.day, pickup(), drop())


class PlannerPageTests(TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.rider = make_user("rider@acme.com")
        self.url = reverse("bookings:plan")

    def weekly_post(self, **days):
        data = {"form": "weekly"}
        data.update({f"day_{n}": days.get(f"day_{n}", "") for n in range(5)})
        return data

    def test_the_page_needs_a_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_the_weekly_plan_saves_and_shows_again(self):
        self.client.force_login(self.driver)
        response = self.client.post(self.url, self.weekly_post(day_0="driving", day_1="riding", day_4="not_going"), follow=True)
        self.assertContains(response, "weekly plan is saved")
        self.assertEqual(planner.weekly_modes(self.driver), {0: "driving", 1: "riding", 4: "not_going"})
        page = self.client.get(self.url)
        self.assertContains(page, '<option value="driving" selected>')

    def test_a_rider_is_not_offered_driving(self):
        self.client.force_login(self.rider)
        page = self.client.get(self.url)
        self.assertNotContains(page, 'value="driving"')
        response = self.client.post(self.url, self.weekly_post(day_0="driving"))
        self.assertEqual(response.status_code, 200)  # refused: not a valid choice
        self.assertFalse(PlanDay.objects.exists())

    def test_a_one_off_day_saves_and_can_be_removed(self):
        self.client.force_login(self.driver)
        day = future_monday()
        self.client.post(self.url, {"form": "override", "date": day.isoformat(), "mode": "not_going"})
        entry = PlanDay.objects.get(user=self.driver, date=day)
        self.assertEqual(entry.mode, "not_going")
        self.assertContains(self.client.get(self.url), "Not going to the office")
        self.client.post(reverse("bookings:plan_override_delete", args=[entry.pk]))
        self.assertFalse(PlanDay.objects.filter(user=self.driver).exists())

    def test_a_past_date_is_refused(self):
        self.client.force_login(self.driver)
        yesterday = timezone.localdate() - timedelta(days=1)
        response = self.client.post(self.url, {"form": "override", "date": yesterday.isoformat(), "mode": "riding"})
        self.assertContains(response, "today or a future date")
        self.assertFalse(PlanDay.objects.exists())

    def test_nobody_can_remove_someone_elses_day(self):
        entry = PlanDay.objects.create(user=self.driver, date=future_monday(), mode="riding")
        self.client.force_login(self.rider)
        response = self.client.post(reverse("bookings:plan_override_delete", args=[entry.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(PlanDay.objects.filter(pk=entry.pk).exists())