#!/usr/bin/env python3
"""
tests/test_timeline_schema.py — Le contrat `ankigen.timeline/1`.

Chaque code d'erreur a son fixture dans tests/fixtures_timeline/invalid/ (le
chemin JSON Pointer attendu est dans expected.json) ; chaque avertissement et
chaque tolérance de collage a son test ici. Le JSON Schema livré est comparé aux
constantes Python : les deux ne doivent jamais raconter deux histoires.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n  # noqa: E402
import timeline_schema as ts  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures_timeline"
VALID_FIXTURES = sorted(FIXTURES.glob("*.json"))
EXPECTED_INVALID = json.loads((FIXTURES / "invalid" / "expected.json").read_text(encoding="utf-8"))


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def check(report):
    """
    Tout code produit doit être déclaré (et donc traduit), et aucun paramètre ne
    doit porter le nom d'un argument de i18n.translate(key, lang, **params).
    """
    for item in report["errors"]:
        assert item["code"] in ts.ERROR_CODES, item
        assert not {"key", "lang"} & set(item["params"]), item
    for item in report["warnings"]:
        assert item["code"] in ts.WARNING_CODES, item
        assert not {"key", "lang"} & set(item["params"]), item
    for item in report["normalizations"]:
        assert item["code"] in ts.NORMALIZATION_CODES, item
    return report


def run(doc, **kwargs):
    return check(ts.validate(copy.deepcopy(doc), **kwargs))


def run_raw(raw, **kwargs):
    return check(ts.validate_raw(raw, **kwargs))


def codes(items):
    return [(item["code"], item["path"]) for item in items]


def minimal(**overrides):
    doc = {"schema": ts.SCHEMA_ID, "title": "Frise",
           "events": [{"id": "e1", "date": "1971", "label": "Évènement"}]}
    doc.update(overrides)
    return doc


def events(*items):
    return minimal(events=list(items))


class TestValidFixtures(unittest.TestCase):
    def test_there_are_fixtures(self):
        self.assertGreaterEqual(len(VALID_FIXTURES), 11)

    def test_every_valid_fixture_passes_without_warning(self):
        for path in VALID_FIXTURES:
            with self.subTest(fixture=path.name):
                report = run(json.loads(path.read_text(encoding="utf-8")))
                self.assertTrue(report["ok"], report["errors"])
                self.assertEqual(report["warnings"], [])
                self.assertIsNotNone(report["normalized"])

    def test_raw_text_of_every_fixture_passes(self):
        for path in VALID_FIXTURES:
            with self.subTest(fixture=path.name):
                self.assertTrue(run_raw(path.read_text(encoding="utf-8"))["ok"])

    def test_normalization_is_idempotent_and_deterministic(self):
        for path in VALID_FIXTURES:
            with self.subTest(fixture=path.name):
                doc = json.loads(path.read_text(encoding="utf-8"))
                first = run(doc)["normalized"]
                second = run(doc)["normalized"]
                self.assertEqual(json.dumps(first, ensure_ascii=False),
                                 json.dumps(second, ensure_ascii=False))
                again = run(first)
                self.assertEqual(again["normalized"], first)
                self.assertEqual(again["normalizations"], [])


class TestInvalidFixtures(unittest.TestCase):
    """Un fichier par code d'erreur, qui ne produit QUE cette erreur, au bon endroit."""

    def test_each_fixture_yields_exactly_its_error(self):
        for name, expected in EXPECTED_INVALID.items():
            with self.subTest(fixture=name):
                raw = (FIXTURES / "invalid" / name).read_text(encoding="utf-8")
                report = run_raw(raw)
                self.assertFalse(report["ok"])
                self.assertIsNone(report["normalized"])
                self.assertEqual(codes(report["errors"]), [(expected["code"], expected["path"])])

    def test_every_error_code_has_a_fixture(self):
        covered = {expected["code"] for expected in EXPECTED_INVALID.values()}
        # too_large demanderait un fichier de 2 Mo : il est testé en mémoire.
        self.assertEqual(set(ts.ERROR_CODES) - covered, {"too_large"})


