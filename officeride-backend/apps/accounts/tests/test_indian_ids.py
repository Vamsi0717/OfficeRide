from datetime import date

from django.test import SimpleTestCase

from apps.accounts import indian_ids as ids

TODAY = date(2026, 10, 15)


class RegistrationNumberTests(SimpleTestCase):
    def test_numbers_from_every_kind_of_state_are_accepted(self):
        for raw in (
            "KA01AB1234", "ka 01 ab 1234", "KA-05-MX-9999", "AP39UD0001", "TG09AB1234", "TS07EH1234", "DL8CAF5030",
            "MH12DE1433", "TN09BZ4321", "KL07CD0099", "UP32AB1", "HR26DK8337", "GJ01AA1111", "WB06A1234", "KA51Z9999",
            "AN01A1234", "LA01AA0001", "JK02AB1234", "UK07AA0001", "PY01CC1234",
        ):
            with self.subTest(raw):
                self.assertEqual(ids.normalise_rc(raw), raw.upper().replace(" ", "").replace("-", ""))

    def test_bharat_series_is_accepted(self):
        self.assertEqual(ids.normalise_rc("22 BH 1234 AA"), "22BH1234AA")

    def test_bad_numbers_are_refused(self):
        for raw in ("CWCQINCIQ", "KCWCQINCIQ", "", "12345", "ZZ01AB1234", "KA00AB1234", "KA01AB0000", "KA01AB12345", "KA1", "KA01ABCD1234"):
            with self.subTest(raw), self.assertRaises(ValueError):
                ids.normalise_rc(raw)

    def test_the_message_names_a_wrong_state_code(self):
        with self.assertRaisesMessage(ValueError, "ZZ is not an Indian state code"):
            ids.normalise_rc("ZZ01AB1234")

    def test_every_state_and_union_territory_has_a_code(self):
        for code in ("KA", "TG", "TS", "AP", "TN", "KL", "MH", "DL", "GJ", "RJ", "UP", "WB", "PB", "HR", "OD", "BR", "AS", "JK", "LA", "GA"):
            self.assertIn(code, ids.STATE_CODES)
        self.assertGreaterEqual(len(ids.STATE_CODES), 36)


class LicenceNumberTests(SimpleTestCase):
    def test_numbers_from_any_state_are_accepted(self):
        for raw, clean in (
            ("KA01 20110012345", "KA0120110012345"), ("DL-0420110149646", "DL0420110149646"),
            ("mh12 19981234567", "MH1219981234567"), ("TN0720201234567", "TN0720201234567"),
            ("TG0920151234567", "TG0920151234567"),
        ):
            with self.subTest(raw):
                self.assertEqual(ids.normalise_licence(raw, today=TODAY), clean)

    def test_bad_numbers_are_refused(self):
        for raw in ("CWCQAAC", "", "KA01 2011001234", "KA01 201100123456", "XX01 20110012345", "KA00 20110012345",
                    "KA01 18000012345", "KA01 20990012345", "0120110012345KA"):
            with self.subTest(raw), self.assertRaises(ValueError):
                ids.normalise_licence(raw, today=TODAY)

    def test_the_message_shows_the_shape(self):
        with self.assertRaisesMessage(ValueError, "KA01 20110012345"):
            ids.normalise_licence("12345", today=TODAY)

    def test_pretty_forms(self):
        self.assertEqual(ids.pretty_rc("KA01AB1234"), "KA 01 AB 1234")
        self.assertEqual(ids.pretty_licence("KA0120110012345"), "KA01 20110012345")
        self.assertEqual(ids.pretty_rc("odd"), "odd")