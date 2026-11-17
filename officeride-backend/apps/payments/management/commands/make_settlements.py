from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.payments import services


class Command(BaseCommand):
    help = "Work out what each driver is owed for a week. By default, last week. Safe to run again."

    def add_arguments(self, parser):
        parser.add_argument("--week-start", help="The Monday of the week, as YYYY-MM-DD. Default: last week's Monday.")

    def handle(self, *args, **options):
        if options["week_start"]:
            try:
                monday = date.fromisoformat(options["week_start"])
            except ValueError:
                raise CommandError("Type the date like 2026-11-09.")
            if monday.weekday() != 0:
                raise CommandError("That date is not a Monday.")
        else:
            monday = services.week_of(timezone.localdate() - timedelta(days=7))[0]
        changed = services.build_settlements(monday)
        for s in changed:
            self.stdout.write(f"{s.driver.email}: {s.rides} ride(s), Rs {s.total_rupees:g} owed, Rs {s.fee_rupees:g} fee")
        self.stdout.write(f"Week of {monday}: {len(changed)} settlement(s) made or updated.")