class TestPasteTolerances(unittest.TestCase):
    """Ce que les modèles ajoutent autour du JSON est retiré, et consigné."""

    DOC = json.dumps(minimal(), ensure_ascii=False)

    def norms(self, report):
        return [item["code"] for item in report["normalizations"]]

    def test_code_fences(self):
        report = run_raw("```json\n" + self.DOC + "\n```")
        self.assertTrue(report["ok"])
        self.assertEqual(self.norms(report), ["fences_removed"])

    def test_prose_around(self):
        report = run_raw("Voici la frise :\n```json\n" + self.DOC + "\n```\nBonne révision !")
        self.assertTrue(report["ok"])
        self.assertEqual(self.norms(report), ["fences_removed", "prose_removed"])

    def test_bom(self):
        report = run_raw("﻿" + self.DOC)
        self.assertTrue(report["ok"])
        self.assertEqual(self.norms(report), ["bom_removed"])

    def test_year_given_as_a_number(self):
        report = run(events({"id": "e1", "date": 1846, "label": "Abrogation des Corn Laws"},
                            {"id": "e2", "date": -44, "label": "Assassinat de César"}))
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["normalized"]["events"][0]["date"], "1846")
        self.assertEqual(report["normalized"]["events"][1]["date"], "-44")
        self.assertEqual(codes(report["normalizations"]),
                         [("year_as_number", "/events/0/date"), ("year_as_number", "/events/1/date")])

    def test_boolean_is_not_a_year(self):
        report = run(events({"id": "e1", "date": True, "label": "x"}))
        self.assertEqual(codes(report["errors"]), [("type_invalid", "/events/0/date")])

    def test_strings_are_trimmed(self):
        report = run(minimal(title="  Frise  "))
        self.assertEqual(report["normalized"]["title"], "Frise")
        self.assertIn(("trimmed", "/title"), codes(report["normalizations"]))

    def test_drawn_labels_are_collapsed_to_one_line(self):
        report = run(events({"id": "e1", "date": "1971", "label": "Fin  de la\nconvertibilité"}))
        self.assertEqual(report["normalized"]["events"][0]["label"], "Fin de la convertibilité")
        self.assertEqual(codes(report["normalizations"]), [("whitespace_collapsed", "/events/0/label")])

    def test_descriptions_keep_their_line_breaks(self):
        report = run(events({"id": "e1", "date": "1971", "label": "x", "description": "a\nb"}))
        self.assertEqual(report["normalized"]["events"][0]["description"], "a\nb")

    def test_defaults_are_filled(self):
        report = run(minimal(), default_lang="fr")
        doc = report["normalized"]
        self.assertEqual(doc["lang"], "fr")
        self.assertEqual(doc["events"][0]["importance"], 2)
        self.assertEqual(doc["events"][0]["origin"], "text")
        self.assertIs(doc["events"][0]["approx"], False)
        self.assertEqual([doc[k] for k in ("tracks", "eras", "periods", "links")], [[], [], [], []])

    def test_empty_optional_string_is_dropped(self):
        report = run(events({"id": "e1", "date": "1971", "label": "x", "description": "  "}))
        self.assertNotIn("description", report["normalized"]["events"][0])

    def test_canonical_key_order(self):
        report = run({"events": [{"label": "x", "date": "1971", "id": "e1"}],
                      "title": "Frise", "schema": ts.SCHEMA_ID})
        doc = report["normalized"]
        self.assertEqual(list(doc), ["schema", "title", "lang", "tracks", "eras", "periods",
                                     "events", "links"])
        self.assertEqual(list(doc["events"][0])[:3], ["id", "label", "date"])


