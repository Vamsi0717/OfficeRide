from apps.bookings.models import RideRequest
from apps.bookings.tests.helpers import car_ride, future_monday, make_request
from apps.rides.tests.helpers import make_user

S = RideRequest.Status


class ChatMixin:
    """A driver with a ride, a rider with an accepted booking on it, and an outsider."""

    def setUp(self):
        super().setUp()
        self.ride = car_ride()
        self.driver = self.ride.driver
        self.driver.phone = "9876543210"
        self.driver.save()
        self.rider = make_user("rider@acme.com", first_name="Anita", last_name="Rao", phone="9123456780")
        self.outsider = make_user("outsider@acme.com")
        self.day = future_monday()
        self.req = make_request(self.ride, self.rider, self.day, status=S.ACCEPTED)

    def make_booking(self, status, email):
        return make_request(self.ride, make_user(email), self.day, status=status)