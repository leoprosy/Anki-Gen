#!/usr/bin/env python3
"""
tests/test_timeline_dates.py — Dates des frises : analyse, intervalles, formatage.

Les dates historiques n'ont pas d'an 0 et `datetime` ne sait pas les représenter :
tout est calculé à la main. Ces tests fixent chaque convention du contrat
(fin inclusive, siècles stricts, siècle ambigu, bissextiles négatives…).

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import timeline_dates as td  # noqa: E402
from timeline_dates import DateError, parse_date  # noqa: E402


def code_of(text, precision=None, **kwargs):
    """Code d'erreur levé par parse_date, ou None si la date est valide."""
    try:
        parse_date(text, precision, **kwargs)
    except DateError as error:
        return error.code
    return None


class TestAstronomicalYears(unittest.TestCase):
    """-44 veut dire 44 av. J.-C. ; en interne, 1 av. J.-C. est l'année 0."""

    def test_historical_to_astronomical(self):
        self.assertEqual(td.to_astronomical(1971), 1971)
        self.assertEqual(td.to_astronomical(1), 1)
        self.assertEqual(td.to_astronomical(-1), 0)
        self.assertEqual(td.to_astronomical(-44), -43)

    def test_astronomical_to_historical(self):
        self.assertEqual(td.to_historical(0), -1)
        self.assertEqual(td.to_historical(-43), -44)
        self.assertEqual(td.to_historical(1), 1)

    def test_round_trip(self):
        for year in (-3000, -44, -1, 1, 14, 1971, 99999):
            self.assertEqual(td.to_historical(td.to_astronomical(year)), year)

    def test_year_zero_has_no_astronomical_value(self):
        with self.assertRaises(ValueError):
            td.to_astronomical(0)

    def test_leap_years_follow_the_astronomical_rule(self):
        self.assertTrue(td.is_leap(2000))
        self.assertFalse(td.is_leap(1900))
        self.assertTrue(td.is_leap(2024))
        self.assertTrue(td.is_leap(0))       # 1 av. J.-C.
        self.assertTrue(td.is_leap(-4))      # 5 av. J.-C.
        self.assertFalse(td.is_leap(-100))   # 101 av. J.-C.
        self.assertTrue(td.is_leap(-400))    # 401 av. J.-C.


class TestParseFormats(unittest.TestCase):
    def test_year_month_day(self):
        date = parse_date("1971-08-15")
        self.assertEqual((date.year, date.month, date.day, date.precision), (1971, 8, 15, "day"))

    def test_year_month(self):
        date = parse_date("1971-08")
        self.assertEqual((date.year, date.month, date.day, date.precision), (1971, 8, None, "month"))

    def test_year_alone(self):
        date = parse_date("1971")
        self.assertEqual((date.year, date.month, date.day, date.precision), (1971, None, None, "year"))

    def test_before_christ(self):
        self.assertEqual(parse_date("-44").year, -44)
        date = parse_date("-753-04-21")
        self.assertEqual((date.year, date.month, date.day), (-753, 4, 21))
        self.assertTrue(date.bc)

    def test_five_digit_years(self):
        self.assertEqual(parse_date("12000").year, 12000)

    def test_rejected_shapes(self):
        for text in ("vers 1450", "1971/08", "71-8", "1971-8", "", "1971-08-15T00",
                     "+1971", "123456", " 1971", "1971 ", "--44", "1971-08-1", "٢٠٢٠"):
            with self.subTest(text=text):
                self.assertEqual(code_of(text), "date_invalid")

    def test_year_zero_does_not_exist(self):
        for text in ("0", "0000", "-0", "0-01", "-0000-01-01"):
            with self.subTest(text=text):
                self.assertEqual(code_of(text), "date_year_zero")

    def test_month_range(self):
        self.assertEqual(code_of("1971-13"), "date_month_invalid")
        self.assertEqual(code_of("1971-00"), "date_month_invalid")
        self.assertIsNone(code_of("1971-12"))

    def test_day_against_month_length(self):
        self.assertEqual(code_of("1971-02-29"), "date_day_invalid")
        self.assertIsNone(code_of("2000-02-29"))
        self.assertEqual(code_of("1900-02-29"), "date_day_invalid")
        self.assertIsNone(code_of("2024-02-29"))
        self.assertEqual(code_of("1971-04-31"), "date_day_invalid")
        self.assertEqual(code_of("1971-08-00"), "date_day_invalid")

    def test_negative_leap_years(self):
        self.assertIsNone(code_of("-1-02-29"))      # astro 0
        self.assertIsNone(code_of("-5-02-29"))      # astro -4
        self.assertEqual(code_of("-4-02-29"), "date_day_invalid")
        self.assertEqual(code_of("-101-02-29"), "date_day_invalid")
        self.assertIsNone(code_of("-401-02-29"))

    def test_error_carries_the_value(self):
        with self.assertRaises(DateError) as caught:
            parse_date("vers 1450")
        self.assertEqual(caught.exception.params["value"], "vers 1450")


