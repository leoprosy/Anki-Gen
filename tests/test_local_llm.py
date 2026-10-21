#!/usr/bin/env python3
"""
tests/test_local_llm.py — Le modèle local : téléchargement vérifié et routes.

Aucun vrai modèle n'est chargé : `complete` est remplacé dans les tests de
route. Le téléchargement passe par une URL file://, sans réseau.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import hashlib
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import local_llm  # noqa: E402
import paths  # noqa: E402
import timeline_extract  # noqa: E402
import timeline_schema  # noqa: E402
from test_timeline_extraction_routes import COBDEN, MELINE, PROJECT, ExtractionTestCase, doc  # noqa: E402
from test_timeline_routes import RoutesTestCase  # noqa: E402


def timeline(events):
    return json.dumps({"schema": "ankigen.timeline/1", "title": "Partie", "lang": "fr",
                       "tracks": [{"id": "commerce", "label": "Commerce"}], "events": events})


EVENT = {"id": "cobden", "track": "commerce", "date": "1860", "label": "Traité Cobden-Chevalier"}
VALID = timeline([EVENT])
BAD_DATE = timeline([dict(EVENT, date="1860-17-95")])
EMPTY = json.dumps({"schema": "ankigen.timeline/1", "title": "x", "tracks": [], "events": []})


class TestDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ankigen-llm-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.source = self.tmp / "source.gguf"
        self.source.write_bytes(b"GGUF" * 1000)
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.dest = self.tmp / "models" / "model.gguf"

    def test_verified_file_lands_in_place(self):
        seen = []
        local_llm.download_to(self.source.as_uri(), self.dest, self.sha, seen.append, chunk=1024)
        self.assertEqual(self.dest.read_bytes(), self.source.read_bytes())
        self.assertEqual(seen[-1], 4000)
        self.assertEqual(list(self.dest.parent.iterdir()), [self.dest])

    def test_checksum_mismatch_leaves_nothing(self):
        with self.assertRaises(ValueError):
            local_llm.download_to(self.source.as_uri(), self.dest, "0" * 64)
        self.assertEqual(list(self.dest.parent.iterdir()), [])


class TestRoutes(RoutesTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(paths, "MODELS_DIR", self.tmp / "models")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status(self):
        body = self.client.get("/api/local-model").get_json()
        self.assertFalse(body["installed"])
        self.assertFalse(body["downloading"])
        self.assertEqual(body["size"], local_llm.MODEL["size"])

    def test_progress_of_the_running_generation(self):
        self.assertIsNone(self.client.get("/api/local-model").get_json()["progress"])
        with mock.patch.dict(local_llm._progress, stage="writing", attempt=2, tokens=3, written=['{"a', '":', ' 1'],
                             part=2, parts=3,
                             writing_since=local_llm.time.monotonic() - 1):
            progress = self.client.get("/api/local-model").get_json()["progress"]
        self.assertEqual((progress["stage"], progress["attempt"], progress["part"], progress["parts"], progress["text"]),
                         ("writing", 2, 2, 3, '{"a": 1'))
        self.assertLess(progress["speed"], 3.1)

    def test_delete_without_model_is_harmless(self):
        body = self.client.delete("/api/local-model").get_json()
        self.assertFalse(body["installed"])


class TestLocalRoute(ExtractionTestCase):
    """La frise passe par le modèle local ; un texte trop long pour sa fenêtre est coupé."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(paths, "MODELS_DIR", self.tmp / "models")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tid = self.created({"kind": "project"}, title="Mondialisation")

    def local(self, **payload):
        return self.client.post(f"/api/timeline/{self.tid}/local", json=payload)

    def test_missing_model_is_explained(self):
        response = self.local()
        self.assertEqual(response.status_code, 409)
        self.assertIn("Réglages", response.get_json()["error"])

    def test_a_paragraph_comes_back_raw_with_the_local_schema(self):
        with mock.patch.object(local_llm, "complete", return_value=EMPTY) as complete:
            body = self.local(chunk_id=1).get_json()
        self.assertEqual(body, {"ok": True, "raw": EMPTY, "parts": 1, "failed": 0})
        (messages, schema), = [call.args for call in complete.call_args_list]
        self.assertIn("Cobden-Chevalier", messages[0]["content"])
        self.assertNotIn("Méline", messages[0]["content"])
        self.assertNotIn("description", schema["properties"]["events"]["items"]["properties"])

    def test_a_text_too_long_is_cut_into_its_paragraphs_and_merged(self):
        prompts = []

        def complete(messages, schema):
            prompt = messages[0]["content"]
            prompts.append(prompt)
            if "Cobden" in prompt and "Méline" in prompt:
                raise local_llm.PromptTooLong(9000)
            return doc([COBDEN]) if "Cobden" in prompt else doc([MELINE]) if "Méline" in prompt else EMPTY
        with mock.patch.object(local_llm, "complete", side_effect=complete):
            body = self.local().get_json()
        self.assertTrue(body["ok"])
        # La frise entière, refusée, puis un prompt par paragraphe du cours.
        paragraphs = len(PROJECT["prompts"])
        self.assertEqual((body["parts"], len(prompts)), (paragraphs, paragraphs + 1))
        self.assertIn("Adam Smith", prompts[-1])
        self.assertNotIn("Méline", prompts[-1])
        self.assertEqual(body["failed"], 0)
        merged = json.loads(body["raw"])
        self.assertEqual([e["label"] for e in merged["events"]], [COBDEN["label"], MELINE["label"]])
        self.assertTrue(self.client.post(f"/api/timeline/{self.tid}", json={"raw": body["raw"]}).get_json()["ok"])
        self.assertIsNone(local_llm.progress())

    def test_an_unbreakable_passage_names_its_size(self):
        with mock.patch.object(local_llm, "complete", side_effect=local_llm.PromptTooLong(9000)):
            response = self.local()
        self.assertEqual(response.status_code, 413)
        self.assertIn("9000", response.get_json()["error"])