class TestNothingElseIsRepaired(unittest.TestCase):
    def test_smart_quotes_are_located(self):
        raw = 'Voici :\n{\n  "schema": "ankigen.timeline/1",\n  "title": “Frise”\n}'
        report = run_raw(raw)
        self.assertEqual(codes(report["errors"]), [("json_smart_quotes", "")])
        params = report["errors"][0]["params"]
        # Ligne et colonne dans le texte COLLÉ, prose comprise.
        self.assertEqual((params["line"], params["column"]), (4, 12))
        self.assertIn("“Frise”", params["excerpt"])

    def test_trailing_comma(self):
        report = run_raw('{"schema": "ankigen.timeline/1", "title": "F", "events": [],}')
        self.assertEqual(codes(report["errors"]), [("json_trailing_comma", "")])

    def test_nan_is_not_json(self):
        report = run_raw('{"schema": "ankigen.timeline/1", "title": "F", "x": NaN}')
        self.assertEqual(codes(report["errors"]), [("json_invalid", "")])

    def test_absurd_nesting_does_not_crash(self):
        report = run_raw("{" + '"a":' * 1 + "[" * 50000 + "]" * 50000 + "}")
        self.assertFalse(report["ok"])

    def test_too_large(self):
        raw = '{"schema": "ankigen.timeline/1", "title": "' + "x" * ts.MAX_DOCUMENT_BYTES + '"}'
        report = run_raw(raw)
        self.assertEqual(codes(report["errors"]), [("too_large", "")])

    def test_root_must_be_an_object(self):
        self.assertEqual(codes(run([])["errors"]), [("type_invalid", "")])
        self.assertEqual(codes(run("frise")["errors"]), [("type_invalid", "")])

    def test_collections_must_be_arrays(self):
        report = run(minimal(tracks={}))
        self.assertEqual(codes(report["errors"]), [("type_invalid", "/tracks")])


class TestKeysAndTypes(unittest.TestCase):
    def test_unknown_key_suggests_the_close_one(self):
        report = run(events({"id": "e1", "date": "1971", "lable": "x", "label": "y"}))
        error = report["errors"][0]
        self.assertEqual((error["code"], error["path"]), ("key_unknown", "/events/0/lable"))
        self.assertEqual(error["params"]["suggestion"], "label")
        self.assertEqual(error["hint"], "key_unknown_suggestion")

    def test_unknown_key_without_suggestion(self):
        report = run(minimal(zzz=1))
        self.assertEqual(codes(report["errors"]), [("key_unknown", "/zzz")])
        self.assertNotIn("hint", report["errors"][0])

    def test_json_pointer_escapes_slash_and_tilde(self):
        report = run(minimal(**{"a/b": 1, "c~d": 2}))
        self.assertEqual({path for _, path in codes(report["errors"])}, {"/a~1b", "/c~0d"})

    def test_duplicate_keys_in_nested_objects(self):
        raw = ('{"schema": "ankigen.timeline/1", "title": "F", '
               '"events": [{"id": "e1", "date": "1971", "label": "x", "label": "y"}]}')
        self.assertEqual(codes(run_raw(raw)["errors"]), [("key_duplicate", "/events/0/label")])

    def test_booleans_are_not_integers(self):
        report = run(events({"id": "e1", "date": "1971", "label": "x", "importance": True}))
        self.assertEqual(codes(report["errors"]), [("type_invalid", "/events/0/importance")])

    def test_floats_are_not_integers(self):
        report = run(events({"id": "e1", "date": "1971", "label": "x", "importance": 2.0}))
        self.assertEqual(codes(report["errors"]), [("type_invalid", "/events/0/importance")])

    def test_all_errors_are_reported_at_once(self):
        report = run(events({"id": "E1", "date": "vers 1450", "label": ""},
                            {"id": "e2", "date": "1971", "label": "x", "importance": 5}))
        self.assertEqual(sorted(codes(report["errors"])), sorted([
            ("id_invalid", "/events/0/id"), ("string_empty", "/events/0/label"),
            ("date_invalid", "/events/0/date"), ("out_of_range", "/events/1/importance")]))