class TestPrecision(unittest.TestCase):
    def test_inferred_from_the_string(self):
        self.assertEqual(parse_date("1971").precision, "year")
        self.assertEqual(parse_date("1971-08").precision, "month")
        self.assertEqual(parse_date("1971-08-15").precision, "day")

    def test_explicit_precision_equal_to_the_string(self):
        self.assertEqual(parse_date("1971-08", "month").precision, "month")

    def test_explicit_precision_must_match_the_string(self):
        self.assertEqual(code_of("1971-08", "year"), "precision_mismatch")
        self.assertEqual(code_of("1971", "day"), "precision_mismatch")
        self.assertEqual(code_of("1971-08-15", "decade"), "precision_mismatch")
        self.assertEqual(code_of("1970-01", "century"), "precision_mismatch")

    def test_unknown_precision(self):
        self.assertEqual(code_of("1971", "week"), "precision_invalid")

    def test_decade_needs_a_round_year(self):
        self.assertEqual(code_of("1975", "decade"), "precision_mismatch")
        self.assertIsNone(code_of("1970", "decade"))


class TestIntervals(unittest.TestCase):
    """Chaque date devient [t0, t1) en années décimales astronomiques."""

    def interval(self, text, precision=None):
        date = parse_date(text, precision)
        return date.t0, date.t1

    def test_year(self):
        self.assertEqual(self.interval("1971"), (1971.0, 1972.0))

    def test_month(self):
        t0, t1 = self.interval("1971-01")
        self.assertEqual(t0, 1971.0)
        self.assertAlmostEqual(t1, 1971 + 31 / 365)
        self.assertEqual(self.interval("1971-12")[1], 1972.0)

    def test_day(self):
        t0, t1 = self.interval("1971-08-15")
        self.assertAlmostEqual(t0, 1971 + 226 / 365)
        self.assertAlmostEqual(t1, 1971 + 227 / 365)

    def test_last_day_of_a_leap_year_ends_exactly_on_the_next_year(self):
        t0, t1 = self.interval("2000-12-31")
        self.assertAlmostEqual(t0, 2000 + 365 / 366)
        self.assertEqual(t1, 2001.0)

    def test_before_christ_uses_astronomical_years(self):
        self.assertEqual(self.interval("-44"), (-43.0, -42.0))
        self.assertEqual(self.interval("-1"), (0.0, 1.0))

    def test_decade(self):
        self.assertEqual(self.interval("1970", "decade"), (1970.0, 1980.0))
        # années 1750 av. J.-C. : de 1759 à 1750 av. J.-C.
        self.assertEqual(self.interval("-1750", "decade"), (-1758.0, -1748.0))

    def test_century_is_strict(self):
        date = parse_date("1501", "century")
        self.assertEqual((date.t0, date.t1), (1501.0, 1601.0))
        self.assertEqual(date.unit, 16)
        self.assertFalse(date.ambiguous)
        self.assertEqual(self.interval("1550", "century"), (1501.0, 1601.0))

    def test_round_century_is_ambiguous_and_read_as_the_next_one(self):
        date = parse_date("1500", "century")
        self.assertTrue(date.ambiguous)
        self.assertEqual(date.unit, 16)
        self.assertEqual((date.t0, date.t1), (1501.0, 1601.0))

    def test_century_before_christ(self):
        # IIIe siècle av. J.-C. : 300 à 201 av. J.-C.
        for text in ("-300", "-201"):
            date = parse_date(text, "century")
            self.assertEqual((date.t0, date.t1), (-299.0, -199.0))
            self.assertEqual(date.unit, -3)
            self.assertFalse(date.ambiguous)
        self.assertEqual(self.interval("-200", "century"), (-199.0, -99.0))

    def test_millennium(self):
        # IIIe millénaire av. J.-C. : 3000 à 2001 av. J.-C.
        self.assertEqual(self.interval("-3000", "millennium"), (-2999.0, -1999.0))
        self.assertEqual(self.interval("2001", "millennium"), (2001.0, 3001.0))
        date = parse_date("2000", "millennium")
        self.assertTrue(date.ambiguous)
        self.assertEqual((date.t0, date.t1, date.unit), (2001.0, 3001.0, 3))


