#!/usr/bin/env python3
"""
tests/test_timeline_merge.py — Fusion des frises extraites paragraphe par paragraphe (§6.4).

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import timeline_extract  # noqa: E402
import timeline_merge as tm  # noqa: E402
import timeline_schema  # noqa: E402
import timeline_store  # noqa: E402


def doc(tracks=(), eras=(), periods=(), events=(), links=()):
    raw = {"schema": "ankigen.timeline/1", "title": "Partie", "lang": "fr", "tracks": list(tracks),
           "eras": list(eras), "periods": list(periods), "events": list(events), "links": list(links)}
    report = timeline_schema.validate(raw, default_lang="fr")
    assert report["ok"], report["errors"]
    return report["normalized"]


def event(id, date, label, track="commerce", **extra):
    return {"id": id, "track": track, "date": date, "label": label, **extra}


COMMERCE = {"id": "commerce", "label": "Commerce"}


def merged(parts, **options):
    result, report = tm.merge(parts, title="Frise", lang="fr", **options)
    validation = timeline_schema.validate(result, default_lang="fr")
    return result, report, validation


class TestIds(unittest.TestCase):
    def test_prefix_by_chunk(self):
        self.assertEqual(tm.prefixed_id(12, "gatt", set()), "c12_gatt")

    def test_truncates_the_original_end_to_fit(self):
        original = "a" * 48
        new = tm.prefixed_id(12, original, set())
        self.assertEqual(len(new), 48)
        self.assertTrue(new.startswith("c12_aaa"))
        self.assertRegex(new, timeline_schema.ID_PATTERN)

    def test_collisions_get_a_suffix_within_the_limit(self):
        taken = set()
        first = tm.prefixed_id(3, "x" * 60, taken)
        second = tm.prefixed_id(3, "x" * 61, taken)
        third = tm.prefixed_id(3, "x" * 62, taken)
        self.assertEqual({len(first), len(second), len(third)}, {48})
        self.assertTrue(second.endswith("-2") and third.endswith("-3"))


class TestTracks(unittest.TestCase):
    def test_tracks_merge_by_normalized_label(self):
        parts = [
            (1, doc([COMMERCE], events=[event("a", "1860", "Traité Cobden-Chevalier")])),
            (2, doc([{"id": "echanges", "label": "  COMMERCÉ "}],
                    events=[event("b", "1892", "Tarif Méline", track="echanges")])),
        ]
        result, report, validation = merged(parts)
        self.assertTrue(validation["ok"], validation["errors"])
        self.assertEqual(result["tracks"], [COMMERCE])
        self.assertEqual({e["track"] for e in result["events"]}, {"commerce"})
        self.assertEqual(report["tracks"], [{"id": "commerce", "label": "Commerce", "chunks": [1, 2],
                                             "variants": ["Commerce", "COMMERCÉ"]}])

    def test_a_reused_id_is_the_same_track(self):
        parts = [
            (1, doc([COMMERCE], events=[event("a", "1860", "Traité Cobden-Chevalier")])),
            (2, doc([{"id": "commerce", "label": "Commerce international"}],
                    events=[event("b", "1892", "Tarif Méline")])),
        ]
        result, _, _ = merged(parts)
        self.assertEqual(result["tracks"], [COMMERCE])

    def test_beyond_twelve_tracks_the_least_used_are_folded(self):
        parts = []
        for chunk in range(14):
            track = {"id": f"t{chunk}", "label": f"Thème {chunk}"}
            count = 3 if chunk < 11 else 1
            parts.append((chunk, doc([track], events=[
                event(f"e{i}", str(1800 + chunk * 10 + i), f"Évènement {chunk} {i}", track=f"t{chunk}")
                for i in range(count)])))
        result, report, validation = merged(parts)
        self.assertTrue(validation["ok"], validation["errors"])
        self.assertEqual(len(result["tracks"]), 12)
        self.assertEqual(result["tracks"][-1], {"id": "other", "label": "Autres"})
        self.assertEqual(report["tracks_folded"], ["Thème 11", "Thème 12", "Thème 13"])
        self.assertEqual(sum(e["track"] == "other" for e in result["events"]), 3)

    def test_elements_without_track_join_an_other_track(self):
        parts = [
            (1, doc([COMMERCE], events=[event("a", "1860", "Traité Cobden-Chevalier")])),
            (2, doc(events=[{"id": "b", "date": "1892", "label": "Tarif Méline"}])),
        ]
        result, _, validation = merged(parts)
        self.assertTrue(validation["ok"], validation["errors"])
        self.assertEqual([t["id"] for t in result["tracks"]], ["commerce", "other"])
        self.assertEqual(result["events"][1]["track"], "other")

    def test_no_tracks_anywhere_stays_without_tracks(self):
        parts = [(1, doc(events=[{"id": "a", "date": "1860", "label": "Traité"}])),
                 (2, doc(events=[{"id": "b", "date": "1892", "label": "Tarif"}]))]
        result, _, validation = merged(parts)
        self.assertTrue(validation["ok"])
        self.assertEqual(result["tracks"], [])


class TestDuplicates(unittest.TestCase):
    def parts(self):
        return [
            (3, doc([COMMERCE], events=[
                event("gatt", "1947", "Signature du GATT", importance=2, tags=["libre-échange"],
                      description="Court.", source_quote="le GATT, signé en 1947"),
                event("suez", "1869-11-17", "Ouverture du canal de Suez"),
            ], links=[{"from": "suez", "to": "gatt"}])),
            (12, doc([COMMERCE], events=[
                event("gatt_signe", "1947-10-30", "Signature du GATT.", importance=3, tags=["GATT"],
                      description="Plus longue description.", source_quote="Le GATT est signé le 30 octobre 1947",
                      date_text="le 30 octobre 1947"),
            ])),
        ]

    def test_duplicates_across_chunks_become_one_element(self):
        result, report, validation = merged(self.parts())
        self.assertTrue(validation["ok"], validation["errors"])
        ids = [e["id"] for e in result["events"]]
        self.assertEqual(ids, ["c3_gatt", "c3_suez"])
        gatt = result["events"][0]
        self.assertEqual(gatt["label"], "Signature du GATT")          # le premier garde son libellé
        self.assertEqual(gatt["importance"], 3)                       # importance maximale
        self.assertEqual(gatt["description"], "Plus longue description.")
        self.assertEqual(gatt["tags"], ["libre-échange", "GATT"])
        self.assertEqual(gatt["date"], "1947-10-30")                  # la date la plus précise
        self.assertEqual(gatt["date_text"], "le 30 octobre 1947")
        self.assertEqual(gatt["source_quote"], "le GATT, signé en 1947")
        self.assertEqual(report["merged"], 1)
        duplicate = report["duplicates"][0]
        self.assertEqual(duplicate["ids"], ["c3_gatt", "c12_gatt_signe"])
        self.assertEqual(duplicate["chunks"], [3, 12])
        # Toutes les citations sont conservées.
        self.assertEqual(duplicate["quotes"], ["le GATT, signé en 1947", "Le GATT est signé le 30 octobre 1947"])
        self.assertFalse(duplicate["separated"])
        self.assertEqual(report["elements"], 2)
        self.assertEqual(result["links"], [{"from": "c3_suez", "to": "c3_gatt"}])

    def test_undoing_a_merge_keeps_both(self):
        key = "c3_gatt+c12_gatt_signe"
        result, report, validation = merged(self.parts(), keep_separate=[key])
        self.assertTrue(validation["ok"])
        self.assertEqual([e["id"] for e in result["events"]], ["c3_gatt", "c3_suez", "c12_gatt_signe"])
        self.assertTrue(report["duplicates"][0]["separated"])
        self.assertEqual(report["merged"], 0)

    def test_duplicates_inside_one_chunk_are_left_to_validation(self):
        parts = [(1, doc([COMMERCE], events=[event("a", "1947", "Signature du GATT"),
                                              event("b", "1947", "Signature du GATT")]))]
        result, report, validation = merged(parts)
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(report["duplicates"], [])
        self.assertIn("duplicate_probable", [w["code"] for w in validation["warnings"]])

    def test_different_dates_or_labels_are_not_duplicates(self):
        parts = [(1, doc([COMMERCE], events=[event("a", "1947", "Signature du GATT")])),
                 (2, doc([COMMERCE], events=[event("a", "1948", "Signature du GATT"),
                                              event("b", "1947", "Plan Marshall")]))]
        result, report, _ = merged(parts)
        self.assertEqual(len(result["events"]), 3)
        self.assertEqual(report["duplicates"], [])

    def test_periods_need_both_bounds_to_match(self):
        bw = {"id": "bw", "track": "commerce", "label": "Système de Bretton Woods", "start": "1944", "end": "1971"}
        parts = [(1, doc([COMMERCE], periods=[bw])),
                 (2, doc([COMMERCE], periods=[dict(bw, start="1944-07", end="1971-08-15")])),
                 (3, doc([COMMERCE], periods=[dict(bw, end="1973")]))]
        result, report, _ = merged(parts)
        self.assertEqual([p["id"] for p in result["periods"]], ["c1_bw", "c3_bw"])
        self.assertEqual(result["periods"][0]["start"], "1944-07")


class TestEras(unittest.TestCase):
    def era(self, id, label, start, end):
        return {"id": id, "label": label, "start": start, "end": end}

    def test_touching_eras_are_kept_and_overlapping_ones_dropped(self):
        parts = [
            (1, doc(eras=[self.era("m1", "Première mondialisation", "1870", "1914")],
                    events=[{"id": "a", "date": "1880", "label": "Un"}])),
            (2, doc(eras=[self.era("guerres", "Désintégration", "1914", "1945"),
                          self.era("belle", "Belle Époque", "1890", "1914")],
                    events=[{"id": "b", "date": "1920", "label": "Deux"}])),
        ]
        result, report, validation = merged(parts)
        self.assertTrue(validation["ok"], validation["errors"])
        self.assertEqual([e["id"] for e in result["eras"]], ["c1_m1", "c2_guerres"])
        self.assertEqual(report["eras_dropped"], [{"chunk": 2, "id": "c2_belle", "label": "Belle Époque",
                                                   "overlaps": "Première mondialisation"}])

    def test_the_same_era_twice_is_merged(self):
        era = self.era("m1", "Première mondialisation", "1870", "1914")
        parts = [(1, doc(eras=[era], events=[{"id": "a", "date": "1880", "label": "Un"}])),
                 (2, doc(eras=[dict(era, id="mondialisation_1")], events=[{"id": "b", "date": "1890", "label": "Deux"}]))]
        result, report, validation = merged(parts)
        self.assertTrue(validation["ok"])
        self.assertEqual(len(result["eras"]), 1)
        self.assertEqual(report["duplicates"][0]["kind"], "eras")
        self.assertEqual(report["eras_dropped"], [])


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_bytes(self):
        fixture = json.loads((ROOT / "tests" / "fixtures_timeline" / "mondialisation.json").read_text(encoding="utf-8"))
        full = timeline_schema.validate(fixture, default_lang="fr")["normalized"]
        halves = [(i, dict(full, events=full["events"][i::2], periods=full["periods"][i::2], eras=[] if i else full["eras"]))
                  for i in range(2)]
        parts = [(i, timeline_schema.validate(half, default_lang="fr")["normalized"]) for i, half in halves]
        first = json.dumps(tm.merge(parts, title="T", lang="fr"), ensure_ascii=False, sort_keys=True)
        second = json.dumps(tm.merge(parts, title="T", lang="fr"), ensure_ascii=False, sort_keys=True)
        self.assertEqual(first, second)
        result, report = tm.merge(parts, title="T", lang="fr")
        self.assertTrue(timeline_schema.validate(result, default_lang="fr")["ok"])
        self.assertEqual(report["elements"], len(full["events"]) + len(full["periods"]) + len(full["eras"]))


class TestMergeRecord(unittest.TestCase):
    def record(self):
        record = timeline_store.new_record(title="Mondialisation", lang="fr",
                                           source={"kind": "chapter", "spans": [[1, 0, 10], [2, 12, 20], [3, 22, 30]]},
                                           source_text="x" * 30, extraction={"strategy": "per_chunk"})
        per_chunk = record["extraction"]["per_chunk"]
        per_chunk["1"] = {"status": "ok", "raw": json.dumps(doc([COMMERCE], events=[event("a", "1860", "Traité")]))}
        per_chunk["2"] = {"status": "empty", "raw": '{"schema": "ankigen.timeline/1", "title": "x", "events": []}'}
        per_chunk["3"] = {"status": "ok", "raw": "```json\n" + json.dumps(
            doc([COMMERCE], events=[event("b", "1892", "Tarif Méline")])) + "\n```"}
        return record

    def test_merges_the_valid_chunks_in_course_order(self):
        report, merge_report = timeline_extract.merge_record(self.record(), lang="fr")
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["normalized"]["title"], "Mondialisation")
        self.assertEqual([e["id"] for e in report["normalized"]["events"]], ["c1_a", "c3_b"])
        self.assertEqual(merge_report["chunks"], [1, 3])

    def test_nothing_to_merge(self):
        record = self.record()
        record["extraction"]["per_chunk"] = {}
        report, merge_report = timeline_extract.merge_record(record, lang="fr")
        self.assertIsNone(report)
        self.assertEqual(merge_report["elements"], 0)

    def test_chunk_status(self):
        extractor = timeline_extract.ManualExtractor()
        empty = '{"schema": "ankigen.timeline/1", "title": "x", "tracks": [], "events": []}'
        self.assertEqual(extractor.parse_response(empty, lang="fr", chunk=True)[1]["status"], "empty")
        self.assertEqual(extractor.parse_response(empty, lang="fr")[1]["status"], "error")
        broken = '{"schema": "ankigen.timeline/1", "title": "x", "events": [],}'
        self.assertEqual(extractor.parse_response(broken, lang="fr", chunk=True)[1]["status"], "error")


if __name__ == "__main__":
    unittest.main()
