#!/usr/bin/env python3
"""
tests/test_timeline_store.py — Persistance des frises dans DATA_DIR/timelines/.

Les frises ne vivent jamais dans projects/ : list_projects() y prend tous les
*.json pour des projets. Les identifiants viennent de l'URL : ils sont validés
avant tout accès disque.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paths  # noqa: E402
import project_store  # noqa: E402
import timeline_store as store  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures_timeline" / "mondialisation.json").read_text(encoding="utf-8"))


class StoreTestCase(unittest.TestCase):
    """Redirige TIMELINES_DIR vers un dossier jetable : aucun test ne touche aux vraies données."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-timelines-"))
        self.dir = self.tmp / "timelines"
        self.dir.mkdir()
        patcher = mock.patch.object(store, "TIMELINES_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)


class TestIdentifiers(StoreTestCase):
    def test_valid(self):
        for tid in ("mondialisation-3f9a", "a", "x" * 64, "0_frise-1"):
            with self.subTest(tid=tid):
                self.assertTrue(store.valid_id(tid))

    def test_malicious_or_malformed(self):
        for tid in ("../x", "..\\x", "a/b", "a\\b", "", "A", "x" * 65, "-x", "_x", "é",
                    "x.json", "x\x00", None, 42, "con", "nul", "aux", "prn", "com1", "lpt9"):
            with self.subTest(tid=tid):
                self.assertFalse(store.valid_id(tid))
                with self.assertRaises(store.TimelineIdError):
                    store.timeline_path(tid)

    def test_every_disk_operation_checks_the_id(self):
        for operation in (store.load_timeline, store.delete_timeline,
                          lambda tid: store.save_timeline(tid, store.new_record(title="x"))):
            with self.subTest(operation=operation):
                with self.assertRaises(store.TimelineIdError):
                    operation("../../projects/cours")
        self.assertEqual(list(self.tmp.rglob("*.json")), [])

    def test_new_id_is_a_slug_of_the_title(self):
        tid = store.new_timeline_id("La dynamique de la mondialisation économique")
        self.assertRegex(tid, r"^la-dynamique-de-la-mondialisation-economique-[0-9a-f]{4}$")
        self.assertTrue(store.valid_id(tid))

    def test_new_id_without_usable_title(self):
        self.assertRegex(store.new_timeline_id("«  »"), r"^timeline-[0-9a-f]{4}$")
        self.assertRegex(store.new_timeline_id(""), r"^timeline-[0-9a-f]{4}$")

    def test_new_id_of_a_long_title_stays_valid(self):
        tid = store.new_timeline_id("Histoire " * 20)
        self.assertLessEqual(len(tid), 64)
        self.assertTrue(store.valid_id(tid))
        self.assertNotIn("--", tid)    # la coupe ne laisse pas de tiret pendant

    def test_new_id_avoids_existing_files(self):
        (self.dir / "frise-aaaa.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(store.secrets, "token_hex", side_effect=["aaaa", "bbbb"]):
            self.assertEqual(store.new_timeline_id("Frise"), "frise-bbbb")


class TestRecords(StoreTestCase):
    NOW = "2026-09-28T18:00:00Z"

    def test_new_record_has_every_field(self):
        record = store.new_record(title="Frise", lang="fr", data=FIXTURE, now=self.NOW,
                                  source={"kind": "text"}, source_text="Le traité de 1860.")
        self.assertEqual(record["version"], store.TIMELINE_VERSION)
        self.assertEqual((record["created_at"], record["updated_at"]), (self.NOW, self.NOW))
        self.assertEqual(record["source"]["kind"], "text")
        self.assertEqual(record["source"]["text_hash"], store.text_hash("Le traité de 1860."))
        self.assertEqual(record["source"]["spans"], [])
        self.assertEqual(record["extraction"], {
            "mode": "strict", "strategy": "single", "skill": False, "per_chunk": {},
            "merge": {"keep_separate": [], "report": None, "hash": None}})
        for key, empty in (("raw_responses", []), ("render_options", {}), ("card_options", {}),
                           ("disabled_cards", [])):
            self.assertEqual(record[key], empty)
        self.assertIsNone(record["cards_deck"])

    def test_source_kinds(self):
        with self.assertRaises(ValueError):
            store.new_record(title="x", source={"kind": "web"})

    def test_source_text_limit(self):
        store.new_record(title="x", source_text="a" * store.MAX_SOURCE_CHARS)
        with self.assertRaises(ValueError):
            store.new_record(title="x", source_text="a" * (store.MAX_SOURCE_CHARS + 1))

    def test_text_hash_is_sha1(self):
        self.assertEqual(store.text_hash("abc"), "a9993e364706816aba3e25717850c26c9cd0d89d")

    def test_raw_responses_keep_the_last_five(self):
        record = store.new_record(title="x")
        for i in range(7):
            store.push_raw_response(record, f"réponse {i}")
        self.assertEqual(record["raw_responses"], [f"réponse {i}" for i in range(2, 7)])

    def test_normalize_fills_missing_fields(self):
        record = store.normalize_record({"id": "x", "data": None})
        self.assertEqual(record["version"], store.TIMELINE_VERSION)
        self.assertEqual(record["raw_responses"], [])
        self.assertEqual(record["source"]["kind"], "import")

    def test_title_comes_from_the_document_when_there_is_one(self):
        self.assertEqual(store.display_title(store.new_record(title="Brouillon", data=FIXTURE)),
                         FIXTURE["title"])
        self.assertEqual(store.display_title(store.new_record(title="Brouillon")), "Brouillon")


class TestCrud(StoreTestCase):
    def test_create_load_save_delete(self):
        tid, record = store.create_timeline(title="Mondialisation", data=FIXTURE)
        path = self.dir / f"{tid}.json"
        self.assertTrue(path.exists())
        loaded = store.load_timeline(tid)
        self.assertEqual(loaded, record)
        self.assertEqual(loaded["id"], tid)

        loaded["cards_deck"] = "Économie::Chronologie"
        with mock.patch.object(store, "_now", return_value="2030-01-01T00:00:00Z"):
            store.save_timeline(tid, loaded)
        again = store.load_timeline(tid)
        self.assertEqual(again["cards_deck"], "Économie::Chronologie")
        self.assertEqual(again["updated_at"], "2030-01-01T00:00:00Z")
        self.assertEqual(again["created_at"], record["created_at"])

        self.assertTrue(store.delete_timeline(tid))
        self.assertFalse(path.exists())
        self.assertIsNone(store.load_timeline(tid))
        self.assertFalse(store.delete_timeline(tid))

    def test_file_is_readable_utf8_json(self):
        tid, _ = store.create_timeline(title="Économie", data=FIXTURE)
        text = (self.dir / f"{tid}.json").read_text(encoding="utf-8")
        self.assertIn("Désintégration", text)    # pas d'échappement é : relisible à la main

    def test_save_forces_the_id_of_the_path(self):
        tid, record = store.create_timeline(title="Frise")
        record["id"] = "autre"
        store.save_timeline(tid, record)
        self.assertEqual(store.load_timeline(tid)["id"], tid)

    def test_atomic_write_keeps_the_previous_file(self):
        tid, record = store.create_timeline(title="Frise", data=FIXTURE)
        before = (self.dir / f"{tid}.json").read_bytes()
        record["cards_deck"] = "Nouveau"
        with mock.patch.object(store.json, "dump", side_effect=OSError("disque plein")):
            with self.assertRaises(OSError):
                store.save_timeline(tid, record)
        self.assertEqual((self.dir / f"{tid}.json").read_bytes(), before)
        self.assertEqual([p.name for p in self.dir.iterdir()], [f"{tid}.json"])

    def test_corrupt_file_is_reported_not_hidden(self):
        (self.dir / "cassee-0000.json").write_text("{ pas du json", encoding="utf-8")
        with self.assertRaises(store.TimelineStoreError):
            store.load_timeline("cassee-0000")


class TestListing(StoreTestCase):
    def test_sorted_by_last_update(self):
        with mock.patch.object(store, "_now", return_value="2026-09-01T00:00:00Z"):
            old, _ = store.create_timeline(title="Ancienne", data=FIXTURE)
        with mock.patch.object(store, "_now", return_value="2026-09-28T00:00:00Z"):
            new, _ = store.create_timeline(title="Récente", source={"kind": "project", "project_id": "CH1"})
        listing = store.list_timelines()
        self.assertEqual([item["id"] for item in listing], [new, old])
        self.assertEqual(listing[0], {
            "id": new, "title": "Récente", "source_kind": "project", "project_id": "CH1",
            "events": 0, "periods": 0, "updated_at": "2026-09-28T00:00:00Z",
        })
        self.assertEqual((listing[1]["events"], listing[1]["periods"]),
                         (len(FIXTURE["events"]), len(FIXTURE["periods"])))

    def test_broken_or_foreign_files_do_not_break_the_dashboard(self):
        store.create_timeline(title="Bonne")
        (self.dir / "cassee-0000.json").write_text("{", encoding="utf-8")
        (self.dir / "Mauvais Nom.json").write_text("{}", encoding="utf-8")
        (self.dir / "liste-0000.json").write_text("[]", encoding="utf-8")
        (self.dir / "retouchee-0000.json").write_text('{"source": {"kind": "web"}}', encoding="utf-8")
        self.assertEqual([item["title"] for item in store.list_timelines()], ["Bonne"])
        with self.assertRaises(store.TimelineStoreError):
            store.load_timeline("retouchee-0000")

    def test_missing_directory(self):
        shutil.rmtree(self.dir)
        self.assertEqual(store.list_timelines(), [])


class TestProjectsIgnoreTimelines(unittest.TestCase):
    """Le glob de list_projects() ne doit jamais voir une frise."""

    def test_directories_are_distinct(self):
        self.assertEqual(paths.TIMELINES_DIR, paths.DATA_DIR / "timelines")
        self.assertNotEqual(paths.TIMELINES_DIR.resolve(), paths.PROJECTS_DIR.resolve())
        self.assertNotIn(paths.PROJECTS_DIR.resolve(), paths.TIMELINES_DIR.resolve().parents)

    def test_list_projects_ignores_saved_timelines(self):
        tmp = Path(tempfile.mkdtemp(prefix="ankigen-data-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        projects, timelines = tmp / "projects", tmp / "timelines"
        with mock.patch.multiple(paths, PROJECTS_DIR=projects, TIMELINES_DIR=timelines,
                                 UPLOAD_DIR=tmp / "uploads", MEDIA_DIR=tmp / "media",
                                 EXPORT_DIR=tmp / "exports"):
            paths.ensure_dirs()
        self.assertTrue(timelines.is_dir())
        (projects / "cours.json").write_text(json.dumps({
            "version": 2, "deck_prefix": "", "source": "cours.docx", "assets": {},
            "prompts": [{"id": 1, "deck": "Cours", "blocks": [], "prompt": "x"}],
        }), encoding="utf-8")
        with mock.patch.object(store, "TIMELINES_DIR", timelines), \
                mock.patch.object(project_store, "PROJECTS_DIR", projects):
            store.create_timeline(title="Frise", data=FIXTURE)
            self.assertEqual([p["id"] for p in project_store.list_projects()], ["cours"])


if __name__ == "__main__":
    unittest.main()