class TestPresent(unittest.TestCase):
    def test_not_allowed_by_default(self):
        self.assertEqual(code_of("present"), "present_not_allowed")

    def test_resolved_against_as_of(self):
        date = parse_date("present", allow_present=True, as_of="2026-09-28")
        self.assertTrue(date.present)
        self.assertEqual((date.year, date.month, date.day, date.precision), (2026, 9, 28, "day"))
        self.assertAlmostEqual(date.t1, 2026 + 271 / 365)

    def test_defaults_to_today(self):
        today = datetime.date.today()
        date = parse_date("present", allow_present=True)
        self.assertEqual((date.year, date.month, date.day), (today.year, today.month, today.day))

    def test_as_of_must_be_a_full_date(self):
        with self.assertRaises(DateError):
            parse_date("present", allow_present=True, as_of="2026")


class TestPositionAndSorting(unittest.TestCase):
    def test_point_precisions_sit_on_t0(self):
        self.assertEqual(parse_date("1850").position, 1850.0)
        self.assertEqual(parse_date("1850-01").position, 1850.0)

    def test_wide_precisions_sit_in_the_middle(self):
        self.assertEqual(parse_date("1970", "decade").position, 1975.0)
        self.assertEqual(parse_date("1501", "century").position, 1551.0)

    def test_sort_key_orders_by_start_then_end(self):
        dates = [parse_date("1945-05-08"), parse_date("1945"), parse_date("1945-05")]
        ordered = sorted(dates, key=td.sort_key)
        self.assertEqual([d.precision for d in ordered], ["year", "month", "day"])

    def test_sort_is_stable_for_equal_dates(self):
        items = [("b", parse_date("1945")), ("a", parse_date("1945")), ("c", parse_date("1944"))]
        ordered = sorted(items, key=lambda item: td.sort_key(item[1]))
        self.assertEqual([name for name, _ in ordered], ["c", "b", "a"])


class TestCommonPrecision(unittest.TestCase):
    """Deux dates se comparent à la plus grossière de leurs deux précisions."""

    def same(self, a, b, pa=None, pb=None):
        return td.same_at_common_precision(parse_date(a, pa), parse_date(b, pb))

    def test_day_against_year(self):
        self.assertTrue(self.same("1947-10-30", "1947"))
        self.assertFalse(self.same("1947-10-30", "1948"))

    def test_day_against_month(self):
        self.assertTrue(self.same("1945-05-08", "1945-05"))
        self.assertFalse(self.same("1945-05-08", "1945-06"))

    def test_year_against_decade(self):
        self.assertTrue(self.same("1975", "1970", pb="decade"))
        self.assertFalse(self.same("1981", "1970", pb="decade"))

    def test_century_uses_the_resolved_unit(self):
        self.assertTrue(self.same("1550-03-01", "1501", pb="century"))
        # 1500 lu comme XVIe siècle, alors que l'an 1500 appartient au XVe
        self.assertFalse(self.same("1500-06-01", "1500", pb="century"))

    def test_before_christ_buckets_do_not_collide_with_after(self):
        self.assertFalse(self.same("-5", "5", pb=None))
        self.assertFalse(self.same("-1750", "1750", pa="decade", pb="decade"))


