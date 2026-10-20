#!/usr/bin/env python3
"""
tests/test_local_llm.py — Le modèle local : téléchargement vérifié et routes.

Aucun vrai modèle n'est chargé : `complete` est remplacé dans les tests de
route. Le téléchargement passe par une URL file://, sans réseau.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import hashlib
import json
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

    def test_missing_model_is_explained(self):
        response = self.client.post("/api/local-model/timeline", json={"prompt": "Extrais."})
        self.assertEqual(response.status_code, 409)
        self.assertIn("Réglages", response.get_json()["error"])

    def test_empty_prompt_is_refused(self):
        response = self.client.post("/api/local-model/timeline", json={"prompt": " "})
        self.assertEqual(response.status_code, 400)

    def test_too_long_prompt_names_its_size(self):
        with mock.patch.object(local_llm, "complete", side_effect=local_llm.PromptTooLong(9000)):
            response = self.client.post("/api/local-model/timeline", json={"prompt": "x"})
        self.assertEqual(response.status_code, 413)
        self.assertIn("9000", response.get_json()["error"])

    def test_answer_comes_back_raw_with_the_timeline_schema(self):
        with mock.patch.object(local_llm, "complete", return_value=EMPTY) as complete:
            body = self.client.post("/api/local-model/timeline",
                                    json={"prompt": "Extrais.", "lang": "fr", "chunk": True}).get_json()
        self.assertEqual(body, {"ok": True, "raw": EMPTY})
        messages, schema = complete.call_args.args
        self.assertEqual(messages, [{"role": "user", "content": "Extrais."}])
        self.assertIn("events", schema["properties"])

    def test_delete_without_model_is_harmless(self):
        body = self.client.delete("/api/local-model").get_json()
        self.assertFalse(body["installed"])


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


if __name__ == "__main__":
    unittest.main()
