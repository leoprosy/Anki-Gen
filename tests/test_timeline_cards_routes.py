#!/usr/bin/env python3
"""
tests/test_timeline_cards_routes.py — Cartes d'une frise dans l'app (phase 6).

Aperçu et réglages (types, deck figé, interrupteur par carte), images rendues à
la demande, exports TSV et ZIP, copie dans collection.media (même contrôle que
pour le projet), et la case « Inclure les cartes des frises liées » de l'export
du projet, désactivée par défaut.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import csv
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as web  # noqa: E402
import paths  # noqa: E402
import project_store  # noqa: E402
import settings  # noqa: E402
import timeline_store  # noqa: E402
from build_anki_csv import ANKI_HEADER_LINES  # noqa: E402
from test_timeline_routes import FIXTURE, RoutesTestCase  # noqa: E402

PROJECT_ID = "CH1 Mondialisation"


def tsv_rows(data):
    lines = data.decode("utf-8").splitlines()
    return lines[:len(ANKI_HEADER_LINES)], list(csv.reader(io.StringIO("\n".join(lines[len(ANKI_HEADER_LINES):])),
                                                         delimiter="\t"))


class CardsTestCase(RoutesTestCase):
    def setUp(self):
        super().setUp()
        for name in ("media", "projects", "exports", "anki"):
            (self.tmp / name).mkdir()
        for target, attribute, value in ((paths, "MEDIA_DIR", self.tmp / "media"),
                                         (web, "MEDIA_DIR", self.tmp / "media"),
                                         (project_store, "PROJECTS_DIR", self.tmp / "projects")):
            patcher = mock.patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(paths, "anki_media_dirs",
                                    return_value=[{"profile": "Test", "path": str(self.tmp / "anki"), "files": 0}])
        patcher.start()
        self.addCleanup(patcher.stop)
        settings.save_settings({"download_dir": str(self.tmp / "exports")})
        self.tid = self.created_id()

    def cards(self, **body):
        response = self.client.post(f"/api/timeline/{self.tid}/cards", json=body)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()


class TestPreview(CardsTestCase):
    def test_default_types_and_frozen_deck(self):
        body = self.cards()
        self.assertEqual(body["types"], ["event_to_date", "date_to_event", "period_bounds"])
        self.assertEqual(body["deck"], "La dynamique de la mondialisation économique::Chronologie")
        self.assertEqual(body["enabled"], len(body["cards"]))
        self.assertGreater(body["counts"]["event_to_date"], 20)
        # Figé dans la frise : il ne suit plus le titre ni la langue de l'interface.
        self.assertEqual(timeline_store.load_timeline(self.tid)["cards_deck"], body["deck"])
        settings.save_settings({"language": "en"})
        self.assertEqual(self.cards()["deck"], body["deck"])

    def test_types_deck_and_toggle_are_saved(self):
        body = self.cards(types=["ordering", "bogus"], deck="  ESH ::  Chronologie  ")
        self.assertEqual(body["types"], ["ordering"])
        self.assertEqual(body["deck"], "ESH::Chronologie")
        target = body["cards"][0]["id"]
        body = self.cards(toggle={"id": target, "enabled": False})
        self.assertFalse(next(c for c in body["cards"] if c["id"] == target)["enabled"])
        self.assertEqual(body["enabled"], len(body["cards"]) - 1)
        record = timeline_store.load_timeline(self.tid)
        self.assertEqual(record["card_options"], {"types": ["ordering"]})
        self.assertEqual(record["disabled_cards"], [target])
        self.assertTrue(next(c for c in self.cards(toggle={"id": target, "enabled": True})["cards"]
                             if c["id"] == target)["enabled"])

    def test_images_are_rendered_on_demand(self):
        body = self.cards(types=["masked_image"])
        card = body["cards"][0]
        url = card["front"].split('src="')[1].split('"')[0]
        self.assertTrue(url.startswith(f"/media/timeline/{self.tid}/ag_tl_"))
        name = url.rsplit("/", 1)[1]
        self.assertFalse((paths.timeline_media_dir(self.tid) / name).exists())
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        response.close()
        self.assertTrue((paths.timeline_media_dir(self.tid) / name).is_file())
        self.assertEqual(self.client.get(f"/media/timeline/{self.tid}/inconnu.png").status_code, 404)
        self.assertEqual(self.client.get(f"/media/timeline/{self.tid}/..%5Cx.png").status_code, 404)
        self.assertEqual(self.client.get("/media/timeline/absent-0000/x.png").status_code, 404)

    def test_empty_timeline_has_no_cards(self):
        empty = self.client.post("/timeline/new", json={"text": "x", "title": "Vide"}).get_json()["id"]
        body = self.client.post(f"/api/timeline/{empty}/cards", json={}).get_json()
        self.assertEqual((body["has_data"], body["cards"]), (False, []))
        self.assertEqual(self.client.get(f"/export/timeline/{empty}/cards.tsv").status_code, 404)

    def test_the_page_has_the_cards_tab(self):
        html = self.client.get(f"/timeline/{self.tid}").get_data(as_text=True)
        self.assertIn('id="tl-panel-cards"', html)
        self.assertIn("timeline-cards.js", html)


class TestExports(CardsTestCase):
    def test_tsv_holds_the_enabled_cards(self):
        body = self.cards()
        off = body["cards"][0]["id"]
        self.cards(toggle={"id": off, "enabled": False})
        response = self.client.get(f"/export/timeline/{self.tid}/cards.tsv")
        self.assertEqual(response.status_code, 200)
        header, rows = tsv_rows(response.data)
        self.assertEqual(header, ANKI_HEADER_LINES)
        self.assertEqual(len(rows), len(body["cards"]) - 1)
        self.assertTrue(all(len(row) == 3 and row[0] == body["deck"] for row in rows))
        self.assertNotIn(body["cards"][0]["front"], [row[1] for row in rows])
        filename = "la-dynamique-de-la-mondialisation-economique-cards.tsv"
        self.assertIn(filename, response.headers["Content-Disposition"])
        self.assertTrue((self.tmp / "exports" / filename).is_file())

    def test_zip_holds_the_tsv_the_images_and_a_readme(self):
        self.cards(types=["event_to_date", "whole_image", "masked_image"])
        response = self.client.get(f"/export/timeline/{self.tid}/cards.zip")
        self.assertEqual(response.status_code, 200)
        archive = zipfile.ZipFile(io.BytesIO(response.data))
        names = archive.namelist()
        tsv = next(n for n in names if n.endswith(".tsv"))
        media = [n for n in names if n.startswith("media/")]
        _, rows = tsv_rows(archive.read(tsv))
        referenced = {part.split('"')[0] for row in rows for part in (row[1] + row[2]).split('<img src="')[1:]}
        self.assertEqual({n[len("media/"):] for n in media}, referenced)
        self.assertTrue(referenced)
        self.assertIn(web.tr("export.readme_filename"), names)

    def test_copy_to_anki_uses_the_same_allowed_list(self):
        self.cards(types=["whole_image"])
        refused = self.client.post(f"/api/timeline/{self.tid}/anki-media", json={"path": str(self.tmp)})
        self.assertEqual(refused.status_code, 400)
        body = self.client.post(f"/api/timeline/{self.tid}/anki-media", json={"path": str(self.tmp / "anki")}).get_json()
        self.assertEqual(len(body["result"]["copied"]), 1)
        self.assertTrue((self.tmp / "anki" / body["result"]["copied"][0]).is_file())
        again = self.client.post(f"/api/timeline/{self.tid}/anki-media", json={"path": str(self.tmp / "anki")}).get_json()
        self.assertEqual(len(again["result"]["identical"]), 1)

    def test_deleting_the_timeline_deletes_its_images(self):
        self.cards(types=["whole_image"])
        self.client.get(f"/export/timeline/{self.tid}/cards.zip")
        self.assertTrue(paths.timeline_media_dir(self.tid).is_dir())
        self.client.post(f"/timeline/{self.tid}/delete")
        self.assertFalse(paths.timeline_media_dir(self.tid).exists())


class TestProjectExport(CardsTestCase):
    """La case « Inclure les cartes des frises liées » : désactivée, rien ne change."""

    def setUp(self):
        super().setUp()
        project_store.save_project(PROJECT_ID, {
            "version": 2, "deck_prefix": "ESH", "source": "CH1.docx", "assets": {},
            "prompts": [{"id": 0, "deck": "ESH::CH1", "prompt": "En 1860…", "blocks": [], "assets": [],
                         "status": "done", "response": "Question\tRéponse"}],
        })
        record = timeline_store.load_timeline(self.tid)
        record["source"] = {"kind": "project", "project_id": PROJECT_ID, "deck_path": "ESH::CH1"}
        record["card_options"] = {"types": ["event_to_date", "whole_image"]}
        timeline_store.save_timeline(self.tid, record)

    def test_off_by_default(self):
        _, rows = tsv_rows(self.client.get(f"/export.tsv/{PROJECT_ID}").data)
        self.assertEqual(rows, [["ESH::CH1", "Question", "Réponse"]])
        report = self.client.get(f"/api/export/report/{PROJECT_ID}").get_json()
        self.assertEqual((report["cards"], report["media"]), (1, []))

    def test_included_on_request(self):
        _, rows = tsv_rows(self.client.get(f"/export.tsv/{PROJECT_ID}?timelines=1").data)
        self.assertEqual(rows[0], ["ESH::CH1", "Question", "Réponse"])
        self.assertTrue(all(row[0] == "ESH::CH1::Chronologie" for row in rows[1:]))
        self.assertGreater(len(rows), 20)
        report = self.client.get(f"/api/export/report/{PROJECT_ID}?timelines=1").get_json()
        self.assertEqual(report["cards"], len(rows))
        self.assertEqual(len(report["media"]), 1)
        archive = zipfile.ZipFile(io.BytesIO(self.client.get(f"/export.zip/{PROJECT_ID}?timelines=1").data))
        self.assertEqual(len([n for n in archive.namelist() if n.startswith("media/")]), 1)
        body = self.client.post(f"/api/export/anki-media/{PROJECT_ID}",
                                json={"path": str(self.tmp / "anki"), "timelines": True}).get_json()
        self.assertEqual(len(body["result"]["copied"]), 1)

    def test_the_work_view_offers_the_option(self):
        html = self.client.get(f"/work/{PROJECT_ID}").get_data(as_text=True)
        self.assertIn('id="export-timelines"', html)
        self.assertIn("(1)", html)


if __name__ == "__main__":
    unittest.main()