class TestFormatting(unittest.TestCase):
    """Une ligne par cas du tableau §5.4, en français et en anglais."""

    def fmt(self, text, lang, precision=None, **kwargs):
        return td.format_date(parse_date(text, precision), lang, **kwargs)

    def rng(self, start, end, lang, **kwargs):
        return td.format_range(parse_date(start), parse_date(end, allow_present=True,
                                                             as_of="2026-09-28"), lang, **kwargs)

    def test_day(self):
        self.assertEqual(self.fmt("1971-08-15", "fr"), "15 août 1971")
        self.assertEqual(self.fmt("1971-08-15", "en"), "15 Aug 1971")

    def test_first_day_of_the_month(self):
        self.assertEqual(self.fmt("1971-08-01", "fr"), "1er août 1971")
        self.assertEqual(self.fmt("1971-08-01", "en"), "1 Aug 1971")

    def test_month(self):
        self.assertEqual(self.fmt("1971-08", "fr"), "août 1971")
        self.assertEqual(self.fmt("1971-08", "en"), "Aug 1971")

    def test_year(self):
        self.assertEqual(self.fmt("1971", "fr"), "1971")
        self.assertEqual(self.fmt("1971", "en"), "1971")

    def test_before_christ(self):
        self.assertEqual(self.fmt("-44", "fr"), "44 av. J.-C.")
        self.assertEqual(self.fmt("-44", "en"), "44 BC")
        self.assertEqual(self.fmt("-44-03-15", "fr"), "15 mars 44 av. J.-C.")
        self.assertEqual(self.fmt("-44-03-15", "en"), "15 Mar 44 BC")

    def test_approximate(self):
        self.assertEqual(self.fmt("1450", "fr", approx=True), "v. 1450")
        self.assertEqual(self.fmt("1450", "en", approx=True), "c. 1450")
        self.assertEqual(self.fmt("-1750", "fr", approx=True), "v. 1750 av. J.-C.")
        self.assertEqual(self.fmt("-1750", "en", approx=True), "c. 1750 BC")

    def test_decade(self):
        self.assertEqual(self.fmt("1970", "fr", "decade"), "années 1970")
        self.assertEqual(self.fmt("1970", "en", "decade"), "1970s")
        self.assertEqual(self.fmt("-1750", "fr", "decade"), "années 1750 av. J.-C.")

    def test_century(self):
        self.assertEqual(self.fmt("1501", "fr", "century"), "XVIe siècle")
        self.assertEqual(self.fmt("1501", "en", "century"), "16th century")
        self.assertEqual(self.fmt("1501", "fr", "century", short=True), "XVIe s.")
        self.assertEqual(self.fmt("1501", "en", "century", short=True), "16th c.")
        self.assertEqual(self.fmt("1", "fr", "century"), "Ier siècle")
        self.assertEqual(self.fmt("1", "en", "century"), "1st century")

    def test_english_ordinals(self):
        for n, expected in ((2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"),
                            (13, "13th"), (21, "21st"), (22, "22nd"), (23, "23rd"), (111, "111th")):
            with self.subTest(n=n):
                self.assertEqual(td.ordinal(n, "en"), expected)

    def test_french_ordinals_are_roman(self):
        for n, expected in ((1, "Ier"), (2, "IIe"), (4, "IVe"), (9, "IXe"), (14, "XIVe"),
                            (21, "XXIe"), (40, "XLe"), (90, "XCe"), (1994, "MCMXCIVe")):
            with self.subTest(n=n):
                self.assertEqual(td.ordinal(n, "fr"), expected)

    def test_millennium(self):
        self.assertEqual(self.fmt("-3000", "fr", "millennium"), "IIIe millénaire av. J.-C.")
        self.assertEqual(self.fmt("-3000", "en", "millennium"), "3rd millennium BC")

    def test_ranges(self):
        self.assertEqual(self.rng("1870", "1914", "fr"), "1870–1914")
        self.assertEqual(self.rng("-753", "-509", "fr"), "753–509 av. J.-C.")
        self.assertEqual(self.rng("-753", "-509", "en"), "753–509 BC")
        self.assertEqual(self.rng("-44", "14", "fr"), "44 av. J.-C.–14")
        self.assertEqual(self.rng("-44", "14", "en"), "44 BC–AD 14")
        self.assertEqual(self.rng("1870", "1914", "fr", approx=True), "v. 1870–1914")

    def test_range_with_equal_bounds_collapses(self):
        self.assertEqual(self.rng("1945", "1945", "fr"), "1945")

    def test_ongoing(self):
        self.assertEqual(self.rng("2001", "present", "fr"), "depuis 2001")
        self.assertEqual(self.rng("2001", "present", "en"), "since 2001")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(self.fmt("1971-08-15", "de"), "15 Aug 1971")
        self.assertEqual(self.fmt("1501", "de", "century"), "16th century")

    def test_format_year_for_axis_ticks(self):
        self.assertEqual(td.format_year(-1, "fr"), "1 av. J.-C.")
        self.assertEqual(td.format_year(1, "en"), "1")


if __name__ == "__main__":
    unittest.main()