class TestMaliciousColors(unittest.TestCase):
    """Une couleur finit dans un attribut SVG : tout sauf #RRGGBB est refusé."""

    def test_rejected(self):
        for color in ("red", "#fff", "#12345G", "red;}</style><script>", "#123456;",
                      "#123456 ", "url(#x)", "#1234567"):
            with self.subTest(color=color):
                report = run(minimal(tracks=[{"id": "t", "label": "T", "color": color}],
                                     events=[{"id": "e1", "date": "1971", "label": "x", "track": "t"}]))
                if color.strip() == "#123456":   # simple espace final : retiré, donc valide
                    self.assertTrue(report["ok"])
                else:
                    self.assertEqual(codes(report["errors"]), [("color_invalid", "/tracks/0/color")])

    def test_accepted(self):
        report = run(events({"id": "e1", "date": "1971", "label": "x", "color": "#0072b2"}))
        self.assertTrue(report["ok"])


class TestLimits(unittest.TestCase):
    def test_label_lengths(self):
        self.assertTrue(run(events({"id": "e1", "date": "1971", "label": "x" * 80}))["ok"])
        report = run(events({"id": "e1", "date": "1971", "label": "x" * 81}))
        self.assertEqual(codes(report["errors"]), [("too_long", "/events/0/label")])
        self.assertEqual(report["errors"][0]["params"], {"length": 81, "max": 80})

    def test_era_labels_are_shorter(self):
        era = {"id": "a", "start": "1870", "end": "1914", "label": "x" * 61}
        self.assertEqual(codes(run(minimal(eras=[era]))["errors"]), [("too_long", "/eras/0/label")])

    def test_tags(self):
        ok = events({"id": "e1", "date": "1971", "label": "x", "tags": ["t" * 30] * 8})
        self.assertTrue(run(ok)["ok"])
        many = events({"id": "e1", "date": "1971", "label": "x", "tags": ["t"] * 9})
        self.assertEqual(codes(run(many)["errors"]), [("too_many", "/events/0/tags")])
        long = events({"id": "e1", "date": "1971", "label": "x", "tags": ["t" * 31]})
        self.assertEqual(codes(run(long)["errors"]), [("too_long", "/events/0/tags/0")])

    def test_counts(self):
        many = [{"id": f"e{i}", "date": str(1000 + i), "label": f"Évènement {i}"} for i in range(400)]
        self.assertTrue(run(minimal(events=many))["ok"])
        many.append({"id": "e400", "date": "1500", "label": "x"})
        self.assertEqual(codes(run(minimal(events=many))["errors"]), [("too_many", "/events")])

    def test_twelve_tracks_is_the_maximum(self):
        tracks = [{"id": f"t{i}", "label": f"Piste {i}"} for i in range(12)]
        evs = [{"id": f"e{i}", "date": "1971", "label": f"x{i}", "track": f"t{i}"} for i in range(12)]
        self.assertTrue(run(minimal(tracks=tracks, events=evs))["ok"])


class TestIdentifiers(unittest.TestCase):
    def test_pattern(self):
        for bad in ("E1", "_e1", "-e1", "é1", "e 1", "x" * 49):
            with self.subTest(id=bad):
                report = run(events({"id": bad, "date": "1971", "label": "x"}))
                self.assertEqual(codes(report["errors"]), [("id_invalid", "/events/0/id")])
        self.assertTrue(run(events({"id": "x" * 48, "date": "1971", "label": "x"}))["ok"])

    def test_unique_across_every_kind(self):
        report = run(minimal(
            tracks=[{"id": "gatt", "label": "Institutions"}],
            periods=[{"id": "p", "track": "gatt", "start": "1947", "end": "1994", "label": "GATT"}],
            events=[{"id": "p", "track": "gatt", "date": "1947", "label": "Signature"}]))
        error = report["errors"][0]
        self.assertEqual((error["code"], error["path"]), ("id_duplicate", "/events/0/id"))
        self.assertEqual(error["params"], {"id": "p", "other": "/periods/0"})


