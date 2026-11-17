from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.fares import services
from apps.fares.catalog import BIKES, CARS, CATALOG, EV_BIKE_EQUIVALENT, EV_CAR_EQUIVALENT
from apps.fares.models import FareSettings, MileageRate
from apps.rides.models import Ride
from apps.rides.tests.helpers import get_model, make_driver, make_ride, make_user
from apps.rides.tests.test_views import offer_payload


class CatalogDataTests(TestCase):
    def test_every_catalog_row_is_in_the_database(self):
        self.assertEqual(MileageRate.objects.exclude(make="").count(), len(CATALOG))

    def test_popular_bangalore_makes_are_there(self):
        cars = set(MileageRate.objects.filter(vehicle_type="car").exclude(make="").values_list("make", flat=True))
        bikes = set(MileageRate.objects.filter(vehicle_type="bike").exclude(make="").values_list("make", flat=True))
        self.assertTrue({"Maruti Suzuki", "Hyundai", "Tata", "Mahindra", "Honda", "Toyota", "Kia"} <= cars)
        self.assertTrue({"Honda", "TVS", "Hero", "Bajaj", "Royal Enfield", "Yamaha", "Suzuki"} <= bikes)

    def test_makers_figures_are_believable_and_electric_models_share_one_standard(self):
        for make, model, fuel, figure in CARS:
            with self.subTest((make, model)):
                self.assertEqual(figure, EV_CAR_EQUIVALENT) if fuel == "electric" else self.assertTrue(9 <= figure <= 27)
        for make, model, fuel, figure in BIKES:
            with self.subTest((make, model)):
                self.assertEqual(figure, EV_BIKE_EQUIVALENT) if fuel == "electric" else self.assertTrue(28 <= figure <= 90)

    def test_electric_cars_and_scooters_are_in_the_list(self):
        names = set(MileageRate.objects.filter(fuel_type="electric").values_list("name", flat=True))
        self.assertTrue({"Nexon EV", "Tiago EV", "Comet EV", "450X", "iQube", "Chetak"} <= names)

    def test_every_non_electric_row_is_a_maker_figure_and_no_electric_row_is(self):
        self.assertFalse(MileageRate.objects.filter(fuel_type="electric", is_maker_figure=True).exists())
        self.assertFalse(MileageRate.objects.exclude(make="").exclude(fuel_type="electric").filter(is_maker_figure=False).exists())
        self.assertFalse(MileageRate.objects.filter(make="", is_maker_figure=True).exists())  # the old classes are left alone

    def test_no_model_is_listed_twice(self):
        keys = [(vt, make, model) for vt, make, model, _f, _k in CATALOG]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_old_vehicle_classes_are_kept_for_rides_made_before(self):
        self.assertTrue(MileageRate.objects.filter(make="", name="Sedan").exists())

    def test_full_name_joins_make_and_model(self):
        self.assertEqual(get_model("car", "Creta (diesel)").full_name, "Hyundai Creta (diesel)")
        self.assertEqual(MileageRate.objects.get(make="", name="Sedan").full_name, "Sedan")


class TrafficCutTests(TestCase):
    """The maker's printed mileage is cut for Bangalore traffic, in the background."""

    def rates(self, cut=20):
        return services.Rates(Decimal("103"), Decimal("2"), Decimal("0.8"), 90, traffic_cut_percent=cut)

    def test_a_printed_30_becomes_24(self):
        rate = MileageRate(vehicle_type="bike", make="X", name="Y", km_per_litre=Decimal("30"), is_maker_figure=True)
        self.assertEqual(self.rates().km_per_litre_for(rate), Decimal("24.0"))

    def test_the_cut_is_a_share_so_a_thirsty_car_loses_less(self):
        thirsty = MileageRate(vehicle_type="car", make="X", name="Y", km_per_litre=Decimal("15"), is_maker_figure=True)
        self.assertEqual(self.rates().km_per_litre_for(thirsty), Decimal("12.0"))

    def test_the_share_comes_from_the_settings(self):
        rate = MileageRate(vehicle_type="bike", make="X", name="Y", km_per_litre=Decimal("30"), is_maker_figure=True)
        self.assertEqual(self.rates(cut=0).km_per_litre_for(rate), Decimal("30.0"))
        self.assertEqual(self.rates(cut=30).km_per_litre_for(rate), Decimal("21.0"))

    def test_a_figure_that_is_not_the_makers_is_used_as_it_is(self):
        old_class = MileageRate.objects.get(make="", name="Sedan")
        self.assertEqual(self.rates().km_per_litre_for(old_class), Decimal("10.0"))
        ev = get_model("car", "Nexon EV")
        self.assertEqual(self.rates().km_per_litre_for(ev), Decimal("15.0"))

    def test_the_cut_never_takes_the_mileage_below_one(self):
        rate = MileageRate(vehicle_type="car", make="X", name="Y", km_per_litre=Decimal("1.2"), is_maker_figure=True)
        self.assertEqual(self.rates(cut=60).km_per_litre_for(rate), Decimal("1"))

    def test_a_bigger_cut_raises_the_fare(self):
        ride = make_ride(make_driver(), seats=3, mileage_rate=get_model("car", "Swift"))
        before = services.full_route_fare(ride).fuel
        row = FareSettings.get_solo()
        row.traffic_cut_percent = 40
        row.save()
        self.assertGreater(services.full_route_fare(ride).fuel, before)

    def test_the_fare_uses_the_cut_mileage_not_the_printed_one(self):
        from apps.fares import engine

        ride = make_ride(make_driver(), seats=3, mileage_rate=get_model("car", "Swift"))
        rates = services.load_rates()
        expected = engine.fare_breakdown(
            fuel_price=103, km_per_litre=Decimal("19.8"), wear_per_km=2, recovery_percent=90, seats=3,
            rider_km=Decimal(ride.route_distance_m) / 1000,
        )
        self.assertEqual(services.full_route_fare(ride, rates).total, expected.total)


