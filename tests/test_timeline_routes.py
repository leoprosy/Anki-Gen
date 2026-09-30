#!/usr/bin/env python3
"""
tests/test_timeline_routes.py — Routes Flask des frises (phase 3).

Création depuis un JSON ou un texte, page, lecture, validation à blanc,
enregistrement, rendu de l'aperçu, suppression. Les données vivent dans un
dossier jetable ; aucune route ne doit laisser un identifiant malicieux
atteindre le disque.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from markupsafe import escape  # l'échappement de Jinja

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as web  # noqa: E402
import settings  # noqa: E402
import timeline_schema  # noqa: E402
import timeline_store  # noqa: E402

FIXTURE = (ROOT / "tests" / "fixtures_timeline" / "mondialisation.json").read_text(encoding="utf-8")


class RoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-timeline-routes-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "timelines").mkdir()
        for target, name, value in ((timeline_store, "TIMELINES_DIR", self.tmp / "timelines"),
                                    (settings, "SETTINGS_FILE", self.tmp / "settings.json")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        settings.save_settings({"language": "fr", "analytics_decided": True})
        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

    def create_from_json(self, raw=FIXTURE, **extra):
        return self.client.post("/timeline/new", json=dict({"json": raw}, **extra))

    def created_id(self):
        response = self.create_from_json()
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["id"]


class TestCreation(RoutesTestCase):
    def test_from_valid_json(self):
        body = self.create_from_json().get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["url"], f"/timeline/{body['id']}")
        record = timeline_store.load_timeline(body["id"])
        self.assertEqual(record["data"]["title"], "La dynamique de la mondialisation économique")
        self.assertEqual(record["source"]["kind"], "import")

    def test_invalid_json_is_refused_with_its_report(self):
        response = self.create_from_json('{"schema": "ankigen.timeline/1", "title": "x", "events": [{"id": "e", '
                                         '"date": "vers 1450", "label": "x"}]}')
        self.assertEqual(response.status_code, 422)
        error = response.get_json()["report"]["errors"][0]
        self.assertEqual(error["path"], "/events/0/date")
        self.assertEqual(error["message"], "« vers 1450 » n'est pas une date.")
        self.assertEqual(list(self.tmp.joinpath("timelines").glob("*.json")), [])

    def test_force_keeps_the_paste_for_correction(self):
        body = self.create_from_json("pas du JSON du tout", force=True).get_json()
        record = timeline_store.load_timeline(body["id"])
        self.assertIsNone(record["data"])
        self.assertEqual(record["raw_responses"], ["pas du JSON du tout"])

    def test_from_text(self):
        body = self.client.post("/timeline/new", json={"text": "En 1860, le traité…", "title": "Commerce",
                                                        "lang": "fr"}).get_json()
        record = timeline_store.load_timeline(body["id"])
        self.assertEqual((record["title"], record["lang"], record["source"]["kind"]), ("Commerce", "fr", "text"))
        self.assertEqual(record["source_text"], "En 1860, le traité…")
        self.assertIsNone(record["data"])

    def test_text_needs_a_title(self):
        response = self.client.post("/timeline/new", json={"text": "x", "title": "  "})
        self.assertEqual(response.status_code, 400)

    def test_text_limit(self):
        response = self.client.post("/timeline/new", json={"text": "a" * (timeline_store.MAX_SOURCE_CHARS + 1),
                                                           "title": "x"})
        self.assertEqual(response.status_code, 400)

    def test_bad_request(self):
        self.assertEqual(self.client.post("/timeline/new", json={}).status_code, 400)


class TestPageAndReading(RoutesTestCase):
    def test_page_embeds_the_timeline_and_its_strings(self):
        tid = self.created_id()
        html = self.client.get(f"/timeline/{tid}").get_data(as_text=True)
        self.assertIn('id="tl-json"', html)
        self.assertIn("Inter-Regular.ttf", html)
        self.assertIn('"timeline.ui.save"', html)       # catalogue timeline. injecté pour window.T
        self.assertIn(tid, html)
        self.assertNotIn('"source_text"', html)          # le texte source reste sur le serveur

    def test_unknown_or_malicious_id_redirects_home(self):
        for tid in ("absent-0000", "CON", "a..b"):
            response = self.client.get(f"/timeline/{tid}")
            self.assertEqual(response.status_code, 302, tid)
        # Un « / » encodé ne passe même pas le routage : aucune route n'est atteinte.
        self.assertEqual(self.client.get("/timeline/..%2F..%2Fsettings").status_code, 404)

    def test_api_get(self):
        tid = self.created_id()
        body = self.client.get(f"/api/timeline/{tid}").get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["timeline"]["id"], tid)
        self.assertTrue(body["report"]["ok"])
        self.assertNotIn("source_text", body["timeline"])
        self.assertEqual(self.client.get("/api/timeline/absent-0000").status_code, 404)

    def test_dashboard_lists_timelines(self):
        tid = self.created_id()
        self.assertEqual([t["id"] for t in self.client.get("/api/timelines").get_json()["timelines"]], [tid])
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn(f"/timeline/{tid}", html)

    def test_dashboard_survives_a_broken_store(self):
        with mock.patch.object(timeline_store, "list_timelines", side_effect=RuntimeError("cassé")), \
                self.assertLogs(web.app.logger, level="ERROR"):
            self.assertEqual(self.client.get("/").status_code, 200)


class TestValidationAndSaving(RoutesTestCase):
    def test_dry_run_validation_in_the_interface_language(self):
        body = self.client.post("/api/timeline/validate", json={"raw": "```json\n" + FIXTURE + "\n```"}).get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["normalizations"][0]["message"], "Clôtures de bloc de code retirées.")
        settings.save_settings({"language": "en"})
        body = self.client.post("/api/timeline/validate", json={"raw": "nope"}).get_json()
        self.assertEqual(body["errors"][0]["message"], "No JSON object found in the text.")

    def test_save_edited_data(self):
        tid = self.created_id()
        data = json.loads(FIXTURE)
        data["title"] = "Titre modifié"
        body = self.client.post(f"/api/timeline/{tid}", json={"data": data}).get_json()
        self.assertTrue(body["ok"])
        record = timeline_store.load_timeline(tid)
        self.assertEqual((record["data"]["title"], record["title"]), ("Titre modifié", "Titre modifié"))

    def test_invalid_save_keeps_the_previous_document(self):
        tid = self.created_id()
        response = self.client.post(f"/api/timeline/{tid}", json={"raw": '{"schema": "x"}'})
        self.assertEqual(response.status_code, 422)
        record = timeline_store.load_timeline(tid)
        self.assertEqual(record["data"]["title"], "La dynamique de la mondialisation économique")
        self.assertEqual(record["raw_responses"][-1], '{"schema": "x"}')     # gardé pour l'audit

    def test_render_options_are_sanitised_and_saved(self):
        tid = self.created_id()
        self.client.post(f"/api/timeline/{tid}", json={"data": json.loads(FIXTURE), "options": {
            "theme": "dark", "density": "compact", "width_mode": "fixed", "width_px": 999999, "evil": "<x>"}})
        self.assertEqual(timeline_store.load_timeline(tid)["render_options"],
                         {"theme": "dark", "density": "compact", "width_mode": "fixed", "width_px": 12000})

    def test_oversized_document(self):
        tid = self.created_id()
        data = json.loads(FIXTURE)
        data["events"][0]["description"] = "x" * (timeline_schema.MAX_DOCUMENT_BYTES + 10)
        response = self.client.post(f"/api/timeline/{tid}", json={"data": data})
        self.assertEqual(response.get_json()["report"]["errors"][0]["code"], "too_large")


class TestRender(RoutesTestCase):
    def test_render_the_saved_document(self):
        tid = self.created_id()
        body = self.client.post(f"/api/timeline/{tid}/render", json={"options": {"theme": "dark"}}).get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["svg"].startswith("<svg"))
        self.assertIn('fill="#1C1C1E"', body["svg"])
        self.assertEqual(body["dates"]["cobden_chevalier"], "23 janvier 1860")
        self.assertEqual(body["dates"]["bretton_woods"], "juillet 1944–15 août 1971")
        self.assertIn("iterations", body["stats"])

    def test_render_unsaved_edits_without_saving_them(self):
        tid = self.created_id()
        data = json.loads(FIXTURE)
        data["title"] = "Brouillon"
        body = self.client.post(f"/api/timeline/{tid}/render", json={"data": data}).get_json()
        self.assertIn("Brouillon", body["svg"])
        self.assertNotEqual(timeline_store.load_timeline(tid)["data"]["title"], "Brouillon")

    def test_invalid_edits_return_the_report(self):
        tid = self.created_id()
        data = json.loads(FIXTURE)
        data["events"][0]["date"] = "1846-13"
        response = self.client.post(f"/api/timeline/{tid}/render", json={"data": data})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["report"]["errors"][0]["path"], "/events/0/date")

    def test_nothing_to_draw(self):
        body = self.client.post("/timeline/new", json={"text": "x", "title": "Vide"}).get_json()
        self.assertEqual(self.client.post(f"/api/timeline/{body['id']}/render", json={}).status_code, 404)

    def test_layout_warnings_carry_messages(self):
        tid = self.created_id()
        data = json.loads(FIXTURE)
        data["events"][0]["label"] = "Abrogation 漢字"
        body = self.client.post(f"/api/timeline/{tid}/render", json={"data": data}).get_json()
        warning = next(w for w in body["warnings"] if w["code"] == "label_unsupported_chars")
        self.assertIn("漢 字", warning["message"])


class TestDateHelper(RoutesTestCase):
    def test_formats_in_the_requested_language(self):
        body = self.client.get("/api/timeline/date?value=1971-08-15&lang=fr").get_json()
        self.assertEqual(body, {"ok": True, "text": "15 août 1971"})
        body = self.client.get("/api/timeline/date?value=-1750&lang=en&approx=1").get_json()
        self.assertEqual(body["text"], "c. 1750 BC")

    def test_reports_the_error(self):
        body = self.client.get("/api/timeline/date?value=vers+1450").get_json()
        self.assertEqual(body, {"ok": False, "message": "« vers 1450 » n'est pas une date."})

    def test_present_only_as_an_end(self):
        self.assertFalse(self.client.get("/api/timeline/date?value=present").get_json()["ok"])
        self.assertTrue(self.client.get("/api/timeline/date?value=present&end=1").get_json()["ok"])


class TestDeletion(RoutesTestCase):
    def test_delete(self):
        tid = self.created_id()
        response = self.client.post(f"/timeline/{tid}/delete")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(timeline_store.load_timeline(tid))

    def test_delete_refuses_a_malicious_id(self):
        self.assertEqual(self.client.post("/timeline/..%5Csettings/delete").status_code, 404)
        self.assertTrue((self.tmp / "settings.json").exists())


class TestHelpPage(RoutesTestCase):
    def test_timeline_section_in_each_language(self):
        import timeline_prompt
        for lang, title in (("fr", "Frises chronologiques"), ("en", "Timelines")):
            with self.subTest(lang=lang):
                settings.save_settings({"language": lang, "analytics_decided": True})
                page = self.client.get("/help").get_data(as_text=True)
                self.assertIn('id="timelines"', page)
                self.assertIn(title, page)
                self.assertIn("schemas/timeline-v1.json", page)
                # Le Skill affiché est celui que sert /timeline/skill.md, dans la langue de l'interface.
                self.assertIn(str(escape(timeline_prompt.skill_text(lang).splitlines()[2])), page)
                self.assertNotIn("help.timelines_", page)          # aucune clé brute


if __name__ == "__main__":
    unittest.main()