class TestTracks(unittest.TestCase):
    def test_no_tracks_means_one_implicit_lane(self):
        report = run(minimal(tracks=[]))
        self.assertTrue(report["ok"])

    def test_track_without_declared_tracks_is_ignored_with_a_warning(self):
        report = run(events({"id": "e1", "date": "1971", "label": "x", "track": "monnaie"}))
        self.assertTrue(report["ok"])
        self.assertEqual(codes(report["warnings"]), [("track_undeclared", "/events/0/track")])

    def test_blank_track_is_missing(self):
        report = run(minimal(tracks=[{"id": "t", "label": "T"}],
                             events=[{"id": "e1", "date": "1971", "label": "x", "track": " "}]))
        self.assertEqual(codes(report["errors"]), [("track_missing", "/events/0")])

    def test_eras_have_no_track(self):
        era = {"id": "a", "start": "1870", "end": "1914", "label": "A", "track": "t"}
        self.assertEqual(codes(run(minimal(eras=[era]))["errors"]), [("key_unknown", "/eras/0/track")])

    def test_unknown_track_suggests_the_close_one(self):
        report = run(minimal(tracks=[{"id": "commerce", "label": "Commerce"}],
                             events=[{"id": "e1", "date": "1971", "label": "x", "track": "comerce"}]))
        error = report["errors"][0]
        self.assertEqual((error["code"], error["params"]["suggestion"]), ("track_unknown", "commerce"))
        self.assertEqual(ts.with_messages(report, "fr")["errors"][0]["hint"],
                         "Vouliez-vous dire « commerce » ?")

    def test_order_range(self):
        report = run(minimal(tracks=[{"id": "t", "label": "T", "order": 0}],
                             events=[{"id": "e1", "date": "1971", "label": "x", "track": "t"}]))
        self.assertEqual(codes(report["errors"]), [("out_of_range", "/tracks/0/order")])


class TestDatesInDocuments(unittest.TestCase):
    def period(self, start, end, **extra):
        return minimal(periods=[dict({"id": "p", "start": start, "end": end, "label": "Période"}, **extra)])

    def test_end_is_inclusive(self):
        self.assertTrue(run(self.period("1939", "1939"))["ok"])
        self.assertTrue(run(self.period("1939-09", "1939-09"))["ok"])

    def test_end_before_start(self):
        report = run(self.period("1945-05-08", "1945-05-07"))
        self.assertEqual(codes(report["errors"]), [("end_before_start", "/periods/0/end")])

    def test_present_only_in_end(self):
        self.assertTrue(run(self.period("1999", "present"))["ok"])
        report = run(self.period("present", "2030"))
        self.assertEqual(codes(report["errors"]), [("present_not_allowed", "/periods/0/start")])

    def test_present_before_start_is_an_error(self):
        report = run(dict(self.period("2030", "present"), as_of="2026-09-28"))
        self.assertEqual(codes(report["errors"]), [("end_before_start", "/periods/0/end")])

    def test_as_of_must_exist(self):
        report = run(minimal(as_of="2026-02-30"))
        self.assertEqual(codes(report["errors"]), [("as_of_invalid", "/as_of")])

    def test_precision_applies_to_both_bounds(self):
        report = run(self.period("1970", "1980", precision="decade"))
        self.assertTrue(report["ok"], report["errors"])

    def test_error_params_carry_the_value(self):
        report = run(events({"id": "e1", "date": "vers 1450", "label": "x"}))
        self.assertEqual(report["errors"][0]["params"], {"value": "vers 1450"})


