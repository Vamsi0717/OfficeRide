"""The fare formula. Pure functions: no database, no Django, so every rule is easy to test.

For one rider on one ride:

    cost per km  = fuel price / km per litre + wear per km
    fuel share   = fuel per km  x recovery% x rider km / seats offered
    wear share   = wear per km  x recovery% x rider km / seats offered
    toll share   = toll total / seats offered
    fare         = fuel share + wear share + toll share, rounded ONCE to whole rupees (half up)
    safety cap   = the fare is never above (cost per km x rider km + toll) / seats, rounded down

Because every seat pays only its share of at most 90% of the cost, riders together never pay
more than fuel + wear + toll. See docs/fare-formula.md.
"""

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

HUNDRED = Decimal("100")
ONE_RUPEE = Decimal("1")
PAISE = Decimal("0.01")


def _d(value):
    """Decimal from an int, float or Decimal. Floats go through str() to avoid binary noise."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class FareBreakdown:
    fuel: Decimal          # rider's share of fuel, to the paisa
    wear: Decimal          # rider's share of wear and tear, to the paisa
    toll: Decimal          # rider's share of toll, to the paisa
    total: int             # what the rider pays: the three parts added, rounded once to whole rupees
    cost_per_km: Decimal   # whole-vehicle running cost per km (fuel + wear), before recovery
    rider_km: Decimal      # distance the fare was worked out for


def cost_per_km(fuel_price, km_per_litre, wear_per_km):
    """Running cost of the vehicle for one km: fuel plus wear and tear."""
    km_per_litre = _d(km_per_litre)
    if km_per_litre <= 0:
        raise ValueError("km per litre must be above zero")
    return _d(fuel_price) / km_per_litre + _d(wear_per_km)


def fare_breakdown(*, fuel_price, km_per_litre, wear_per_km, recovery_percent, seats, rider_km,
                   toll_total=0, route_km=None):
    """Everything about one rider's fare. rider_km is capped at route_km when route_km is given."""
    seats = int(seats)
    if seats < 1:
        raise ValueError("seats must be at least 1")
    recovery_percent = _d(recovery_percent)
    if not (0 < recovery_percent <= 100):
        raise ValueError("recovery percent must be above 0 and at most 100")
    rider_km = _d(rider_km)
    if rider_km < 0:
        raise ValueError("rider km cannot be negative")
    toll_total = _d(toll_total)
    if toll_total < 0:
        raise ValueError("toll cannot be negative")
    if route_km is not None:
        rider_km = min(rider_km, _d(route_km))

    recovery = recovery_percent / HUNDRED
    wear_per_km = _d(wear_per_km)
    per_km = cost_per_km(fuel_price, km_per_litre, wear_per_km)  # also refuses a mileage of zero
    fuel_per_km = _d(fuel_price) / _d(km_per_litre)

    fuel = fuel_per_km * recovery * rider_km / seats
    wear = wear_per_km * recovery * rider_km / seats
    toll = toll_total / seats
    total = (fuel + wear + toll).quantize(ONE_RUPEE, rounding=ROUND_HALF_UP)  # the only rounding that counts
    # Rounding up must never push the riders above the real cost. The 10% margin covers this on
    # normal trips, but a very short trip with many seats and a toll could overshoot by a rupee.
    cap = ((per_km * rider_km + toll_total) / seats).to_integral_value(rounding=ROUND_FLOOR)
    total = int(min(total, cap))
    return FareBreakdown(
        fuel=fuel.quantize(PAISE, rounding=ROUND_HALF_UP),
        wear=wear.quantize(PAISE, rounding=ROUND_HALF_UP),
        toll=toll.quantize(PAISE, rounding=ROUND_HALF_UP),
        total=total,
        cost_per_km=per_km,
        rider_km=rider_km,
    )


def rider_fare(**kwargs):
    """Just the rupee amount. Takes the same keyword arguments as fare_breakdown."""
    return fare_breakdown(**kwargs).total