class TestDedupeIds(unittest.TestCase):
    def test_repeats_are_dropped_and_reused_ids_renamed(self):
        meline = dict(MELINE, id="cobden")
        raw = doc([COBDEN, dict(COBDEN), meline])
        cleaned = json.loads(timeline_extract.dedupe_ids(raw))
        self.assertEqual([(e["id"], e["label"]) for e in cleaned["events"]],
                         [("cobden", COBDEN["label"]), ("cobden-2", MELINE["label"])])
        self.assertTrue(timeline_schema.validate_raw(json.dumps(cleaned), default_lang="fr")["ok"])

    def test_clean_or_unreadable_answers_are_untouched(self):
        for raw in (doc([COBDEN, MELINE]), '{"events": [', "[]"):
            self.assertEqual(timeline_extract.dedupe_ids(raw), raw)


class TestSplitText(unittest.TestCase):
    def test_cuts_before_the_heading_nearest_the_middle(self):
        text = "## A\n\nUn. Deux.\n\n## B\n\nTrois.\n\n## C\n\nQuatre."
        self.assertEqual(timeline_extract.split_text(text), ["## A\n\nUn. Deux.", "## B\n\nTrois.\n\n## C\n\nQuatre."])

    def test_a_single_paragraph_is_cut_between_sentences(self):
        self.assertEqual(timeline_extract.split_text("En 1860, un traité. En 1892, un tarif."),
                         ["En 1860, un traité.", "En 1892, un tarif."])

    def test_a_single_word_cannot_be_cut(self):
        self.assertIsNone(timeline_extract.split_text("Cobden"))


class TestLocalExtractor(unittest.TestCase):
    """La boucle de correction, avec un faux modèle qui répond dans l'ordre."""

    def run_with(self, answers, chunk=False):
        calls = []

        def complete(messages, schema):
            calls.append([dict(m) for m in messages])
            answer = answers[len(calls) - 1]
            if isinstance(answer, Exception):
                raise answer
            return answer
        raw = timeline_extract.LocalExtractor(complete).run("Extrais.", lang="fr", chunk=chunk)
        return raw, calls

    def test_valid_answer_is_not_corrected(self):
        raw, calls = self.run_with([VALID])
        self.assertEqual((raw, len(calls)), (VALID, 1))

    def test_empty_paragraph_is_a_valid_answer(self):
        raw, calls = self.run_with([EMPTY], chunk=True)
        self.assertEqual(len(calls), 1)

    def test_refused_answer_is_replayed_with_the_correction(self):
        raw, calls = self.run_with([BAD_DATE, VALID])
        self.assertEqual(raw, VALID)
        self.assertEqual([m["role"] for m in calls[1]], ["user", "assistant", "user"])
        self.assertEqual(calls[1][1]["content"], BAD_DATE)
        self.assertIn("/events/0/date", calls[1][2]["content"])

    def test_gives_up_after_two_corrections_with_the_last_answer(self):
        raw, calls = self.run_with([BAD_DATE, BAD_DATE, "{}"])
        self.assertEqual((raw, len(calls)), ("{}", 3))

    def test_failed_correction_keeps_the_previous_answer(self):
        raw, calls = self.run_with([BAD_DATE, RuntimeError("trop long")])
        self.assertEqual(raw, BAD_DATE)

    def test_failed_first_attempt_is_raised(self):
        with self.assertRaises(RuntimeError):
            self.run_with([RuntimeError("modèle illisible")])


