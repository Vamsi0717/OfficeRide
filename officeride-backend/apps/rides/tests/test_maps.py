from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from apps.rides import maps


class FakeMapsTests(SimpleTestCase):
    def test_search_finds_a_sample_place(self):
        names = [p.name for p in maps.FakeMaps().search_places("bellan")]
        self.assertEqual(names, ["Bellandur"])

    def test_search_is_case_insensitive_and_limited(self):
        self.assertEqual(len(maps.FakeMaps().search_places("a", limit=3)), 3)

    def test_no_match(self):
        self.assertEqual(maps.FakeMaps().search_places("zzzz"), [])

    def test_route_is_a_line_from_start_to_end(self):
        route = maps.FakeMaps().get_route(13.0076, 77.6954, 12.9260, 77.6760)
        self.assertEqual(route.points[0], (13.0076, 77.6954))
        self.assertEqual(route.points[-1], (12.9260, 77.6760))
        self.assertAlmostEqual(route.distance_m / 1000, 11.6, delta=0.8)
        self.assertGreater(route.duration_s, 0)


@override_settings(MAPS_PROVIDER="fake")
class ProviderChoiceTests(SimpleTestCase):
    def test_fake_provider(self):
        self.assertIsInstance(maps.get_provider(), maps.FakeMaps)

    @override_settings(MAPS_PROVIDER="google", GOOGLE_MAPS_API_KEY="")
    def test_google_without_a_key_is_a_configuration_error(self):
        with self.assertRaises(ImproperlyConfigured):
            maps.get_provider()

    @override_settings(MAPS_PROVIDER="google", GOOGLE_MAPS_API_KEY="k")
    def test_google_provider(self):
        self.assertIsInstance(maps.get_provider(), maps.GoogleMaps)

    @override_settings(MAPS_PROVIDER="nonsense")
    def test_unknown_provider(self):
        with self.assertRaises(ImproperlyConfigured):
            maps.get_provider()


@override_settings(GOOGLE_MAPS_API_KEY="test-key", MAPS_TIMEOUT_SECONDS=5)
class GoogleMapsTests(SimpleTestCase):
    def setUp(self):
        self.google = maps.GoogleMaps("test-key")

    def test_place_search_request_and_parsing(self):
        reply = {
            "places": [
                {"displayName": {"text": "Embassy Tech Village"}, "formattedAddress": "Devarabisanahalli, Bengaluru",
                 "location": {"latitude": 12.9366, "longitude": 77.6931}},
                {"displayName": {"text": "Chennai Central"}, "formattedAddress": "Chennai",
                 "location": {"latitude": 13.0827, "longitude": 80.2707}},
                {"displayName": {"text": "No location"}},
            ]
        }
        with mock.patch.object(maps, "_http_post_json", return_value=reply) as post:
            results = self.google.search_places("embassy", limit=4)
        url, headers, body, timeout = post.call_args.args
        self.assertEqual(url, maps.PLACES_URL)
        self.assertEqual(headers["X-Goog-Api-Key"], "test-key")
        self.assertIn("places.location", headers["X-Goog-FieldMask"])
        self.assertEqual(body["textQuery"], "embassy")
        self.assertEqual(body["pageSize"], 4)
        self.assertEqual(body["regionCode"], "IN")
        self.assertEqual(timeout, 5)
        # Only the Bangalore place with coordinates is kept.
        self.assertEqual([r.name for r in results], ["Embassy Tech Village"])
        self.assertEqual((results[0].lat, results[0].lng), (12.9366, 77.6931))

    def test_route_request_and_parsing(self):
        reply = {"routes": [{"distanceMeters": 11250, "duration": "1980s",
                             "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC"}}]}
        with mock.patch.object(maps, "_http_post_json", return_value=reply) as post:
            route = self.google.get_route(12.95, 77.60, 12.93, 77.69)
        url, headers, body, _ = post.call_args.args
        self.assertEqual(url, maps.ROUTES_URL)
        self.assertEqual(body["travelMode"], "DRIVE")
        self.assertEqual(body["origin"]["location"]["latLng"], {"latitude": 12.95, "longitude": 77.60})
        self.assertIn("routes.polyline.encodedPolyline", headers["X-Goog-FieldMask"])
        self.assertEqual(route.distance_m, 11250)
        self.assertEqual(route.duration_s, 1980)
        self.assertEqual(route.points, [(38.5, -120.2), (40.7, -120.95)])

    def test_no_route_found(self):
        with mock.patch.object(maps, "_http_post_json", return_value={}):
            with self.assertRaises(maps.MapsError):
                self.google.get_route(12.95, 77.60, 12.93, 77.69)

    def test_malformed_route_reply(self):
        with mock.patch.object(maps, "_http_post_json", return_value={"routes": [{"distanceMeters": 5}]}):
            with self.assertRaises(maps.MapsError):
                self.google.get_route(12.95, 77.60, 12.93, 77.69)


class HttpHelperTests(SimpleTestCase):
    def test_network_failure_becomes_maps_error(self):
        import urllib.error

        with mock.patch.object(maps.urllib.request, "urlopen", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(maps.MapsError), self.assertLogs("apps.rides.maps", level="ERROR"):
                maps._http_post_json("https://example.test", {}, {}, 1)

    def test_bad_json_becomes_maps_error(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"not json"
        with mock.patch.object(maps.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(maps.MapsError), self.assertLogs("apps.rides.maps", level="ERROR"):
                maps._http_post_json("https://example.test", {}, {}, 1)

    def test_good_reply_is_decoded(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true}'
        with mock.patch.object(maps.urllib.request, "urlopen", return_value=response):
            self.assertEqual(maps._http_post_json("https://example.test", {}, {}, 1), {"ok": True})