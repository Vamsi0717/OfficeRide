# How OfficeRide works out a fare

Riders share the running cost of a trip the driver already makes. This is not a taxi fare and the driver does not earn a profit.

## The formula

For one rider on one ride:

    cost per km  = petrol price / km per litre + wear per km
    fuel share   = (petrol price / km per litre) x recovery% x rider km / seats offered
    wear share   = wear per km x recovery% x rider km / seats offered
    toll share   = toll for the whole trip / seats offered
    fare         = fuel share + wear share + toll share

- **Rider km** is how far along the driver's route the rider travels, from their pickup to their drop. It is never more than the whole route.
- **Seats offered** is the number of seats the driver listed. A two-wheeler always offers 1.
- **Recovery%** is 90 to start. Riders together repay at most 90% of fuel and wear, so the driver always carries a share of the cost.
- **Wear per km** is set separately for cars (start ₹2.00) and two-wheelers (start ₹0.80).
- **Km per litre** comes from the vehicle class the driver picks (for example Sedan 10, Scooter 40).
- Petrol price, wear, recovery and the mileage classes are edited by staff in the admin. No code change is needed.

## Rounding

1. Nothing is rounded while adding the fuel, wear and toll shares.
2. The sum is rounded **once**, to the nearest whole rupee, with .5 going up.
3. The parts shown on screen (fuel, wear, toll) are rounded to the paisa for display only. They can differ from the total by a few paise.
4. **Safety cap:** the fare is never more than `(cost per km x rider km + toll) / seats offered`, rounded down. This stops rounding from ever pushing the riders above the real cost of the trip.

## Driver adjustment

The driver may move the fare up or down by up to **₹20 per rider** (`MAX_ADJUSTMENT_RS` in `apps/fares/engine.py`).

- The adjustment is added to the rounded standard fare, after the safety cap.
- It is a whole-rupee amount and is the same for every rider on that ride, however far they travel.
- A fare is never below ₹0.
- The ride page shows the standard fare and says how much the driver changed it.
- The database refuses any value outside -20 to +20.

Example: standard fare ₹67 and the driver sets +20, so riders pay **₹87**. With -20 they pay **₹47**.

## The promise

With no adjustment, with every seat filled and every rider travelling the full route, the riders together never pay more than petrol + wear + toll for the trip. The tests check this for cars and two-wheelers, 1 to 6 seats, short and long trips, with and without toll. A driver who raises the fare (up to ₹20 per rider) can take the total above the trip cost. That is the driver's choice, and the ride page says so.

## Worked examples

**Car.** KR Puram to Bellandur, 15 km, SUV at 8 km/l, petrol ₹103, wear ₹2/km, 90%, 3 seats.
Cost per km = 103 / 8 + 2 = 14.875. Fare = 14.875 x 0.9 x 15 / 3 = 66.94, so **₹67 one way**. The 30 km round trip is **₹134**.

**Two-wheeler.** Same 15 km on a commuter motorcycle at 45 km/l, wear ₹0.80/km, 1 seat.
Cost per km = 103 / 45 + 0.80 = 3.0889. Fare = 3.0889 x 0.9 x 15 = 41.70, so **₹42 one way**.