class TestEras(unittest.TestCase):
    def eras(self, *spans):
        return minimal(eras=[{"id": f"a{i}", "label": f"Ère {i}", "start": s, "end": e}
                             for i, (s, e) in enumerate(spans)])

    def test_one_unit_at_the_contact_point_is_tolerated(self):
        self.assertTrue(run(self.eras(("1870", "1914"), ("1914", "1945")))["ok"])
        self.assertTrue(run(self.eras(("1914-08", "1918-11"), ("1918-11", "1939-09")))["ok"])

    def test_disjoint_eras(self):
        self.assertTrue(run(self.eras(("1945", "1973"), ("1870", "1914")))["ok"])

    def test_real_overlap(self):
        report = run(self.eras(("1870", "1920"), ("1900", "1945")))
        self.assertEqual(codes(report["errors"]), [("eras_overlap", "/eras/1")])
        self.assertEqual(report["errors"][0]["params"], {"other": "a0"})

    def test_containment(self):
        report = run(self.eras(("1870", "1945"), ("1914", "1918")))
        self.assertEqual(codes(report["errors"]), [("eras_overlap", "/eras/1")])

    def test_two_years_is_more_than_one_unit(self):
        report = run(self.eras(("1870", "1915"), ("1914", "1945")))
        self.assertEqual(codes(report["errors"]), [("eras_overlap", "/eras/1")])


class TestWarnings(unittest.TestCase):
    def test_label_contains_its_year(self):
        report = run(events({"id": "e1", "date": "1860-01-23", "label": "Traité de 1860"}))
        self.assertTrue(report["ok"])
        self.assertEqual(codes(report["warnings"]), [("label_contains_year", "/events/0/label")])
        self.assertEqual(report["warnings"][0]["params"], {"year": 1860})

    def test_other_numbers_are_fine(self):
        report = run(events({"id": "e1", "date": "1860", "label": "Traité des 18600 articles"},
                            {"id": "e2", "date": "1945", "label": "Crise de 1929"}))
        self.assertEqual(report["warnings"], [])

    def test_period_label_with_a_bound(self):
        report = run(minimal(periods=[{"id": "p", "start": "1939", "end": "1945",
                                       "label": "Guerre 1939-1945"}]))
        self.assertEqual(codes(report["warnings"]), [("label_contains_year", "/periods/0/label")])

    def test_ambiguous_century(self):
        report = run(events({"id": "e1", "date": "1500", "precision": "century", "label": "Renaissance"}))
        self.assertTrue(report["ok"])
        self.assertEqual(codes(report["warnings"]), [("century_ambiguous", "/events/0/date")])
        self.assertEqual(report["warnings"][0]["params"], {"value": "1500", "first": 1501})

    def test_ambiguous_millennium(self):
        report = run(events({"id": "e1", "date": "2000", "precision": "millennium", "label": "x"}))
        self.assertEqual(codes(report["warnings"]), [("millennium_ambiguous", "/events/0/date")])
        self.assertEqual(report["warnings"][0]["params"]["first"], 2001)

    def test_model_additions(self):
        report = run(events({"id": "e1", "date": "1971", "label": "x", "origin": "model"}))
        self.assertEqual(codes(report["warnings"]), [("origin_model", "/events/0")])

    def test_probable_duplicate(self):
        report = run(events({"id": "gatt", "date": "1947-10-30", "label": "Signature du GATT"},
                            {"id": "gatt2", "date": "1947", "label": "Signature du G.A.T.T."}))
        self.assertEqual(codes(report["warnings"]), [("duplicate_probable", "/events/1")])
        self.assertEqual(report["warnings"][0]["params"], {"other": "gatt"})

    def test_not_a_duplicate_at_another_date_or_in_another_track(self):
        self.assertEqual(run(events({"id": "a", "date": "1947", "label": "Signature du GATT"},
                                    {"id": "b", "date": "1948", "label": "Signature du GATT"}))["warnings"], [])
        tracks = [{"id": "fr", "label": "France"}, {"id": "it", "label": "Italie"}]
        doc = minimal(tracks=tracks, events=[
            {"id": "a", "track": "fr", "date": "1999-01-01", "label": "Passage à l'euro"},
            {"id": "b", "track": "it", "date": "1999-01-01", "label": "Passage à l'euro"}])
        self.assertEqual(run(doc)["warnings"], [])

    def test_duplicate_periods_need_both_bounds(self):
        same = [{"id": "a", "start": "1944", "end": "1971", "label": "Bretton Woods"},
                {"id": "b", "start": "1944", "end": "1971", "label": "Bretton-Woods"}]
        self.assertEqual(codes(run(minimal(periods=same))["warnings"]), [("duplicate_probable", "/periods/1")])
        other_end = [same[0], dict(same[1], end="1973")]
        self.assertEqual(run(minimal(periods=other_end))["warnings"], [])

    def test_too_many_pivots(self):
        evs = [{"id": f"e{i}", "date": str(1900 + i), "label": f"Évènement {i}",
                "importance": 3 if i < 1 else 2} for i in range(4)]
        self.assertEqual(run(minimal(events=evs))["warnings"], [])        # 1 sur 4 : 25 %
        evs[1]["importance"] = 3
        report = run(minimal(events=evs))
        self.assertEqual(codes(report["warnings"]), [("importance_high_ratio", "")])
        self.assertEqual(report["warnings"][0]["params"], {"count": 2, "total": 4})

    def test_a_single_pivot_is_never_too_many(self):
        self.assertEqual(run(events({"id": "e1", "date": "1971", "label": "x", "importance": 3}))["warnings"], [])

    def test_empty_track(self):
        report = run(minimal(tracks=[{"id": "t", "label": "T"}, {"id": "u", "label": "U"}],
                             events=[{"id": "e1", "date": "1971", "label": "x", "track": "t"}]))
        self.assertEqual(codes(report["warnings"]), [("track_empty", "/tracks/1")])

    def test_warnings_are_kept_next_to_errors(self):
        report = run(events({"id": "e1", "date": "1860", "label": "Traité de 1860"},
                            {"id": "e2", "date": "vers 1450", "label": "x"}))
        self.assertFalse(report["ok"])
        self.assertEqual(codes(report["warnings"]), [("label_contains_year", "/events/0/label")])


