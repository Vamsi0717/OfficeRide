from django.test import SimpleTestCase, override_settings

from apps.rides import geo

from .helpers import END, START, line, point_along


class DistanceTests(SimpleTestCase):
    def test_haversine_kr_puram_to_bellandur(self):
        km = geo.haversine_m(13.0076, 77.6954, 12.9260, 77.6760) / 1000
        self.assertAlmostEqual(km, 9.3, delta=0.4)

    def test_same_point_is_zero(self):
        self.assertEqual(geo.haversine_m(12.9, 77.6, 12.9, 77.6), 0)

    def test_cumulative_distances(self):
        points = line()
        cumulative = geo.cumulative_distances_m(points)
        self.assertEqual(cumulative[0], 0)
        self.assertEqual(len(cumulative), len(points))
        self.assertAlmostEqual(cumulative[-1] / 1000, 10.85, delta=0.1)
        self.assertEqual(cumulative, sorted(cumulative))

    def test_bounding_box(self):
        self.assertEqual(geo.bounding_box([(1, 5), (3, 2), (2, 9)]), (1, 3, 2, 9))


class PolylineTests(SimpleTestCase):
    def test_decodes_the_documented_google_example(self):
        points = geo.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        self.assertEqual(points, [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)])


@override_settings(BANGALORE_BOUNDS={"south": 12.70, "west": 77.35, "north": 13.25, "east": 77.85})
class BangaloreBoxTests(SimpleTestCase):
    def test_inside_and_outside(self):
        self.assertTrue(geo.in_bangalore(12.9716, 77.5946))
        self.assertFalse(geo.in_bangalore(13.0827, 80.2707))  # Chennai
        self.assertFalse(geo.in_bangalore(12.2958, 76.6394))  # Mysuru


class ProjectionTests(SimpleTestCase):
    def setUp(self):
        self.points = line()
        self.cumulative = geo.cumulative_distances_m(self.points)

    def test_point_on_the_route(self):
        distance, along = geo.project_onto_route(self.points, self.cumulative, *point_along(0.5))
        self.assertLess(distance, 5)
        self.assertAlmostEqual(along, self.cumulative[-1] / 2, delta=10)

    def test_point_off_the_route_reports_the_gap(self):
        distance, along = geo.project_onto_route(self.points, self.cumulative, *point_along(0.25, north_m=800))
        self.assertAlmostEqual(distance, 800, delta=10)
        self.assertAlmostEqual(along, self.cumulative[-1] / 4, delta=10)

    def test_point_before_the_start_snaps_to_the_start(self):
        distance, along = geo.project_onto_route(self.points, self.cumulative, START[0], START[1] - 0.01)
        self.assertEqual(along, 0)
        self.assertAlmostEqual(distance, 0.01 * 111320 * 0.9743, delta=15)

    def test_point_past_the_end_snaps_to_the_end(self):
        _, along = geo.project_onto_route(self.points, self.cumulative, END[0], END[1] + 0.01)
        self.assertAlmostEqual(along, self.cumulative[-1], delta=1)

    def test_single_point_route(self):
        distance, along = geo.project_onto_route([START], [0.0], START[0] + 0.001, START[1])
        self.assertAlmostEqual(distance, 110.5, delta=1)
        self.assertEqual(along, 0.0)