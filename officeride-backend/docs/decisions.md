# Decisions

A short record of choices that change how OfficeRide behaves, and why.

## When the rider pays (Phase 8)

**The rider pays after the driver accepts, and before the ride leaves.**

- A request that is still waiting is not paid, so nobody is charged for a seat that may be refused.
- Paying after the ride would mean chasing people for money. Paying before it means the driver knows the seat is paid.
- Until the refund rules are built (Phase 8 part 2), a paid booking that is cancelled is refunded by hand.

## What the rider is charged

- The amount is the fare saved on the booking (standard fare plus the driver's change), in whole paise.
- The platform fee is `PLATFORM_FEE_PAISE`. It is **0 during the pilot**. When it is above zero it is added on its own line, and the driver is paid the fare without it.
- The amount is always worked out on the server. The browser never sends an amount.