#!/usr/bin/env python3
"""
tests/test_timeline_extraction_routes.py — Routes de l'extraction (phase 4).

Portées depuis la vue de travail, création avec instantané du texte source,
prompts d'extraction et de correction, collage paragraphe par paragraphe,
fusion (et son annulation), citations vérifiées. Projet et frises vivent dans
un dossier jetable.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import project_store  # noqa: E402
import timeline_prompt  # noqa: E402
import timeline_store  # noqa: E402
from test_timeline_routes import FIXTURE, RoutesTestCase  # noqa: E402

PROJECT_ID = "CH1 Mondialisation"
PREFIX = "ESH::CH1: La mondialisation(1)"


def chunk(i, deck, text):
    return {"id": i, "deck": deck, "prompt": text, "blocks": [{"type": "text", "text": text}],
            "assets": [], "status": "pending", "response": ""}


PROJECT = {
    "version": 2, "deck_prefix": "ESH", "source": "CH1_ La mondialisation.docx", "assets": {},
    "prompts": [
        chunk(0, "ESH", "CH1: La mondialisation"),
        chunk(1, f"{PREFIX}::I - Première mondialisation",
              "Le traité Cobden-Chevalier de 1860 ouvre l'ère du libre-échange en Europe."),
        chunk(2, f"{PREFIX}::I - Première mondialisation::A) Protectionnisme",
              "Le tarif Méline de 1892 marque le retour du protectionnisme en France."),
        chunk(3, f"{PREFIX}::II - Les théories", "Adam Smith défend le libre-échange."),
    ],
}


def doc(events, tracks=({"id": "commerce", "label": "Commerce"},)):
    return json.dumps({"schema": "ankigen.timeline/1", "title": "Partie", "lang": "fr",
                       "tracks": list(tracks), "events": events})


COBDEN = {"id": "cobden", "track": "commerce", "date": "1860", "label": "Traité Cobden-Chevalier",
          "source_quote": "Le traité Cobden-Chevalier de 1860 ouvre l'ère du libre-échange"}
MELINE = {"id": "meline", "track": "commerce", "date": "1892", "label": "Tarif Méline",
          "source_quote": "Le tarif Méline de 1892 marque le retour du protectionnisme"}
EMPTY = json.dumps({"schema": "ankigen.timeline/1", "title": "x", "tracks": [], "events": []})


class ExtractionTestCase(RoutesTestCase):
    def setUp(self):
        super().setUp()
        (self.tmp / "projects").mkdir()
        patcher = mock.patch.object(project_store, "PROJECTS_DIR", self.tmp / "projects")
        patcher.start()
        self.addCleanup(patcher.stop)
        project_store.save_project(PROJECT_ID, json.loads(json.dumps(PROJECT)))

    def create(self, scope, **extra):
        scope = dict({"project_id": PROJECT_ID}, **scope)
        return self.client.post("/timeline/new", json=dict({"scope": scope}, **extra))

    def created(self, scope, **extra):
        response = self.create(scope, **extra)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["id"]

    def per_chunk(self):
        return self.created({"kind": "chapter", "deck_path": f"{PREFIX}::I - Première mondialisation"},
                            strategy="per_chunk")


class TestScopes(ExtractionTestCase):
    def test_scopes_of_the_current_chunk(self):
        body = self.client.get(f"/api/timeline/scopes/{PROJECT_ID}?chunk_id=2").get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["threshold"], timeline_prompt.SINGLE_PROMPT_MAX_CHARS)
        self.assertEqual(body["chunk"]["chunk_ids"], [2])
        self.assertEqual([c["deck_path"] for c in body["chapters"]], [f"{PREFIX}::I - Première mondialisation"])
        self.assertEqual(body["chapters"][0]["chunk_ids"], [1, 2])
        self.assertEqual(body["chapters"][0]["title"], "Première mondialisation")
        self.assertEqual(body["project"]["chunks"], 4)
        self.assertEqual(body["project"]["strategy"], "single")
        self.assertGreater(body["project"]["tokens"], 0)

    def test_unknown_project(self):
        self.assertEqual(self.client.get("/api/timeline/scopes/absent").status_code, 404)

    def test_lists_the_timelines_of_the_course(self):
        tid = self.created({"kind": "project"})
        body = self.client.get(f"/api/timeline/scopes/{PROJECT_ID}").get_json()
        self.assertEqual([t["id"] for t in body["timelines"]], [tid])

    def test_the_work_view_offers_the_timeline_button(self):
        html = self.client.get(f"/work/{PROJECT_ID}").get_data(as_text=True)
        self.assertIn('id="tl-scope"', html)
        self.assertIn("timeline-scope.js", html)
        self.assertIn("Paragraphe par paragraphe", html)


class TestCreationFromScope(ExtractionTestCase):
    def test_the_source_text_is_frozen_with_its_spans(self):
        tid = self.created({"kind": "chapter", "deck_path": f"{PREFIX}::I - Première mondialisation"})
        record = timeline_store.load_timeline(tid)
        self.assertEqual(record["title"], "Première mondialisation")
        self.assertEqual(record["source"]["kind"], "chapter")
        self.assertEqual(record["source"]["chunk_ids"], [1, 2])
        self.assertEqual([span[0] for span in record["source"]["spans"]], [1, 2])
        self.assertIn("## CH1: La mondialisation(1) › I - Première mondialisation\n\nLe traité", record["source_text"])
        self.assertEqual(record["extraction"]["strategy"], "single")
        self.assertIsNone(record["data"])
        # Le projet peut changer ensuite : la frise garde son texte.
        project_store.delete_project(PROJECT_ID)
        body = self.client.get(f"/api/timeline/{tid}/prompt").get_json()
        self.assertIn("Le tarif Méline de 1892", body["prompt"])
        self.assertFalse(self.client.get(f"/api/timeline/{tid}").get_json()["timeline"]["project_exists"])

    def test_title_mode_strategy_and_language_are_kept(self):
        tid = self.created({"kind": "chunk", "chunk_ids": [2]}, title="Tarifs", mode="enriched", lang="en",
                           strategy="per_chunk")
        record = timeline_store.load_timeline(tid)
        self.assertEqual((record["title"], record["lang"]), ("Tarifs", "en"))
        self.assertEqual(record["extraction"]["mode"], "enriched")
        self.assertEqual(record["extraction"]["strategy"], "per_chunk")

    def test_long_scopes_default_to_paragraph_by_paragraph(self):
        with mock.patch.object(timeline_prompt, "SINGLE_PROMPT_MAX_CHARS", 100):
            tid = self.created({"kind": "project"})
        self.assertEqual(timeline_store.load_timeline(tid)["extraction"]["strategy"], "per_chunk")

    def test_refusals(self):
        self.assertEqual(self.client.post("/timeline/new", json={"scope": {"kind": "project",
                                                                           "project_id": "absent"}}).status_code, 404)
        self.assertEqual(self.create({"kind": "chapter", "deck_path": "ESH::Nulle part"}).status_code, 400)
        self.assertEqual(self.create({"kind": "galaxy"}).status_code, 400)
        self.assertEqual(self.create({"kind": "chunk", "chunk_ids": ["x"]}).status_code, 400)


class TestPrompts(ExtractionTestCase):
    def test_single_prompt(self):
        tid = self.created({"kind": "project"}, title="Mondialisation")
        body = self.client.get(f"/api/timeline/{tid}/prompt").get_json()
        self.assertTrue(body["ok"])
        self.assertIn("Titre de la frise : Mondialisation", body["prompt"])
        self.assertIn("## Mode strict", body["prompt"])
        self.assertIn("Adam Smith défend le libre-échange.", body["prompt"])
        self.assertNotIn("## Ce passage", body["prompt"])
        self.assertGreater(body["tokens"], 0)

    def test_mode_and_skill(self):
        tid = self.created({"kind": "project"})
        enriched = self.client.get(f"/api/timeline/{tid}/prompt?mode=enriched").get_json()["prompt"]
        self.assertIn("## Mode enrichi", enriched)
        skill = self.client.get(f"/api/timeline/{tid}/prompt?skill=1").get_json()["prompt"]
        self.assertNotIn("## Format du JSON", skill)
        # Les réglages enregistrés servent de défaut.
        self.client.post(f"/api/timeline/{tid}", json={"extraction": {"mode": "enriched", "skill": True}})
        record = timeline_store.load_timeline(tid)
        self.assertEqual((record["extraction"]["mode"], record["extraction"]["skill"]), ("enriched", True))
        self.assertIn("en mode enrichi", self.client.get(f"/api/timeline/{tid}/prompt").get_json()["prompt"])

    def test_chunk_prompt_reuses_the_tracks(self):
        tid = self.per_chunk()
        self.client.post(f"/api/timeline/{tid}", json={"raw": doc([COBDEN]), "chunk_id": 1})
        body = self.client.get(f"/api/timeline/{tid}/prompt?chunk_id=2").get_json()
        self.assertIn("Le tarif Méline", body["prompt"])
        self.assertNotIn("Cobden", body["prompt"].split("<<<SOURCE")[1])
        self.assertIn("## Ce passage", body["prompt"])
        self.assertIn('"commerce" (Commerce)', body["prompt"])
        self.assertEqual(self.client.get(f"/api/timeline/{tid}/prompt?chunk_id=3").status_code, 404)

    def test_no_prompt_without_source_text(self):
        tid = self.created_id()          # JSON importé
        self.assertEqual(self.client.get(f"/api/timeline/{tid}/prompt").status_code, 404)

    def test_skill_text(self):
        response = self.client.get("/timeline/skill.md?lang=en")
        self.assertEqual(response.mimetype, "text/markdown")
        self.assertTrue(response.get_data(as_text=True).startswith("---\nname: ankigen-timeline\n"))


class TestSinglePaste(ExtractionTestCase):
    def test_invalid_paste_then_correction_prompt(self):
        tid = self.created({"kind": "project"})
        raw = doc([dict(COBDEN, date="vers 1860"), dict(MELINE, lable="x")])
        response = self.client.post(f"/api/timeline/{tid}", json={"raw": raw})
        self.assertEqual(response.status_code, 422)
        body = self.client.get(f"/api/timeline/{tid}/correction-prompt").get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["errors"], 2)
        self.assertIn("Ton JSON contient les erreurs suivantes", body["prompt"])
        self.assertIn("/events/0/date", body["prompt"])
        self.assertIn("/events/1/lable", body["prompt"])

    def test_nothing_to_fix(self):
        tid = self.created({"kind": "project"})
        self.assertEqual(self.client.get(f"/api/timeline/{tid}/correction-prompt").status_code, 404)
        self.client.post(f"/api/timeline/{tid}", json={"raw": doc([COBDEN])})
        self.assertEqual(self.client.get(f"/api/timeline/{tid}/correction-prompt").status_code, 404)

    def test_quotes_are_checked_against_the_source(self):
        tid = self.created({"kind": "project"})
        invented = {"id": "versailles", "track": "commerce", "date": "1919", "label": "Traité de Versailles",
                    "source_quote": "Le traité de Versailles redessine l'Europe en 1919"}
        body = self.client.post(f"/api/timeline/{tid}", json={"raw": doc([COBDEN, invented])}).get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["report"]["quotes"], {"cobden": "verified", "versailles": "not_found"})
        warning = next(w for w in body["report"]["warnings"] if w["code"] == "quote_not_found")
        self.assertEqual(warning["path"], "/events/1/source_quote")
        self.assertEqual(warning["message"], "Citation introuvable dans le cours : cet élément n'en vient peut-être pas.")
        render = self.client.post(f"/api/timeline/{tid}/render", json={}).get_json()
        self.assertEqual(render["quotes"]["versailles"], "not_found")
        self.assertIn("Marqueur cerclé", render["svg"])
        report = self.client.get(f"/api/timeline/{tid}").get_json()["report"]
        self.assertIn("quote_not_found", [w["code"] for w in report["warnings"]])
        # Une correction peut reprendre les avertissements, sur demande.
        body = self.client.get(f"/api/timeline/{tid}/correction-prompt?warnings=1").get_json()
        self.assertIn("/events/1/source_quote", body["prompt"])


class TestPerChunk(ExtractionTestCase):
    def paste(self, tid, chunk_id, raw, **extra):
        return self.client.post(f"/api/timeline/{tid}", json=dict({"raw": raw, "chunk_id": chunk_id}, **extra))

    def test_view_lists_the_paragraphs(self):
        tid = self.per_chunk()
        chunks = self.client.get(f"/api/timeline/{tid}").get_json()["timeline"]["chunks"]
        self.assertEqual([(c["id"], c["status"], c["mentions"]) for c in chunks], [(1, "pending", 1), (2, "pending", 1)])
        self.assertEqual(chunks[1]["title"], "A) Protectionnisme")

    def test_paragraphs_merge_into_the_timeline(self):
        tid = self.per_chunk()
        body = self.paste(tid, 1, doc([COBDEN])).get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["chunk"], {"id": 1, "status": "ok"})
        self.assertTrue(body["merged"])
        self.assertEqual([e["id"] for e in body["data"]["events"]], ["c1_cobden"])
        body = self.paste(tid, 2, doc([MELINE])).get_json()
        self.assertEqual([e["id"] for e in body["data"]["events"]], ["c1_cobden", "c2_meline"])
        self.assertEqual(body["data"]["title"], "Première mondialisation")
        self.assertEqual(body["merge"]["elements"], 2)
        self.assertEqual(body["merge"]["tracks"][0]["chunks"], [1, 2])
        self.assertEqual([c["status"] for c in body["chunks"]], ["ok", "ok"])
        record = timeline_store.load_timeline(tid)
        self.assertEqual(len(record["data"]["events"]), 2)
        self.assertEqual(record["extraction"]["per_chunk"]["2"]["status"], "ok")

    def test_a_paragraph_without_date_is_not_an_error(self):
        tid = self.per_chunk()
        self.paste(tid, 1, doc([COBDEN]))
        body = self.paste(tid, 2, EMPTY).get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["chunk"]["status"], "empty")
        self.assertEqual(len(body["data"]["events"]), 1)

    def test_an_invalid_paragraph_keeps_the_timeline_and_gets_a_correction(self):
        tid = self.per_chunk()
        self.paste(tid, 1, doc([COBDEN]))
        response = self.paste(tid, 2, doc([dict(MELINE, date="1892-13")]))
        self.assertEqual(response.status_code, 422)
        body = response.get_json()
        self.assertEqual(body["chunk"]["status"], "error")
        self.assertFalse(body["merged"])
        self.assertEqual(len(body["data"]["events"]), 1)
        correction = self.client.get(f"/api/timeline/{tid}/correction-prompt?chunk_id=2").get_json()
        self.assertIn("/events/0/date", correction["prompt"])
        self.assertEqual(self.paste(tid, 9, EMPTY).status_code, 404)

    def test_edits_are_not_overwritten_without_consent(self):
        tid = self.per_chunk()
        data = self.paste(tid, 1, doc([COBDEN])).get_json()["data"]
        data["events"][0]["label"] = "Traité de 1860 retouché"
        self.client.post(f"/api/timeline/{tid}", json={"data": data})
        body = self.paste(tid, 2, doc([MELINE])).get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["edited"])
        self.assertFalse(body["merged"])
        self.assertEqual(timeline_store.load_timeline(tid)["extraction"]["per_chunk"]["2"]["status"], "ok")
        self.assertEqual(self.client.post(f"/api/timeline/{tid}/merge", json={}).status_code, 409)
        body = self.client.post(f"/api/timeline/{tid}/merge", json={"force": True}).get_json()
        self.assertTrue(body["merged"])
        self.assertEqual([e["label"] for e in body["data"]["events"]], ["Traité Cobden-Chevalier", "Tarif Méline"])

    def test_undo_and_redo_a_duplicate_merge(self):
        tid = self.per_chunk()
        self.paste(tid, 1, doc([COBDEN]))
        body = self.paste(tid, 2, doc([dict(COBDEN, id="traite")])).get_json()
        duplicate = body["merge"]["duplicates"][0]
        self.assertEqual(duplicate["ids"], ["c1_cobden", "c2_traite"])
        self.assertEqual(len(body["data"]["events"]), 1)
        body = self.client.post(f"/api/timeline/{tid}/merge", json={"separate": duplicate["key"]}).get_json()
        self.assertEqual(len(body["data"]["events"]), 2)
        self.assertTrue(body["merge"]["duplicates"][0]["separated"])
        body = self.client.post(f"/api/timeline/{tid}/merge", json={"join": duplicate["key"]}).get_json()
        self.assertEqual(len(body["data"]["events"]), 1)

    def test_the_page_opens_on_the_prompt(self):
        tid = self.per_chunk()
        html = self.client.get(f"/timeline/{tid}").get_data(as_text=True)
        self.assertIn('id="tl-panel-prompt"', html)
        self.assertIn('id="tl-dock-counter"', html)
        self.assertIn("Copier le prompt", html)


if __name__ == "__main__":
    unittest.main()
