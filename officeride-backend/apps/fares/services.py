"""Loads the fare numbers from the database and calls the engine. Views call these functions."""

from dataclasses import dataclass
from decimal import Decimal

from . import engine
from .models import FareSettings


@dataclass(frozen=True)
class Rates:
    fuel_price: Decimal
    car_wear_per_km: Decimal
    bike_wear_per_km: Decimal
    recovery_percent: int
    diesel_price: Decimal = Decimal("89.00")
    cng_price: Decimal = Decimal("90.00")
    traffic_cut_percent: int = 20

    def fuel_price_for(self, fuel_type):
        """Price of one litre (one kg for CNG) of the fuel this vehicle burns."""
        # Electric vehicles are priced like petrol ones: the same fare per km.
        return {"diesel": self.diesel_price, "cng": self.cng_price}.get(fuel_type, self.fuel_price)

    def km_per_litre_for(self, rate):
        """The mileage the fare is worked out from. A maker's figure is cut for Bangalore traffic.

        Neither the driver nor the rider ever sees this number."""
        if not rate.is_maker_figure:
            return rate.km_per_litre
        cut = Decimal(100 - self.traffic_cut_percent) / 100
        return max(Decimal("1"), (rate.km_per_litre * cut).quantize(Decimal("0.1")))

    def wear_per_km(self, vehicle_type):
        return self.bike_wear_per_km if vehicle_type == "bike" else self.car_wear_per_km


def load_rates():
    """One database read. Load it once and pass it on when pricing many rides."""
    s = FareSettings.get_solo()
    return Rates(
        s.fuel_price_per_litre, s.car_wear_per_km, s.bike_wear_per_km, s.recovery_percent,
        s.diesel_price_per_litre, s.cng_price_per_kg, s.traffic_cut_percent,
    )


def fare_for(ride, rider_distance_m=None, rates=None):
    """Fare breakdown for one rider on a ride, or None when the ride has no vehicle class yet.

    rider_distance_m is how far along the route the rider travels. None means the whole route."""
    if ride.mileage_rate_id is None:
        return None
    rates = rates or load_rates()
    route_m = ride.route_distance_m
    rider_m = route_m if rider_distance_m is None else min(rider_distance_m, route_m)  # never above the route
    return engine.fare_breakdown(
        fuel_price=rates.fuel_price_for(ride.mileage_rate.fuel_type),
        km_per_litre=rates.km_per_litre_for(ride.mileage_rate),
        wear_per_km=rates.wear_per_km(ride.vehicle_type),
        recovery_percent=rates.recovery_percent,
        seats=ride.seats,
        rider_km=Decimal(rider_m) / 1000,
        toll_total=ride.toll_total,
        adjustment=ride.fare_adjustment,
    )


def full_route_fare(ride, rates=None):
    return fare_for(ride, None, rates)


def attach_fares(matches):
    """Sets match.fare on each RideMatch using a single database read for the rates."""
    rates = load_rates()
    for m in matches:
        m.fare = fare_for(m.ride, m.rider_distance_m, rates)
    return matches