class TestMessages(unittest.TestCase):
    def test_every_code_is_translated(self):
        prefixes = (("err", ts.ERROR_CODES), ("warn", ts.WARNING_CODES),
                    ("norm", ts.NORMALIZATION_CODES), ("hint", ts.HINT_CODES))
        for lang in i18n.LANGUAGES:
            catalog = i18n.load_catalog(lang)
            for prefix, all_codes in prefixes:
                for code in all_codes:
                    self.assertIn(f"timeline.{prefix}.{code}", catalog, lang)

    def test_no_orphan_message(self):
        import timeline_layout
        declared = ({f"timeline.err.{c}" for c in ts.ERROR_CODES}
                    | {f"timeline.warn.{c}" for c in ts.WARNING_CODES + timeline_layout.WARNING_CODES}
                    | {f"timeline.norm.{c}" for c in ts.NORMALIZATION_CODES}
                    | {f"timeline.hint.{c}" for c in ts.HINT_CODES})
        catalog = i18n.load_catalog("en")
        present = {k for k in catalog if re.match(r"timeline\.(err|warn|norm|hint)\.", k)}
        self.assertEqual(present - declared, set())

    def test_messages_follow_the_requested_language(self):
        report = run(events({"id": "e1", "date": "vers 1450", "label": "x"}))
        fr = ts.with_messages(report, "fr")["errors"][0]
        self.assertEqual(fr["message"], "« vers 1450 » n'est pas une date.")
        self.assertIn("approx", fr["hint"])
        en = ts.with_messages(report, "en")["errors"][0]
        self.assertEqual(en["message"], "“vers 1450” is not a date.")

    def test_every_invalid_fixture_renders_in_every_language(self):
        for name in EXPECTED_INVALID:
            report = run_raw((FIXTURES / "invalid" / name).read_text(encoding="utf-8"))
            for lang in i18n.LANGUAGES:
                with self.subTest(fixture=name, lang=lang):
                    error = ts.with_messages(report, lang)["errors"][0]
                    self.assertTrue(error["message"])
                    self.assertFalse(error["message"].startswith("timeline."), error)

    def test_every_message_renders_with_its_params(self):
        """Aucun gabarit ne doit réclamer un paramètre que le code ne fournit pas."""
        raws = [(FIXTURES / "invalid" / name).read_text(encoding="utf-8") for name in EXPECTED_INVALID]
        reports = [run_raw(raw) for raw in raws]
        reports.append(run(events({"id": "e1", "date": "1500", "precision": "century",
                                   "label": "Traité de 1500", "origin": "model"})))
        for lang in i18n.LANGUAGES:
            catalog = i18n.load_catalog(lang)
            for report in reports:
                for prefix, items in (("err", report["errors"]), ("warn", report["warnings"])):
                    for item in items:
                        keys = [f"timeline.{prefix}.{item['code']}"]
                        hint = item.get("hint") or item["code"]
                        if f"timeline.hint.{hint}" in catalog:
                            keys.append(f"timeline.hint.{hint}")
                        for key in keys:
                            with self.subTest(lang=lang, key=key):
                                catalog[key].format(**item["params"])   # KeyError si un paramètre manque


