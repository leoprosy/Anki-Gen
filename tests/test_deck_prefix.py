#!/usr/bin/env python3
"""
tests/test_deck_prefix.py — Chemins de deck avec et sans préfixe.

Le préfixe par défaut est vide depuis l'ouverture au public : un segment vide
joint naïvement produirait « ::Chapitre », que Anki refuse.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parse_cours import build_deck_path  # noqa: E402
from project_store import DEFAULT_DECK_NAME, export_rows, normalize  # noqa: E402


class TestBuildDeckPath(unittest.TestCase):
    def test_prefix_and_stack(self):
        stack = [(1, "Chapter 1"), (2, "Section A")]
        self.assertEqual(build_deck_path(stack, "Econ"), "Econ::Chapter 1::Section A")

    def test_empty_prefix_produces_no_leading_separator(self):
        stack = [(1, "Chapter 1"), (2, "Section A")]
        self.assertEqual(build_deck_path(stack, ""), "Chapter 1::Section A")

    def test_none_prefix_behaves_like_empty(self):
        self.assertEqual(build_deck_path([(1, "Chapter 1")], None), "Chapter 1")

    def test_whitespace_only_prefix_behaves_like_empty(self):
        self.assertEqual(build_deck_path([(1, "Chapter 1")], "   "), "Chapter 1")

    def test_never_starts_or_ends_with_the_separator(self):
        for prefix in ("", "   ", None, "Econ"):
            path = build_deck_path([(1, "Chapter 1")], prefix)
            self.assertFalse(path.startswith("::"), f"préfixe {prefix!r} → {path!r}")
            self.assertFalse(path.endswith("::"), f"préfixe {prefix!r} → {path!r}")

    def test_empty_stack_and_empty_prefix_is_empty(self):
        self.assertEqual(build_deck_path([], ""), "")


class TestExportDeckFallback(unittest.TestCase):
    """Une ligne TSV sans nom de deck est refusée par Anki : il faut un repli."""

    @staticmethod
    def _project(deck):
        return normalize({
            "version": 2,
            "deck_prefix": "",
            "assets": {},
            "prompts": [{
                "id": 0, "deck": deck, "blocks": [], "assets": [],
                "prompt": "", "status": "done", "response": "Q\tA",
            }],
        })

    def test_prompt_without_deck_falls_back_to_the_app_name(self):
        rows, _ = export_rows(self._project(""))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], DEFAULT_DECK_NAME)

    def test_prompt_with_a_deck_keeps_it(self):
        rows, _ = export_rows(self._project("Chapter 1"))
        self.assertEqual(rows[0][0], "Chapter 1")


if __name__ == "__main__":
    unittest.main()