class TestPickGpu(unittest.TestCase):
    """Le choix de la carte : une carte dédiée assez grande, sinon le processeur."""

    def dev(self, name, discrete=True, gib=12):
        return {"name": name, "discrete": discrete, "vram": gib << 30}

    def test_discrete_card_is_chosen_over_the_integrated_one(self):
        devices = [self.dev("AMD Radeon(TM) Graphics", discrete=False, gib=16), self.dev("RTX 4070")]
        self.assertEqual(local_llm.pick_gpu(devices), 1)

    def test_direct3d12_twin_is_ignored(self):
        devices = [self.dev("RTX 4070"), self.dev("Microsoft Direct3D12 (RTX 4070)")]
        self.assertEqual(local_llm.pick_gpu(devices), 0)
        self.assertIsNone(local_llm.pick_gpu(devices[1:]))

    def test_integrated_or_small_cards_fall_back_to_the_cpu(self):
        self.assertIsNone(local_llm.pick_gpu([self.dev("Radeon 780M", discrete=False, gib=16)]))
        self.assertIsNone(local_llm.pick_gpu([self.dev("GTX 1050", gib=4)]))
        self.assertIsNone(local_llm.pick_gpu([]))

    def test_largest_card_wins(self):
        self.assertEqual(local_llm.pick_gpu([self.dev("RTX 3060", gib=8), self.dev("RTX 4090", gib=24)]), 1)


@unittest.skipUnless(local_llm.available() and local_llm.model_path().is_file(), "modèle local absent")
class TestGrammarFirstSampler(unittest.TestCase):
    """Vérifier d'abord le jeton glouton donne la même réponse que filtrer tout le vocabulaire."""

    def test_same_answer_as_full_filtering(self):
        from llama_cpp import Llama
        llm = Llama(str(local_llm.model_path()), n_ctx=512, n_gpu_layers=0, verbose=False)
        default = llm._init_sampler
        schema = {"type": "object", "properties": {"year": {"type": "integer"}, "label": {"type": "string"}},
                  "required": ["year", "label"]}

        def answer():
            # Une question en prose : le premier jeton glouton (« La ») est refusé, le repli sert.
            out = llm.create_chat_completion(
                messages=[{"role": "user", "content": "En une phrase : quand la Bastille a-t-elle été prise ?"}],
                response_format={"type": "json_object", "schema": schema}, temperature=0, max_tokens=30)
            return out["choices"][0]["message"]["content"]
        expected = answer()
        local_llm._grammar_first(llm)
        self.assertIsNot(llm._init_sampler, default)
        self.assertEqual(answer(), expected)


class TestLocalSchema(unittest.TestCase):
    """La grammaire locale, plus serrée que le contrat, ne produit que des documents du contrat."""

    def setUp(self):
        self.schema = timeline_extract.local_schema()
        self.events = self.schema["properties"]["events"]["items"]

    def test_impossible_dates_cannot_be_written(self):
        pattern = re.compile(self.events["properties"]["date"]["pattern"])
        for date in ("1789", "-44", "1971-08", "1971-08-15"):
            self.assertTrue(pattern.match(date), date)
        for date in ("1789-17", "0", "0789", "1971-00", "1971-08-32", "present"):
            self.assertFalse(pattern.match(date), date)

    def test_verbose_fields_are_dropped_and_quotes_required(self):
        self.assertNotIn("description", self.events["properties"])
        self.assertNotIn("tags", self.events["properties"])
        self.assertIn("source_quote", self.events["required"])
        self.assertIn("track", self.events["required"])
        self.assertEqual(self.schema["properties"]["eras"]["maxItems"], 1)

    def test_the_contract_schema_is_untouched(self):
        contract = timeline_schema.json_schema()["properties"]["events"]["items"]
        self.assertIn("description", contract["properties"])
        self.assertNotIn("source_quote", contract["required"])

    def test_a_document_of_the_local_shape_is_valid(self):
        doc = json.loads(VALID)
        doc.update(eras=[], periods=[])
        doc["events"][0]["source_quote"] = "traité de commerce"
        self.assertTrue(timeline_schema.validate_raw(json.dumps(doc), default_lang="fr")["ok"])


if __name__ == "__main__":
    unittest.main()