class TestJsonSchemaFile(unittest.TestCase):
    """static/schemas/timeline-v1.json est dérivé des constantes : il ne doit pas dériver."""

    ALLOWED = {"$schema", "title", "type", "enum", "const", "required", "properties",
               "additionalProperties", "maxLength", "maxItems", "minimum", "maximum",
               "pattern", "items"}

    def setUp(self):
        self.schema = json.loads(ts.SCHEMA_FILE.read_text(encoding="utf-8"))

    def test_file_matches_the_python_constants(self):
        self.assertEqual(self.schema, ts.json_schema(),
                         "régénérer : python timeline_schema.py --write-schema")

    def test_only_the_llama_cpp_subset(self):
        def walk(node, path="#"):
            self.assertLessEqual(set(node) - self.ALLOWED, set(), path)
            for key, child in node.get("properties", {}).items():
                walk(child, f"{path}/properties/{key}")
            if isinstance(node.get("items"), dict):
                walk(node["items"], f"{path}/items")
        walk(self.schema)

    def test_no_additional_properties_anywhere(self):
        def walk(node):
            if node.get("type") == "object":
                self.assertIs(node["additionalProperties"], False)
                for child in node["properties"].values():
                    walk(child)
            if isinstance(node.get("items"), dict):
                walk(node["items"])
        walk(self.schema)

    def test_required_members(self):
        props = self.schema["properties"]
        self.assertEqual(self.schema["required"], ["schema", "title"])
        self.assertEqual(props["events"]["items"]["required"], ["id", "label", "date"])
        self.assertEqual(props["periods"]["items"]["required"], ["id", "label", "start", "end"])
        self.assertNotIn("track", props["eras"]["items"]["properties"])
        self.assertEqual(props["schema"]["const"], ts.SCHEMA_ID)

    def test_date_patterns_agree_with_the_parser(self):
        date = self.schema["properties"]["events"]["items"]["properties"]["date"]["pattern"]
        end = self.schema["properties"]["periods"]["items"]["properties"]["end"]["pattern"]
        for path in VALID_FIXTURES:
            doc = json.loads(path.read_text(encoding="utf-8"))
            for event in doc.get("events", []):
                self.assertTrue(re.fullmatch(date, event["date"]), event)
            for period in doc.get("periods", []):
                self.assertTrue(re.fullmatch(date, period["start"]), period)
                self.assertTrue(re.fullmatch(end, period["end"]), period)
        self.assertFalse(re.fullmatch(date, "present"))
        self.assertFalse(re.fullmatch(date, "١٩٧١"))


if __name__ == "__main__":
    unittest.main()