class ElectricFareTests(TestCase):
    """An electric ride costs the same per km as a petrol one, whichever electric model it is."""

    def setUp(self):
        self.driver = make_driver()

    def fare(self, name, vehicle_type="car", **extra):
        ride = make_ride(self.driver, seats=3, mileage_rate=get_model(vehicle_type, name), **extra)
        return services.full_route_fare(ride)

    def test_every_electric_car_has_the_same_fare(self):
        self.assertEqual(self.fare("Nexon EV").total, self.fare("Comet EV").total)
        self.assertEqual(self.fare("Nexon EV").fuel, self.fare("Atto 3 EV").fuel)

    def test_an_electric_car_costs_the_same_as_a_petrol_car_of_standard_mileage(self):
        standard = MileageRate.objects.create(vehicle_type="car", make="Std", name="Petrol 15", km_per_litre=Decimal("15"))
        petrol = make_ride(self.driver, seats=3, mileage_rate=standard)
        self.assertEqual(self.fare("Tiago EV").total, services.full_route_fare(petrol).total)

    def test_the_diesel_and_cng_prices_do_not_move_an_electric_fare(self):
        before = self.fare("Nexon EV").fuel
        row = FareSettings.get_solo()
        row.diesel_price_per_litre = Decimal("200")
        row.cng_price_per_kg = Decimal("200")
        row.save()
        self.assertEqual(self.fare("Nexon EV").fuel, before)

    def test_the_traffic_cut_does_not_move_an_electric_fare(self):
        before = self.fare("Nexon EV").fuel
        row = FareSettings.get_solo()
        row.traffic_cut_percent = 50
        row.save()
        self.assertEqual(self.fare("Nexon EV").fuel, before)

    def test_electric_scooters_share_one_fare_too(self):
        biker = make_driver("biker@acme.com", vehicle_type="bike")
        fares = {
            services.full_route_fare(make_ride(biker, seats=1, vehicle_type="bike", has_spare_helmet=True,
                                               mileage_rate=get_model("bike", name))).total
            for name in ("450X", "iQube", "Chetak", "S1 Pro")
        }
        self.assertEqual(len(fares), 1)


class FuelPriceTests(TestCase):
    def setUp(self):
        self.driver = make_driver()

    def test_starting_prices(self):
        s = FareSettings.get_solo()
        self.assertEqual((s.diesel_price_per_litre, s.cng_price_per_kg), (Decimal("89.00"), Decimal("90.00")))

    def test_each_fuel_uses_its_own_price(self):
        rates = services.load_rates()
        self.assertEqual(rates.fuel_price_for("petrol"), Decimal("103.00"))
        self.assertEqual(rates.fuel_price_for("diesel"), Decimal("89.00"))
        self.assertEqual(rates.fuel_price_for("cng"), Decimal("90.00"))

    def test_the_fare_follows_the_model_s_mileage_and_fuel(self):
        thrifty = make_ride(self.driver, seats=3, mileage_rate=get_model("car", "Alto K10"))
        thirsty = make_ride(self.driver, seats=3, mileage_rate=get_model("car", "Fortuner"))
        self.assertLess(services.full_route_fare(thrifty).total, services.full_route_fare(thirsty).total)

    def test_diesel_and_petrol_versions_of_one_car_are_priced_apart(self):
        petrol = make_ride(self.driver, seats=3, mileage_rate=get_model("car", "Creta (petrol)"))
        diesel = make_ride(self.driver, seats=3, mileage_rate=get_model("car", "Creta (diesel)"))
        self.assertLess(services.full_route_fare(diesel).fuel, services.full_route_fare(petrol).fuel)

    def test_changing_the_diesel_price_changes_only_diesel_fares(self):
        diesel = make_ride(self.driver, seats=3, mileage_rate=get_model("car", "Thar"))
        petrol = make_ride(self.driver, seats=3, mileage_rate=get_model("car", "Swift"))
        before = services.full_route_fare(diesel).fuel, services.full_route_fare(petrol).fuel
        row = FareSettings.get_solo()
        row.diesel_price_per_litre = Decimal("120")
        row.save()
        after = services.full_route_fare(diesel).fuel, services.full_route_fare(petrol).fuel
        self.assertGreater(after[0], before[0])
        self.assertEqual(after[1], before[1])

    def test_a_cng_car_uses_the_cng_price_and_not_the_petrol_price(self):
        cng = make_ride(self.driver, seats=3, mileage_rate=get_model("car", "Ertiga CNG"))
        before = services.full_route_fare(cng).fuel
        row = FareSettings.get_solo()
        row.cng_price_per_kg = Decimal("180")
        row.save()
        self.assertGreater(services.full_route_fare(cng).fuel, before)
        row.cng_price_per_kg = Decimal("90")
        row.fuel_price_per_litre = Decimal("200")
        row.save()
        self.assertEqual(services.full_route_fare(cng).fuel, before)
