# Decisions

A short record of choices that change how OfficeRide behaves, and why.

## When the rider pays (Phase 8)

**The rider pays after the driver accepts, and before the ride leaves.**

- A request that is still waiting is not paid, so nobody is charged for a seat that may be refused.
- Paying after the ride would mean chasing people for money. Paying before it means the driver knows the seat is paid.

## What the rider is charged

- The amount is the fare saved on the booking (standard fare plus the driver's change), in whole paise.
- The platform fee is `PLATFORM_FEE_PAISE`. It is **0 during the pilot**. When it is above zero it is added on its own line, and the driver is paid the fare without it.
- The amount is always worked out on the server. The browser never sends an amount.

## Refunds (Phase 8 part 2)

| What happened | Refund |
|---|---|
| The rider cancels before the ride leaves | Full, including the platform fee |
| The driver cancels before the ride leaves | Full, including the platform fee |
| The rider reports that the driver did not come | Full |
| The driver reports that the rider did not come | None |
| The ride was completed | None |

- A late cancellation (under an hour before departure) is still refunded in full. The person who cancelled late gets a strike, which is the penalty.
- A refund Razorpay refuses does not stop the cancellation. The payment stays marked paid with a note, and an admin can press **Retry the refund**.
- Open question: a rider could falsely report that the driver did not come to get a refund. For the pilot an admin can look at such cases from the strikes and complaints lists. Revisit when there is real data.

## Paying drivers (Phase 8 part 2)

- A driver's earnings are the fares of rides that were **completed and paid**. Refunded, cancelled and no-show bookings are not counted.
- Every week (Monday to Sunday) the command `python manage.py make_settlements` adds up what each driver is owed. It is safe to run again, and a payment is never counted twice.
- The admin pays the driver by hand (bank or UPI), types the transfer reference on the settlement and marks it as paid out.
- Open question for the lawyer: how the platform fee sits with the rule that riders never pay more than the trip's running cost. Keep `PLATFORM_FEE_PAISE` at 0 until this is answered.