#!/usr/bin/env python3
"""
tests/test_i18n.py — Résolution des traductions et intégrité des catalogues.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n  # noqa: E402


class TestCatalogParity(unittest.TestCase):
    """Une clé présente d'un côté et pas de l'autre est un texte non traduit en prod."""

    def test_same_keys_in_every_language(self):
        catalogs = {lang: i18n.load_catalog(lang) for lang in i18n.LANGUAGES}
        reference = set(catalogs[i18n.DEFAULT_LANG])
        self.assertTrue(reference, "le catalogue anglais ne doit pas être vide")
        for lang, catalog in catalogs.items():
            missing = reference - set(catalog)
            extra = set(catalog) - reference
            self.assertEqual(missing, set(), f"clés absentes de {lang}.json : {sorted(missing)}")
            self.assertEqual(extra, set(), f"clés en trop dans {lang}.json : {sorted(extra)}")

    def test_catalogs_are_flat_strings(self):
        for lang in i18n.LANGUAGES:
            for key, value in i18n.load_catalog(lang).items():
                self.assertIsInstance(value, str, f"{lang}.json : {key} n'est pas une chaîne")

    def test_no_empty_translation(self):
        for lang in i18n.LANGUAGES:
            for key, value in i18n.load_catalog(lang).items():
                self.assertTrue(value.strip(), f"{lang}.json : {key} est vide")


class TestTranslate(unittest.TestCase):
    def tearDown(self):
        i18n._CACHE.pop("xx", None)

    def test_returns_translation_for_known_key(self):
        self.assertEqual(i18n.translate("app.name", "en"), "Ankigen")

    def test_unknown_key_returns_the_key_itself(self):
        # Visible en développement, mais jamais une page cassée en production.
        self.assertEqual(i18n.translate("nope.not_a_key", "fr"), "nope.not_a_key")

    def test_falls_back_to_english_when_missing_in_language(self):
        i18n._CACHE["xx"] = {}
        self.assertEqual(i18n.translate("app.name", "xx"), "Ankigen")

    def test_interpolates_parameters(self):
        i18n._CACHE["xx"] = {"test.count": "{n} card(s)"}
        self.assertEqual(i18n.translate("test.count", "xx", n=3), "3 card(s)")

    def test_missing_parameter_returns_template_instead_of_raising(self):
        i18n._CACHE["xx"] = {"test.count": "{n} card(s)"}
        self.assertEqual(i18n.translate("test.count", "xx"), "{n} card(s)")


class TestCatalogForJs(unittest.TestCase):
    def tearDown(self):
        i18n._CACHE.pop("xx", None)

    def test_keeps_only_the_js_namespace(self):
        subset = i18n.catalog_for_js("en")
        self.assertTrue(subset, "le namespace js. ne doit pas être vide")
        for key in subset:
            self.assertTrue(key.startswith("js."))

    def test_falls_back_to_english_entries(self):
        i18n._CACHE["xx"] = {}
        self.assertEqual(i18n.catalog_for_js("xx"), i18n.catalog_for_js("en"))


class TestAvailableLanguages(unittest.TestCase):
    def test_lists_every_language_with_a_label(self):
        codes = [entry["code"] for entry in i18n.available_languages()]
        self.assertEqual(codes, list(i18n.LANGUAGES))
        for entry in i18n.available_languages():
            self.assertTrue(entry["label"].strip())


if __name__ == "__main__":
    unittest.main()
